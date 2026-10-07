"""Unit tests for spw_amp_severity pure-logic helpers (no CASA required)."""

from __future__ import annotations

import numpy as np

from ms_inspect.tools.spw_amp_severity import _ChanReservoir, _corr_first_axis


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
