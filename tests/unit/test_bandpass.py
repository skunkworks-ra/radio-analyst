"""
Unit tests for ms_bandpass.

This tool had no dedicated unit-test file at all before this — its
execute=False path (including the SpW-coverage guardrail it shares with
initial_bandpass/gaincal/polcal) was exercised only incidentally, through
test_stage_log_wiring.py's AST-level checks, against a fake MS that made
check_spw_coverage silently take its except-Exception fallback rather than
run for real. See tests/unit/conftest.py for the real MS fixture and
tests/unit/test_initial_bandpass.py for the sibling tool's version of this
same fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ms_modify.bandpass import run


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
                "",
                str(tmp_path / "nodir" / "bandpass.b"),
                str(tmp_path / "nodir"),
            )


class TestScriptGeneration:
    def test_writes_script(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "bandpass.b")
        result = run(real_ms_raw, "3C147", "", caltable, str(workdir), execute=False)
        assert result["status"] == "ok"
        script_path = Path(result["data"]["script_path"]["value"])
        assert script_path.exists()
        assert "field='3C147'" in script_path.read_text()


class TestSpwCoverageWiring:
    def test_warning_surfaces_when_solve_field_misses_a_spw(self, real_ms_raw, tmp_path):
        # J1331+3030 was only observed on spw0; the explicit target 3C147
        # needs spw0+spw1 — a real, detectable gap.
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "bandpass.b")
        result = run(
            real_ms_raw,
            "J1331+3030",
            "",
            caltable,
            str(workdir),
            target_fields="3C147",
            execute=False,
        )
        assert any("SpW coverage gap" in w for w in result["warnings"])

    def test_no_warning_when_solve_field_covers_every_spw(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        caltable = str(workdir / "bandpass.b")
        result = run(real_ms_raw, "3C147", "", caltable, str(workdir), execute=False)
        assert not any("SpW coverage gap" in w for w in result["warnings"])
