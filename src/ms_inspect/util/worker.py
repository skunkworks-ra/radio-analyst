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

The CASA log file is taken from ``_ANALYST_CASA_LOGFILE``: the parent gives each
call its own log, and reads it back after the call (util/dispatch.py).
Importing ms_inspect applies it (see util/logs.py); without it CASA is silenced.
"""

from __future__ import annotations

import importlib
import json
import os
import sys

from ms_inspect.util.logs import LOGFILE_ENV, configure_casa_log


def _resolve(module: str, qualname: str):
    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _run_tool_with_provenance(tool_fn, *args, **kwargs) -> tuple[str, dict | None]:
    """Run `tool_fn`, returning `(wire_json, provenance)`."""
    from ms_inspect.exceptions import RadioMSError
    from ms_inspect.util.formatting import wire_envelope

    try:
        result = tool_fn(*args, **kwargs)
        provenance = result.get("provenance") if isinstance(result, dict) else None
        return (
            json.dumps(wire_envelope(result), separators=(",", ":"), default=str),
            provenance,
        )
    except RadioMSError as e:
        return (
            json.dumps(
                {**e.to_dict(), "log_path": os.environ.get(LOGFILE_ENV)},
                separators=(",", ":"),
                default=str,
            ),
            None,
        )


def run_tool_sync(tool_fn, *args, **kwargs) -> str:
    """
    Run `tool_fn` and JSON-encode its symmetric wire envelope.

    Here rather than in util/dispatch.py so the child never imports mcp or
    pydantic (about 0.3 s per call). RadioMSError is converted to the
    documented error envelope. Any other exception is re-raised.
    """
    wire_json, _ = _run_tool_with_provenance(tool_fn, *args, **kwargs)
    return wire_json


def main() -> int:
    reply_fd = os.dup(1)
    os.dup2(2, 1)
    request = json.loads(sys.stdin.read())

    configure_casa_log()

    try:
        tool_fn = _resolve(request["module"], request["qualname"])
        wire_json, provenance = _run_tool_with_provenance(
            tool_fn, *request["args"], **request["kwargs"]
        )
        reply: dict = {"result": wire_json}
        if provenance is not None:
            reply["provenance"] = provenance
    except Exception as exc:  # noqa: BLE001 - every error is returned to the parent
        reply = {"exception": {"type": type(exc).__name__, "message": str(exc)}}

    sys.stdout.flush()
    with os.fdopen(reply_fd, "w") as out:
        json.dump(reply, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
