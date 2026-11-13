"""
Unit tests for ms_calsol_stats (src/ms_inspect/tools/calsol_stats.py).

No CASA installation required — all casatools calls mocked via open_table.
Tests cover: path validation, metadata readers, per-slice stats, G/B/K
output shape, flagged-fraction accounting, and the response envelope.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ms_inspect.tools import calsol_stats

# ---------------------------------------------------------------------------
# Mock builders
# ---------------------------------------------------------------------------

_ANT_NAMES = ["ea01", "ea02", "ea03"]
_N_ANT = len(_ANT_NAMES)
_N_CORR = 2
_N_CHAN_G = 1
_N_CHAN_B = 4


def _make_tb(
    *,
    keywords: dict | None = None,
    getcol_side: dict | None = None,
    nrows: int = 0,
    query_result: MagicMock | None = None,
) -> MagicMock:
    """Build a mock table context manager."""
    tb = MagicMock()
    tb.__enter__ = MagicMock(return_value=tb)
    tb.__exit__ = MagicMock(return_value=False)
    tb.nrows.return_value = nrows

    if keywords is not None:
        tb.getkeywords.return_value = keywords

    if getcol_side is not None:

        def _getcol(col):
            return getcol_side[col]

        tb.getcol.side_effect = _getcol

    if query_result is not None:
        tb.query.return_value = query_result

    return tb


def _make_subtable(
    *,
    nrows: int,
    ant1: np.ndarray,
    cparam: np.ndarray | None = None,
    fparam: np.ndarray | None = None,
    flag: np.ndarray,
    snr: np.ndarray,
) -> MagicMock:
    """Build a mock subtable (result of tb.query())."""
    sub = MagicMock()
    sub.nrows.return_value = nrows
    sub.close = MagicMock()

    def _getcol(col):
        if col == "ANTENNA1":
            return ant1
        if col == "CPARAM":
            return cparam
        if col == "FPARAM":
            return fparam
        if col == "FLAG":
            return flag
        if col == "SNR":
            return snr
        raise KeyError(col)

    sub.getcol.side_effect = _getcol
    return sub


def _g_table_data(n_rows_per_ant: int = 3):
    """
    G table slice: 2 corr, 1 chan, n_rows_per_ant rows per antenna.
    All solutions unflagged, amplitude ~1, phase ~0.
    """
    n_rows = _N_ANT * n_rows_per_ant
    ant1 = np.repeat(np.arange(_N_ANT), n_rows_per_ant)
    cparam = np.ones((_N_CORR, _N_CHAN_G, n_rows), dtype=complex)
    flag = np.zeros((_N_CORR, _N_CHAN_G, n_rows), dtype=bool)
    snr = np.full((_N_CORR, _N_CHAN_G, n_rows), 30.0)
    return ant1, cparam, flag, snr


def _b_table_data():
    """B table slice: 2 corr, 4 chan, 1 solution per antenna."""
    n_rows = _N_ANT
    ant1 = np.arange(_N_ANT)
    cparam = np.ones((_N_CORR, _N_CHAN_B, n_rows), dtype=complex) * 0.9
    flag = np.zeros((_N_CORR, _N_CHAN_B, n_rows), dtype=bool)
    snr = np.full((_N_CORR, _N_CHAN_B, n_rows), 50.0)
    return ant1, cparam, flag, snr


def _k_table_data():
    """K table slice: 2 corr, 1 chan, 1 solution per antenna."""
    n_rows = _N_ANT
    ant1 = np.arange(_N_ANT)
    # FPARAM: [n_corr, 1, n_rows], delays in ns
    fparam = np.array([[[1.0, 2.0, 3.0]], [[1.1, 2.1, 3.1]]], dtype=float)
    flag = np.zeros((2, 1, n_rows), dtype=bool)
    snr = np.full((2, 1, n_rows), 20.0)
    return ant1, fparam, flag, snr


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


class TestPathValidation:
    def test_missing_path_returns_error(self, tmp_path):
        result = calsol_stats.run(str(tmp_path / "nonexistent.g"))
        assert result["status"] == "error"
        assert result["error_type"] == "CALTABLE_NOT_FOUND"

    def test_file_not_dir_returns_error(self, tmp_path):
        f = tmp_path / "notatable.g"
        f.write_text("x")
        result = calsol_stats.run(str(f))
        assert result["status"] == "error"
        assert result["error_type"] == "CALTABLE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


class TestReadTableType:
    def test_g_jones(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        tb = _make_tb(keywords={"VisCal": "G Jones"})
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._read_table_type(str(tbl))
        assert result == "G"

    def test_b_jones(self, tmp_path):
        tbl = tmp_path / "BP.b"
        tbl.mkdir()
        tb = _make_tb(keywords={"VisCal": "B Jones"})
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._read_table_type(str(tbl))
        assert result == "B"

    def test_k_jones(self, tmp_path):
        tbl = tmp_path / "delay.k"
        tbl.mkdir()
        tb = _make_tb(keywords={"VisCal": "K Jones"})
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._read_table_type(str(tbl))
        assert result == "K"

    def test_missing_viscal_returns_empty(self, tmp_path):
        tbl = tmp_path / "weird.ct"
        tbl.mkdir()
        tb = _make_tb(keywords={})
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._read_table_type(str(tbl))
        assert result == ""


# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------


class TestStatHelpers:
    def test_steady_offset_gives_scatter_not_offset(self):
        rng = np.random.default_rng(0)
        ph = np.deg2rad(60.0 + rng.normal(0, 5.0, (1, 1, 2000)))
        assert calsol_stats._phase_scatter_deg(ph)[0][0] == pytest.approx(5.0, rel=0.05)

    def test_wrap_at_180(self):
        ph = np.deg2rad(np.array([[[179.0, -179.0, 179.0, -179.0]]]))
        assert calsol_stats._phase_scatter_deg(ph)[0][0] == pytest.approx(1.0, abs=1e-6)
        assert abs(calsol_stats._phase_mean_deg(ph.ravel())) == pytest.approx(180.0, abs=1e-6)

    def test_per_corr_offsets_removed(self):
        ph = np.deg2rad(np.array([[[40.0] * 5], [[-40.0] * 5]]))  # RR +40, LL -40
        np.testing.assert_allclose(calsol_stats._phase_scatter_deg(ph)[0], [0.0, 0.0], atol=1e-6)

    def test_single_time_uses_channel_axis(self):
        # Single-solution B table: a 40 deg phase ramp across 5 channels, about a
        # 70 deg offset. Scatter across channels about the mean, not NaN.
        ramp = np.deg2rad(70.0 + np.array([-20.0, -10.0, 0.0, 10.0, 20.0]))
        ph = np.stack([ramp, ramp])[:, :, np.newaxis]
        vals, axes = calsol_stats._phase_scatter_deg(ph)
        np.testing.assert_allclose(vals, [np.sqrt(200.0)] * 2, rtol=1e-3)
        assert axes == ["channel", "channel"]

    def test_time_axis_reported(self):
        ph = np.zeros((1, 1, 5))
        assert calsol_stats._phase_scatter_deg(ph)[1] == ["time"]

    def test_single_sample_has_no_scatter(self):
        vals, axes = calsol_stats._phase_scatter_deg(np.zeros((1, 1, 1)))
        assert np.isnan(vals[0]) and axes == [None]

    def test_all_nan(self):
        ph = np.full((2, 1, 5), math.nan)
        assert np.all(np.isnan(calsol_stats._phase_scatter_deg(ph)[0]))

    def test_safe_mean_ignores_nan(self):
        arr = np.array([1.0, 2.0, math.nan, 3.0])
        assert calsol_stats._safe_mean(arr) == pytest.approx(2.0)

    def test_safe_mean_all_nan(self):
        assert math.isnan(calsol_stats._safe_mean(np.full(3, math.nan)))

    def test_safe_std_single_value(self):
        # std of one valid element is nan (no spread)
        arr = np.array([5.0, math.nan])
        assert math.isnan(calsol_stats._safe_std(arr))


# ---------------------------------------------------------------------------
# _process_slice — G table
# ---------------------------------------------------------------------------


class TestProcessSliceG:
    def _run(self, tmp_path, ant1, cparam, flag, snr):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        sub = _make_subtable(nrows=len(ant1), ant1=ant1, cparam=cparam, flag=flag, snr=snr)
        tb = _make_tb(nrows=len(ant1), query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            return calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="G", n_chan_max=1
            )

    def test_all_antennas_present(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data()
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        assert set(result.keys()) == {0, 1, 2}

    def test_amplitude_mean_near_one(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data()
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        for a in range(_N_ANT):
            assert result[a]["amp_mean"] == pytest.approx(1.0, abs=1e-6)

    def test_phase_rms_near_zero(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data()
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        for a in range(_N_ANT):
            assert result[a]["phase_rms_deg"] == pytest.approx(0.0, abs=1e-6)
            assert result[a]["phase_rms_deg_per_corr"] == pytest.approx([0.0] * _N_CORR, abs=1e-6)

    def test_unflagged_fraction_zero(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data()
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        for a in range(_N_ANT):
            assert result[a]["flagged_frac"] == pytest.approx(0.0)

    def test_flagged_solutions_counted(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data(n_rows_per_ant=2)
        # flag all rows for antenna 0
        flag[:, :, ant1 == 0] = True
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        assert result[0]["flagged_frac"] == pytest.approx(1.0)
        assert result[1]["flagged_frac"] == pytest.approx(0.0)

    def test_snr_mean(self, tmp_path):
        ant1, cparam, flag, snr = _g_table_data()
        result = self._run(tmp_path, ant1, cparam, flag, snr)
        for a in range(_N_ANT):
            assert result[a]["snr_mean"] == pytest.approx(30.0)

    def test_empty_slice_returns_empty(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        sub = MagicMock()
        sub.nrows.return_value = 0
        sub.close = MagicMock()
        tb = _make_tb(nrows=0, query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="G", n_chan_max=1
            )
        assert result == {}

    def test_sub_close_always_called(self, tmp_path):
        """Verify sub.close() is called even when nrows == 0."""
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        sub = MagicMock()
        sub.nrows.return_value = 0
        sub.close = MagicMock()
        tb = _make_tb(query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="G", n_chan_max=1
            )
        sub.close.assert_called_once()


# ---------------------------------------------------------------------------
# _process_slice — B table
# ---------------------------------------------------------------------------


class TestProcessSliceB:
    def _run(self, tmp_path):
        tbl = tmp_path / "BP.b"
        tbl.mkdir()
        ant1, cparam, flag, snr = _b_table_data()
        sub = _make_subtable(nrows=_N_ANT, ant1=ant1, cparam=cparam, flag=flag, snr=snr)
        tb = _make_tb(nrows=_N_ANT, query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            return calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="B", n_chan_max=_N_CHAN_B
            )

    def test_amp_array_length(self, tmp_path):
        result = self._run(tmp_path)
        for a in range(_N_ANT):
            assert len(result[a]["amp_array"]) == _N_CHAN_B

    def test_amp_array_values(self, tmp_path):
        result = self._run(tmp_path)
        for a in range(_N_ANT):
            for v in result[a]["amp_array"]:
                assert v == pytest.approx(0.9, abs=1e-6)

    def test_amp_array_padded_with_nan(self, tmp_path):
        tbl = tmp_path / "BP.b"
        tbl.mkdir()
        ant1, cparam, flag, snr = _b_table_data()
        # Use n_chan=2 but n_chan_max=4 → last 2 entries should be NaN
        cparam_short = cparam[:, :2, :]
        flag_short = flag[:, :2, :]
        snr_short = snr[:, :2, :]
        sub = _make_subtable(
            nrows=_N_ANT, ant1=ant1, cparam=cparam_short, flag=flag_short, snr=snr_short
        )
        tb = _make_tb(nrows=_N_ANT, query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="B", n_chan_max=4
            )
        for a in range(_N_ANT):
            arr = result[a]["amp_array"]
            assert not math.isnan(arr[0])
            assert not math.isnan(arr[1])
            assert math.isnan(arr[2])
            assert math.isnan(arr[3])


# ---------------------------------------------------------------------------
# _process_slice — K table
# ---------------------------------------------------------------------------


class TestProcessSliceK:
    def _run(self, tmp_path):
        tbl = tmp_path / "delay.k"
        tbl.mkdir()
        ant1, fparam, flag, snr = _k_table_data()
        sub = _make_subtable(nrows=_N_ANT, ant1=ant1, fparam=fparam, flag=flag, snr=snr)
        tb = _make_tb(nrows=_N_ANT, query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            return calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="K", n_chan_max=1
            )

    def test_delay_ns_shape(self, tmp_path):
        result = self._run(tmp_path)
        for a in range(_N_ANT):
            # [n_corr, n_rows] — 1 row per antenna
            assert len(result[a]["delay_ns"]) == _N_CORR

    def test_delay_ns_values(self, tmp_path):
        result = self._run(tmp_path)
        # antenna 0: corr0=1.0, corr1=1.1
        assert result[0]["delay_ns"][0][0] == pytest.approx(1.0)
        assert result[0]["delay_ns"][1][0] == pytest.approx(1.1)

    def test_flagged_delay_is_nan(self, tmp_path):
        tbl = tmp_path / "delay.k"
        tbl.mkdir()
        ant1, fparam, flag, snr = _k_table_data()
        flag[:, :, 0] = True  # flag antenna 0
        sub = _make_subtable(nrows=_N_ANT, ant1=ant1, fparam=fparam, flag=flag, snr=snr)
        tb = _make_tb(nrows=_N_ANT, query_result=sub)
        with patch("ms_inspect.tools.calsol_stats.open_table", return_value=tb):
            result = calsol_stats._process_slice(
                str(tbl), spw=0, field=0, ant_names=_ANT_NAMES, table_type="K", n_chan_max=1
            )
        for corr in range(_N_CORR):
            assert math.isnan(result[0]["delay_ns"][corr][0])


# ---------------------------------------------------------------------------
# run() — full G table end-to-end
# ---------------------------------------------------------------------------


def _patch_all_for_g(tbl_path, spw_ids=(0,), field_ids=(0, 1)):
    """
    Construct all mocks needed to run calsol_stats.run() on a G table.
    Returns (patch_target, side_effect_fn).
    """
    ant1, cparam, flag, snr = _g_table_data()

    ant_tb = _make_tb(getcol_side={"NAME": np.array(_ANT_NAMES)})
    field_tb = _make_tb(getcol_side={"NAME": np.array(["3C286", "J0137"])})
    kw_tb = _make_tb(keywords={"VisCal": "G Jones"})
    axis_tb = _make_tb(
        getcol_side={
            "SPECTRAL_WINDOW_ID": np.array([0, 0, 0, 0, 0, 0]),
            "FIELD_ID": np.array([0, 0, 0, 1, 1, 1]),
        }
    )
    sub = _make_subtable(nrows=_N_ANT * 3, ant1=ant1, cparam=cparam, flag=flag, snr=snr)
    slice_tb = _make_tb(nrows=_N_ANT * 3, query_result=sub)

    calls = []

    def _open_table(path, **kwargs):
        p = str(path)
        calls.append(p)
        if p.endswith("ANTENNA"):
            return ant_tb
        if p.endswith("FIELD"):
            return field_tb
        if p == str(tbl_path):
            # first call: keywords; second: axis ids; subsequent: slices
            n = sum(1 for c in calls if c == str(tbl_path))
            if n == 1:
                return kw_tb
            if n == 2:
                return axis_tb
            return slice_tb
        return slice_tb

    return _open_table


class TestRunG:
    def test_status_ok(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl))
        assert result["status"] == "ok"

    def test_table_type_field(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        assert result["data"]["table_type"]["value"] == "G"

    def test_axis_metadata(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        d = result["data"]
        assert d["n_antennas"]["value"] == _N_ANT
        assert d["n_spw"]["value"] == 1
        assert d["n_field"]["value"] == 2
        assert d["ant_names"]["value"] == _ANT_NAMES
        assert d["field_names"]["value"] == ["3C286", "J0137"]

    def test_flagged_frac_shape(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        ff = result["data"]["flagged_frac"]["value"]
        # shape [n_ant=3, n_spw=1, n_field=2]
        assert len(ff) == _N_ANT
        assert len(ff[0]) == 1
        assert len(ff[0][0]) == 2

    def test_overall_flagged_frac_zero(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        assert result["data"]["overall_flagged_frac"]["value"] == pytest.approx(0.0)

    def test_no_antennas_lost(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        assert result["data"]["n_antennas_lost"]["value"] == 0
        assert result["data"]["antennas_lost"]["value"] == []

    def test_g_table_has_no_delay_fields(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl))
        assert "delay_ns" not in result["data"]
        assert "delay_rms_ns" not in result["data"]

    def test_g_table_has_amp_phase_fields(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        ot = _patch_all_for_g(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl))
        d = result["data"]
        assert "amp_mean" in d
        assert "phase_rms_deg" in d
        assert "amp_array" not in d  # amp_array is B-only


# ---------------------------------------------------------------------------
# amp_outlier_scan — per-(field, SpW) reference
# ---------------------------------------------------------------------------


class TestAmpOutlierScan:
    ANTS = [f"ea{i:02d}" for i in range(1, 28)]

    def _amp(self, n_spw=4, levels=(1.0, 3.0), seed=0):
        rng = np.random.default_rng(seed)
        amp = np.empty((len(self.ANTS), n_spw, len(levels)))
        for fi, lvl in enumerate(levels):
            amp[:, :, fi] = lvl * (1 + rng.normal(0, 0.02, (len(self.ANTS), n_spw)))
        return amp

    def test_field_at_different_level_gives_no_hits(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        rows, _ = amp_outlier_scan(self._amp(), self.ANTS, [0, 1, 2, 3], ["flux", "phase"], 5.0)
        assert rows == []

    def test_spectral_tilt_gives_no_hits(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._amp()
        amp[:, :, 1] *= np.linspace(0.9, 1.1, 4)  # 20% tilt across the band
        rows, _ = amp_outlier_scan(amp, self.ANTS, [0, 1, 2, 3], ["flux", "phase"], 5.0)
        assert rows == []

    def test_bad_antenna_caught_with_reference(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._amp()
        amp[4, 2, 1] = 1.5  # ea05, SpW 2, phase cal at 3.0
        rows, _ = amp_outlier_scan(amp, self.ANTS, [0, 1, 2, 3], ["flux", "phase"], 5.0)
        assert [(r["antenna"], r["spw"], r["field"]) for r in rows] == [("ea05", 2, "phase")]
        assert abs(rows[0]["ref_median"] - 3.0) < 0.1
        assert rows[0]["n_sigma_field"] is not None

    def test_reference_shows_whole_spw_offset(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._amp()
        amp[:, 3, 0] *= 1.5  # every antenna in SpW 3 of the flux cal
        rows, ref = amp_outlier_scan(amp, self.ANTS, [0, 1, 2, 3], ["flux", "phase"], 5.0)
        assert rows == []
        off = ref[0]["spw_offset_n_sigma_field"]
        assert off[3] > 5 and all(abs(x) < 5 for x in off[:3])

    def test_sparse_or_flat_group_is_null(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._amp()
        amp[2:, 0, 0] = np.nan  # 2 finite values
        amp[:, 1, 0] = 1.0  # MAD = 0
        rows, ref = amp_outlier_scan(amp, self.ANTS, [0, 1, 2, 3], ["flux", "phase"], 5.0)
        assert ref[0]["spw_median"][0] is None and ref[0]["spw_n"][0] == 2
        assert ref[0]["spw_median"][1] is None
        assert not any(r["field"] == "flux" and r["spw"] in (0, 1) for r in rows)


class TestAmpFracFloor:
    """An amplitude outlier needs both the sigma test and a fractional deviation."""

    ANTS = [f"ea{i:02d}" for i in range(1, 27)]

    def _tight(self):
        # 26 antennas agreeing to ~0.2%, the spread seen on a real phase cal.
        rng = np.random.default_rng(1)
        return (1.517 * (1 + rng.normal(0, 0.002, len(self.ANTS)))).reshape(-1, 1, 1)

    def test_many_sigma_small_offset_is_not_an_outlier(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._tight()
        amp[11, 0, 0] = 1.476  # 2.7% low: many sigma on a 0.2% spread
        rows, _ = amp_outlier_scan(amp, self.ANTS, [0], ["phase"], 5.0)
        assert rows == []

    def test_large_offset_is_an_outlier(self):
        from ms_inspect.tools.calsol_stats import amp_outlier_scan

        amp = self._tight()
        amp[11, 0, 0] = 1.517 * 0.6  # 40% low
        rows, _ = amp_outlier_scan(amp, self.ANTS, [0], ["phase"], 5.0)
        assert [r["antenna"] for r in rows] == ["ea12"]
        assert rows[0]["frac_dev"] > 0.30

    def test_threshold_reported(self):
        from ms_inspect.tools.calsol_stats import AMP_FRAC_MIN, _compute_outliers

        out = _compute_outliers(None, self._tight(), self.ANTS, [0], ["phase"], 3.0, 5.0)
        assert out["thresholds"]["amp_frac_min"] == AMP_FRAC_MIN


def _patch_all_for_k(tbl_path):
    """Mocks for calsol_stats.run() on a K table whose SNR column is all 0 (as CASA writes)."""
    ant1, fparam, flag, _ = _k_table_data()
    snr = np.zeros_like(fparam)
    ant_tb = _make_tb(getcol_side={"NAME": np.array(_ANT_NAMES)})
    field_tb = _make_tb(getcol_side={"NAME": np.array(["3C286"])})
    kw_tb = _make_tb(keywords={"VisCal": "K Jones"})
    axis_tb = _make_tb(
        getcol_side={"SPECTRAL_WINDOW_ID": np.array([0, 0, 0]), "FIELD_ID": np.array([0, 0, 0])}
    )
    sub = _make_subtable(nrows=_N_ANT, ant1=ant1, fparam=fparam, flag=flag, snr=snr)
    slice_tb = _make_tb(nrows=_N_ANT, query_result=sub)
    calls = []

    def _open_table(path, **kwargs):
        p = str(path)
        calls.append(p)
        if p.endswith("ANTENNA"):
            return ant_tb
        if p.endswith("FIELD"):
            return field_tb
        if p == str(tbl_path):
            n = sum(1 for c in calls if c == str(tbl_path))
            return kw_tb if n == 1 else axis_tb if n == 2 else slice_tb
        return slice_tb

    return _open_table


class TestRunKSnr:
    def test_zero_snr_delay_table_reports_no_low_snr(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RADIO_MCP_DIR", raising=False)
        tbl = tmp_path / "delay.k"
        tbl.mkdir()
        ot = _patch_all_for_k(tbl)
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            result = calsol_stats.run(str(tbl), verbosity="full")
        assert result["status"] == "ok"
        out = result["data"]["outliers"]
        assert out["low_snr"] == [] and out["low_snr_n_antennas"] == 0
        assert result["data"]["snr_mean"]["flag"] == "UNAVAILABLE"
        npz = np.load(str(tbl) + ".calsol_stats.npz")
        assert "snr_mean" not in npz.files


# ---------------------------------------------------------------------------
# Table-wide scalars: amp_median and delay_abs_max_ns
# ---------------------------------------------------------------------------


class TestTableScalars:
    def _cparam(self):
        # Antenna 0 at 1.0 throughout; antennas 1 and 2 at 0.1, 0.1, 10.
        # Median over every solution is 1.0; median of the per-antenna means is 3.4.
        rows = [1.0, 1.0, 1.0, 0.1, 0.1, 10.0, 0.1, 0.1, 10.0]
        return np.array([[rows], [rows]], dtype=complex)

    def _run(self, tmp_path, verbosity):
        tbl = tmp_path / "leak.d"
        tbl.mkdir()
        ant1, _, flag, snr = _g_table_data()
        sub = _make_subtable(nrows=_N_ANT * 3, ant1=ant1, cparam=self._cparam(), flag=flag, snr=snr)
        base = _patch_all_for_g(tbl)

        def _open_table(path, **kwargs):
            got = base(path, **kwargs)
            got.query.return_value = sub
            return got

        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=_open_table):
            return calsol_stats.run(str(tbl), verbosity=verbosity)

    def test_amp_median_is_over_every_solution_not_the_antenna_means(self, tmp_path):
        d = self._run(tmp_path, "full")["data"]
        # the custom solutions were read: antenna 1's mean is 3.4, not 1.0
        assert d["amp_mean"]["value"][1][0][0] == pytest.approx(3.4)
        assert d["amp_median"]["value"] == pytest.approx(1.0)

    def test_default_compact_call_returns_amp_median(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=_patch_all_for_g(tbl)):
            d = calsol_stats.run(str(tbl))["data"]
        assert d["amp_median"]["value"] == pytest.approx(1.0)
        assert d["amp_median"]["flag"] == "COMPLETE"

    def test_delay_abs_max_in_full_and_compact(self, tmp_path):
        tbl = tmp_path / "delay.k"
        tbl.mkdir()
        for verbosity in ("full", "compact"):
            with patch(
                "ms_inspect.tools.calsol_stats.open_table", side_effect=_patch_all_for_k(tbl)
            ):
                d = calsol_stats.run(str(tbl), verbosity=verbosity)["data"]
            got = d["delay_abs_max_ns"]
            got = got["value"] if isinstance(got, dict) else got
            assert got == pytest.approx(3.1)
            assert "amp_median" not in d

    def test_g_table_has_no_delay_abs_max(self, tmp_path):
        tbl = tmp_path / "gain.g"
        tbl.mkdir()
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=_patch_all_for_g(tbl)):
            d = calsol_stats.run(str(tbl), verbosity="full")["data"]
        assert "delay_abs_max_ns" not in d


class TestKcrossAndSignedCompactDelay:
    """CR-2: KCROSS corr-1 structural zero exclusion and signed largest-|delay| in compact mode."""

    def _mock_delay_table(self, tbl_path, viscal: str, spw_delays: dict[int, np.ndarray]):
        """Build open_table side_effect for a K or KCROSS table with per-SPW FPARAM [n_corr, 1, n_ant]."""
        spws = sorted(spw_delays.keys())
        ant_tb = _make_tb(getcol_side={"NAME": np.array(_ANT_NAMES)})
        field_tb = _make_tb(getcol_side={"NAME": np.array(["3C286"])})
        kw_tb = _make_tb(keywords={"VisCal": viscal})
        axis_tb = _make_tb(
            getcol_side={
                "SPECTRAL_WINDOW_ID": np.repeat(spws, _N_ANT),
                "FIELD_ID": np.zeros(len(spws) * _N_ANT, dtype=int),
            }
        )
        ant1 = np.arange(_N_ANT)
        flag = np.zeros((2, 1, _N_ANT), dtype=bool)
        snr = np.zeros((2, 1, _N_ANT), dtype=float)
        subs = {
            spw: _make_subtable(
                nrows=_N_ANT, ant1=ant1, fparam=fparam, flag=flag.copy(), snr=snr.copy()
            )
            for spw, fparam in spw_delays.items()
        }

        calls: list[str] = []

        def _open_table(path, **kwargs):
            p = str(path)
            calls.append(p)
            if p.endswith("ANTENNA"):
                return ant_tb
            if p.endswith("FIELD"):
                return field_tb
            n = sum(1 for c in calls if c == str(tbl_path))
            if n == 1:
                return kw_tb
            if n == 2:
                return axis_tb
            tb = _make_tb(nrows=len(spws) * _N_ANT)

            def _query(expr):
                for spw in spws:
                    if f"SPECTRAL_WINDOW_ID == {spw}" in expr:
                        return subs[spw]
                raise AssertionError(f"Unexpected query: {expr}")

            tb.query.side_effect = _query
            return tb

        return _open_table

    def test_kcross_single_spw_excludes_corr1_structural_zero(self, tmp_path):
        tbl = tmp_path / "kcross.K"
        tbl.mkdir()
        # Corr 0 holds 10.69 ns on every antenna; corr 1 holds CASA's structural 0.0.
        fparam = np.array([[[10.69, 10.69, 10.69]], [[0.0, 0.0, 0.0]]], dtype=float)
        for viscal in ("Kcross Jones", "KCROSS Jones"):
            ot = self._mock_delay_table(tbl, viscal, {0: fparam})
            with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
                compact = calsol_stats.run(str(tbl), verbosity="compact")["data"]
            ot_full = self._mock_delay_table(tbl, viscal, {0: fparam})
            with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot_full):
                full = calsol_stats.run(str(tbl), verbosity="full")["data"]

            # No 0.5x compact dilution and no 1/sqrt(2) RMS dilution!
            assert compact["delay_ns"]["value"] == pytest.approx([10.69, 10.69, 10.69])
            assert compact["delay_rms_ns"]["value"] == [[pytest.approx(10.69)]]
            assert compact["delay_abs_max_ns"]["value"] == pytest.approx(10.69)
            assert full["delay_rms_ns"]["value"] == [[pytest.approx(10.69)]]
            assert full["delay_abs_max_ns"]["value"] == pytest.approx(10.69)

    def test_kcross_multi_spw_opposite_sign_no_cancellation(self, tmp_path):
        tbl = tmp_path / "kcross2.K"
        tbl.mkdir()
        # SPW 0 = +10.69 ns, SPW 1 = -6.68 ns (run S3 sign-cancellation regression)
        f0 = np.array([[[10.69, 10.69, 10.69]], [[0.0, 0.0, 0.0]]], dtype=float)
        f1 = np.array([[[-6.68, -6.68, -6.68]], [[0.0, 0.0, 0.0]]], dtype=float)
        ot = self._mock_delay_table(tbl, "Kcross Jones", {0: f0, 1: f1})
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            compact = calsol_stats.run(str(tbl), verbosity="compact")["data"]
        assert compact["delay_ns"]["value"] == pytest.approx([10.69, 10.69, 10.69])

        # Flip magnitudes so negative SPW dominates: sign of -10.69 must be preserved!
        f0_neg = np.array([[[6.68, 6.68, 6.68]], [[0.0, 0.0, 0.0]]], dtype=float)
        f1_neg = np.array([[[-10.69, -10.69, -10.69]], [[0.0, 0.0, 0.0]]], dtype=float)
        ot_neg = self._mock_delay_table(tbl, "Kcross Jones", {0: f0_neg, 1: f1_neg})
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot_neg):
            compact_neg = calsol_stats.run(str(tbl), verbosity="compact")["data"]
        assert compact_neg["delay_ns"]["value"] == pytest.approx([-10.69, -10.69, -10.69])

    def test_standard_k_table_retains_both_parallel_hands(self, tmp_path):
        tbl = tmp_path / "delay.K"
        tbl.mkdir()
        fparam = np.array([[[1.0, 2.0, 3.0]], [[1.1, -2.5, 0.0]]], dtype=float)
        ot = self._mock_delay_table(tbl, "K Jones", {0: fparam})
        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
            compact = calsol_stats.run(str(tbl), verbosity="compact")["data"]
        assert compact["delay_ns"]["value"] == pytest.approx([1.1, -2.5, 3.0])
        assert compact["delay_abs_max_ns"]["value"] == pytest.approx(3.0)
        # Both corr 0 and corr 1 contribute to K-table RMS (including legitimate 0.0 on ant 2 corr 1)
        expected_rms = math.sqrt(np.mean(np.array([1.0, 2.0, 3.0, 1.1, -2.5, 0.0]) ** 2))
        assert compact["delay_rms_ns"]["value"] == [[pytest.approx(expected_rms)]]
