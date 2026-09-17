#!/usr/bin/env python3
"""CI-only: merge per-tool Layer 1 (+ optional Layer 2) JSON artifacts,
downloaded into one directory tree, into a single CSV lookup table.

    python scripts/ci/merge_tool_report.py --results-dir downloaded-artifacts --out tool_probe_report.csv
"""

import argparse
import csv
import glob
import json
import os


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--out", default="tool_probe_report.csv")
    args = ap.parse_args()

    layer1_files = sorted(
        glob.glob(os.path.join(args.results_dir, "**", "*.layer1.json"), recursive=True)
    )
    layer2_by_tool = {}
    for path in glob.glob(os.path.join(args.results_dir, "**", "*.layer2.json"), recursive=True):
        record = json.load(open(path))
        layer2_by_tool[record["tool"]] = record.get("llm_reported", "")

    rows = []
    for path in layer1_files:
        record = json.load(open(path))
        rows.append(
            {
                "tool": record["tool"],
                "server": record["server"],
                "args_filled": json.dumps(record.get("args_filled", {})),
                "raw_status": record["probe_status"],
                "raw_response": record.get("response") or record.get("reason", ""),
                "llm_reported": layer2_by_tool.get(record["tool"], ""),
            }
        )

    rows.sort(key=lambda r: (r["server"], r["tool"]))
    with open(args.out, "w", newline="") as fh:
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

    failed = [r["tool"] for r in rows if r["raw_status"] != "PASS"]
    print(f"{len(rows)} tools, {len(failed)} failed layer 1: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
