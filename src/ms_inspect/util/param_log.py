"""
param_log.py — a per-workdir record of the arguments of every writing tool call.

Off unless ANALYST_PARAM_LOG is set to a non-empty value. When on, every call
to an ms_modify or ms_create tool that takes a ``workdir`` appends one line to
``<workdir>/param_log.jsonl``: the tool, the arguments the server passed, the
outcome, and the analyst revision. Failed calls are recorded too — a retry is
part of the choice the agent made, not noise.

A call with execute=False only writes a script; it does not prove the script
ran. So when a call returns a ``script_path``, that script is copied to
``<workdir>/param_log/`` under the call's id, with its sha256. A later script
run writes the sha256 of its own file into stage_log.jsonl, and the two are
joined by hash: a match means the generated script ran unchanged, a stage_log
line with the same product but another hash means the script was edited, and
no match means it never ran. The copy also survives the next call that writes
a script of the same name.

ms_inspect tools are skipped: almost none take a workdir, and their arguments
are selections rather than tuning choices.

Arguments are recorded as the server passed them, after the input model has
filled its defaults, so a value equal to the default cannot be told apart from
an omitted one here. Compare against the input-model defaults at the recorded
revision.

The record must never change a tool's result. A failure to write it goes to
stderr — the MCP server log — and the tool result is returned untouched.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import traceback
import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

#: Env var that turns the record on.
ENABLE_ENV = "ANALYST_PARAM_LOG"

#: Filename and snapshot directory, both relative to the workdir.
PARAM_LOG_NAME = "param_log.jsonl"
SNAPSHOT_DIR = "param_log"

#: Packages whose tools are recorded.
_RECORDED_PACKAGES = ("ms_modify", "ms_create")


def enabled() -> bool:
    return bool(os.environ.get(ENABLE_ENV))


@cache
def analyst_rev() -> dict:
    """Git revision of the running source, and whether the tree had local edits.

    Uncommitted edits can change defaults, so ``dirty`` must travel with ``rev``.
    Outside a git checkout both are None.
    """
    here = Path(__file__).resolve().parent

    def _git(*cmd: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(here), *cmd],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    rev = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no") if rev else None
    return {"rev": rev, "dirty": None if status is None else bool(status)}


def _named_args(tool_fn, args: tuple, kwargs: dict) -> dict:
    """Bind the call to the tool's signature, without filling its defaults."""
    try:
        bound = inspect.signature(tool_fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return {"_args": list(args), **kwargs}
    return dict(bound.arguments)


def _unwrap(value):
    """A field() wrapper's value, or the value itself."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(script_path: str, workdir: Path, call_id: str) -> dict:
    src = Path(script_path)
    if not src.is_file():
        return {"script_path": script_path, "script_sha256": None}
    dest_dir = workdir / SNAPSHOT_DIR
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / f"{call_id}_{src.name}"
    shutil.copy2(src, dest)
    return {
        "script_path": script_path,
        "script_sha256": _sha256(dest),
        "script_snapshot": str(dest),
    }


def record_call(tool_fn, args: tuple, kwargs: dict, result=None, error=None) -> None:
    """Append one line for this call, if the record is on and the tool qualifies.

    ``result`` is the tool's envelope on success, or the error envelope of a
    RadioMSError. ``error`` is any other exception the tool raised.
    """
    if not enabled():
        return
    module = getattr(tool_fn, "__module__", "") or ""
    if not module.startswith(_RECORDED_PACKAGES):
        return
    try:
        named = _named_args(tool_fn, args, kwargs)
        workdir = named.get("workdir")
        if not workdir or not Path(workdir).is_dir():
            return
        workdir = Path(workdir)
        call_id = uuid.uuid4().hex[:12]

        line: dict = {
            "call_id": call_id,
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "tool": f"{module}.{getattr(tool_fn, '__qualname__', '?')}",
            "args": named,
            **analyst_rev(),
        }
        if error is not None:
            line["status"] = "exception"
            line["error"] = f"{type(error).__name__}: {error}"
        elif isinstance(result, dict):
            line["status"] = result.get("status", "unknown")
            if line["status"] == "error":
                line["error"] = f"{result.get('error_type')}: {result.get('message')}"
            data = result.get("data")
            script_path = _unwrap(data.get("script_path")) if isinstance(data, dict) else None
            if isinstance(script_path, str):
                line.update(_snapshot(script_path, workdir, call_id))
        else:
            line["status"] = "unknown"

        with open(workdir / PARAM_LOG_NAME, "a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        print(
            f"param_log: failed to record a call to {module}:\n{traceback.format_exc()}",
            file=sys.stderr,
        )
