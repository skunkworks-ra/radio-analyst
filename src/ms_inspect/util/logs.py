"""
util/logs.py — where this package's logs go, and keeping CASA out of the cwd.

casatools creates ``casa-<stamp>.log`` in the working directory of whatever
process imports it, unless ``casaconfig.config.logfile`` is set first. Left
alone that litters the repo root, the user's project, and every pool worker.

- By default every process here points that setting at ``os.devnull``
  (``configure_casa_log``, run when any of the three packages is imported).
- The tool-dispatch parent passes one real log per server process to its
  children through ``_ANALYST_CASA_LOGFILE``; a child, and any pool worker it
  spawns, then writes there.
- Everything lives under ``<workdir>/logs/``: ``casa-*.log`` (one per server
  process), ``server.log`` (Python logging) and ``events.jsonl`` (one line per
  tool call). The workdir is ``RADIO_MCP_DIR`` if set, else the cwd.
- ``prune_logs`` removes CASA logs older than 14 days, then the oldest until
  the rest fit in 200 MB. It runs at server start.

Standard library only: the worker child imports this and must not pay for mcp.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

#: Set by the dispatch parent (and by launch.sh to ``os.devnull``) to name the CASA log.
LOGFILE_ENV = "_ANALYST_CASA_LOGFILE"
#: Overrides the directory whose ``logs/`` subdirectory holds everything.
WORKDIR_ENV = "RADIO_MCP_DIR"

RETENTION_DAYS = 14
RETENTION_BYTES = 200 * 1024 * 1024

_casa_logfile: str | None = None


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


def casa_log_path() -> str:
    """The one CASA log for this server process, created lazily with its directory."""
    global _casa_logfile
    if _casa_logfile is None:
        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        _casa_logfile = str((directory / f"casa-{stamp}-{os.getpid()}.log").resolve())
    return _casa_logfile


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


def with_casa_log(script: str) -> str:
    """Insert the CASA log setting into a generated script, after any shebang.

    The script then writes to the server's CASA log (or nowhere, if it was
    generated outside a server) instead of creating ``casa-*.log`` in whatever
    directory it is run from, and its ``_record_stage`` lines carry the path.
    """
    path = os.environ.get(LOGFILE_ENV) or os.devnull
    preamble = (
        f"# CASA log: {path}\n"
        "import os as _os\n"
        f'_os.environ["{LOGFILE_ENV}"] = {path!r}\n'
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


def write_script(path, script: str) -> None:
    """Write a generated Python script with the CASA log preamble."""
    Path(path).write_text(with_casa_log(script))
