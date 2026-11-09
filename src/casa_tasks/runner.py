"""
runner.py — run one CASA task in the worker child process.

``run_task`` is what ``ms_inspect.util.dispatch.run_tool`` executes in a fresh
process. It calls ``casatasks.<task>(**params)`` unchanged and returns the
standard envelope with:

- the task's return value, converted to JSON types (numpy arrays to lists);
- the CASA log of this call only: WARN and SEVERE lines plus the last lines.
  CASA can return normally from a failed solve and report it only in the log.
  If the task itself logged a SEVERE line, completeness_summary is SUSPECT.
- for casa-modify with ``stage`` and ``workdir``: one stage-log line.

A failure to write the stage-log line is a warning in the result, never an
error. The CASA task has already finished at that point; its result stands.

Imports neither mcp nor casatasks at module level: the child pays only for
what the call uses.
"""

from __future__ import annotations

import json
import os
import re
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


def _log_lines(path: str | None) -> list[str]:
    """Lines of the per-call log; empty if there is none."""
    if path is None:
        return []
    try:
        return Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return []


def _log_fields(path: str | None, lines: list[str]) -> dict:
    """WARN/SEVERE lines and the last lines of the per-call log."""
    warnings = [ln for ln in lines if "\tWARN\t" in ln or "\tSEVERE\t" in ln]
    return {"casa_log": path, "log_warnings": warnings, "log_tail": lines[-LOG_TAIL_LINES:]}


def task_severe_lines(task: str, lines: list[str]) -> list[str]:
    """SEVERE lines the task itself logged, not the notices of the CASA import.

    casatasks writes '##### Begin Task: <task> #####' when the task starts; only
    lines from there on count. If the marker is absent (a log level above INFO
    suppresses it), every SEVERE line counts except the casaconfig
    measures_update notice.
    """
    marker = re.compile(rf"Begin Task: {re.escape(task)}\s+#####")
    start = next((i for i, ln in enumerate(lines) if marker.search(ln)), None)
    if start is None:
        return [ln for ln in lines if "\tSEVERE\t" in ln and "measures_update" not in ln]
    return [ln for ln in lines[start:] if "\tSEVERE\t" in ln]


def product_path(task: str, params: dict) -> str | None:
    """Absolute path of the product a stage-log line checks, or None if not given."""
    param, suffixes = PRODUCT.get(task, ("vis", ("",)))
    value = params.get(param)
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str) or not value:
        return None
    candidates = [os.path.abspath(os.path.expanduser(value + suffix)) for suffix in suffixes]
    return next((c for c in candidates if os.path.exists(c)), candidates[0])


def record_stage_line(
    workdir: str,
    stage: str,
    task: str,
    params: dict,
    casa_log: str | None = None,
    severe_lines: int = 0,
) -> str | None:
    """Append one line to <workdir>/stage_log.jsonl. Return a warning, or None.

    Never raises. A missing product is recorded with ``exists: false`` (the log
    reader then does not count the stage as complete) and returned as a warning.
    ``severe_lines`` is recorded when non-zero; it does not change ``exists``.
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
    if severe_lines:
        entry["severe_lines"] = severe_lines
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
    log_path: str | None = None,
) -> dict:
    """Run casatasks.<task>(**params) and return the standard envelope.

    ``log_path`` is this call's CASA log. The server chooses it, so it can name
    the file even when the child dies before it returns.
    """
    started = time.monotonic()
    log_path = log_path or _call_log_path(task)
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
            "data": {"params": params, **_log_fields(log_path, _log_lines(log_path))},
            "provenance": {"casa_calls": [call]},
        }

    lines = _log_lines(log_path)
    severe = task_severe_lines(task, lines)
    warnings: list[str] = []
    if severe:
        warnings.append(
            f"CASA logged {len(severe)} SEVERE line(s) during {task}; see log_warnings. "
            "Some tasks log SEVERE and still succeed: read the lines before acting."
        )
    if stage is not None and workdir:
        warning = record_stage_line(workdir, stage, task, params, log_path, len(severe))
        if warning:
            warnings.append(warning)
    elif stage is not None:
        warnings.append(f"stage {stage!r} given without workdir; nothing recorded")

    return {
        "tool": task,
        "ms_path": ms_path,
        "status": "ok",
        "completeness_summary": "SUSPECT" if severe else "COMPLETE",
        "data": {
            "params": params,
            "return": to_jsonable(result),
            "wall_time_s": round(time.monotonic() - started, 3),
            **_log_fields(log_path, lines),
        },
        "warnings": warnings,
        "provenance": {"casa_calls": [call]},
    }
