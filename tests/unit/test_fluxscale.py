"""
Unit tests for ms_fluxscale.

Before this file existed, fluxscale.run() — the tool's actual entry point —
had zero test coverage. The only test touching this module
(test_stage_log_wiring.py::test_fluxscale_records_its_fluxtable) calls
_build_script() directly, bypassing run() entirely — including
_resolve_field_ids(), which does a real, unguarded open_table() against the
input caltable (no try/except) to map field names to the IDs that actually
carry solutions there. That call needs a real caltable — real_caltable
(tests/unit/conftest.py) has solutions for both 3C147 and J1331+3030.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ms_modify.fluxscale import run


def _make_workdir(tmp_path) -> Path:
    workdir = tmp_path / "work"
    workdir.mkdir()
    return workdir


class TestValidation:
    def test_missing_workdir_raises(self, real_ms_raw, real_caltable, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="workdir does not exist"):
            run(
                real_ms_raw,
                real_caltable,
                str(tmp_path / "nodir" / "flux.fluxscale"),
                "3C147",
                ["J1331+3030"],
                str(tmp_path / "nodir"),
            )

    def test_missing_input_caltable_raises(self, real_ms_raw, tmp_path):
        from ms_inspect.exceptions import ComputationError

        workdir = _make_workdir(tmp_path)
        with pytest.raises(ComputationError, match="Input caltable not found"):
            run(
                real_ms_raw,
                str(tmp_path / "no_such.gcal"),
                str(workdir / "flux.fluxscale"),
                "3C147",
                ["J1331+3030"],
                str(workdir),
            )


class TestFieldResolution:
    def test_reference_and_transfer_resolve_to_real_field_ids(
        self, real_ms_raw, real_caltable, tmp_path
    ):
        # real_caltable has solutions for both fields (field="" at build
        # time) — both names must resolve to their real caltable IDs, not
        # ride through as unresolved names.
        workdir = _make_workdir(tmp_path)
        result = run(
            real_ms_raw,
            real_caltable,
            str(workdir / "flux.fluxscale"),
            "3C147",
            ["J1331+3030"],
            str(workdir),
            execute=False,
        )
        assert result["data"]["reference"] == "0"
        assert result["data"]["transfer"] == ["1"]

    def test_unresolvable_name_falls_back_to_the_raw_name(
        self, real_ms_raw, real_caltable, tmp_path
    ):
        # 3C286 was never observed in this fixture, so it carries no
        # solutions in real_caltable — _resolve_field_ids must fall back to
        # the raw name rather than inventing an ID.
        workdir = _make_workdir(tmp_path)
        result = run(
            real_ms_raw,
            real_caltable,
            str(workdir / "flux.fluxscale"),
            "3C147",
            ["3C286"],
            str(workdir),
            execute=False,
        )
        assert result["data"]["transfer"] == ["3C286"]


class TestScriptGeneration:
    def test_writes_script(self, real_ms_raw, real_caltable, tmp_path):
        workdir = _make_workdir(tmp_path)
        result = run(
            real_ms_raw,
            real_caltable,
            str(workdir / "flux.fluxscale"),
            "3C147",
            ["J1331+3030"],
            str(workdir),
            execute=False,
        )
        assert result["status"] == "ok"
        script_path = Path(result["data"]["script_path"]["value"])
        assert script_path.exists()
        script = script_path.read_text()
        # Resolved IDs, not raw names, must be what reaches the script.
        assert "reference='0'" in script
        assert "transfer=['1']" in script
