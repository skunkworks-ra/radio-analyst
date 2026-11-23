"""
Unit tests for ms_inspect/tools/corrected_stats.py pure numeric core.

No CASA required — exercises parallel-hand selection and the per-field
amplitude/phase statistics on synthetic visibility arrays.
"""

from __future__ import annotations

import numpy as np

from ms_inspect.tools.corrected_stats import _field_stats, _parallel_indices


class TestParallelIndices:
    def test_circular_basis(self):
        # RR RL LR LL  → codes 5 6 7 8 ; parallel = RR(0), LL(3)
        assert _parallel_indices([5, 6, 7, 8]) == [0, 3]

    def test_linear_basis(self):
        # XX XY YX YY → codes 9 10 11 12 ; parallel = XX(0), YY(3)
        assert _parallel_indices([9, 10, 11, 12]) == [0, 3]

    def test_parallel_only(self):
        assert _parallel_indices([5, 8]) == [0, 1]

    def test_unknown_falls_back_to_all(self):
        assert _parallel_indices([99, 98]) == [0, 1]


class TestFieldStats:
    def _block(self, amp, phase_deg, n_chan=10, n_rows=20, n_corr=4):
        """Build a [n_corr, n_chan, n_rows] complex block at fixed amp/phase."""
        val = amp * np.exp(1j * np.deg2rad(phase_deg))
        return np.full((n_corr, n_chan, n_rows), val, dtype=complex)

    def test_point_source_clean(self):
        data = self._block(15.0, 0.0)
        flag = np.zeros_like(data, dtype=bool)
        s = _field_stats(data, flag, [0, 3], None, None)
        assert abs(s["amp_median"] - 15.0) < 1e-6
        assert s["amp_robust_std"] == 0.0
        assert abs(s["phase_rms_deg"]) < 1e-6
        # channel-averaged: one sample per (parallel corr, row) = 2 * 20
        assert s["n_samples"] == 2 * 20

    def test_channel_range_excludes_edges(self):
        data = self._block(1.0, 0.0)
        # Corrupt edge channels (0 and 9) with huge amplitude.
        data[:, 0, :] = 1000.0
        data[:, 9, :] = 1000.0
        flag = np.zeros_like(data, dtype=bool)
        # Without edge exclusion the median is pulled up.
        s_all = _field_stats(data, flag, [0, 3], None, None)
        assert s_all["amp_p95"] > 100
        # In-band channels 1..8 only → clean.
        s_in = _field_stats(data, flag, [0, 3], 1, 9)
        assert abs(s_in["amp_median"] - 1.0) < 1e-6
        assert s_in["amp_p95"] < 2.0

    def test_all_flagged(self):
        data = self._block(5.0, 0.0)
        flag = np.ones_like(data, dtype=bool)
        s = _field_stats(data, flag, [0, 3], None, None)
        assert s["amp_median"] is None
        assert s["phase_rms_deg"] is None
        assert s["n_samples"] == 0

    def test_phase_rms(self):
        # Half the rows at +30 deg, half at -30 deg → RMS = 30 deg.
        data = self._block(2.0, 0.0, n_rows=20)
        data[:, :, :10] = 2.0 * np.exp(1j * np.deg2rad(30.0))
        data[:, :, 10:] = 2.0 * np.exp(1j * np.deg2rad(-30.0))
        flag = np.zeros_like(data, dtype=bool)
        s = _field_stats(data, flag, [0, 3], None, None)
        assert abs(s["phase_rms_deg"] - 30.0) < 0.5


def test_mixed_polarization_rows_and_mixed_channel_counts_per_ddid(tmp_path):
    """Multi-row POLARIZATION ([RR,LL] row 0 + [RR,RL,LR,LL] row 1) with mixed
    channel counts (16 vs 64) must neither crash on getcol nor mis-index RL as LL."""
    from unittest.mock import MagicMock, patch

    from ms_inspect.tools import corrected_stats

    ms_dir = tmp_path / "mixed_pol.ms"
    ms_dir.mkdir()
    (ms_dir / "table.info").write_text("Type = Measurement Set\n")

    # DDID 0: 2 corrs [RR, LL], 16 chans, amp = 2.0 Jy
    d0 = np.full((2, 16, 4), 2.0 + 0j, dtype=complex)
    f0 = np.zeros_like(d0, dtype=bool)
    # DDID 1: 4 corrs [RR, RL, LR, LL], 64 chans; RR=LL=2.0 Jy, RL=LR=999.0 Jy!
    # If POLARIZATION row 0 ([0, 1]) were wrongly applied to DDID 1, index 1 would
    # read RL=999.0 Jy instead of LL=2.0 Jy.
    d1 = np.full((4, 64, 4), 2.0 + 0j, dtype=complex)
    d1[1, :, :] = 999.0 + 0j
    d1[2, :, :] = 999.0 + 0j
    f1 = np.zeros_like(d1, dtype=bool)

    def make_dd_sub(dd):
        sub = MagicMock()
        sub.nrows.return_value = 4
        data, flag = (d0, f0) if dd == 0 else (d1, f1)
        sub.getcol.side_effect = lambda col, **kw: data if col == "CORRECTED_DATA" else flag
        return sub

    field_sub = MagicMock()
    field_sub.nrows.return_value = 8
    field_sub.getcol.return_value = np.array([0, 0, 0, 0, 1, 1, 1, 1])

    main_tb = MagicMock()
    main_tb.__enter__.return_value = main_tb
    main_tb.colnames.return_value = ["DATA", "CORRECTED_DATA", "FLAG"]
    main_tb.query.side_effect = lambda expr: (
        make_dd_sub(int(expr.split("DATA_DESC_ID ==")[1].strip()))
        if "DATA_DESC_ID ==" in expr
        else field_sub
    )

    field_tb = MagicMock()
    field_tb.__enter__.return_value = field_tb
    field_tb.getcol.return_value = ["TARGET"]

    def fake_open(path, **kw):
        return field_tb if str(path).endswith("FIELD") else main_tb

    with (
        patch.object(corrected_stats, "open_table", side_effect=fake_open),
        patch.object(
            corrected_stats,
            "parallel_corr_by_ddid",
            return_value=[[(0, "RR"), (1, "LL")], [(0, "RR"), (3, "LL")]],
        ),
    ):
        res = corrected_stats.run(str(ms_dir), field="TARGET")

    assert res["status"] == "ok"
    pf = res["data"]["per_field"][0]
    assert pf["amp_median"]["value"] == 2.0
    assert pf["amp_p95"]["value"] == 2.0
    assert pf["n_samples"]["value"] == 16  # 2 parallel corrs * 4 rows * 2 DDIDs
