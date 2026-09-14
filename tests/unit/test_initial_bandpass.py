"""
Unit tests for ms_initial_bandpass.

Tests cover the execute=False script-generation path, with a focus on the
applycal_field / applymode plumbing added to decouple the Step 3 applycal
field from the solve field (it previously hardwired field='', which
corrupted the FLAG state of non-BP calibrators).

These tests deliberately exercise real CASA metadata reads via the shared
`real_ms_raw` fixture (tests/unit/conftest.py) — run() calls
check_spw_coverage() even under execute=False, and that call must be
exercised for real, not accidentally routed through its swallow-and-degrade
fallback against an invalid fixture (the bug this file used to have: its own
"No CASA required" docstring was wrong, every test here silently rode
check_spw_coverage's except-Exception fallback against a table.info-only
stub instead of exercising it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ms_modify.initial_bandpass import run


def _make_workdir(tmp_path) -> Path:
    workdir = tmp_path / "work"
    workdir.mkdir()
    return workdir


# ---------------------------------------------------------------------------
# Validation / required arguments
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_workdir_raises(self, real_ms_raw, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="workdir does not exist"):
            run(real_ms_raw, "3C147", "3C147", "ea05", str(tmp_path / "nodir"))

    def test_applycal_field_is_required(self):
        # No default for applycal_field — calling without it is a TypeError.
        import inspect

        sig = inspect.signature(run)
        assert sig.parameters["applycal_field"].default is inspect.Parameter.empty

    def test_applymode_defaults_to_calflagstrict(self):
        import inspect

        sig = inspect.signature(run)
        assert sig.parameters["applymode"].default == "calflagstrict"


# ---------------------------------------------------------------------------
# execute=False script generation
# ---------------------------------------------------------------------------


class TestScriptGeneration:
    def test_writes_script(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        result = run(real_ms_raw, "3C147", "3C147", "ea05", str(workdir), execute=False)
        assert result["status"] == "ok"
        assert (workdir / "initial_bandpass.py").exists()

    def test_solve_uses_bp_field_applycal_uses_applycal_field(self, real_ms_raw, tmp_path):
        # The whole point of #2: gaincal/bandpass solve on bp_field, but the
        # Step 3 applycal must apply only to applycal_field.
        workdir = _make_workdir(tmp_path)
        run(real_ms_raw, "3C147", "J1331+3030", "ea05", str(workdir), execute=False)
        script = (workdir / "initial_bandpass.py").read_text()

        # Split at the applycal call so we can attribute field= occurrences.
        solve_part, _, applycal_part = script.partition("applycal(")
        assert "field='3C147'" in solve_part  # gaincal + bandpass
        assert "field='J1331+3030'" in applycal_part  # Step 3 applycal
        assert "field='3C147'" not in applycal_part

    def test_applycal_field_empty_is_honored(self, real_ms_raw, tmp_path):
        # field='' (all fields) is a valid, deliberate choice — not the default.
        workdir = _make_workdir(tmp_path)
        run(real_ms_raw, "3C147", "", "ea05", str(workdir), execute=False)
        script = (workdir / "initial_bandpass.py").read_text()
        _, _, applycal_part = script.partition("applycal(")
        assert "field=''" in applycal_part

    def test_default_applymode_in_script(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        run(real_ms_raw, "3C147", "3C147", "ea05", str(workdir), execute=False)
        script = (workdir / "initial_bandpass.py").read_text()
        assert "applymode='calflagstrict'" in script

    def test_calflag_applymode_override_in_script(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        run(
            real_ms_raw,
            "3C147",
            "3C147",
            "ea05",
            str(workdir),
            applymode="calflag",
            execute=False,
        )
        script = (workdir / "initial_bandpass.py").read_text()
        assert "applymode='calflag'" in script
        assert "applymode='calflagstrict'" not in script


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


class TestResponse:
    def test_response_records_applycal_field_and_applymode(self, real_ms_raw, tmp_path):
        workdir = _make_workdir(tmp_path)
        result = run(
            real_ms_raw,
            "3C147",
            "J1331+3030",
            "ea05",
            str(workdir),
            applymode="calflag",
            execute=False,
        )
        data = result["data"]
        assert data["bp_field"] == "3C147"
        assert data["applycal_field"] == "J1331+3030"
        assert data["applymode"] == "calflag"


# ---------------------------------------------------------------------------
# SpW-coverage guardrail (real CASA metadata, not the swallow-and-degrade
# fallback — see module docstring)
# ---------------------------------------------------------------------------


class TestSpwCoverageWiring:
    def test_warning_surfaces_when_solve_field_misses_a_spw(self, real_ms_raw, tmp_path):
        # Solve on J1331+3030 (spw0 only, per the fixture); the explicit
        # target 3C147 was observed on spw0+spw1. That's a real gap —
        # check_spw_coverage must find it against real metadata, and run()
        # must surface it in the top-level response, not swallow it.
        workdir = _make_workdir(tmp_path)
        result = run(
            real_ms_raw,
            "J1331+3030",
            "J1331+3030",
            "ea05",
            str(workdir),
            target_fields="3C147",
            execute=False,
        )
        assert any("SpW coverage gap" in w for w in result["warnings"])

    def test_no_warning_when_solve_field_covers_every_spw(self, real_ms_raw, tmp_path):
        # 3C147 was observed on both spw0 and spw1, so it covers everything
        # the (intent-inferred) target J1331+3030 needs. No warning is the
        # correct real answer here, not an accident of a fallback.
        workdir = _make_workdir(tmp_path)
        result = run(real_ms_raw, "3C147", "3C147", "ea05", str(workdir), execute=False)
        assert not any("SpW coverage gap" in w for w in result["warnings"])
