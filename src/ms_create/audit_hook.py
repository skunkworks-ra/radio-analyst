"""
audit_hook.py -- deterministic builder for {workdir}/orchestrator/{n:02d}_{stage}_try{k}.json.

Parses the Claude Code session JSONL transcript on Stop / SessionEnd, correlates
each Agent stage invocation + verbatim handoff + subsequent read-only MCP tool
calls with the orchestrator's compact <stage_decision>{...}</stage_decision>
block, and writes {workdir}/orchestrator/{n:02d}_{stage}_try{k}.json idempotently.

Eliminates 16-26 KB of Sonnet Write tool output per run while preserving full,
unabridged audit provenance directly from the session transcript.

No CASA dependency. main() never raises: a hook must not fail the session.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path

_STAGE_DECISION_RE = re.compile(
    r"<stage_decision>\s*(\{.*?\})\s*</stage_decision>",
    re.DOTALL,
)
_AGENT_ID_RE = re.compile(r"(?:agentId|session_id|task_id):\s*([A-Za-z0-9_-]+)")
_USAGE_TAG_RE = re.compile(r"<usage>\s*(.*?)\s*</usage>", re.DOTALL)
_WORKDIR_ARG_RE = re.compile(r"workdir['\"]?\s*[=:]\s*['\"]?([^\s,'\"\}]+)")

_KNOWN_STAGE_SLUGS = frozenset(
    {"inspect", "precal", "calibrate", "polcal", "image", "postcal", "selfcal"}
)
_OPENCODE_MCP_PREFIXES = (
    "radio-analyst_ms-inspect_",
    "radio-analyst_ms-modify_",
    "radio-analyst_ms-create_",
    "ms-inspect_",
    "ms-modify_",
    "ms-create_",
)


def _extract_text(content: object) -> str:
    """Flatten Claude Code tool_result or message content into a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return ""


def _is_mcp_tool(raw_name: str) -> bool:
    return raw_name.startswith("mcp__") or raw_name.startswith(_OPENCODE_MCP_PREFIXES)


def _short_tool_name(raw_name: str) -> str:
    if "__" in raw_name:
        return raw_name.rsplit("__", 1)[-1]
    for pfx in _OPENCODE_MCP_PREFIXES:
        if raw_name.startswith(pfx):
            return raw_name[len(pfx) :]
    return raw_name


def _unwrap_params(raw_input: object) -> dict:
    if not isinstance(raw_input, dict):
        return {}
    inner = raw_input.get("params")
    if isinstance(inner, dict) and set(raw_input.keys()) <= {"params"}:
        return inner
    if isinstance(inner, str) and set(raw_input.keys()) <= {"params"}:
        stripped = inner.strip()
        if stripped.startswith("{"):
            with contextlib.suppress(json.JSONDecodeError):
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
    return dict(raw_input)


def _stage_from_subagent_type(subagent_type: str) -> str | None:
    # e.g. "radio-analyst:precal-stage" or "precal-stage" -> "precal"
    tail = subagent_type.split(":")[-1].strip()
    if tail.endswith("-stage") and tail[:-6] in _KNOWN_STAGE_SLUGS:
        return tail[:-6]
    return None


def _safe_stage_slug(stage: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", stage.strip()).strip("_")
    return slug or "stage"


def parse_stage_decisions(text: str) -> list[dict]:
    """Extract all valid JSON dicts inside <stage_decision>...</stage_decision> blocks."""
    out: list[dict] = []
    for match in _STAGE_DECISION_RE.finditer(text):
        raw = match.group(1)
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("stage"):
            out.append(obj)
    return out


def _load_normalized_items(
    raw_text: str,
) -> list[tuple[str, object, str, dict, str, dict | None]]:
    """Normalize Claude Code JSONL, OpenCode export JSON, and OpenCode JSONL into a stream.

    Returns tuples of:
      - ("tool", tool_call_id, raw_tool_name, input_dict, output_text, metadata_dict_or_None)
      - ("text", dedup_key, text_str, {}, "", None)
    """
    items: list[tuple[str, object, str, dict, str, dict | None]] = []

    stripped = raw_text.lstrip()
    if stripped.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError):
            doc = json.loads(raw_text)
            if isinstance(doc, dict) and isinstance(doc.get("messages"), list):
                for m_idx, msg_entry in enumerate(doc["messages"]):
                    if not isinstance(msg_entry, dict):
                        continue
                    info = msg_entry.get("info") if isinstance(msg_entry.get("info"), dict) else {}
                    role = info.get("role") or msg_entry.get("role")
                    if role != "assistant":
                        continue
                    mid = str(info.get("id") or msg_entry.get("id") or f"_oc_msg_{m_idx}")
                    for p_idx, part in enumerate(msg_entry.get("parts") or []):
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype == "tool":
                            call_id = str(
                                part.get("callID") or part.get("id") or f"{mid}_t_{p_idx}"
                            )
                            raw_name = str(part.get("tool") or part.get("name") or "")
                            state = part.get("state") if isinstance(part.get("state"), dict) else {}
                            inp = state.get("input") if isinstance(state.get("input"), dict) else {}
                            out_val = state.get("output")
                            res_text = (
                                out_val
                                if isinstance(out_val, str)
                                else (json.dumps(out_val) if out_val is not None else "")
                            )
                            meta = (
                                state.get("metadata")
                                if isinstance(state.get("metadata"), dict)
                                else None
                            )
                            items.append(("tool", call_id, raw_name, inp, res_text, meta))
                        elif ptype == "text":
                            tkey = ("oc_export", mid, p_idx)
                            items.append(("text", tkey, str(part.get("text") or ""), {}, "", None))
                return items

    events: list[dict] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            events.append(ev)

    # First pass for Claude Code JSONL: index tool_results by tool_use_id.
    tool_results: dict[str, tuple[str, dict | None]] = {}
    for ev in events:
        if ev.get("type") != "user":
            continue
        tur = ev.get("toolUseResult")
        tur_dict = tur if isinstance(tur, dict) else None
        msg = ev.get("message") or {}
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tuid = block.get("tool_use_id")
                if isinstance(tuid, str) and tuid:
                    tool_results[tuid] = (_extract_text(block.get("content")), tur_dict)

    for ev_idx, ev in enumerate(events):
        etype = ev.get("type")
        if etype == "assistant":
            msg = ev.get("message") or {}
            mid = str(msg.get("id") or f"_cc_msg_{ev_idx}")
            content = msg.get("content") or []
            if not isinstance(content, list):
                continue
            for b_idx, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    tuid = str(block.get("id") or "")
                    if not tuid:
                        continue
                    raw_name = str(block.get("name") or "")
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    res_text, tur_meta = tool_results.get(tuid, ("", None))
                    items.append(("tool", tuid, raw_name, inp, res_text, tur_meta))
                elif btype == "text":
                    items.append(
                        ("text", ("cc", mid, b_idx), str(block.get("text") or ""), {}, "", None)
                    )
        elif etype == "tool_use" and isinstance(ev.get("part"), dict):
            part = ev["part"]
            call_id = str(part.get("callID") or part.get("id") or f"_oc_tool_{ev_idx}")
            raw_name = str(part.get("tool") or part.get("name") or "")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            inp = state.get("input") if isinstance(state.get("input"), dict) else {}
            out_val = state.get("output")
            res_text = (
                out_val
                if isinstance(out_val, str)
                else (json.dumps(out_val) if out_val is not None else "")
            )
            meta = state.get("metadata") if isinstance(state.get("metadata"), dict) else None
            items.append(("tool", call_id, raw_name, inp, res_text, meta))
        elif etype == "text" and isinstance(ev.get("part"), dict):
            part = ev["part"]
            pid = part.get("id")
            tkey = ("oc_run", str(pid)) if pid else ("oc_run_idx", ev_idx)
            items.append(("text", tkey, str(part.get("text") or ""), {}, "", None))

    return items


def build_audit_records_from_transcript(
    transcript_path: str | Path,
    *,
    default_workdir: str | Path | None = None,
) -> list[Path]:
    """
    Parse ``transcript_path`` and write ``{workdir}/orchestrator/{n:02d}_{stage}_try{k}.json``
    for every ``<stage_decision>`` block whose ``workdir`` exists on disk.

    Supports Claude Code JSONL transcripts, ``opencode export`` JSON files, and
    ``opencode run --format json`` JSONL transcripts.
    Idempotent: re-running on the same or an extended transcript produces identical files.
    Returns the list of audit JSON paths written or verified.
    """
    tpath = Path(transcript_path)
    if not tpath.is_file():
        return []

    items = _load_normalized_items(tpath.read_text(errors="replace"))

    seen_msg_tool_ids: set[str] = set()
    seen_msg_text_ids: set[object] = set()
    default_wd_path: Path | None = (
        Path(str(default_workdir).strip()).expanduser()
        if default_workdir and str(default_workdir).strip()
        else None
    )
    inferred_workdir: str | None = (
        str(default_wd_path) if default_wd_path is not None and default_wd_path.is_dir() else None
    )

    # Active pending stage windows (populated only when a known *-stage subagent runs).
    pending_windows: list[dict] = []
    stage_attempt_counts: dict[str, int] = {}
    recorded_keys: set[tuple[int, str, int]] = set()
    auto_seq = 0
    written_paths: list[Path] = []

    def _emit_decision(dec: dict) -> None:
        nonlocal auto_seq
        stage = str(dec.get("stage") or "").strip()
        if not stage:
            return
        safe_stage = _safe_stage_slug(stage)
        raw_seq = dec.get("seq") or dec.get("n")
        raw_attempt = dec.get("try") or dec.get("attempt")
        if raw_seq is not None and raw_attempt is not None:
            key = (int(raw_seq), safe_stage, int(raw_attempt))
            if key in recorded_keys:
                return
        auto_seq += 1
        seq = int(raw_seq or auto_seq)
        stage_attempt_counts[safe_stage] = stage_attempt_counts.get(safe_stage, 0) + 1
        attempt = int(raw_attempt or stage_attempt_counts[safe_stage])
        key = (seq, safe_stage, attempt)
        if key in recorded_keys:
            return

        dec_wd = str(dec.get("workdir") or "").strip()
        wd_path: Path | None = None
        if dec_wd:
            p_dec = Path(dec_wd).expanduser()
            if p_dec.is_dir():
                wd_path = p_dec
            elif default_wd_path is not None and default_wd_path.is_dir():
                wd_path = default_wd_path
        elif inferred_workdir and Path(inferred_workdir).is_dir():
            wd_path = Path(inferred_workdir)
        elif default_wd_path is not None and default_wd_path.is_dir():
            wd_path = default_wd_path
        if wd_path is None:
            return

        recorded_keys.add(key)

        matching = [
            cand
            for cand in pending_windows
            if not cand["consumed"]
            and (
                cand["stage_hint"] == stage
                or (cand["stage_hint"] == "image" and stage == "image_iquv")
            )
        ]
        for w in matching:
            w["consumed"] = True

        primary = matching[0] if matching else None
        all_checks = [c for w in matching for c in w["checks"]]
        all_pngs = [p for w in matching for p in w["png_paths_read"]]

        png_reviewed = dec.get("png_reviewed")
        if png_reviewed is None and all_pngs:
            png_reviewed = f"viewed: {', '.join(all_pngs)}"

        record: dict[str, object] = {
            "n": seq,
            "stage": stage,
            "attempt": attempt,
            "workdir": str(wd_path.resolve()),
            "prompt": primary["prompt"] if primary is not None else "",
            "handoff": primary["handoff"] if primary is not None else "",
            "checks": all_checks,
            "decision": dec.get("decision"),
            "deciding_metric": dec.get("deciding_metric"),
            "reason": dec.get("reason", ""),
            "debug_directive": dec.get("debug_directive"),
            "agent_id": primary["agent_id"] if primary is not None else None,
            "png_reviewed": png_reviewed,
            "agent_usage": primary["agent_usage"] if primary is not None else None,
        }
        if len(matching) > 1:
            record["aux_runs"] = [
                {
                    "subagent_type": w["subagent_type"],
                    "prompt": w["prompt"],
                    "handoff": w["handoff"],
                    "agent_id": w["agent_id"],
                    "agent_usage": w["agent_usage"],
                }
                for w in matching[1:]
            ]

        orch_dir = wd_path / "orchestrator"
        orch_dir.mkdir(parents=True, exist_ok=True)
        out_file = orch_dir / f"{seq:02d}_{safe_stage}_try{attempt}.json"
        payload = json.dumps(record, indent=2) + "\n"
        if not out_file.is_file() or out_file.read_text(errors="replace") != payload:
            tmp_file = out_file.with_suffix(".json.tmp")
            tmp_file.write_text(payload)
            tmp_file.replace(out_file)
        written_paths.append(out_file)

    for kind, item_id, str_val, inp, res_text, tur_meta in items:
        if kind == "tool":
            tuid = str(item_id or "")
            if not tuid or tuid in seen_msg_tool_ids:
                continue
            seen_msg_tool_ids.add(tuid)
            raw_name = str_val

            if raw_name in ("Agent", "Task", "task"):
                prompt_str = str(inp.get("prompt") or "")
                sub_type = str(inp.get("subagent_type") or inp.get("agent") or "")
                stage_hint = _stage_from_subagent_type(sub_type)

                if stage_hint is not None:
                    m_wd = _WORKDIR_ARG_RE.search(prompt_str)
                    if m_wd:
                        cand_wd = Path(m_wd.group(1)).expanduser()
                        if cand_wd.is_dir():
                            inferred_workdir = str(cand_wd)

                    agent_id = None
                    agent_usage = None
                    if tur_meta:
                        agent_id = (
                            tur_meta.get("agentId")
                            or tur_meta.get("sessionId")
                            or tur_meta.get("session_id")
                            or agent_id
                        )
                        agent_usage = tur_meta.get("usage") or tur_meta.get("tokens") or agent_usage
                    m_aid = _AGENT_ID_RE.search(res_text)
                    if m_aid and not agent_id:
                        agent_id = m_aid.group(1)
                    m_usg = _USAGE_TAG_RE.search(res_text)
                    if m_usg and not agent_usage:
                        agent_usage = m_usg.group(1).strip()

                    pending_windows.append(
                        {
                            "stage_hint": stage_hint,
                            "subagent_type": sub_type,
                            "prompt": prompt_str,
                            "handoff": res_text,
                            "agent_id": agent_id,
                            "agent_usage": agent_usage,
                            "checks": [],
                            "png_paths_read": [],
                            "consumed": False,
                        }
                    )
            else:
                params = _unwrap_params(inp)
                if _short_tool_name(raw_name) == "ms_record_stage_decision":
                    _emit_decision(params)
                    continue
                if (
                    _is_mcp_tool(raw_name)
                    and isinstance(params.get("workdir"), str)
                    and params["workdir"]
                ):
                    cand_wd = Path(params["workdir"]).expanduser()
                    if cand_wd.is_dir():
                        inferred_workdir = str(cand_wd)
                active_win = next(
                    (w for w in reversed(pending_windows) if not w["consumed"]),
                    None,
                )
                if raw_name in ("Read", "read"):
                    fp = str(inp.get("file_path") or inp.get("filePath") or "")
                    if fp.lower().endswith(".png") and active_win is not None:
                        active_win["png_paths_read"].append(fp)
                elif _is_mcp_tool(raw_name) and active_win is not None:
                    parsed_out: object = res_text
                    with contextlib.suppress(ValueError, TypeError):
                        parsed_out = json.loads(res_text)
                    active_win["checks"].append(
                        {
                            "tool": _short_tool_name(raw_name),
                            "tool_args": params,
                            "output": parsed_out,
                        }
                    )

        elif kind == "text":
            text_key = item_id
            if text_key in seen_msg_text_ids:
                continue
            txt = str_val
            decisions = parse_stage_decisions(txt)
            if not decisions:
                continue
            seen_msg_text_ids.add(text_key)

            for dec in decisions:
                _emit_decision(dec)

    return written_paths


def main() -> int:
    """Stop / SessionEnd hook entrypoint: read hook JSON on stdin and write audit JSONs."""
    try:
        hook = json.load(sys.stdin)
        transcript = hook.get("transcript_path")
        if not transcript or not Path(transcript).is_file():
            return 0
        build_audit_records_from_transcript(transcript, default_workdir=hook.get("cwd"))
    except Exception as exc:
        print(f"audit_hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
