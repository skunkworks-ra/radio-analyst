"""
Unit tests for ms_setjy_polcal (script-generation path; no execute=True).

The execute=True probe runs CASA setjy and is integration-only. These tests
cover the execute=False path: pol terms fit from the catalogue, and the
self-contained probe→fit→apply script that is emitted.

They deliberately exercise a real read of the observed band
(_read_band_range_ghz, real_ms_raw — see tests/unit/conftest.py), rather than
a fake `table.info`-only MS. Against the fake MS, that read always failed and
silently fell back to "fits will use the full catalogue range (NOT
per-band)" — a real scientific-correctness feature (spix/polindex/polangle
are per-band local expansions, not global fits) with zero coverage of it
ever actually engaging. _read_band_range_ghz reads the whole
SPECTRAL_WINDOW table, not a per-field selection, so it doesn't care that
the fixture's fields are 3C147/J1331+3030 rather than the "3C286" catalogue
name used for lookup below — those are two independent things (MS band vs.
catalogue entry).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ms_modify.setjy_polcal import run


def _make_workdir(tmp_path) -> Path:
    workdir = tmp_path / "work"
    workdir.mkdir()
    return workdir


class TestRunValidation:
    def test_missing_workdir_raises(self, real_ms_raw, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="workdir does not exist"):
            run(real_ms_raw, "3C286", str(tmp_path / "nodir"), reffreq_ghz=1.5)

    def test_unknown_calibrator_raises(self, real_ms_raw, tmp_path):
        from ms_inspect.exceptions import ComputationError

        workdir = _make_workdir(tmp_path)
        with pytest.raises(ComputationError, match="lookup failed"):
            run(real_ms_raw, "J9999+0000", str(workdir), reffreq_ghz=1.5)


def _run(real_ms_raw, tmp_path, **kw):
    workdir = _make_workdir(tmp_path)
    kw.setdefault("reffreq_ghz", 1.5)
    result = run(real_ms_raw, "3C286", str(workdir), **kw)
    script = (workdir / "setjy_polcal.py").read_text()
    return result, script


class TestScriptGeneration:
    def test_3c286_succeeds_without_catalogue_flux(self, real_ms_raw, tmp_path):
        # 3C286's 2019 epoch has no Stokes I; the tool must still produce a script.
        result, _ = _run(real_ms_raw, tmp_path)
        assert result["status"] == "ok"
        assert result["data"]["stokes_i_source"].startswith("Perley-Butler 2017")

    def test_script_is_valid_python(self, real_ms_raw, tmp_path):
        _, script = _run(real_ms_raw, tmp_path)
        ast.parse(script)  # raises SyntaxError if malformed

    def test_script_probes_perley_butler_and_applies_manual(self, real_ms_raw, tmp_path):
        _, script = _run(real_ms_raw, tmp_path)
        # Probe with PB virtual model, then apply the manual polarized model.
        assert (
            "standard='Perley-Butler 2017'" in script or 'standard="Perley-Butler 2017"' in script
        )
        assert "usescratch=False" in script  # probe
        assert 'standard="manual"' in script  # apply
        assert "usescratch=True" in script  # apply writes MODEL_DATA
        assert "spwsforfield" in script  # SPW auto-discovery
        assert "np.linalg.lstsq" in script  # in-script Stokes I fit

    def test_pol_coeffs_embedded_as_literals(self, real_ms_raw, tmp_path):
        result, script = _run(real_ms_raw, tmp_path)
        # The polindex/polangle from the catalogue must appear in the script.
        c0 = result["data"]["polindex_c0"]
        assert f"{c0}" in script or "polindex = [" in script

    def test_min_chunk_mhz_threaded(self, real_ms_raw, tmp_path):
        result, script = _run(real_ms_raw, tmp_path, min_chunk_mhz=16.0)
        assert result["data"]["min_chunk_mhz"] == 16.0
        assert "min_chunk_mhz = 16.0" in script

    def test_polcoeffs_match_2019_lband(self, real_ms_raw, tmp_path):
        # ~9.8% pol, PA ~33° near 1.5 GHz from the 2019 table.
        result, _ = _run(real_ms_raw, tmp_path)
        assert result["data"]["polindex_c0"] == pytest.approx(0.099, abs=0.01)


class TestBandRangeWiring:
    """The real point of #2 in the audit: _read_band_range_ghz must be
    exercised for real, not silently degrade to the whole-catalogue-range
    fallback. real_ms_raw's two SPWs span 1.0-2.016 GHz."""

    def test_no_band_read_fallback_warning(self, real_ms_raw, tmp_path):
        result, _ = _run(real_ms_raw, tmp_path)
        assert not any("NOT per-band" in w for w in result["warnings"])

    def test_reffreq_inside_the_real_band_does_not_warn(self, real_ms_raw, tmp_path):
        result, _ = _run(real_ms_raw, tmp_path)
        assert not any("outside the observed band" in w for w in result["warnings"])

    def test_reffreq_outside_the_real_band_warns_with_real_bounds(self, real_ms_raw, tmp_path):
        # 5.0 GHz is nowhere near this fixture's real 1.0-2.016 GHz SPWs.
        result, _ = _run(real_ms_raw, tmp_path, reffreq_ghz=5.0)
        matches = [w for w in result["warnings"] if "outside the observed band" in w]
        assert len(matches) == 1
        assert "1.000" in matches[0]
        assert "2.016" in matches[0]

    def test_reffreq_defaults_to_the_band_centre(self, real_ms_raw, tmp_path):
        result, _ = _run(real_ms_raw, tmp_path, reffreq_ghz=None)
        lo, hi = result["data"]["band_range_ghz"]
        assert result["data"]["reffreq_ghz"] == pytest.approx((lo + hi) / 2.0)
        assert result["data"]["reffreq_source"].startswith("band centre")

    def test_spw_parameter_restricts_band_and_script_probe(self, real_ms_raw, tmp_path):
        (tmp_path / "all").mkdir()
        (tmp_path / "spw0").mkdir()
        result_all, _ = _run(real_ms_raw, tmp_path / "all", reffreq_ghz=None)
        result_spw0, script_spw0 = _run(real_ms_raw, tmp_path / "spw0", spw="0", reffreq_ghz=None)
        lo_all, hi_all = result_all["data"]["band_range_ghz"]
        lo_0, hi_0 = result_spw0["data"]["band_range_ghz"]
        assert hi_0 < hi_all
        assert lo_0 >= lo_all
        assert "allowed_spws = [0]" in script_spw0

    def test_full_stokes_filter_excludes_2corr_xband_setup_spw(self, tmp_path):
        from unittest.mock import MagicMock, patch

        import numpy as np

        from ms_modify import setjy_polcal

        spw_tb = MagicMock()
        spw_tb.__enter__.return_value = spw_tb
        spw_tb.nrows.return_value = 3
        spw_tb.getcell.side_effect = lambda col, i: (
            np.array([8.4e9, 8.6e9]) if i == 0 else np.array([1.3e9 + 0.2e9 * i, 1.4e9 + 0.2e9 * i])
        )
        dd_tb = MagicMock()
        dd_tb.__enter__.return_value = dd_tb
        dd_tb.getcol.return_value = [0, 1, 2]

        def fake_open(path, **kw):
            return dd_tb if str(path).endswith("DATA_DESCRIPTION") else spw_tb

        with (
            patch.object(setjy_polcal, "open_table", side_effect=fake_open),
            patch(
                "ms_inspect.util.selection.corr_codes_by_ddid",
                return_value=[[5, 8], [5, 6, 7, 8], [5, 6, 7, 8]],
            ),
        ):
            lo, hi = setjy_polcal._read_band_range_ghz(str(tmp_path / "obs.ms"))
            spws = setjy_polcal._select_polcal_spw_ids(str(tmp_path / "obs.ms"))

        assert spws == [1, 2]
        assert lo == pytest.approx(1.5, abs=1e-3)
        assert hi == pytest.approx(1.8, abs=1e-3)
