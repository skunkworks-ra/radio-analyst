"""
Unit tests for ms_flag_data and the shared manual-selection validation.

No CASA required. Tests cover:
- validate_manual_selection: empty selection, missing reason, unknown keys
- _build_script: selection and reason embedded, summary scoped to the selection
- run: path/workdir validation, script generation
- ledger replay: run() accepts the MCP input fields as flat keyword arguments
"""

from __future__ import annotations

import inspect

import pytest

from ms_inspect.exceptions import ComputationError
from ms_modify.flag_data import SELECTION_KEYS, _build_script
from ms_modify.manual_selection import validate_manual_selection


class TestValidateManualSelection:
    def test_empty_selection_refused(self):
        # flagdata(mode='manual') with no selection flags the whole MS
        with pytest.raises(ComputationError, match="entire Measurement Set"):
            validate_manual_selection(
                {"antenna": "", "scan": " "}, "x", SELECTION_KEYS, "Measurement Set"
            )

    def test_reason_required(self):
        with pytest.raises(ComputationError, match="reason"):
            validate_manual_selection({"antenna": "ea05"}, "", SELECTION_KEYS, "Measurement Set")

    def test_unknown_key_refused(self):
        with pytest.raises(ComputationError, match="Unsupported"):
            validate_manual_selection({"feed": "1"}, "x", SELECTION_KEYS, "Measurement Set")

    def test_ms_allows_correlation_and_uvrange(self):
        out = validate_manual_selection(
            {"correlation": "RR", "uvrange": "<0.5km", "spw": ""}, "x", SELECTION_KEYS, "MS"
        )
        assert out == {"correlation": "RR", "uvrange": "<0.5km"}


class TestBuildScript:
    def test_selection_reason_and_scoped_summary(self):
        s = _build_script("t.ms", "/w", {"antenna": "ea05", "scan": "3"}, "phase jump scan 3")
        compile(s, "flag_data.py", "exec")
        assert "Reason: phase jump scan 3" in s
        assert s.count("antenna='ea05', scan='3'") == 3  # summary, manual, summary
        assert "flagbackup=True" in s
        assert "_record_stage(" in s


class TestRun:
    def _make_ms(self, tmp_path):
        ms = tmp_path / "t.ms"
        ms.mkdir()
        (ms / "table.info").write_text("Type = Measurement Set\n")
        return ms

    def test_missing_workdir_raises(self, tmp_path):
        from ms_modify.flag_data import run

        ms = self._make_ms(tmp_path)
        with pytest.raises(ComputationError, match="workdir does not exist"):
            run(str(ms), str(tmp_path / "nodir"), reason="x", antenna="ea05")

    def test_empty_selection_refused_in_run(self, tmp_path):
        from ms_modify.flag_data import run

        ms = self._make_ms(tmp_path)
        with pytest.raises(ComputationError, match="entire Measurement Set"):
            run(str(ms), str(tmp_path), reason="x")

    def test_generates_script(self, tmp_path, monkeypatch):
        import ms_modify.flag_data as mod

        monkeypatch.setattr(mod, "validate_ms_path", lambda p: tmp_path / "t.ms")
        work = tmp_path / "work"
        work.mkdir()
        result = mod.run(
            "t.ms", str(work), reason="ea05 amp 40% low", antenna="ea05", field="3C286"
        )
        assert result["status"] == "ok"
        assert result["data"]["selection"] == {"antenna": "ea05", "field": "3C286"}
        assert result["data"]["reason"] == "ea05 amp 40% low"
        assert "antenna='ea05', field='3C286'" in (work / "flag_data.py").read_text()


class TestReplayKwargs:
    # The ledger replays run(**params) with the recorded MCP input fields, so
    # every selection field must be a keyword argument of run().
    def test_flag_data_run_takes_input_fields(self):
        from ms_modify.flag_data import run
        from ms_modify.server import FlagDataInput

        assert set(FlagDataInput.model_fields) <= set(inspect.signature(run).parameters)

    def test_flag_caltable_run_takes_input_fields(self):
        from ms_modify.flag_caltable import run
        from ms_modify.server import FlagCaltableInput

        assert set(FlagCaltableInput.model_fields) <= set(inspect.signature(run).parameters)
