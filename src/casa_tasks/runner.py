"""
runner.py — run one CASA task in the worker child process.

``run_task`` is what ``ms_inspect.util.dispatch.run_tool`` executes in a fresh
process. It calls ``casatasks.<task>(**params)`` unchanged and returns the
standard envelope with:

- the task's return value, converted to JSON types (numpy arrays to lists);
- the CASA log of this call only: WARN and SEVERE lines plus the last lines.
  CASA can return normally from a failed solve and report it only in the log.
- for casa-modify with ``stage`` and ``workdir``: one stage-log line.

A failure to write the stage-log line is a warning in the result, never an
error. The CASA task has already finished at that point; its result stands.

Imports neither mcp nor casatasks at module level: the child pays only for
what the call uses.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from casa_tasks.config import PRODUCT
from ms_inspect.util.logs import LOGFILE_ENV
from ms_inspect.util.stage_log import SCHEMA_VERSION, STAGE_LOG_NAME

#: Lines from the end of the per-call CASA log returned with every result.
LOG_TAIL_LINES = 30
#: Largest JSON text of the call parameters stored in one stage-log line.
MAX_LOGGED_PARAMS_CHARS = 2048


def to_jsonable(obj: Any) -> Any:
    """Convert a CASA return value to JSON types. numpy arrays become lists."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if hasattr(obj, "tolist"):  # numpy ndarray and numpy scalars
        return to_jsonable(obj.tolist())
    if isinstance(obj, bytes):
        return obj.decode(errors="replace")
    return str(obj)


def _call_log_path(task: str) -> str | None:
    """A CASA log file for this call, next to the server's CASA log. None if CASA is silenced."""
    server_log = os.environ.get(LOGFILE_ENV)
    if not server_log or server_log == os.devnull:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return str(Path(server_log).with_name(f"casa-{stamp}-{os.getpid()}-{task}.log"))


def _read_log(path: str | None) -> dict:
    """WARN/SEVERE lines and the last lines of the per-call log."""
    if path is None:
        return {"casa_log": None, "log_warnings": [], "log_tail": []}
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    warnings = [ln for ln in lines if "\tWARN\t" in ln or "\tSEVERE\t" in ln]
    return {"casa_log": path, "log_warnings": warnings, "log_tail": lines[-LOG_TAIL_LINES:]}


def product_path(task: str, params: dict) -> str | None:
    """Absolute path of the product a stage-log line checks, or None if not given."""
    param, suffixes = PRODUCT.get(task, ("vis", ("",)))
    value = params.get(param)
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value:
        return None
    candidates = [os.path.abspath(value + suffix) for suffix in suffixes]
    return next((c for c in candidates if os.path.exists(c)), candidates[0])


def record_stage_line(
    workdir: str, stage: str, task: str, params: dict, casa_log: str | None = None
) -> str | None:
    """Append one line to <workdir>/stage_log.jsonl. Return a warning, or None.

    Never raises. A missing product is recorded with ``exists: false`` (the log
    reader then does not count the stage as complete) and returned as a warning.
    """
    product = product_path(task, params)
    exists = product is not None and os.path.exists(product)
    params_text = json.dumps(params, default=str)
    entry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analyst_rev": os.environ.get("ANALYST_REV", "unknown"),
        "stage": stage,
        "product": product,
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exists": exists,
        "task": task,
        "params": params
        if len(params_text) <= MAX_LOGGED_PARAMS_CHARS
        else {"truncated": params_text[:MAX_LOGGED_PARAMS_CHARS]},
    }
    if casa_log:
        entry["casa_log"] = casa_log
    if not exists:
        entry["error"] = "product not found after the step that writes it"
    try:
        with open(os.path.join(workdir, STAGE_LOG_NAME), "a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        return f"stage log not written to {workdir!r}: {type(exc).__name__}: {exc}"
    if not exists:
        return (
            f"stage {stage!r}: product {product!r} does not exist after {task}; "
            "recorded as not complete"
        )
    return None


def run_task(
    task: str,
    params: dict,
    stage: str | None = None,
    workdir: str | None = None,
) -> dict:
    """Run casatasks.<task>(**params) and return the standard envelope."""
    started = time.monotonic()
    log_path = _call_log_path(task)
    if log_path is not None:
        from casaconfig import config

        config.logfile = log_path
    import casatasks

    ms_path = params.get("vis") if isinstance(params.get("vis"), str) else None
    call = f"casatasks.{task}(**params)"
    try:
        result = getattr(casatasks, task)(**params)
    except Exception as exc:  # noqa: BLE001 - every CASA failure goes back to the model
        return {
            "tool": task,
            "ms_path": ms_path,
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "data": {"params": params, **_read_log(log_path)},
            "provenance": {"casa_calls": [call]},
        }

    warnings: list[str] = []
    if stage is not None and workdir:
        warning = record_stage_line(workdir, stage, task, params, log_path)
        if warning:
            warnings.append(warning)
    elif stage is not None:
        warnings.append(f"stage {stage!r} given without workdir; nothing recorded")

    return {
        "tool": task,
        "ms_path": ms_path,
        "status": "ok",
        "completeness_summary": "COMPLETE",
        "data": {
            "params": params,
            "return": to_jsonable(result),
            "wall_time_s": round(time.monotonic() - started, 3),
            **_read_log(log_path),
        },
        "warnings": warnings,
        "provenance": {"casa_calls": [call]},
    }
