"""
Module-level tools for test_server_locking.py.

run_tool executes each call in a child process that imports the tool by module
and name, so test tools must live at module level. Overlap is measured across
processes: each call writes its start and end time to a file in `record_dir`.
"""

from __future__ import annotations

import os
import signal
import time
import uuid
from pathlib import Path


def record(path: str, record_dir: str, duration: float = 0.3) -> dict:
    start = time.time()
    time.sleep(duration)
    end = time.time()
    Path(record_dir, uuid.uuid4().hex).write_text(f"{start} {end}")
    return {"ms_path": path}


def record_action(action: str, workdir: str, record_dir: str, duration: float = 0.3) -> dict:
    return record(workdir, record_dir, duration)


def max_overlap(record_dir: str) -> int:
    """Largest number of recorded calls that were running at one instant."""
    spans = [tuple(map(float, p.read_text().split())) for p in Path(record_dir).iterdir()]
    events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans])
    active = peak = 0
    for _, step in events:
        active += step
        peak = max(peak, active)
    return peak


def slow(path: str) -> dict:
    time.sleep(0.5)
    return {"ms_path": path}


def crash(path: str) -> dict:
    os.kill(os.getpid(), signal.SIGSEGV)
    return {}


def raise_value_error(path: str) -> dict:
    raise ValueError("bad value from the tool")


def print_to_stdout(path: str) -> dict:
    print("noise that CASA would print")
    os.write(1, b"noise from C++\n")
    return {"ms_path": path}


def pid(path: str) -> dict:
    return {"pid": os.getpid()}
