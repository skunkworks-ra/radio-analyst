"""
Unit tests for the per-workdir parameter record written from run_tool_sync.

The record exists to support counting: which arguments each tool call carried,
which calls failed, and which generated scripts actually ran. So every test
checks the content of the line, not only that a line exists.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ms_inspect.exceptions import ComputationError
from ms_inspect.util import param_log, stage_log
from ms_inspect.util.dispatch import run_tool_sync
from ms_inspect.util.formatting import field as fmt_field


def _tool(module: str, body):
    body.__module__ = module
    return body


def _lines(workdir: Path) -> list[dict]:
    path = workdir / param_log.PARAM_LOG_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _script_tool(module: str = "ms_modify.fake"):
    """A tool that writes a script recording one stage, like a real generator."""

    def run(ms_path, workdir, sigma=5.0, execute=False):
        product = Path(workdir) / "cal.G"
        product.mkdir(exist_ok=True)
        script = Path(workdir) / "fake.py"
        script.write_text(
            stage_log.RECORD_STAGE_SNIPPET
            + f"\n# sigma={sigma}\n"
            + f"_record_stage({workdir!r}, 'fake', {str(product)!r})\n"
        )
        return {"status": "ok", "data": {"script_path": fmt_field(str(script))}}

    return _tool(module, run)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(param_log.ENABLE_ENV, "1")


def test_nothing_is_written_when_the_env_var_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(param_log.ENABLE_ENV, raising=False)
    run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path), sigma=6.0)
    assert _lines(tmp_path) == []
    assert not (tmp_path / param_log.SNAPSHOT_DIR).exists()


def test_a_successful_call_records_named_args_and_a_script_snapshot(tmp_path, on):
    run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path), sigma=6.0)

    (line,) = _lines(tmp_path)
    assert line["status"] == "ok"
    assert line["tool"] == "ms_modify.fake._script_tool.<locals>.run"
    assert line["args"] == {"ms_path": "/data/x.ms", "workdir": str(tmp_path), "sigma": 6.0}
    snapshot = Path(line["script_snapshot"])
    assert snapshot.parent == tmp_path / param_log.SNAPSHOT_DIR
    assert line["script_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert {"rev", "dirty"} <= set(line)


def test_args_the_server_did_not_pass_are_not_filled_from_run_defaults(tmp_path, on):
    run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path))
    (line,) = _lines(tmp_path)
    assert "sigma" not in line["args"]
    assert "execute" not in line["args"]


def test_a_second_call_does_not_destroy_the_first_script(tmp_path, on):
    tool = _script_tool()
    run_tool_sync(tool, "/data/x.ms", str(tmp_path), sigma=5.0)
    run_tool_sync(tool, "/data/x.ms", str(tmp_path), sigma=6.0)

    first, second = _lines(tmp_path)
    assert "sigma=5.0" in Path(first["script_snapshot"]).read_text()
    assert "sigma=6.0" in Path(second["script_snapshot"]).read_text()
    assert first["script_sha256"] != second["script_sha256"]


def test_a_tool_error_is_recorded_and_the_envelope_is_unchanged(tmp_path, on):
    def run(ms_path, workdir, sigma=5.0):
        raise ComputationError("sigma must be > 0", ms_path=ms_path)

    out = run_tool_sync(_tool("ms_modify.fake", run), "/data/x.ms", str(tmp_path), sigma=-1.0)

    assert json.loads(out)["status"] == "error"
    (line,) = _lines(tmp_path)
    assert line["status"] == "error"
    assert "sigma must be > 0" in line["error"]
    assert line["args"]["sigma"] == -1.0


def test_an_unexpected_exception_is_recorded_and_still_raised(tmp_path, on):
    def run(ms_path, workdir):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_tool_sync(_tool("ms_modify.fake", run), "/data/x.ms", str(tmp_path))
    (line,) = _lines(tmp_path)
    assert line["status"] == "exception"
    assert line["error"] == "RuntimeError: boom"


def test_ms_inspect_tools_are_not_recorded(tmp_path, on):
    run_tool_sync(_script_tool("ms_inspect.tools.fake"), "/data/x.ms", str(tmp_path))
    assert _lines(tmp_path) == []


def test_a_tool_without_a_workdir_is_not_recorded(tmp_path, on):
    def run(ms_path, sigma=5.0):
        return {"status": "ok", "data": {}}

    run_tool_sync(_tool("ms_modify.fake", run), str(tmp_path / "x.ms"), sigma=6.0)
    assert list(tmp_path.iterdir()) == []


def test_a_failure_to_record_leaves_the_result_untouched(tmp_path, on, monkeypatch, capsys):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(param_log, "_snapshot", broken)
    out = run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path))

    assert json.loads(out)["status"] == "ok"
    assert "param_log: failed to record" in capsys.readouterr().err


def test_the_snapshot_hash_matches_the_stage_log_line_of_the_script_that_ran(tmp_path, on):
    run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path), sigma=6.0)
    (call,) = _lines(tmp_path)

    subprocess.run([sys.executable, call["script_path"]], check=True)

    (ran,) = stage_log.read_stage_log(tmp_path)
    assert ran["script_sha256"] == call["script_sha256"]


def test_an_edited_script_does_not_match_its_call(tmp_path, on):
    run_tool_sync(_script_tool(), "/data/x.ms", str(tmp_path), sigma=6.0)
    (call,) = _lines(tmp_path)
    script = Path(call["script_path"])
    script.write_text(script.read_text().replace("sigma=6.0", "sigma=4.0"))

    subprocess.run([sys.executable, str(script)], check=True)

    (ran,) = stage_log.read_stage_log(tmp_path)
    assert ran["script_sha256"] != call["script_sha256"]
