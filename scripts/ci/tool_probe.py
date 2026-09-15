#!/usr/bin/env python3
"""Layer 1: raw MCP stdio probe for a single tool.

Speaks MCP directly to one server (no LLM, no tokens) and calls one tool with
the args from tool_manifest.json. Ground truth for the harness in
tool_probe_llm.py -- both read the same manifest so they can't drift apart.

Pass criterion is deliberately loose: any well-formed MCP response counts,
whether the tool succeeded or returned its own error envelope. Only a
transport-level failure (crash, timeout, no response) is a probe failure.
Most manifest entries point non-MS tools at nonexistent files on purpose --
we're proving the server is alive and returns clean errors, not exercising
real science.

Runs identically in CI and locally:
    pixi run python scripts/ci/tool_probe.py --server ms-inspect --tool ms_observation_info --smoke-ms smoke.ms
"""
import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_manifest.json")

SERVE_SCRIPT = {
    "ms-inspect": "serve.sh",
    "ms-modify": "serve-modify.sh",
    "ms-create": "serve-create.sh",
}


def load_args(server: str, tool: str, smoke_ms: str) -> dict:
    manifest = json.load(open(MANIFEST_PATH))["tools"]
    if server not in manifest or tool not in manifest[server]:
        raise SystemExit(f"tool '{tool}' not found under server '{server}' in {MANIFEST_PATH}")
    raw = json.dumps(manifest[server][tool])
    filled = raw.replace("{SMOKE_MS}", os.path.abspath(smoke_ms))
    return json.loads(filled)


async def probe(server: str, tool: str, args: dict, timeout_s: float) -> dict:
    params = StdioServerParameters(
        command="bash",
        args=[os.path.join(REPO_ROOT, "bin", SERVE_SCRIPT[server])],
        env=dict(os.environ, RADIO_MCP_TRANSPORT="stdio"),
    )

    async def run() -> dict:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                if tool not in tools:
                    return {"probe_status": "FAIL", "reason": f"'{tool}' not advertised by {server}"}
                result = await session.call_tool(tool, {"params": args})
                text = result.content[0].text if result.content else ""
                return {
                    "probe_status": "PASS",
                    "is_error": bool(result.isError),
                    "response": text[:2000],
                }

    try:
        return await asyncio.wait_for(run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"probe_status": "FAIL", "reason": f"timed out after {timeout_s}s (no response)"}
    except Exception as exc:  # transport crash, not a tool error
        return {"probe_status": "FAIL", "reason": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, choices=sorted(SERVE_SCRIPT))
    ap.add_argument("--tool", required=True)
    ap.add_argument("--smoke-ms", default="smoke.ms")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", help="write JSON result here (default: stdout only)")
    args = ap.parse_args()

    tool_args = load_args(args.server, args.tool, args.smoke_ms)
    result = asyncio.run(probe(args.server, args.tool, tool_args, args.timeout))
    record = {"server": args.server, "tool": args.tool, "args_filled": tool_args, **result}

    print(json.dumps(record, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump(record, open(args.out, "w"), indent=2)

    return 0 if record["probe_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
