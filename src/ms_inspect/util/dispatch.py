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

from ms_inspect.exceptions import RadioMSError
from ms_inspect.util.formatting import compact_fields
from ms_inspect.util.worker import LOGFILE_ENV

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


_casa_logfile: str | None = None


def _casa_logfile_path() -> str:
    """One CASA log per server process, in its working directory, named as CASA names it."""
    global _casa_logfile
    if _casa_logfile is None:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        _casa_logfile = os.path.abspath(f"casa-{stamp}.log")
    return _casa_logfile


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def run_tool_sync(tool_fn, *args, **kwargs) -> str:
    """
    Run `tool_fn` and JSON-encode its result. Called in the worker process.

    RadioMSError is converted to the documented error envelope. Any other
    exception is re-raised for FastMCP to surface as a tool error.
    """
    try:
        result = tool_fn(*args, **kwargs)
        return json.dumps(compact_fields(result), separators=(",", ":"), default=str)
    except RadioMSError as e:
        return json.dumps(e.to_dict(), separators=(",", ":"), default=str)


async def run_tool(tool_fn, *args, _lock_path: str | None = None, **kwargs) -> str:
    """
    Execute a tool function in a child process; return JSON-encoded result.

    The tool must be a module-level function, because the child imports it by
    module and name. Arguments and results cross the process boundary as JSON.

    Concurrent calls against the same resource path are serialized via a per-path
    lock. By default the resource is the first positional argument (MS, ASDM,
    image, or caltable), which is the convention every tool `run()` follows.
    Pass `_lock_path` explicitly for the few tools whose first argument is not
    the resource (e.g. `reduction_log.run(action, workdir, ...)`).

    Tools with neither a positional argument nor `_lock_path` run unserialized.

    The convention is checked, not assumed: a key that is neither an existing
    path nor path-shaped raises, rather than silently locking on something
    meaningless. Failing open would drop serialization for that tool and surface
    later as an intermittent CASA crash under concurrency — far harder to
    diagnose than the error below. A path-shaped key that does not exist is
    passed through untouched, so a mistyped MS path still reaches the tool's own
    validation and returns the documented error envelope.
    """
    lock_key = _lock_path if _lock_path is not None else (str(args[0]) if args else None)

    if lock_key is not None and not _is_plausible_lock_key(lock_key):
        source = "_lock_path" if _lock_path is not None else "first positional argument"
        raise ValueError(
            f"run_tool: lock key from {source} is not a resource path: {lock_key!r} "
            f"(tool {getattr(tool_fn, '__module__', '?')}."
            f"{getattr(tool_fn, '__qualname__', tool_fn)}). Per-path serialization "
            "needs the MS/ASDM/image/caltable path; pass _lock_path explicitly for "
            "tools whose first argument is not the resource."
        )

    async with contextlib.AsyncExitStack() as stack:
        if lock_key is not None:
            await stack.enter_async_context(path_lock(lock_key))
        return await _run_in_child(tool_fn, args, kwargs)


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


async def _run_in_child(tool_fn, args: tuple, kwargs: dict) -> str:
    """Run one tool call in a fresh process (util/worker.py) and return its JSON result."""
    module, qualname = _tool_ref(tool_fn)
    request = json.dumps({"module": module, "qualname": qualname, "args": args, "kwargs": kwargs})

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env[LOGFILE_ENV] = _casa_logfile_path()

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
            f"running and other calls are unaffected. Last stderr: {tail or '(none)'}"
        )

    reply = json.loads(out)
    if "exception" in reply:
        exc = reply["exception"]
        raise RuntimeError(f"{exc['type']}: {exc['message']}")
    return reply["result"]
