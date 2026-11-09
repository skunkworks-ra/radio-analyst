"""
Logging layout: CASA stays out of the working directory, everything lands in
<workdir>/logs/, old CASA logs are pruned, and the paths are reported.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

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


# ------------------------------------------------------------- per-call CASA log

_BEGIN = "t\tINFO\tgaincal::::\t##### Begin Task: gaincal            #####"
_END = "t\tINFO\tgaincal::::\t##### End Task: gaincal              #####"
_SEVERE = "t\tSEVERE\tgaincal::::\tsolve failed for all antennas"
_MEASURES = "t\tSEVERE\t::casa\tmeasures_update: the measures data is not maintained by casaconfig"


def _events(workdir):
    return [
        json.loads(line) for line in (workdir / "logs" / "events.jsonl").read_text().splitlines()
    ]


def test_each_call_gets_its_own_casa_log(workdir):
    async def go():
        await asyncio.gather(
            run_tool(dt.write_casa_log, "/data/a.ms", [_MEASURES]),
            run_tool(dt.write_casa_log, "/data/b.ms", [_MEASURES]),
        )

    asyncio.run(go())
    logs_named = {e["casa_log"] for e in _events(workdir)}
    assert len(logs_named) == 2
    for path in logs_named:
        assert Path(path).read_text() == _MEASURES + "\n"


def test_severe_inside_a_task_makes_the_result_suspect(workdir):
    result = asyncio.run(run_tool(dt.write_casa_log, "/data/a.ms", [_BEGIN, _SEVERE, _END]))
    env = result.structuredContent
    assert not result.isError
    assert env["completeness_summary"] == "SUSPECT"
    assert env["warnings"][0] == "from the tool"
    assert "CASA logged 1 SEVERE line(s) during gaincal" in env["warnings"][1]
    assert env["casa_severe"]["lines"] == [_SEVERE]
    assert env["casa_severe"]["casa_log"] == _events(workdir)[0]["casa_log"]


def test_severe_outside_every_task_leaves_the_result_alone(workdir):
    result = asyncio.run(run_tool(dt.write_casa_log, "/data/a.ms", [_MEASURES, _BEGIN, _END]))
    env = result.structuredContent
    assert env["completeness_summary"] == "COMPLETE"
    assert env["warnings"] == ["from the tool"]
    assert "casa_severe" not in env


def test_severe_keeps_a_worse_completeness_flag(workdir):
    lines = [_BEGIN, _SEVERE, _END]
    result = asyncio.run(run_tool(dt.write_casa_log, "/data/a.ms", lines, "UNAVAILABLE"))
    assert result.structuredContent["completeness_summary"] == "UNAVAILABLE"


def test_severe_lines_are_capped_in_the_result(workdir):
    from ms_inspect.util.dispatch import MAX_SEVERE_LINES

    lines = [_BEGIN, *[_SEVERE] * (MAX_SEVERE_LINES + 5), _END]
    env = asyncio.run(run_tool(dt.write_casa_log, "/data/a.ms", lines)).structuredContent
    assert len(env["casa_severe"]["lines"]) == MAX_SEVERE_LINES
    assert f"CASA logged {MAX_SEVERE_LINES + 5} SEVERE" in env["warnings"][1]


def test_flag_casa_severe_leaves_error_envelopes_alone(tmp_path):
    from ms_inspect.util.dispatch import flag_casa_severe

    log = tmp_path / "casa.log"
    log.write_text("\n".join([_BEGIN, _SEVERE, _END]) + "\n")
    envelope = {"status": "error", "error_type": "X", "message": "m"}
    assert flag_casa_severe(dict(envelope), str(log)) == envelope


def test_real_casa_task_severe_marks_the_result_suspect(workdir, tmp_path):
    pytest.importorskip("casatasks")
    not_an_image = tmp_path / "not_an_image.im"
    not_an_image.mkdir()
    env = asyncio.run(run_tool(dt.casa_task_severe, str(not_an_image))).structuredContent
    assert env["completeness_summary"] == "SUSPECT"
    assert any("Unable to open image" in line for line in env["casa_severe"]["lines"])
    assert not any("measures_update" in line for line in env["casa_severe"]["lines"])


def test_stage_line_written_in_the_call_sees_casa_lines_logged_before_it(workdir, tmp_path):
    """CASA writes its log lines at once, so record_stage counts them in-process."""
    pytest.importorskip("casatasks")
    not_an_image = tmp_path / "not_an_image.im"
    not_an_image.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    call = run_tool(dt.casa_task_severe_then_record, str(not_an_image), str(out))
    entry = asyncio.run(call).structuredContent["data"]
    assert entry["schema_version"] == 2
    assert entry["casa_tasks"] == ["imhead"]
    assert entry["severe_lines"] >= 1


def test_generated_script_records_where_its_log_lines_begin(monkeypatch, tmp_path):
    log = tmp_path / "casa-x.log"
    log.write_text("lines of the generating call\n")
    monkeypatch.setenv(logs.LOGFILE_ENV, str(log))
    monkeypatch.setenv(logs.LOGSTART_ENV, "unset by the test")
    try:
        from casaconfig import config

        monkeypatch.setattr(config, "logfile", config.logfile)
    except ImportError:
        pass
    preamble = logs.with_casa_log("")
    exec(preamble, {})  # noqa: S102 - the preamble under test
    assert os.environ[logs.LOGSTART_ENV] == str(log.stat().st_size)
