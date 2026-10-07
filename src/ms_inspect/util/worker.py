"""
util/worker.py — Child-process entry point for one tool call.

Run as ``python -m ms_inspect.util.worker``. Reads one JSON request on stdin:

    {"module": ..., "qualname": ..., "args": [...], "kwargs": {...}}

imports the tool function, runs it through ``run_tool_sync`` and writes one JSON
reply to the original stdout:

    {"result": "<JSON-encoded tool result>"}                    on success
    {"exception": {"type": ..., "message": ...}}                on a raised error

CASA prints to stdout from C++ and Python alike, so stdout is moved to stderr
before anything is imported; only the reply goes to the saved descriptor.

The CASA log file is taken from ``_ANALYST_CASA_LOGFILE`` (set by the parent) so
every call from one server appends to one log, as a single in-process server did.
"""

from __future__ import annotations

import importlib
import json
import os
import sys

LOGFILE_ENV = "_ANALYST_CASA_LOGFILE"


def _set_casa_logfile() -> None:
    """Point casatools at the parent's log file. casatools reads it once, at import."""
    logfile = os.environ.get(LOGFILE_ENV)
    if not logfile:
        return
    try:
        from casaconfig import config
    except ImportError:
        return
    config.logfile = logfile


def _resolve(module: str, qualname: str):
    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def main() -> int:
    reply_fd = os.dup(1)
    os.dup2(2, 1)
    request = json.loads(sys.stdin.read())

    _set_casa_logfile()

    from ms_inspect.util.dispatch import run_tool_sync

    try:
        tool_fn = _resolve(request["module"], request["qualname"])
        reply = {"result": run_tool_sync(tool_fn, *request["args"], **request["kwargs"])}
    except Exception as exc:  # noqa: BLE001 - every error is returned to the parent
        reply = {"exception": {"type": type(exc).__name__, "message": str(exc)}}

    sys.stdout.flush()
    with os.fdopen(reply_fd, "w") as out:
        json.dump(reply, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
