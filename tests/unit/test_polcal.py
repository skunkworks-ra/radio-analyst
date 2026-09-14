"""
Unit tests for ms_polcal.

This tool had no dedicated unit-test file at all before this — see
tests/unit/test_bandpass.py's module docstring for the shared reason
(check_spw_coverage needs a real MS, tests/unit/conftest.py, to be
exercised for real rather than silently falling back). polcal has no spw
selection of its own — it always solves on every SpW the field carries, so
the guardrail call passes spw='' unconditionally (see polcal.py's own
comment at the check_spw_coverage call site).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ms_modify.polcal import run


def _make_workdir(tmp_path) -> Path:
    workdir = tmp_path / "work"
    workdir.mkdir()
    return workdir


class TestValidation:
    def test_missing_workdir_raises(self, real_ms_raw, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="workdir does not exist"):
            run(
                real_ms_raw,
                "3C147",
                str(tmp_path / "nodir" / "pol.df"),
                str(tmp_path / "nodir"),
                poltype="Df",
            )


class TestScriptGeneration:
    def test_writes_script(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "pol.df")
        result = run(real_ms_raw, "3C147", caltable, str(workdir), poltype="Df", execute=False)
        assert result["status"] == "ok"
        script_path = Path(result["data"]["script_path"]["value"])
        assert script_path.exists()
        assert "field='3C147'" in script_path.read_text()


class TestSpwCoverageWiring:
    def test_warning_surfaces_when_solve_field_misses_a_spw(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "pol.df")
        result = run(
            real_ms_raw,
            "J1331+3030",
            caltable,
            str(workdir),
            poltype="Df",
            target_fields="3C147",
            execute=False,
        )
        assert any("SpW coverage gap" in w for w in result["warnings"])

    def test_no_warning_when_solve_field_covers_every_spw(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "pol.df")
        result = run(real_ms_raw, "3C147", caltable, str(workdir), poltype="Df", execute=False)
        assert not any("SpW coverage gap" in w for w in result["warnings"])
