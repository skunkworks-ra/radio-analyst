"""
Unit tests for the shared tool dispatch used by all three MCP servers.

Each call runs in its own child process. Concurrent calls against the same
resource path must not overlap; calls against different paths may run
concurrently. A crash or cancellation in one call must not take down the server.
The write servers (ms_modify, ms_create) get the same guarantees as ms_inspect.
"""

from __future__ import annotations

import asyncio
import json
import os

import dispatch_tools as dt
import pytest

from ms_create.server import _run_tool as create_run_tool
from ms_inspect.server import _run_tool
from ms_inspect.util.dispatch import run_tool
from ms_modify.server import _run_tool as modify_run_tool


def test_same_path_serialized(tmp_path):
    async def go():
        await asyncio.gather(*[_run_tool(dt.record, "/data/a.ms", str(tmp_path)) for _ in range(3)])

    asyncio.run(go())
    assert dt.max_overlap(str(tmp_path)) == 1


def test_different_paths_concurrent(tmp_path):
    async def go():
        await asyncio.gather(
            _run_tool(dt.record, "/data/a.ms", str(tmp_path), 1.0),
            _run_tool(dt.record, "/data/b.ms", str(tmp_path), 1.0),
        )

    asyncio.run(go())
    assert dt.max_overlap(str(tmp_path)) == 2


@pytest.mark.parametrize(
    "dispatch",
    [_run_tool, modify_run_tool, create_run_tool],
    ids=["inspect", "modify", "create"],
)
def test_all_servers_share_one_dispatch(dispatch, tmp_path):
    """All three servers must serialize identically — same object, same lock table."""
    assert dispatch is run_tool

    async def go():
        await asyncio.gather(
            *[dispatch(dt.record, "/data/shared.ms", str(tmp_path)) for _ in range(3)]
        )

    asyncio.run(go())
    assert dt.max_overlap(str(tmp_path)) == 1


def test_lock_shared_across_servers(tmp_path):
    """A read on an MS must not run while a write on the same MS is in flight."""

    async def go():
        await asyncio.gather(
            modify_run_tool(dt.record, "/data/same.ms", str(tmp_path)),
            _run_tool(dt.record, "/data/same.ms", str(tmp_path)),
            create_run_tool(dt.record, "/data/same.ms", str(tmp_path)),
        )

    asyncio.run(go())
    assert dt.max_overlap(str(tmp_path)) == 1


def test_explicit_lock_path_overrides_first_arg(tmp_path):
    """Tools whose first arg is not the resource (reduction_log) lock on _lock_path."""

    async def go():
        # Different first args ('append' vs 'render'), same workdir → must serialize.
        await asyncio.gather(
            run_tool(
                dt.record_action, "append", "/work/run1", str(tmp_path), _lock_path="/work/run1"
            ),
            run_tool(
                dt.record_action, "render", "/work/run1", str(tmp_path), _lock_path="/work/run1"
            ),
        )

    asyncio.run(go())
    assert dt.max_overlap(str(tmp_path)) == 1


def test_does_not_block_event_loop():
    """A long tool call must not stall the event loop — other coroutines keep running."""
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    async def go():
        await asyncio.gather(modify_run_tool(dt.slow, "/data/slow.ms"), ticker())

    asyncio.run(go())
    assert ticks == 20


def test_non_path_lock_key_raises(tmp_path):
    """A first positional arg that was never a path must fail loudly, not lock on junk.

    The failure mode being guarded: a tool whose first arg is an action verb,
    whose author did not know to pass _lock_path, would otherwise serialize on
    'append' — i.e. not at all with respect to the MS.
    """

    async def go():
        await run_tool(dt.record_action, "append", "/work/run1", str(tmp_path))

    with pytest.raises(ValueError, match="not a resource path"):
        asyncio.run(go())


def test_nonexistent_but_path_shaped_key_is_allowed(tmp_path):
    """A mistyped MS path reaches the tool, which returns the documented envelope."""

    async def go():
        return await _run_tool(dt.record, "/data/typo-does-not-exist.ms", str(tmp_path), 0.0)

    assert "typo-does-not-exist.ms" in asyncio.run(go())


# ---------------------------------------------------------------------------
# Child-process behaviour
# ---------------------------------------------------------------------------


def test_each_call_runs_in_its_own_process():
    async def go():
        return await asyncio.gather(
            _run_tool(dt.pid, "/data/a.ms"), _run_tool(dt.pid, "/data/b.ms")
        )

    pids = {json.loads(r)["pid"] for r in asyncio.run(go())}
    assert len(pids) == 2 and os.getpid() not in pids


def test_a_crash_ends_only_that_call():
    async def go():
        crashed = _run_tool(dt.crash, "/data/a.ms")
        healthy = _run_tool(dt.slow, "/data/b.ms")
        return await asyncio.gather(crashed, healthy, return_exceptions=True)

    crashed, healthy = asyncio.run(go())
    assert isinstance(crashed, RuntimeError) and "SIGSEGV" in str(crashed)
    assert "b.ms" in healthy
    assert "b.ms" in asyncio.run(_run_tool(dt.slow, "/data/b.ms"))


def test_tool_exception_is_raised_with_its_type_and_message():
    with pytest.raises(RuntimeError, match="ValueError: bad value from the tool"):
        asyncio.run(_run_tool(dt.raise_value_error, "/data/a.ms"))


def test_stdout_noise_does_not_corrupt_the_result():
    assert (
        json.loads(asyncio.run(_run_tool(dt.print_to_stdout, "/data/a.ms")))["ms_path"]
        == "/data/a.ms"
    )


def test_cancelled_call_kills_its_child(tmp_path):
    async def go():
        task = asyncio.create_task(_run_tool(dt.record, "/data/a.ms", str(tmp_path), 3.0))
        await asyncio.sleep(1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(3.0)

    asyncio.run(go())
    assert list(tmp_path.iterdir()) == []


def test_local_function_is_refused():
    def local(path):
        return {}

    with pytest.raises(TypeError, match="not an importable module-level function"):
        asyncio.run(_run_tool(local, "/data/a.ms"))
