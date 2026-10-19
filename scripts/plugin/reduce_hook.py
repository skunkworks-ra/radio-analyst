#!/usr/bin/env python3
"""radio-analyst hooks for the `reduce` skill. Log, then reconcile at Stop; never deny.

  UserPromptSubmit  /reduce or /radio-analyst:reduce activates the session
  PostToolUse       a Skill call for reduce activates; once active, every tool call is logged
  PostToolUseFailure  logged as a failed call
  Stop              score the logged MCP calls against stages.json; if items are open,
                    and no background task is running, send the model back once with the list

The log is $CLAUDE_PROJECT_DIR/reduce_hooks.jsonl (the session's start directory;
the hook's cwd follows any `cd` the model runs), one JSON line per event. Nothing is written
in a session that never activated. Any error in this script exits 0 (fail open);
at Stop the error is shown as a systemMessage so it is not silent. Stdlib only.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reduce_contract import CONTRACT, make_call, score  # noqa: E402

LOG_NAME = "reduce_hooks.jsonl"
SKILL_NAMES = {"reduce", "radio-analyst:reduce"}
PROMPT_RE = re.compile(r"^\s*/(radio-analyst:)?reduce\b")
SCRIPT_RE = re.compile(r'script_path\\*"\s*:\s*\\*"([^"\\]+)')
ERROR_RE = re.compile(r'(\\*"isError\\*"\s*:\s*true|\\*"status\\*"\s*:\s*\\*"error)')


def read_log(log: Path) -> list[dict]:
    if not log.exists():
        return []
    out = []
    for ln in log.open():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def append(log: Path, rec: dict) -> None:
    rec["t"] = round(time.time(), 3)
    with log.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def is_active(records: list[dict], session: str) -> bool:
    return any(r.get("event") == "activate" and r.get("session_id") == session for r in records)


def session_records(records: list[dict], session: str) -> list[dict]:
    return [r for r in records if r.get("session_id") == session]


def sha256(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def handle(ev: dict) -> dict | None:
    event = ev.get("hook_event_name", "")
    session = ev.get("session_id", "")
    # not ev["cwd"]: it moves with the model's `cd` (run 20261019T065217Z went silent that way)
    log = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ev.get("cwd") or ".") / LOG_NAME
    records = read_log(log)
    active = is_active(records, session)

    if event == "UserPromptSubmit":
        if not active and PROMPT_RE.match(ev.get("prompt", "")):
            append(log, {"event": "activate", "session_id": session, "via": "prompt"})
        return None

    if event in ("PostToolUse", "PostToolUseFailure"):
        tool = ev.get("tool_name", "")
        inp = ev.get("tool_input") or {}
        if not active and tool == "Skill" and inp.get("skill") in SKILL_NAMES:
            append(log, {"event": "activate", "session_id": session, "via": "skill"})
            active = True
        if not active:
            return None
        rec = {"event": "call", "session_id": session, "tool": tool, "input": inp}
        if event == "PostToolUseFailure":
            rec["ok"] = False
            rec["error"] = str(ev.get("error", ""))[:2000]
        else:
            resp = json.dumps(ev.get("tool_response"), default=str)
            rec["ok"] = not ERROR_RE.search(resp)
            # generated scripts: hash at generation, so a later hand edit shows at Stop
            for path in set(SCRIPT_RE.findall(resp)) if tool.startswith("mcp__") else ():
                append(
                    log,
                    {
                        "event": "script",
                        "session_id": session,
                        "path": path,
                        "sha256": sha256(path),
                    },
                )
        append(log, rec)
        return None

    if event == "Stop":
        if not active or ev.get("stop_hook_active") or ev.get("background_tasks"):
            return None
        mine = session_records(records, session)
        calls = [
            make_call(i, r["tool"], r.get("input"), r.get("ok"))
            for i, r in enumerate(mine, 1)
            if r.get("event") == "call" and r.get("tool", "").startswith("mcp__")
        ]
        r = score(calls, json.loads(CONTRACT.read_text()))
        items = list(r["open"])
        latest = {x["path"]: x["sha256"] for x in mine if x.get("event") == "script"}
        # an edit is recorded once a ledger append names the script (the tool stores its hash)
        recorded = {
            c["input"].get("script_path")
            for c in calls
            if c["tool"] == "ms_reduction_log" and c["ok"] and c["input"].get("action") == "append"
        }
        for path, digest in latest.items():
            now = sha256(path)
            if digest and now and now != digest and path not in recorded:
                items.append(
                    f"edited after generation: {path} (record the edit with ms_reduction_log)"
                )
        append(log, {"event": "stop", "session_id": session, "open": items})
        if not items:
            return None
        reason = (
            "reduce contract (stages.json): these items are open. Either do them, or say in your "
            "report why each one was skipped.\n- " + "\n- ".join(items)
        )
        return {"decision": "block", "reason": reason}

    return None


def main() -> int:
    ev = {}
    try:
        ev = json.load(sys.stdin)
        out = handle(ev)
        if out:
            print(json.dumps(out))
    except Exception as e:  # fail open, but say so where it can be seen
        if ev.get("hook_event_name") == "Stop":
            print(json.dumps({"systemMessage": f"reduce hook error: {type(e).__name__}: {e}"}))
        else:
            print(f"reduce hook error: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
