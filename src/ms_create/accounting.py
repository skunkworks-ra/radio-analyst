"""
accounting.py -- per-session tokens and cost of a Claude Code or OpenCode run,
from its session transcripts. Run by the plugin's SessionEnd hook
(scripts/plugin/session_end.sh and .opencode/plugins/hooks.js), so every run
carries its own accounting.

Sources:
  Claude Code:
    <transcript>.jsonl                        the main session (the orchestrator)
    <transcript dir>/subagents/agent-*.jsonl  one per subagent (stage agent)
    <transcript dir>/subagents/agent-*.meta.json  its agentType
  OpenCode (opencode export / client.session SDK):
    session.json                              the main session ({info, messages})
    session_<child_id>.json                   each child subagent session (parentID == main id)

Tokens per session are MEASURED: the final usage of each distinct assistant
message, summed. (Checked on orch_20261106/full2 for Claude Code and
orch_opencode_20261106 for OpenCode: message sums equal session totals to the
single token.)

Cost per session is an ESTIMATE from list prices (PRICES), applied per message:
cache read at 0.1x the input price (Sonnet 5.5: 0.05x), cache write at 1.25x for
5-minute and 2x for 1-hour entries (usage.cache_creation splits writes by TTL),
and the Haiku 5.5 tier above 100K-token prompts. Models not listed in PRICES
(e.g. NRP / TACC open-weight endpoints) report cost_usd_estimate = None.

The workdir is the one the session's own ms_report call named (read from the
transcript), so a session that never built a report writes nothing.

No CASA dependency. main() never raises: a hook must not fail the session.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections import defaultdict
from pathlib import Path

#: $ per million tokens: (input, output, tier) with tier = (prompt tokens above
#: which, input, output). Source: claude-api skill model table (cached
#: 2026-10-06), except the Sonnet read rate (CACHE_READ_FACTORS), which follows
#: the CLI. A model not listed gets no cost.
PRICES: dict[str, tuple[float, float, tuple[int, float, float] | None]] = {
    "claude-sonnet-5-5": (2.00, 10.00, None),
    "claude-haiku-5-5": (0.10, 0.50, (100_000, 0.50, 2.50)),
    "claude-opus-5-5": (4.00, 20.00, None),
}
CACHE_READ_FACTOR = 0.1
#: per-model read factor where the CLI's measured cost shows a different one
CACHE_READ_FACTORS = {"claude-sonnet-5-5": 0.05}
CACHE_WRITE_FACTOR = 1.25  # 5-minute TTL
CACHE_WRITE_1H_FACTOR = 2.0

ACCOUNTING_NAME = "accounting.json"
_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _load_opencode_doc(path: Path) -> dict | None:
    """Return parsed OpenCode {info, messages} export dict, or None if JSONL."""
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return None
    stripped = raw.lstrip()
    if not stripped.startswith("{"):
        return None
    with contextlib.suppress(ValueError):
        doc = json.loads(raw)
        if isinstance(doc, dict) and isinstance(doc.get("messages"), list):
            return doc
    return None


def _opencode_model_label(info: dict) -> str | None:
    prov = str(info.get("providerID") or (info.get("model") or {}).get("providerID") or "").strip()
    mod = str(
        info.get("modelID")
        or (info.get("model") or {}).get("id")
        or (info.get("model") or {}).get("modelID")
        or ""
    ).strip()
    if prov and mod:
        return f"{prov}/{mod}"
    return mod or None


def _messages(path: Path) -> list[tuple[str | None, dict, int]]:
    """(model, final usage, tool calls) per distinct assistant message id."""
    oc_doc = _load_opencode_doc(path)
    if oc_doc is not None:
        oc_usage: dict[str, tuple[str | None, dict]] = {}
        oc_tools: dict[str, set[str]] = defaultdict(set)
        fallback_model = _opencode_model_label(oc_doc.get("info") or {})
        for idx, entry in enumerate(oc_doc["messages"]):
            if not isinstance(entry, dict):
                continue
            info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
            if (info.get("role") or entry.get("role")) != "assistant":
                continue
            mid = str(info.get("id") or entry.get("id") or f"_oc_{idx}")
            for p_idx, part in enumerate(entry.get("parts") or []):
                if isinstance(part, dict) and part.get("type") == "tool":
                    oc_tools[mid].add(str(part.get("callID") or part.get("id") or f"{mid}_{p_idx}"))
            tok = info.get("tokens") if isinstance(info.get("tokens"), dict) else {}
            cache = tok.get("cache") if isinstance(tok.get("cache"), dict) else {}
            u = {
                "input_tokens": tok.get("input") or 0,
                "output_tokens": tok.get("output") or 0,
                "reasoning_tokens": tok.get("reasoning") or 0,
                "cache_read_input_tokens": cache.get("read") or 0,
                "cache_creation_input_tokens": cache.get("write") or 0,
            }
            oc_usage[mid] = (_opencode_model_label(info) or fallback_model, u)
        return [(m, u, len(oc_tools[mid])) for mid, (m, u) in oc_usage.items()]

    usage: dict[str, tuple[str | None, dict]] = {}
    tools: dict[str, set] = defaultdict(set)
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        mid = msg.get("id") or f"_{len(usage)}"
        tools[mid].update(
            b.get("id") for b in msg.get("content") or [] if b.get("type") == "tool_use"
        )
        usage[mid] = (msg.get("model"), msg.get("usage") or {})
    return [(m, u, len(tools[mid])) for mid, (m, u) in usage.items()]


def _price_key(model: str | None) -> str:
    if not model:
        return ""
    if model in PRICES:
        return model
    tail = model.split("/", 1)[-1]
    return tail if tail in PRICES else ""


def _cost(model: str | None, u: dict) -> float | None:
    pkey = _price_key(model)
    price = PRICES.get(pkey)
    if price is None:
        return None
    pin, pout, tier = price
    prompt = sum(
        u.get(k) or 0
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    if tier and prompt > tier[0]:
        pin, pout = tier[1], tier[2]
    write = u.get("cache_creation_input_tokens") or 0
    write_1h = min((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0, write)
    return (
        (u.get("input_tokens") or 0) * pin
        + (u.get("output_tokens") or 0) * pout
        + (u.get("cache_read_input_tokens") or 0)
        * CACHE_READ_FACTORS.get(pkey, CACHE_READ_FACTOR)
        * pin
        + (write - write_1h) * CACHE_WRITE_FACTOR * pin
        + write_1h * CACHE_WRITE_1H_FACTOR * pin
    ) / 1e6


def _session(name: str, path: Path) -> dict:
    row: dict = {"session": name, "messages": 0, "tool_calls": 0, **{k: 0 for k in _FIELDS}}
    reasoning_total = 0
    models: set[str] = set()
    cost: float | None = 0.0
    for model, u, n_tools in _messages(path):
        row["messages"] += 1
        row["tool_calls"] += n_tools
        for k in _FIELDS:
            row[k] += u.get(k) or 0
        reasoning_total += u.get("reasoning_tokens") or 0
        if model:
            models.add(model)
        c = _cost(model, u)
        cost = None if c is None or cost is None else cost + c
    if reasoning_total > 0:
        row["reasoning_tokens"] = reasoning_total
    row["model"] = ",".join(sorted(models))
    row["cost_usd_estimate"] = round(cost, 4) if cost is not None else None
    return row


def from_transcript(transcript_path: str) -> dict:
    """Accounting for a session and its subagents, from Claude Code or OpenCode transcripts."""
    main = Path(transcript_path)
    oc_doc = _load_opencode_doc(main)
    rows = [_session("main (orchestrator)", main)]

    if oc_doc is not None:
        root_id = str((oc_doc.get("info") or {}).get("id") or "")
        children: list[tuple[int, str, Path]] = []
        for f in sorted(main.parent.glob("session_*.json")):
            if f.resolve() == main.resolve():
                continue
            c_doc = _load_opencode_doc(f)
            if c_doc is None:
                continue
            c_info = c_doc.get("info") or {}
            if root_id and str(c_info.get("parentID") or "") != root_id:
                continue
            created = int((c_info.get("time") or {}).get("created") or 0)
            label = str(c_info.get("agent") or f.stem)
            children.append((created, label, f))
        children.sort(key=lambda item: (item[0], item[2].name))
        for _, label, f in children:
            rows.append(_session(label, f))
        note_str = (
            "Tokens per session are measured (OpenCode session exports). Cost is a "
            "list-price estimate per message where known (accounting.py PRICES); "
            "unpriced open-weight endpoints report cost_usd_estimate = null."
        )
    else:
        sub_dir = main.with_suffix("") / "subagents"
        for f in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []:
            meta = f.with_name(f.stem + ".meta.json")
            try:
                name = json.loads(meta.read_text()).get("agentType") or f.stem
            except (OSError, ValueError):
                name = f.stem
            rows.append(_session(name, f))
        note_str = (
            "Tokens per session are measured (Claude Code session transcripts). Cost is a "
            "list-price estimate per message (accounting.py PRICES), cache writes priced by "
            "TTL. Haiku and Sonnet match the CLI's own cost figure on five runs; Opus is "
            "unchecked."
        )

    costs = [r["cost_usd_estimate"] for r in rows]
    by_model: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["cost_usd_estimate"] is not None:
            by_model[r["model"]] += r["cost_usd_estimate"]
    return {
        "source": str(main),
        "sessions": rows,
        "total_cost_usd_estimate": round(sum(costs), 4) if None not in costs else None,
        "model_cost_usd_estimate": {m: round(c, 4) for m, c in by_model.items()},
        "note": note_str,
    }


def _extract_workdir_from_input(raw_input: object) -> str | None:
    if not isinstance(raw_input, dict):
        return None
    params = raw_input.get("params", raw_input)
    if isinstance(params, str):
        stripped = params.strip()
        if stripped.startswith("{"):
            with contextlib.suppress(ValueError):
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    params = parsed
    if isinstance(params, dict):
        wd = params.get("workdir")
        if isinstance(wd, str) and wd.strip():
            return wd.strip()
    return None


def _report_workdir(transcript: Path) -> Path | None:
    """The workdir of this session's last ms_report call, from its transcript."""
    oc_doc = _load_opencode_doc(transcript)
    if oc_doc is not None:
        wd_oc: str | None = None
        for entry in oc_doc["messages"]:
            if not isinstance(entry, dict):
                continue
            for part in entry.get("parts") or []:
                if not isinstance(part, dict) or part.get("type") != "tool":
                    continue
                tname = str(part.get("tool") or part.get("name") or "")
                if tname.endswith("ms_report"):
                    state = part.get("state") if isinstance(part.get("state"), dict) else {}
                    cand = _extract_workdir_from_input(state.get("input"))
                    if cand:
                        wd_oc = cand
        return Path(wd_oc) if wd_oc and Path(wd_oc).is_dir() else None

    wd: str | None = None
    for line in transcript.read_text(errors="replace").splitlines():
        if "ms_report" not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use" and str(block.get("name", "")).endswith("ms_report"):
                cand = _extract_workdir_from_input(block.get("input"))
                if cand:
                    wd = cand
    return Path(wd) if wd and Path(wd).is_dir() else None


def main() -> int:
    """SessionEnd hook: write accounting.json and rebuild the report. Never fails."""
    try:
        hook = json.load(sys.stdin)
        transcript = hook.get("transcript_path")
        if not transcript or not Path(transcript).exists():
            return 0
        wd = _report_workdir(Path(transcript))
        if wd is None:  # this session built no report: nothing to account into
            return 0
        (wd / ACCOUNTING_NAME).write_text(json.dumps(from_transcript(transcript), indent=1))
        if (wd / "report_inputs.json").exists():
            from ms_create import report

            report.run(str(wd), reuse_saved=True)
    except Exception as exc:  # a hook must not fail the session
        print(f"accounting hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
