"""
Unit tests for ms_split_average. No CASA required (execute=False only).
"""

from __future__ import annotations

import pytest

from ms_inspect.exceptions import ComputationError
from ms_modify.split_average import MAX_TIMEBIN_S, run


@pytest.fixture
def setup(tmp_path):
    ms = tmp_path / "cal.ms"
    ms.mkdir()
    (ms / "table.info").write_text("Type = Measurement Set\n")
    wd = tmp_path / "work"
    wd.mkdir()
    return ms, wd


def _run(ms, wd, **over):
    kw = {
        "ms_path": str(ms),
        "workdir": str(wd),
        "field": "3C391 C1",
        "output_ms": str(wd / "target_avg.ms"),
        "width": [16],
        "timebin_s": 30.0,
    }
    kw.update(over)
    return run(**kw)


def test_script_carries_the_split_arguments(setup):
    ms, wd = setup
    res = _run(ms, wd)
    assert res["status"] == "ok"
    script = (wd / "split_average.py").read_text()
    compile(script, "split_average.py", "exec")
    assert "'width': 16" in script
    assert "'timebin': '30s'" in script
    assert "'datacolumn': 'corrected'" in script
    assert "'keepflags': False" in script
    assert "'field': '3C391 C1'" in script
    assert "_record_stage(" in script and "'split_average'" in script
    assert res["data"]["output_ms"]["flag"] == "UNAVAILABLE"
    assert not (wd / "target_avg.ms").exists()


def test_per_spw_width_list_is_passed_as_a_list(setup):
    ms, wd = setup
    _run(ms, wd, width=[16, 32], spw="0,1")
    assert "'width': [16, 32]" in (wd / "split_average.py").read_text()


def test_zero_timebin_means_no_time_averaging(setup):
    ms, wd = setup
    res = _run(ms, wd, timebin_s=0.0)
    assert res["data"]["timebin"] == "0s"


def test_timebin_at_cap_is_accepted(setup):
    ms, wd = setup
    assert _run(ms, wd, timebin_s=MAX_TIMEBIN_S)["status"] == "ok"


@pytest.mark.parametrize("timebin", [30.5, 60.0, -1.0])
def test_timebin_outside_range_is_refused(setup, timebin):
    ms, wd = setup
    with pytest.raises(ComputationError, match="timebin_s"):
        _run(ms, wd, timebin_s=timebin)
    assert not (wd / "split_average.py").exists()


def test_empty_field_is_refused(setup):
    ms, wd = setup
    with pytest.raises(ComputationError, match="field is required"):
        _run(ms, wd, field="")


def test_zero_width_is_refused(setup):
    ms, wd = setup
    with pytest.raises(ComputationError, match="width"):
        _run(ms, wd, width=[0])


def test_existing_output_is_refused(setup):
    ms, wd = setup
    (wd / "target_avg.ms").mkdir()
    with pytest.raises(ComputationError, match="already exists"):
        _run(ms, wd)


def test_output_equal_to_input_is_refused(setup):
    ms, wd = setup
    with pytest.raises(ComputationError):
        _run(ms, wd, output_ms=str(ms))


def test_output_outside_workdir_is_refused(setup, tmp_path):
    ms, wd = setup
    with pytest.raises(ComputationError, match="not inside workdir"):
        _run(ms, wd, output_ms=str(tmp_path / "elsewhere.ms"))


def test_missing_workdir_is_refused(setup, tmp_path):
    ms, _ = setup
    with pytest.raises(ComputationError, match="workdir does not exist"):
        _run(ms, tmp_path / "nope", output_ms=str(tmp_path / "nope" / "a.ms"))


def test_input_model_rejects_timebin_above_30s():
    from pydantic import ValidationError

    from ms_modify.server import SplitAverageInput

    base = {"ms_path": "/a.ms", "workdir": "/w", "field": "T", "output_ms": "/w/b.ms"}
    assert SplitAverageInput(**base, timebin_s=30.0).timebin_s == 30.0
    with pytest.raises(ValidationError):
        SplitAverageInput(**base, timebin_s=30.1)
