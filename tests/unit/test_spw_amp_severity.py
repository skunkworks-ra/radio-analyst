"""Unit tests for spw_amp_severity pure-logic helpers (no CASA required)."""

from __future__ import annotations

import numpy as np

from ms_inspect.tools.spw_amp_severity import _ChanDiffTracker, _ChanReservoir, _corr_first_axis


def test_corr_first_axis_folds_corr_and_rows():
    # [n_corr=2, n_chan=3, n_rows=4] → [n_chan=3, n_corr*n_rows=8]
    arr = np.arange(2 * 3 * 4).reshape(2, 3, 4)
    out = _corr_first_axis(arr)
    assert out.shape == (3, 8)
    # channel 0 must contain exactly the corr/row values at chan index 0
    expected_ch0 = np.concatenate([arr[0, 0, :], arr[1, 0, :]])
    np.testing.assert_array_equal(np.sort(out[0]), np.sort(expected_ch0))


def test_reservoir_stats_recover_distribution():
    rng = np.random.default_rng(0)
    data = rng.normal(10.0, 2.0, size=200_000)
    data = np.abs(data)  # amplitudes are positive
    res = _ChanReservoir(5000)
    # feed in several batches to exercise the merge path
    for batch in np.array_split(data, 7):
        res.add(batch, rng)
    st = res.stats()
    # sample-based median/MAD should track the population within a few percent
    assert abs(st["median"] - np.median(data)) / np.median(data) < 0.02
    pop_mad = np.median(np.abs(data - np.median(data)))
    assert abs(st["mad"] - pop_mad) / pop_mad < 0.05
    # min/max are tracked EXACTLY, not from the sample
    assert st["min"] == float(data.min())
    assert st["max"] == float(data.max())


def test_reservoir_bounded_memory():
    rng = np.random.default_rng(1)
    res = _ChanReservoir(1000)
    for _ in range(50):
        res.add(rng.random(10_000), rng)
    assert res.vals.size <= 1000
    assert res.n_unflagged == 50 * 10_000


def test_reservoir_empty_returns_none():
    assert _ChanReservoir(100).stats() is None


def test_parallel_corr_follows_ddid_polarization_row():
    from ms_inspect.util.selection import parallel_corr_from_codes

    # POLARIZATION row 0 = RR LL, row 1 = RR RL LR LL; DDID 0 points at row 1.
    corr_by_pol = [[5, 8], [5, 6, 7, 8]]
    out = parallel_corr_from_codes(corr_by_pol, pol_ids=[1, 0])
    assert out[0] == [(0, "RR"), (3, "LL")]
    assert out[1] == [(0, "RR"), (1, "LL")]


def test_cross_hands_widen_pooled_mad():
    # Bright calibrator: parallel hands ~10 Jy, cross hands ~0.1 Jy.
    rng = np.random.default_rng(2)
    amp = np.empty((4, 1, 1000))
    amp[[0, 3]] = 10.0 + rng.normal(0, 0.1, (2, 1, 1000))
    amp[[1, 2]] = 0.1 + rng.normal(0, 0.01, (2, 1, 1000))
    pooled = _corr_first_axis(amp)[0]
    par = _corr_first_axis(amp[[0, 3]])[0]
    mad = lambda v: np.median(np.abs(v - np.median(v)))  # noqa: E731
    assert mad(pooled) > 10 * mad(par)


def test_run_parallel_hands_and_residual(real_ms_calibrated):
    from ms_inspect.tools.spw_amp_severity import run

    out = run(real_ms_calibrated, datacolumn="residual", max_per_chan_records=0)
    assert out["status"] == "ok"
    spws = out["data"]["per_spw"]
    assert spws and all(s["correlations_used"] == ["LL", "RR"] for s in spws)


def test_run_unmatched_field_raises(real_ms_calibrated):
    import pytest

    from ms_inspect.exceptions import ComputationError
    from ms_inspect.tools.spw_amp_severity import run

    with pytest.raises(ComputationError, match="matches no field"):
        run(real_ms_calibrated, field="NOPE")


def test_chan_diff_tracker_cancels_extended_sky_and_detects_rfi():
    """Adjacent-channel complex diff cancels smooth extended sky (std/MAD ~ 1.0)
    and strongly flags narrow-band/burst RFI (std/MAD >> 1, gt10sigma > 0)."""
    rng = np.random.default_rng(7)
    n_par, n_chan, n_rows = 2, 64, 500
    sky = rng.exponential(scale=3.0, size=(n_par, 1, n_rows)) * np.exp(
        1j * rng.uniform(-np.pi, np.pi, size=(n_par, 1, n_rows))
    )
    noise = 0.05 * (
        rng.normal(0, 1, (n_par, n_chan, n_rows)) + 1j * rng.normal(0, 1, (n_par, n_chan, n_rows))
    )
    clean = sky + noise
    dv_clean = np.abs(clean[:, 1:, :] - clean[:, :-1, :]).ravel() / np.sqrt(2.0)

    tr_clean = _ChanDiffTracker(50_000)
    for batch in np.array_split(dv_clean, 4):
        tr_clean.add(batch, rng)
    st_clean = tr_clean.stats()
    assert st_clean is not None
    assert 0.90 < st_clean["std_over_mad"] < 1.15
    assert st_clean["gt10sigma_frac"] == 0.0

    dirty = clean.copy()
    dirty[:, 20:22, :300] += 5.0
    dv_dirty = np.abs(dirty[:, 1:, :] - dirty[:, :-1, :]).ravel() / np.sqrt(2.0)
    tr_dirty = _ChanDiffTracker(50_000)
    tr_dirty.add(dv_dirty, rng)
    st_dirty = tr_dirty.stats()
    assert st_dirty is not None
    assert st_dirty["std_over_mad"] > 5.0
    assert st_dirty["gt10sigma_frac"] > 0.01
    assert st_dirty["rms"] > 2.0 * st_clean["rms"]


def test_run_emits_chan_diff_and_spw_rms_ratio(real_ms_calibrated):
    from ms_inspect.tools.spw_amp_severity import run

    out = run(real_ms_calibrated, datacolumn="CORRECTED_DATA", max_per_chan_records=0)
    assert out["status"] == "ok"
    d = out["data"]
    assert d["chan_diff_rms"]["flag"] == "COMPLETE"
    assert d["chan_diff_std_over_mad"]["flag"] == "COMPLETE"
    assert d["max_spw_chan_diff_std_over_mad"]["flag"] == "COMPLETE"
    assert d["spw_rms_ratio"]["flag"] == "COMPLETE"
    assert d["spw_rms_ratio"]["value"] >= 1.0
    for e in d["per_spw"]:
        assert e["chan_diff_rms"]["flag"] == "COMPLETE"
        assert e["chan_diff_std_over_mad"]["flag"] == "COMPLETE"


def _make_fake_multi_spw_ms(tmp_path, *, flag_spw2: bool = False):
    """Build mocked table context for a 3-SPW MS (SPW 0, 1, 2) with optional 100%-flagged SPW 2."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    ms_dir = tmp_path / "synthetic.ms"
    ms_dir.mkdir()
    (ms_dir / "table.info").write_text("Type = Measurement Set\n")

    rng = np.random.default_rng(123)
    n_chan = 8
    n_rows = 40
    spw_freqs = {
        0: np.linspace(1.00e9, 1.064e9, n_chan),
        1: np.linspace(1.40e9, 1.464e9, n_chan),
        2: np.linspace(1.80e9, 1.864e9, n_chan),
    }
    dd_to_spw = [0, 1, 2]
    data_by_dd: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for ddid in range(3):
        vis = (1.0 + 0.2 * ddid) + 0.05 * (
            rng.normal(0, 1, (2, n_chan, n_rows)) + 1j * rng.normal(0, 1, (2, n_chan, n_rows))
        )
        flg = np.zeros((2, n_chan, n_rows), dtype=bool)
        if ddid == 1:
            # 25% flagged on SPW 1
            flg[:, :2, :] = True
        if ddid == 2 and flag_spw2:
            flg[:, :, :] = True
        data_by_dd[ddid] = (vis, flg)

    queried_ddids: list[int] = []

    class _FakeSubTable:
        def __init__(self, ddid: int):
            self._ddid = ddid

        def nrows(self) -> int:
            return n_rows

        def getcol(self, col: str, startrow: int = 0, nrow: int = n_rows):
            vis, flg = data_by_dd[self._ddid]
            sl = slice(startrow, startrow + nrow)
            if col == "FLAG":
                return flg[:, :, sl]
            return vis[:, :, sl]

        def close(self) -> None:
            pass

    @contextmanager
    def fake_open_table(path: str):
        tb = MagicMock()
        if path.endswith("/DATA_DESCRIPTION"):
            tb.getcol.return_value = dd_to_spw
        elif path.endswith("/SPECTRAL_WINDOW"):
            tb.nrows.return_value = len(spw_freqs)
            tb.getcell.side_effect = lambda col, row: spw_freqs[row]
        elif path.endswith("/FIELD"):
            tb.getcol.return_value = ["TARGET"]
        else:
            tb.colnames.return_value = ["DATA", "CORRECTED_DATA", "MODEL_DATA", "FLAG"]

            def _query(expr: str):
                # expr looks like 'DATA_DESC_ID == 1' or 'DATA_DESC_ID == 1 && FIELD_ID IN [0]'
                ddid = int(expr.split("DATA_DESC_ID ==", 1)[1].strip().split()[0])
                queried_ddids.append(ddid)
                return _FakeSubTable(ddid)

            tb.query.side_effect = _query
        yield tb

    corr_by_dd = [[(0, "RR"), (1, "LL")] for _ in dd_to_spw]
    return ms_dir, fake_open_table, corr_by_dd, queried_ddids


def test_spw_filter_skips_unselected_ddids_and_records_stage_log(tmp_path, monkeypatch):
    import json

    from ms_inspect.exceptions import ComputationError
    from ms_inspect.tools import spw_amp_severity

    ms_dir, fake_open_table, corr_by_dd, queried_ddids = _make_fake_multi_spw_ms(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    monkeypatch.setattr(spw_amp_severity, "open_table", fake_open_table)
    monkeypatch.setattr(spw_amp_severity, "parallel_corr_by_ddid", lambda _ms: corr_by_dd)

    # List-repr and comma/range spw filtering: only SPW 0 and 2 should be scanned.
    out = spw_amp_severity.run(
        str(ms_dir),
        datacolumn="CORRECTED_DATA",
        spw="[0, 2]",
        workdir=str(workdir),
        max_per_chan_records=0,
    )
    assert out["status"] == "ok"
    d = out["data"]
    assert d["spw"] == "0,2"
    assert d["n_spw"] == 2
    assert [e["spw_id"] for e in d["per_spw"]] == [0, 2]
    assert queried_ddids == [0, 2]
    # No verdict arrays anywhere in data
    assert "clean_spws" not in d
    assert "bad_spws" not in d

    # stage_log.jsonl records spw in measurement
    log_lines = [
        json.loads(line) for line in (workdir / "stage_log.jsonl").read_text().splitlines() if line
    ]
    assert len(log_lines) == 1
    assert log_lines[0]["stage"] == "spw_amp_severity"
    assert log_lines[0]["measurement"]["spw"] == "0,2"

    # Unmatched / out-of-range SPW raises ComputationError before scanning chunks
    import pytest

    with pytest.raises(ComputationError):
        spw_amp_severity.run(str(ms_dir), spw="99")

    # Channel slice syntax (':') is rejected rather than silently stripped
    with pytest.raises(ComputationError, match="Channel selection"):
        spw_amp_severity.run(str(ms_dir), spw="0:5~58")


def test_per_spw_counts_freq_ghz_and_uniform_keys_on_empty_spw(tmp_path, monkeypatch):
    import pytest

    from ms_inspect.tools import spw_amp_severity

    ms_dir, fake_open_table, corr_by_dd, _ = _make_fake_multi_spw_ms(tmp_path, flag_spw2=True)
    monkeypatch.setattr(spw_amp_severity, "open_table", fake_open_table)
    monkeypatch.setattr(spw_amp_severity, "parallel_corr_by_ddid", lambda _ms: corr_by_dd)

    out = spw_amp_severity.run(
        str(ms_dir),
        datacolumn="CORRECTED_DATA",
        max_per_chan_records=0,
    )
    per_spw = {e["spw_id"]: e for e in out["data"]["per_spw"]}
    assert set(per_spw.keys()) == {0, 1, 2}

    # SPW 0: 0% flagged (2 par * 8 chan * 40 rows = 640 unflagged)
    assert per_spw[0]["n_unflagged"] == 640
    assert per_spw[0]["n_flagged"] == 0
    assert per_spw[0]["unflagged_fraction"] == pytest.approx(1.0)
    assert per_spw[0]["centre_freq_ghz"] == pytest.approx(per_spw[0]["centre_freq_mhz"] / 1000.0)

    # SPW 1: 25% flagged (2 of 8 channels flagged)
    assert per_spw[1]["n_unflagged"] == 480
    assert per_spw[1]["n_flagged"] == 160
    assert per_spw[1]["unflagged_fraction"] == pytest.approx(0.75)

    # SPW 2: 100% flagged -> uniform keys with populated SPWs + UNAVAILABLE fmt_fields
    assert per_spw[2]["n_unflagged"] == 0
    assert per_spw[2]["n_flagged"] == 640
    assert per_spw[2]["unflagged_fraction"] == pytest.approx(0.0)
    assert per_spw[2]["centre_freq_ghz"] == pytest.approx(per_spw[2]["centre_freq_mhz"] / 1000.0)
    assert set(per_spw[2].keys()) == set(per_spw[0].keys())
    for k in (
        "band_floor",
        "band_robust_sigma",
        "estimated_discardable_frac",
        "chan_diff_rms",
        "chan_diff_noise_density",
        "chan_diff_std",
        "chan_diff_mad_sigma",
        "chan_diff_std_over_mad",
        "chan_diff_gt10sigma_frac",
        "chan_diff_max",
    ):
        assert per_spw[2][k]["value"] is None
        assert per_spw[2][k]["flag"] == "UNAVAILABLE"

    assert per_spw[0]["chan_width_hz"] == pytest.approx((1.064e9 - 1.00e9) / 7, rel=1e-6)
    assert per_spw[0]["chan_diff_noise_density"]["flag"] == "COMPLETE"
    assert out["data"]["spw_noise_density_ratio"]["flag"] == "COMPLETE"

    # Counts, centre_freq_ghz, chan_width_hz, and chan_diff_noise_density survive per_chan truncation!
    out_trunc = spw_amp_severity.run(
        str(ms_dir),
        datacolumn="CORRECTED_DATA",
        max_per_chan_records=4,
    )
    assert out_trunc["data"]["per_chan_truncated"]["value"] is True
    for entry in out_trunc["data"]["per_spw"]:
        assert "per_chan" not in entry
        assert "centre_freq_ghz" in entry
        assert "chan_width_hz" in entry
        assert "chan_diff_noise_density" in entry
        assert "n_unflagged" in entry
        assert "n_flagged" in entry
        assert "unflagged_fraction" in entry


def test_mixed_channel_widths_noise_density_ratio_near_one(tmp_path, monkeypatch):
    """Pure thermal noise in mixed 2 MHz continuum + 15.625 kHz zoom SPWs:
    raw spw_rms_ratio ~ sqrt(128) = 11.3, while bandwidth-normalized spw_noise_density_ratio ~ 1.0."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    import pytest

    from ms_inspect.tools import spw_amp_severity

    ms_dir = tmp_path / "mixed_bw.ms"
    ms_dir.mkdir()
    (ms_dir / "table.info").write_text("Type = Measurement Set\n")

    rng = np.random.default_rng(42)
    n_chan = 32
    n_rows = 200
    # SPW 0, 1: 2 MHz continuum; SPW 2: 15.625 kHz zoom (128x narrower)
    cw_by_spw = {0: 2.0e6, 1: 2.0e6, 2: 15_625.0}
    spw_freqs = {
        spw_id: 1.4e9 + np.arange(n_chan, dtype=float) * cw for spw_id, cw in cw_by_spw.items()
    }
    dd_to_spw = [0, 1, 2]
    # Constant noise density sigma_0 = 50 Jy * Hz^{1/2} -> per-channel sigma = sigma_0 / sqrt(cw)
    sigma_density = 50.0
    data_by_dd: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for ddid, spw_id in enumerate(dd_to_spw):
        sigma_ch = sigma_density / np.sqrt(cw_by_spw[spw_id])
        # Complex Gaussian with E[|V(ch) - V(ch-1)|^2 / 2] = 2 * sigma_ch^2 (real + imag)
        vis = 1.0 + (sigma_ch / np.sqrt(2.0)) * (
            rng.normal(0.0, 1.0, (2, n_chan, n_rows))
            + 1j * rng.normal(0.0, 1.0, (2, n_chan, n_rows))
        )
        flg = np.zeros((2, n_chan, n_rows), dtype=bool)
        data_by_dd[ddid] = (vis, flg)

    class _FakeSubTable:
        def __init__(self, ddid: int):
            self._ddid = ddid

        def nrows(self) -> int:
            return n_rows

        def getcol(self, col: str, startrow: int = 0, nrow: int = n_rows):
            vis, flg = data_by_dd[self._ddid]
            sl = slice(startrow, startrow + nrow)
            return flg[:, :, sl] if col == "FLAG" else vis[:, :, sl]

        def close(self) -> None:
            pass

    @contextmanager
    def fake_open_table(path: str):
        tb = MagicMock()
        if path.endswith("/DATA_DESCRIPTION"):
            tb.getcol.return_value = dd_to_spw
        elif path.endswith("/SPECTRAL_WINDOW"):
            tb.nrows.return_value = len(spw_freqs)
            tb.colnames.return_value = ["CHAN_FREQ", "CHAN_WIDTH"]

            def _getcell(col: str, row: int):
                if col == "CHAN_FREQ":
                    return spw_freqs[row]
                if col == "CHAN_WIDTH":
                    # Include negative channel widths (USB/LSB) to verify |CHAN_WIDTH|
                    sign = -1.0 if row == 2 else 1.0
                    return np.full(n_chan, sign * cw_by_spw[row], dtype=float)
                raise KeyError(col)

            tb.getcell.side_effect = _getcell
        elif path.endswith("/FIELD"):
            tb.getcol.return_value = ["TARGET"]
        else:
            tb.colnames.return_value = ["DATA", "CORRECTED_DATA", "FLAG"]
            tb.query.side_effect = lambda expr: _FakeSubTable(
                int(expr.split("DATA_DESC_ID ==", 1)[1].strip().split()[0])
            )
        yield tb

    corr_by_dd = [[(0, "RR"), (1, "LL")] for _ in dd_to_spw]
    monkeypatch.setattr(spw_amp_severity, "open_table", fake_open_table)
    monkeypatch.setattr(spw_amp_severity, "parallel_corr_by_ddid", lambda _ms: corr_by_dd)

    out = spw_amp_severity.run(str(ms_dir), datacolumn="CORRECTED_DATA", max_per_chan_records=0)
    assert out["status"] == "ok"
    d = out["data"]

    # Raw RMS ratio sees sqrt(2e6 / 15625) = sqrt(128) = 11.314x jump on pure thermal noise
    assert d["spw_rms_ratio"]["flag"] == "COMPLETE"
    assert d["spw_rms_ratio"]["value"] == pytest.approx(np.sqrt(128.0), rel=0.05)

    # Bandwidth-normalized noise density ratio stays ~1.0
    assert d["spw_noise_density_ratio"]["flag"] == "COMPLETE"
    assert d["spw_noise_density_ratio"]["value"] == pytest.approx(1.0, abs=0.05)

    per_spw = {e["spw_id"]: e for e in d["per_spw"]}
    assert per_spw[0]["chan_width_hz"] == pytest.approx(2.0e6)
    assert per_spw[2]["chan_width_hz"] == pytest.approx(15_625.0)
    for spw_id in (0, 1, 2):
        assert per_spw[spw_id]["chan_diff_noise_density"]["flag"] == "COMPLETE"
        assert per_spw[spw_id]["chan_diff_noise_density"]["value"] == pytest.approx(
            sigma_density, rel=0.05
        )


def test_server_spw_amp_severity_input_exposes_spw():
    from ms_inspect.server import SpwAmpSeverityInput

    model = SpwAmpSeverityInput(ms_path="/fake.ms", spw="3,4,5,8,16,17")
    assert model.spw == "3,4,5,8,16,17"
    default_model = SpwAmpSeverityInput(ms_path="/fake.ms")
    assert default_model.spw == ""
