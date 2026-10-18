"""
Logging layout: CASA stays out of the working directory, everything lands in
<workdir>/logs/, old CASA logs are pruned, and the paths are reported.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import dispatch_tools as dt
import pytest

from ms_inspect.util import logs
from ms_inspect.util.dispatch import run_tool
from ms_inspect.util.stage_log import read_stage_log, record_stage


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A clean working directory that is also the logging workdir."""
    wd = tmp_path / "wd"
    wd.mkdir()
    monkeypatch.chdir(wd)
    monkeypatch.setenv(logs.WORKDIR_ENV, str(wd))
    monkeypatch.delenv(logs.LOGFILE_ENV, raising=False)
    monkeypatch.setattr(logs, "_casa_logfile", None)
    return wd


def _only_logs_dir(wd):
    assert sorted(p.name for p in wd.iterdir()) == ["logs"]


def test_server_startup_leaves_only_logs_dir(workdir):
    logs.init_server_logging("test-server")
    _only_logs_dir(workdir)
    assert (workdir / "logs" / "server.log").is_file()


def test_tool_call_leaves_only_logs_dir_and_writes_event(workdir, tmp_path):
    pytest.importorskip("casatools")
    record_dir = tmp_path / "rec"
    record_dir.mkdir()
    asyncio.run(run_tool(dt.import_casa, "/data/a.ms"))
    _only_logs_dir(workdir)
    events = [
        json.loads(line) for line in (workdir / "logs" / "events.jsonl").read_text().splitlines()
    ]
    assert len(events) == 1
    assert events[0]["status"] == "ok"
    assert events[0]["tool"].endswith("import_casa")
    assert os.path.dirname(events[0]["casa_log"]) == str(workdir / "logs")
    assert os.path.exists(events[0]["casa_log"])


def test_pool_call_leaves_only_logs_dir(workdir):
    pytest.importorskip("casatools")
    asyncio.run(run_tool(dt.pool_import_casa, "/data/a.ms"))
    _only_logs_dir(workdir)


def test_error_response_reports_log_path(workdir):
    result = asyncio.run(run_tool(dt.raise_ms_not_found, "/data/a.ms"))
    assert result.isError
    path = result.structuredContent["log_path"]
    assert os.path.dirname(path) == str(workdir / "logs")
    event = json.loads((workdir / "logs" / "events.jsonl").read_text().splitlines()[0])
    assert event["status"] == "error"
    assert event["error_type"] == "MS_NOT_FOUND"
    assert event["casa_log"] == path


def test_prune_removes_old_files_then_oldest_over_the_size_cap(tmp_path):
    now = time.time()
    day = 86400

    def make(name, age_days, size):
        p = tmp_path / name
        p.write_bytes(b"x" * size)
        os.utime(p, (now - age_days * day, now - age_days * day))
        return p

    old = make("casa-old.log", 20, 10)
    oldest_kept = make("casa-b.log", 5, 100)
    newer = make("casa-c.log", 1, 100)
    shared = make("server.log", 30, 10)
    removed = logs.prune_logs(tmp_path, max_age_days=14, max_bytes=150, now=now)
    assert set(removed) == {old, oldest_kept}
    assert newer.exists() and shared.exists()


def test_generated_script_carries_log_path(monkeypatch, tmp_path):
    monkeypatch.setenv(logs.LOGFILE_ENV, "/some/logs/casa-x.log")
    out = tmp_path / "s.py"
    logs.write_script(out, '#!/usr/bin/env python\n"""doc"""\nx = 1\n')
    text = out.read_text()
    assert text.startswith("#!/usr/bin/env python\n# CASA log: /some/logs/casa-x.log\n")
    assert text.endswith("x = 1\n")
    compile(text, "s.py", "exec")


def test_stage_log_records_casa_log(monkeypatch, tmp_path):
    monkeypatch.setenv(logs.LOGFILE_ENV, "/some/logs/casa-x.log")
    product = tmp_path / "p"
    product.write_text("")
    record_stage(str(tmp_path), "gaincal", str(product))
    assert read_stage_log(tmp_path)[0]["casa_log"] == "/some/logs/casa-x.log"
