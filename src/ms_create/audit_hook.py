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
_AGENT_ID_RE = re.compile(r"agentId:\s*([A-Za-z0-9_-]+)")
_USAGE_TAG_RE = re.compile(r"<usage>\s*(.*?)\s*</usage>", re.DOTALL)
_WORKDIR_ARG_RE = re.compile(r"workdir\s*[=:]\s*([^\s,'\"\}]+)")


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


def _short_tool_name(raw_name: str) -> str:
    if "__" in raw_name:
        return raw_name.rsplit("__", 1)[-1]
    return raw_name


def _unwrap_params(raw_input: object) -> dict:
    if not isinstance(raw_input, dict):
        return {}
    inner = raw_input.get("params")
    if isinstance(inner, dict) and set(raw_input.keys()) <= {"params"}:
        return inner
    return dict(raw_input)


def _stage_from_subagent_type(subagent_type: str) -> str:
    # e.g. "radio-analyst:precal-stage" -> "precal"
    tail = subagent_type.split(":")[-1].strip()
    if tail.endswith("-stage"):
        tail = tail[: -len("-stage")]
    return tail


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


def build_audit_records_from_transcript(
    transcript_path: str | Path,
    *,
    default_workdir: str | Path | None = None,
) -> list[Path]:
    """
    Parse ``transcript_path`` and write ``{workdir}/orchestrator/{n:02d}_{stage}_try{k}.json``
    for every ``<stage_decision>`` block whose ``workdir`` exists on disk.

    Idempotent: re-running on the same or an extended transcript produces identical files.
    Returns the list of audit JSON paths written or verified.
    """
    tpath = Path(transcript_path)
    if not tpath.is_file():
        return []

    events: list[dict] = []
    for line in tpath.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            events.append(ev)

    # First pass: index all tool_results by tool_use_id so streaming assistant/user pairs correlate cleanly.
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

    seen_msg_tool_ids: set[str] = set()
    seen_msg_text_ids: set[tuple[str, int]] = set()
    inferred_workdir: str | None = str(default_workdir) if default_workdir else None

    # Active pending stage windows (populated when Agent tool_use is seen).
    pending_windows: list[dict] = []
    stage_attempt_counts: dict[str, int] = {}
    auto_seq = 0
    written_paths: list[Path] = []

    for ev in events:
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        mid = str(msg.get("id") or f"_idx_{len(seen_msg_text_ids)}")
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue

        for b_idx, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "tool_use":
                tuid = str(block.get("id") or "")
                if not tuid or tuid in seen_msg_tool_ids:
                    continue
                seen_msg_tool_ids.add(tuid)
                raw_name = str(block.get("name") or "")
                inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                res_text, tur_meta = tool_results.get(tuid, ("", None))

                if raw_name in ("Agent", "Task"):
                    prompt_str = str(inp.get("prompt") or "")
                    sub_type = str(inp.get("subagent_type") or "")
                    stage_hint = _stage_from_subagent_type(sub_type)
                    m_wd = _WORKDIR_ARG_RE.search(prompt_str)
                    if m_wd and not inferred_workdir:
                        inferred_workdir = m_wd.group(1)

                    agent_id = None
                    agent_usage = None
                    if tur_meta:
                        agent_id = tur_meta.get("agentId") or agent_id
                        agent_usage = tur_meta.get("usage") or agent_usage
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
                    if isinstance(params.get("workdir"), str) and params["workdir"]:
                        inferred_workdir = params["workdir"]
                    if raw_name == "Read":
                        fp = str(inp.get("file_path") or "")
                        if fp.lower().endswith(".png") and pending_windows:
                            pending_windows[-1]["png_paths_read"].append(fp)
                    elif raw_name.startswith("mcp__") and pending_windows:
                        parsed_out: object = res_text
                        with contextlib.suppress(ValueError, TypeError):
                            parsed_out = json.loads(res_text)
                        pending_windows[-1]["checks"].append(
                            {
                                "tool": _short_tool_name(raw_name),
                                "tool_args": params,
                                "output": parsed_out,
                            }
                        )

            elif btype == "text":
                text_key = (mid, b_idx)
                if text_key in seen_msg_text_ids:
                    continue
                txt = str(block.get("text") or "")
                decisions = parse_stage_decisions(txt)
                if not decisions:
                    continue
                seen_msg_text_ids.add(text_key)

                for dec in decisions:
                    auto_seq += 1
                    stage = str(dec.get("stage") or "").strip()
                    safe_stage = _safe_stage_slug(stage)
                    seq = int(dec.get("seq") or dec.get("n") or auto_seq)
                    stage_attempt_counts[safe_stage] = stage_attempt_counts.get(safe_stage, 0) + 1
                    attempt = int(
                        dec.get("try") or dec.get("attempt") or stage_attempt_counts[safe_stage]
                    )
                    wd_str = str(dec.get("workdir") or inferred_workdir or "").strip()
                    if not wd_str:
                        continue
                    wd_path = Path(wd_str)
                    if not wd_path.is_dir():
                        continue

                    # Match the latest unconsumed pending window (preferring matching stage prefix).
                    win: dict | None = None
                    for cand in reversed(pending_windows):
                        if not cand["consumed"] and (
                            cand["stage_hint"] == stage or stage.startswith(cand["stage_hint"])
                        ):
                            win = cand
                            break
                    if win is None:
                        for cand in reversed(pending_windows):
                            if not cand["consumed"]:
                                win = cand
                                break
                    if win is not None:
                        win["consumed"] = True

                    png_reviewed = dec.get("png_reviewed")
                    if png_reviewed is None and win is not None and win["png_paths_read"]:
                        png_reviewed = f"viewed: {', '.join(win['png_paths_read'])}"

                    record = {
                        "n": seq,
                        "stage": stage,
                        "attempt": attempt,
                        "workdir": str(wd_path.resolve()),
                        "prompt": win["prompt"] if win is not None else "",
                        "handoff": win["handoff"] if win is not None else "",
                        "checks": win["checks"] if win is not None else [],
                        "decision": dec.get("decision"),
                        "deciding_metric": dec.get("deciding_metric"),
                        "reason": dec.get("reason", ""),
                        "debug_directive": dec.get("debug_directive"),
                        "agent_id": win["agent_id"] if win is not None else None,
                        "png_reviewed": png_reviewed,
                        "agent_usage": win["agent_usage"] if win is not None else None,
                    }

                    orch_dir = wd_path / "orchestrator"
                    orch_dir.mkdir(parents=True, exist_ok=True)
                    out_file = orch_dir / f"{seq:02d}_{safe_stage}_try{attempt}.json"
                    payload = json.dumps(record, indent=2) + "\n"
                    if not out_file.is_file() or out_file.read_text(errors="replace") != payload:
                        tmp_file = out_file.with_suffix(".json.tmp")
                        tmp_file.write_text(payload)
                        tmp_file.replace(out_file)
                    written_paths.append(out_file)

    return written_paths


def main() -> int:
    """Stop / SessionEnd hook entrypoint: read hook JSON on stdin and write audit JSONs."""
    try:
        hook = json.load(sys.stdin)
        transcript = hook.get("transcript_path")
        if not transcript or not Path(transcript).is_file():
            return 0
        build_audit_records_from_transcript(transcript)
    except Exception as exc:
        print(f"audit_hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
