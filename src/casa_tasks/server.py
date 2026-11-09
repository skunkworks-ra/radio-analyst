"""
server.py — the casa-inspect and casa-modify MCP servers.

One tool per CASA task; the tool name is the task name. Each server is a
FastMCP object whose list-tools and call-tools handlers are replaced, for one
reason: FastMCP builds its argument model from a Python signature and silently
drops an argument it does not know, so a misspelled CASA parameter would run
with the default. The replaced handlers list the JSON schemas from catalog.py
with ``additionalProperties: false``, and the MCP SDK validates every call
against them before the handler runs: an unknown parameter is an error.

Replacing the handlers also hides any ``@mcp.tool`` tools on the same object,
so these servers hold CASA tasks only.

Calls go through ms_inspect.util.dispatch.run_tool: one child process per call,
serialized per Measurement Set.
"""

from __future__ import annotations

import os
import sys

from mcp import types
from mcp.server.fastmcp import FastMCP

from casa_tasks.catalog import build_catalog, use_mcp
from casa_tasks.config import WRAPPER_PARAMS
from casa_tasks.runner import run_task
from ms_inspect.util.dispatch import envelope_result, run_tool
from ms_inspect.util.formatting import error_envelope
from ms_inspect.util.logs import init_server_logging

#: HTTP port when RADIO_MCP_PORT is unset; the ms-* servers use 8000-8002.
_DEFAULT_PORT = {"inspect": 8003, "modify": 8004}

#: Parameters whose value names the resource a call is serialized on, in order.
_LOCK_PARAMS = ("vis", "imagename", "caltable", "asdm")


def lock_path(params: dict) -> str | None:
    """Absolute path of the resource a call locks on, or None to run unlocked."""
    for name in _LOCK_PARAMS:
        value = params.get(name)
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, str) and value:
            return os.path.abspath(value)
    return None


def build_server(kind: str, restricted: bool | None = None) -> FastMCP:
    """A FastMCP server listing the CASA tasks of one kind ('inspect' or 'modify')."""
    restricted = use_mcp() if restricted is None else restricted
    catalog = build_catalog(kind, restricted)
    tools = [
        types.Tool(
            name=task,
            description=spec["description"],
            inputSchema=spec["inputSchema"],
            annotations=types.ToolAnnotations(readOnlyHint=kind == "inspect"),
        )
        for task, spec in catalog.items()
    ]
    mcp = FastMCP(f"casa-{kind}")
    low = mcp._mcp_server

    @low.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tools

    @low.call_tool()
    async def _call_tool(name: str, arguments: dict) -> types.CallToolResult:
        if name not in catalog:
            return envelope_result(
                error_envelope(name, None, "UnknownTool", f"casa-{kind} has no tool {name!r}")
            )
        params = dict(arguments or {})
        wrapper = (
            {k: params.pop(k) for k in WRAPPER_PARAMS if k in params} if kind == "modify" else {}
        )
        try:
            return await run_tool(
                run_task,
                task=name,
                params=params,
                stage=wrapper.get("stage"),
                workdir=wrapper.get("workdir"),
                _lock_path=lock_path(params),
                _label=f"casa-{kind}.{name}",
            )
        except Exception as exc:  # noqa: BLE001 - a crashed child is a tool error, not a server error
            vis = params.get("vis") if isinstance(params.get("vis"), str) else None
            return envelope_result(error_envelope(name, vis, type(exc).__name__, str(exc)))

    return mcp


def _main(kind: str) -> None:
    init_server_logging(f"casa-{kind}")
    mcp = build_server(kind)
    if os.environ.get("RADIO_MCP_TRANSPORT", "stdio").lower() == "http":
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = int(os.environ.get("RADIO_MCP_PORT", _DEFAULT_PORT[kind]))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


def main_inspect() -> None:
    _main("inspect")


def main_modify() -> None:
    _main("modify")


if __name__ == "__main__":
    _main(sys.argv[1] if len(sys.argv) > 1 else "modify")
