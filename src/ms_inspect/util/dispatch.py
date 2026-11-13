"""
util/dispatch.py — Shared MCP tool dispatch for all three servers.

Every `@mcp.tool` coroutine in ms_inspect, ms_modify, and ms_create funnels
through `run_tool()`. It provides three things that must not diverge between
the read, write, and ingest servers:

1. **One child process per call.** casacore is not thread-safe within one
   process, for the same table or for different ones: two calls at once can
   segfault the whole server. Each call runs in its own Python process
   (util/worker.py), so calls stay concurrent, a native crash ends only that
   call, and a cancelled call is killed.
2. **Per-path serialization.** Calls against the same resource path still run
   one at a time, so a read never overlaps a write on the same MS.
3. **A uniform error envelope.** RadioMSError becomes the documented error
   dict (design_docs/DESIGN.md §7.2); anything else propagates to FastMCP.
4. **One CASA log per call, read back.** CASA can return normally from a failed
   step and report the failure only in its log. Each call gets its own CASA
   log (util/logs.py); a SEVERE line logged inside a casatasks task makes the
   result SUSPECT, with the lines in a warning. Some tasks log SEVERE and still
   succeed, so SUSPECT asks the caller to read the lines; it is not a failure.

The envelope goes out twice in one result: as ``structuredContent`` for a
client that reads structured output, and as compact JSON text for one that
does not. An error envelope sets ``isError``, so the model sees a tool error it
can correct rather than a success whose status field says otherwise.

No CASA dependency.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
import weakref
from typing import Annotated, Any, Literal

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict

from ms_inspect.util.formatting import worst_flag
from ms_inspect.util.logs import LOGFILE_ENV, call_log_path, log_event
from ms_inspect.util.stage_log import casa_task_log

#: Most SEVERE lines copied into one result; the rest are in the CASA log.
MAX_SEVERE_LINES = 20

#: Part of every server's instructions: how to read flag_casa_severe's output.
CASA_LOG_NOTE = (
    "A result marked SUSPECT with a 'CASA logged N SEVERE line(s)' warning lists the "
    "lines in casa_severe; some CASA tasks log SEVERE and still succeed, so read them "
    "before acting. Ignore a SEVERE 'measures_update ... not maintained by casaconfig' "
    "line in a CASA log: it is a notice about the local CASA data setup, not a failure. "
)


# Loose on purpose: ``data`` differs per tool. The schema tells a client where
# status, completeness and warnings live; it does not re-validate each payload.
# No docstring: pydantic would ship it in every tool's schema on every listing.
class ToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "error"]
    tool: str | None = None
    ms_path: str | None = None
    completeness_summary: str | None = None
    data: Any = None
    warnings: list[Any] = []
    provenance: dict[str, Any] | None = None
    error_type: str | None = None
    message: str | None = None


#: Return annotation for every ``@mcp.tool`` coroutine. FastMCP reads the
#: second argument as the output schema and validates structuredContent against it.
ToolResult = Annotated[CallToolResult, ToolEnvelope]

# ---------------------------------------------------------------------------
# Per-resource locks
# ---------------------------------------------------------------------------

# One asyncio.Lock per resolved path, per event loop (an asyncio.Lock belongs to
# the loop it was first used on).
_PATH_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _is_plausible_lock_key(key: str) -> bool:
    """
    True if `key` can be a resource path — it exists, or it is path-shaped.

    Deliberately permissive about non-existence: tools validate their own paths
    and return a proper error envelope for a typo. What this rejects is a key
    that was never a path at all, e.g. an action verb passed as the first
    positional argument by a tool whose author did not know about `_lock_path`.
    """
    if os.path.exists(key):
        return True
    return os.sep in key or (os.altsep is not None and os.altsep in key)


def path_lock(path: str) -> asyncio.Lock:
    """Return this event loop's lock for `path`, creating it on first use."""
    # realpath: the same MS may be referenced via symlinked aliases
    # (e.g. /users/... -> /lustre/...); those must share one lock.
    path = os.path.realpath(path)
    locks = _PATH_LOCKS.setdefault(asyncio.get_running_loop(), {})
    lock = locks.get(path)
    if lock is None:
        lock = asyncio.Lock()
        locks[path] = lock
    return lock


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def envelope_result(envelope: dict) -> CallToolResult:
    """Wrap an envelope as a tool result: structured content plus compact text.

    The text is produced first and the structured content parsed back from it,
    so both carry exactly the same values (``default=str`` has already turned
    anything non-JSON into a string).
    """
    text = json.dumps(envelope, separators=(",", ":"), default=str)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=json.loads(text),
        isError=envelope.get("status") == "error",
    )


async def run_tool(
    tool_fn,
    *args,
    _lock_path: str | list[str] | None = None,
    _label: str | None = None,
    **kwargs,
) -> CallToolResult:
    """
    Execute a tool function in a child process; return the tool result.

    The tool must be a module-level function, because the child imports it by
    module and name. Arguments and results cross the process boundary as JSON;
    the parent wraps the child's JSON as a CallToolResult.

    Concurrent calls against the same resource path are serialized via a per-path
    lock. By default the resource is the first positional argument (MS, ASDM,
    image, or caltable), which is the convention every tool `run()` follows.
    Pass `_lock_path` explicitly for the few tools whose first argument is not
    the resource (e.g. `reduction_log.run(action, workdir, ...)`).

    Tools with neither a positional argument nor `_lock_path` run unserialized.

    `_lock_path` may be a list for a call that reads several resources (CASA
    concat). Each distinct resource is locked once, in sorted order of its
    resolved path, so two calls whose sets overlap take the shared locks in the
    same order, and an alias of a path already in the set is not locked twice
    (an asyncio.Lock is not reentrant). An empty list runs unlocked.

    `_label` names the call in events.jsonl, for a generic tool function that
    serves many tools.

    The convention is checked, not assumed: a key that is neither an existing
    path nor path-shaped raises, rather than silently locking on something
    meaningless. Failing open would drop serialization for that tool and surface
    later as an intermittent CASA crash under concurrency — far harder to
    diagnose than the error below. A path-shaped key that does not exist is
    passed through untouched, so a mistyped MS path still reaches the tool's own
    validation and returns the documented error envelope.
    """
    if _lock_path is not None:
        source = "_lock_path"
        raw_keys = [_lock_path] if isinstance(_lock_path, str) else list(_lock_path)
    else:
        source = "first positional argument"
        raw_keys = [str(args[0])] if args else []

    for lock_key in raw_keys:
        if _is_plausible_lock_key(lock_key):
            continue
        raise ValueError(
            f"run_tool: lock key from {source} is not a resource path: {lock_key!r} "
            f"(tool {getattr(tool_fn, '__module__', '?')}."
            f"{getattr(tool_fn, '__qualname__', tool_fn)}). Per-path serialization "
            "needs the MS/ASDM/image/caltable path; pass _lock_path explicitly for "
            "tools whose first argument is not the resource."
        )

    started = time.monotonic()
    status, error_type = "crash", None
    casa_log = call_log_path()
    drop_log = False
    try:
        async with contextlib.AsyncExitStack() as stack:
            for lock_key in sorted({os.path.realpath(k) for k in raw_keys}):
                await stack.enter_async_context(path_lock(lock_key))
            envelope = json.loads(await _run_in_child(tool_fn, args, kwargs, casa_log))
        status, error_type = envelope.get("status", "ok"), envelope.get("error_type")
        result = envelope_result(flag_casa_severe(envelope, casa_log))
        tasks, severe, _ = casa_task_log(casa_log)
        # Keep the CASA log when a casatasks task ran, when CASA logged SEVERE
        # (including casatools SEVERE lines outside any task), or when the call
        # failed: those logs carry diagnostic evidence referenced by the output.
        drop_log = status == "ok" and not tasks and not severe
        return result
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        logged_casa_log: str | None = casa_log
        if drop_log:
            with contextlib.suppress(OSError):
                os.unlink(casa_log)
            logged_casa_log = None
        log_event(
            tool=_label
            or f"{getattr(tool_fn, '__module__', '?')}.{getattr(tool_fn, '__qualname__', '?')}",
            resource=raw_keys[0] if len(raw_keys) == 1 else (raw_keys or None),
            status=status,
            error_type=error_type,
            duration_s=round(time.monotonic() - started, 3),
            casa_log=logged_casa_log,
        )


def flag_casa_severe(envelope: dict, casa_log: str) -> dict:
    """Mark a successful result SUSPECT when CASA logged SEVERE lines.

    Reads the call's own CASA log (both casatasks and casatools SEVERE lines,
    ignoring only the benign casaconfig import notice). Error envelopes and
    clean calls are returned unchanged.
    """
    if envelope.get("status") != "ok":
        return envelope
    tasks, severe, _ = casa_task_log(casa_log)
    if not severe:
        return envelope
    current = envelope.get("completeness_summary") or "COMPLETE"
    envelope["completeness_summary"] = worst_flag([current, "SUSPECT"])
    where = f" during {', '.join(dict.fromkeys(tasks))}" if tasks else ""
    envelope["warnings"] = [
        *(envelope.get("warnings") or []),
        f"CASA logged {len(severe)} SEVERE line(s){where}; "
        "see casa_severe. Some tasks log SEVERE and still succeed: read the lines "
        "before acting on the result.",
    ]
    envelope["casa_severe"] = {"casa_log": casa_log, "lines": severe[:MAX_SEVERE_LINES]}
    return envelope


def _tool_ref(tool_fn) -> tuple[str, str]:
    """Module and qualified name of a module-level function the child can import."""
    module = getattr(tool_fn, "__module__", None)
    qualname = getattr(tool_fn, "__qualname__", None)
    if not module or not qualname or "<locals>" in qualname:
        raise TypeError(
            f"run_tool: {tool_fn!r} is not an importable module-level function; "
            "the tool runs in a child process that imports it by module and name."
        )
    return module, qualname


async def _run_in_child(tool_fn, args: tuple, kwargs: dict, casa_log: str) -> str:
    """Run one tool call in a fresh process (util/worker.py) and return its JSON result."""
    module, qualname = _tool_ref(tool_fn)
    request = json.dumps({"module": module, "qualname": qualname, "args": args, "kwargs": kwargs})

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env[LOGFILE_ENV] = casa_log

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "ms_inspect.util.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await proc.communicate(request.encode())
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise

    name = f"{module}.{qualname}"
    if proc.returncode != 0 or not out:
        code = proc.returncode
        cause = f"signal {signal.Signals(-code).name}" if code and code < 0 else f"exit code {code}"
        tail = " | ".join(err.decode(errors="replace").strip().splitlines()[-5:])
        raise RuntimeError(
            f"{name} ended in its worker process with {cause}; the server is still "
            f"running and other calls are unaffected. CASA log: {casa_log}. "
            f"Last stderr: {tail or '(none)'}"
        )

    reply = json.loads(out)
    if "exception" in reply:
        exc = reply["exception"]
        raise RuntimeError(f"{exc['type']}: {exc['message']} (CASA log: {casa_log})")
    return reply["result"]
