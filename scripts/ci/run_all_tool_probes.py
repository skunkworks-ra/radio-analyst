#!/usr/bin/env python3
"""Local runner: Layer 1 (always) + Layer 2 (optional) across all 52 tools.

    pixi run test-tool-probe                       # layer 1 only
    pixi run test-tool-probe --llm                  # layer 1 + layer 2

Writes results/tool_probe_report.csv -- the same lookup table the CI
matrix + merge job produces: tool | server | args_filled | raw_status |
raw_response | llm_reported (blank unless --llm).
"""

import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "tool_manifest.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-ms", default="smoke.ms")
    ap.add_argument("--llm", action="store_true", help="also run layer 2 (spends tokens)")
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    manifest = json.load(open(MANIFEST_PATH))["tools"]
    os.makedirs(args.out_dir, exist_ok=True)
    rows = []
    failures = 0

    for server, tools in manifest.items():
        for tool in tools:
            out_path = os.path.join(args.out_dir, f"{tool}.layer1.json")
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(HERE, "tool_probe.py"),
                    "--server",
                    server,
                    "--tool",
                    tool,
                    "--smoke-ms",
                    args.smoke_ms,
                    "--out",
                    out_path,
                ],
                capture_output=True,
                text=True,
            )
            record = json.load(open(out_path))
            if record["probe_status"] != "PASS":
                failures += 1

            llm_reported = ""
            if args.llm:
                llm_out = os.path.join(args.out_dir, f"{tool}.layer2.json")
                llm_proc = subprocess.run(
                    [
                        sys.executable,
                        os.path.join(HERE, "tool_probe_llm.py"),
                        "--server",
                        server,
                        "--tool",
                        tool,
                        "--smoke-ms",
                        args.smoke_ms,
                        "--out",
                        llm_out,
                    ],
                    capture_output=True,
                    text=True,
                )
                if os.path.exists(llm_out):
                    llm_reported = json.load(open(llm_out)).get("llm_reported", "")

            rows.append(
                {
                    "tool": tool,
                    "server": server,
                    "args_filled": json.dumps(record.get("args_filled", {})),
                    "raw_status": record["probe_status"],
                    "raw_response": record.get("response") or record.get("reason", ""),
                    "llm_reported": llm_reported,
                }
            )
            print(f"{record['probe_status']:4s} {server:10s} {tool}")

    report_path = os.path.join(args.out_dir, "tool_probe_report.csv")
    with open(report_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "tool",
                "server",
                "args_filled",
                "raw_status",
                "raw_response",
                "llm_reported",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} tools probed, {failures} failed. Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
