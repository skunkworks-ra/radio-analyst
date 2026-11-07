"""
accounting.py — per-session tokens and cost of a Claude Code run, from its
session transcripts. Run by the plugin's SessionEnd hook
(scripts/plugin/session_end.sh), so every run carries its own accounting.

Sources, all written by Claude Code itself:
  <transcript>.jsonl                        the main session (the orchestrator)
  <transcript dir>/subagents/agent-*.jsonl  one per subagent (stage agent)
  <transcript dir>/subagents/agent-*.meta.json  its agentType

Tokens per session are MEASURED: the final usage of each distinct assistant
message, summed. (Checked on orch_20261106/full2: the four subagent transcripts
sum to the CLI's measured Haiku totals to the token, and the main transcript to
its Sonnet totals.)

Cost per session is an ESTIMATE from list prices (PRICES), applied per message:
cache read at 0.1x and cache write at 1.25x the input price, and the Haiku 5.5
tier above 100K-token prompts. Checked against the CLI's measured cost on two
runs (orch_20261106 full2 and smoke2): Haiku matched both (0.2537, 0.0030).
Sonnet did not: -2.0% and -27%. Its cache writes are all 1-hour, whose rate the
price source does not give, and no single rate fits both runs (they imply 2.68
and 3.72 $/M), so the Sonnet cost is approximate. Opus prices are unchecked.

The workdir is the one the session's own ms_report call named (read from the
transcript), so a session that never built a report writes nothing.

No CASA dependency. main() never raises: a hook must not fail the session.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

#: $ per million tokens: (input, output, tier) with tier = (prompt tokens above
#: which, input, output). Source: claude-api skill model table (cached
#: 2026-10-06). A model not listed gets no cost.
PRICES: dict[str, tuple[float, float, tuple[int, float, float] | None]] = {
    "claude-sonnet-5-5": (2.00, 10.00, None),
    "claude-haiku-5-5": (0.10, 0.50, (100_000, 0.50, 2.50)),
    "claude-opus-5-5": (4.00, 20.00, None),
}
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25

ACCOUNTING_NAME = "accounting.json"
_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _messages(path: Path) -> list[tuple[str | None, dict, int]]:
    """(model, final usage, tool calls) per distinct assistant message id."""
    usage: dict[str, tuple[str | None, dict]] = {}
    tools: dict[str, set] = defaultdict(set)
    for line in path.read_text().splitlines():
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


def _cost(model: str | None, u: dict) -> float | None:
    price = PRICES.get(model or "")
    if price is None:
        return None
    pin, pout, tier = price
    prompt = sum(
        u.get(k) or 0
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    if tier and prompt > tier[0]:
        pin, pout = tier[1], tier[2]
    return (
        (u.get("input_tokens") or 0) * pin
        + (u.get("output_tokens") or 0) * pout
        + (u.get("cache_read_input_tokens") or 0) * CACHE_READ_FACTOR * pin
        + (u.get("cache_creation_input_tokens") or 0) * CACHE_WRITE_FACTOR * pin
    ) / 1e6


def _session(name: str, path: Path) -> dict:
    row: dict = {"session": name, "messages": 0, "tool_calls": 0, **{k: 0 for k in _FIELDS}}
    models: set[str] = set()
    cost: float | None = 0.0
    for model, u, n_tools in _messages(path):
        row["messages"] += 1
        row["tool_calls"] += n_tools
        for k in _FIELDS:
            row[k] += u.get(k) or 0
        if model:
            models.add(model)
        c = _cost(model, u)
        cost = None if c is None or cost is None else cost + c
    row["model"] = ",".join(sorted(models))
    row["cost_usd_estimate"] = round(cost, 4) if cost is not None else None
    return row


def from_transcript(transcript_path: str) -> dict:
    """Accounting for a session and its subagents, from Claude Code transcripts."""
    main = Path(transcript_path)
    rows = [_session("main (orchestrator)", main)]
    sub_dir = main.with_suffix("") / "subagents"
    for f in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []:
        meta = f.with_name(f.stem + ".meta.json")
        try:
            name = json.loads(meta.read_text()).get("agentType") or f.stem
        except (OSError, ValueError):
            name = f.stem
        rows.append(_session(name, f))
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
        "note": (
            "Tokens per session are measured (Claude Code session transcripts). Cost is a "
            "list-price estimate per message (accounting.py PRICES). Haiku's matched the "
            "CLI's measured cost on two runs; Sonnet's came out 2% and 27% low, so treat "
            "Sonnet cost as approximate."
        ),
    }


def _report_workdir(transcript: Path) -> Path | None:
    """The workdir of this session's last ms_report call, from its transcript."""
    wd = None
    for line in transcript.read_text().splitlines():
        if "ms_report" not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use" and str(block.get("name", "")).endswith("ms_report"):
                params = block.get("input", {}).get("params", block.get("input", {}))
                wd = params.get("workdir") or wd
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
