"""
util/logs.py — where this package's logs go, and keeping CASA out of the cwd.

casatools creates ``casa-<stamp>.log`` in the working directory of whatever
process imports it, unless ``casaconfig.config.logfile`` is set first. Left
alone that litters the repo root, the user's project, and every pool worker.

- By default every process here points that setting at ``os.devnull``
  (``configure_casa_log``, run when any of the three packages is imported).
- The tool-dispatch parent gives every tool call its own CASA log and passes
  it to the child through ``_ANALYST_CASA_LOGFILE``; the child, and any pool
  worker it spawns, writes there. One file per call means the parent can read
  back exactly what CASA logged during that call (util/dispatch.py). A script
  the call generates logs to the same file when it is run later.
- Everything lives under ``<workdir>/logs/``: ``casa-*.log`` (one per tool
  call), ``server.log`` (Python logging) and ``events.jsonl`` (one line per
  tool call, naming its CASA log). The workdir is ``RADIO_MCP_DIR`` if set,
  else the cwd.
- A successful call that ran no casatasks task and logged no SEVERE lines keeps
  no CASA log: dispatch unlinks it and records ``casa_log: null`` in
  ``events.jsonl`` so no dangling path is left behind. (Generated scripts still
  embed the path from ``_ANALYST_CASA_LOGFILE`` and create it when executed.)
- ``prune_logs`` removes CASA logs older than 14 days, then the oldest until
  the rest fit in 200 MB. It runs at server start.

Standard library only: the worker child imports this and must not pay for mcp.
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

#: Set by the dispatch parent (and by launch.sh to ``os.devnull``) to name the CASA log.
LOGFILE_ENV = "_ANALYST_CASA_LOGFILE"
#: Byte offset in the CASA log where the next stage-log line starts counting. A
#: generated script sets it at start (with_casa_log), because it appends to a
#: log that already holds the generating call's lines; each stage-log line then
#: moves it past what it counted. Unset means 0.
LOGSTART_ENV = "_ANALYST_CASA_LOGSTART"
#: Tool metadata embedded into generated scripts so _record_stage stamps replayable
#: call metadata into stage_log.jsonl without manual ms_reduction_log appends.
TOOL_NAME_ENV = "_ANALYST_TOOL_NAME"
SCRIPT_PATH_ENV = "_ANALYST_SCRIPT_PATH"
CALL_PARAMS_ENV = "_ANALYST_CALL_PARAMS"
#: Overrides the directory whose ``logs/`` subdirectory holds everything.
WORKDIR_ENV = "RADIO_MCP_DIR"

RETENTION_DAYS = 14
RETENTION_BYTES = 200 * 1024 * 1024


def configure_casa_log() -> None:
    """Point casatools at the log named by the environment, else at devnull.

    casatools reads the setting once, at import, so this must run before the
    first ``import casatools`` / ``casatasks`` in the process.
    """
    try:
        from casaconfig import config
    except ImportError:
        return
    config.logfile = os.environ.get(LOGFILE_ENV) or os.devnull


def logs_dir() -> Path:
    """``<workdir>/logs`` (not created)."""
    return Path(os.environ.get(WORKDIR_ENV) or os.getcwd()) / "logs"


def call_log_path() -> str:
    """A new CASA log path for one tool call; creates the logs directory, not the file."""
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return str((directory / f"casa-{stamp}-{uuid.uuid4().hex[:8]}.log").resolve())


def prune_logs(
    directory: Path,
    *,
    max_age_days: float = RETENTION_DAYS,
    max_bytes: int = RETENTION_BYTES,
    now: float | None = None,
) -> list[Path]:
    """Delete old ``casa-*.log`` files in `directory`; return what was removed.

    ``server.log`` and ``events.jsonl`` are shared and still being appended to,
    so they are left alone.
    """
    now = time.time() if now is None else now
    removed: list[Path] = []
    files = []
    for path in directory.glob("casa-*.log"):
        try:
            st = path.stat()
        except OSError:
            continue
        files.append((st.st_mtime, st.st_size, path))
    files.sort()  # oldest first

    def drop(path: Path) -> bool:
        try:
            path.unlink()
        except OSError:
            return False
        removed.append(path)
        return True

    kept = []
    for mtime, size, path in files:
        if now - mtime > max_age_days * 86400 and drop(path):
            continue
        kept.append((size, path))
    total = sum(size for size, _ in kept)
    for size, path in kept:
        if total <= max_bytes:
            break
        if drop(path):
            total -= size
    return removed


def init_server_logging(name: str) -> None:
    """Server start-up: silence CASA, prune old logs, open ``server.log``. Never raises."""
    configure_casa_log()
    directory = logs_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        prune_logs(directory)
        handler = logging.FileHandler(directory / "server.log")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if not any(getattr(h, "_ra_server_log", False) for h in root.handlers):
        handler._ra_server_log = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
    logging.getLogger(name).info("started pid=%d workdir=%s", os.getpid(), directory.parent)


def log_event(**fields) -> None:
    """Append one line to ``events.jsonl``. A logging failure never fails a tool call."""
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    try:
        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "events.jsonl", "a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


def _extract_caller_tool_meta() -> tuple[str | None, dict | None]:
    """Extract (TOOL_NAME, bound signature params) when called directly from a write tool."""
    try:
        frame = sys._getframe(2)
    except ValueError:
        return None, None
    tool_name = frame.f_globals.get("TOOL_NAME")
    if (
        not isinstance(tool_name, str)
        or not tool_name.startswith("ms_")
        or tool_name == "ms_reduction_log"
    ):
        return None, None
    if frame.f_code.co_name not in ("run", "set_intents"):
        return None, None
    fn = frame.f_globals.get(frame.f_code.co_name) or frame.f_globals.get("run")
    if not callable(fn):
        return tool_name, None
    try:
        sig = inspect.signature(fn)
        raw = {k: frame.f_locals[k] for k in sig.parameters if k in frame.f_locals}
        params = json.loads(json.dumps(raw, default=str))
    except Exception:
        params = None
    return tool_name, params


def with_casa_log(
    script: str,
    *,
    tool_name: str | None = None,
    script_path: str | None = None,
    call_params: dict | None = None,
) -> str:
    """Insert the CASA log setting into a generated script, after any shebang.

    The script then writes to the CASA log of the call that generated it (or
    nowhere, if it was generated outside a server) instead of creating
    ``casa-*.log`` in whatever directory it is run from, and its
    ``_record_stage`` lines carry the path. It also records where its own lines
    begin in that log (LOGSTART_ENV).
    """
    path = os.environ.get(LOGFILE_ENV) or os.devnull
    extra = ""
    if tool_name:
        extra += f'_os.environ["{TOOL_NAME_ENV}"] = {tool_name!r}\n'
    if script_path:
        extra += f'_os.environ["{SCRIPT_PATH_ENV}"] = {script_path!r}\n'
    if call_params is not None:
        encoded = base64.b64encode(
            json.dumps(call_params, separators=(",", ":"), default=str).encode("utf-8")
        ).decode("ascii")
        extra += f'_os.environ["{CALL_PARAMS_ENV}"] = {encoded!r}\n'
    preamble = (
        f"# CASA log: {path}\n"
        "import os as _os\n"
        f'_os.environ["{LOGFILE_ENV}"] = {path!r}\n'
        f'_os.environ["{LOGSTART_ENV}"] = str(_os.path.getsize({path!r}) '
        f"if _os.path.isfile({path!r}) else 0)\n"
        f"{extra}"
        "try:\n"
        "    from casaconfig import config as _casaconfig\n"
        f"    _casaconfig.logfile = {path!r}\n"
        "except ImportError:\n"
        "    pass\n"
    )
    if script.startswith("#!"):
        shebang, _, rest = script.partition("\n")
        return f"{shebang}\n{preamble}{rest}"
    return preamble + script


def write_script(
    path,
    script: str,
    *,
    tool_name: str | None = None,
    call_params: dict | None = None,
) -> None:
    """Write a generated Python script with the CASA log preamble."""
    if tool_name is None and call_params is None:
        tool_name, call_params = _extract_caller_tool_meta()
    resolved = str(Path(path).resolve()) if tool_name else None
    Path(path).write_text(
        with_casa_log(
            script,
            tool_name=tool_name,
            script_path=resolved,
            call_params=call_params,
        )
    )
