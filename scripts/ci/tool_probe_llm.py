#!/usr/bin/env python3
"""Layer 2 (optional, costs tokens): drive one tool through `claude -p` and
record what the LLM reports back, next to the manifest args it was told to
use. Meant to sit side by side with tool_probe.py's raw MCP ground truth so a
harness can diff "what the tool actually returned" vs "what the model says
it returned" -- useful for catching tool-use hallucination, not just outages.

`cli_status` reflects only whether the `claude -p` invocation itself ran to
completion and returned parseable output. It says nothing about whether the
underlying tool call succeeded -- a tool that returns an error, or even a
schema-validation rejection, still leaves `cli_status: PASS` if the CLI
reported back cleanly. tool_probe.py's `probe_status` is the ground truth for
tool-call outcome; read `llm_reported` here to see what the model said
happened, and diff it against tool_probe.py's `response` for that tool.

    pixi run python scripts/ci/tool_probe_llm.py --server ms-inspect --tool ms_observation_info --smoke-ms smoke.ms
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MANIFEST_PATH = os.path.join(HERE, "tool_manifest.json")

MCP_SERVER_NAME = {"ms-inspect": "ms-inspect", "ms-modify": "ms-modify", "ms-create": "ms-create"}


def load_args(server: str, tool: str, smoke_ms: str) -> dict:
    manifest = json.load(open(MANIFEST_PATH))["tools"]
    if server not in manifest or tool not in manifest[server]:
        raise SystemExit(f"tool '{tool}' not found under server '{server}' in {MANIFEST_PATH}")
    raw = json.dumps(manifest[server][tool])
    filled = raw.replace("{SMOKE_MS}", os.path.abspath(smoke_ms))
    return json.loads(filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, choices=sorted(MCP_SERVER_NAME))
    ap.add_argument("--tool", required=True)
    ap.add_argument("--smoke-ms", default="smoke.ms")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--out")
    args = ap.parse_args()

    tool_args = load_args(args.server, args.tool, args.smoke_ms)
    allowed = f"mcp__{args.server}__{args.tool}"
    prompt = (
        f"Call the {args.tool} tool from the {args.server} MCP server with exactly "
        f"these params: {json.dumps(tool_args)}. Report the tool's response verbatim, "
        f"including if it returned an error -- do not summarize or interpret it."
    )

    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=REPO_ROOT)
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            args.model,
            "--mcp-config",
            os.path.join(REPO_ROOT, ".mcp.json"),
            "--allowed-tools",
            allowed,
            "--permission-prompts",
            "none",
            "--strict-mcp-config",
            "--output-format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    llm_reported = ""
    cli_status = "FAIL"
    try:
        payload = json.loads(proc.stdout)
        llm_reported = payload.get("result", proc.stdout)
        cli_status = "PASS" if proc.returncode == 0 else "FAIL"
    except json.JSONDecodeError:
        llm_reported = proc.stdout or proc.stderr

    record = {
        "server": args.server,
        "tool": args.tool,
        "args_filled": tool_args,
        "cli_status": cli_status,
        "llm_reported": llm_reported[:2000] if isinstance(llm_reported, str) else llm_reported,
    }
    print(json.dumps(record, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump(record, open(args.out, "w"), indent=2)
    return 0 if cli_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
