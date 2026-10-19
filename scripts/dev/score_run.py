#!/usr/bin/env python3
"""Score one run dir against the reduce contract (.claude/skills/reduce/stages.json).

Reads <run>/trace.jsonl (claude -p stream-json) and <run>/workdir/reduction_log.jsonl.
For each contract step: the action call that worked (last ok call), each before/after
check (OK = called in its window, CACHED = earlier ok call not invalidated since,
STALE = invalidated since, MISSING), and whether a ledger append followed. Stdlib only.

Usage: score_run.py <run_dir> [--stages path/to/stages.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from reduce_contract import CONTRACT, calls_from_trace, score  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--stages", type=Path, default=CONTRACT)
    a = ap.parse_args()

    r = score(calls_from_trace(a.run_dir / "trace.jsonl"), json.loads(a.stages.read_text()))
    print("\n".join(r["lines"]))
    log = a.run_dir / "workdir" / "reduction_log.jsonl"
    n_led = sum(1 for ln in log.open() if ln.strip()) if log.exists() else 0
    (na, ta), (nc, tc) = r["actions"], r["checks"]
    print(f"\nactions called {na}/{ta}, checks satisfied {nc}/{tc}, ledger entries {n_led}")
    print(
        "note: a check is not matched to its action's ms_path or field; caltable/image paths are."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
