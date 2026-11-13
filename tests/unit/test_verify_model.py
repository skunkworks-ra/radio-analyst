"""Unit tests for ms_verify_model classification + metrics (no CASA required)."""

from __future__ import annotations

import numpy as np

from ms_inspect.tools.verify_model import _indices, _model_metrics, classify

# Default thresholds mirroring the tool defaults.
_KW = dict(
    default_amp_tol=0.05,
    default_phase_rms_deg=1.0,
    plausible_min_jy=0.1,
    plausible_max_jy=100.0,
    crosshand_ratio_thresh=0.001,
)


class TestClassify:
    def test_pinned_default_flagged(self):
        # amp ~1.0 with flat phase = untouched MODEL=1 Jy default
        status, ratio, reasons = classify(1.0, 0.0, 0.0, False, **_KW)
        assert status == "SUSPECT"
        assert any("default" in r for r in reasons)

    def test_real_one_jy_source_not_flagged(self):
        # A genuine ~1 Jy source has phase structure -> not pinned
        status, _, reasons = classify(1.0, 12.0, 0.0, False, **_KW)
        assert status == "COMPLETE"
        assert reasons == []

    def test_out_of_band_amp_flagged(self):
        status, _, reasons = classify(1e-4, 20.0, 0.0, False, **_KW)
        assert status == "SUSPECT"
        assert any("plausible band" in r for r in reasons)

    def test_polcal_with_polarization_ok(self):
        # cross/parallel ratio 0.06 > 0.001 -> polarization present
        status, ratio, reasons = classify(7.0, 15.0, 0.42, True, **_KW)
        assert status == "COMPLETE"
        assert ratio == round(0.42 / 7.0, 6)

    def test_polcal_missing_polarization_flagged(self):
        # Stokes-I model / clobbered: zero cross-hands on a pol-cal field
        status, ratio, reasons = classify(7.0, 15.0, 0.0, True, **_KW)
        assert status == "SUSPECT"
        assert any("no polarization" in r for r in reasons)
        assert ratio == 0.0

    def test_nonpolcal_zero_crosshand_not_flagged(self):
        # A Stokes-I flux/phase cal legitimately has zero cross-hands
        status, _, reasons = classify(7.0, 15.0, 0.0, False, **_KW)
        assert status == "COMPLETE"

    def test_polcal_no_crosshand_correlations_flagged(self):
        # MS without cross-hand correlations (cross_amp None) on a pol cal
        status, ratio, reasons = classify(7.0, 15.0, None, True, **_KW)
        assert status == "SUSPECT"
        assert ratio is None
        assert any("no cross-hand" in r for r in reasons)


class TestIndices:
    def test_parallel_and_cross_split(self):
        # RR,RL,LR,LL = 5,6,7,8
        codes = [5, 6, 7, 8]
        assert _indices(codes, {5, 8, 9, 12}) == [0, 3]
        assert _indices(codes, {6, 7, 10, 11}) == [1, 2]


class TestModelMetrics:
    def test_polarized_model_metrics(self):
        # [corr, chan, row]; corr order RR,RL,LR,LL
        n_chan, n_row = 2, 4
        data = np.zeros((4, n_chan, n_row), dtype=complex)
        data[0] = 5.0  # RR
        data[3] = 5.0  # LL
        data[1] = 0.5  # RL (Q/U)
        data[2] = 0.5  # LR
        flag = np.zeros((4, n_chan, n_row), dtype=bool)
        m = _model_metrics(data, flag, par_idx=[0, 3], cross_idx=[1, 2])
        assert m["par_amp"] == 5.0
        assert m["cross_amp"] == 0.5
        assert m["par_phase_rms"] == 0.0

    def test_stokes_i_only_zero_crosshands(self):
        data = np.zeros((4, 1, 3), dtype=complex)
        data[0] = 2.0
        data[3] = 2.0
        flag = np.zeros((4, 1, 3), dtype=bool)
        m = _model_metrics(data, flag, par_idx=[0, 3], cross_idx=[1, 2])
        assert m["par_amp"] == 2.0
        assert m["cross_amp"] == 0.0

    def test_all_flagged_returns_none(self):
        data = np.ones((4, 1, 2), dtype=complex)
        flag = np.ones((4, 1, 2), dtype=bool)
        m = _model_metrics(data, flag, par_idx=[0, 3], cross_idx=[1, 2])
        assert m["n_par"] == 0
        assert m["par_amp"] is None


def test_correlations_follow_ddid_polarization_row(real_ms_raw_copy):
    """POLARIZATION row 0 is not the row the data uses: the DDIDs point at row 1
    (RR LL); row 0 holds cross-hands only. Reading row 0 would take RR/LL as
    cross-hands."""
    from casatools import table

    from ms_inspect.tools.verify_model import run

    tb = table()
    tb.open(real_ms_raw_copy + "/POLARIZATION", nomodify=False)
    tb.copyrows(real_ms_raw_copy + "/POLARIZATION", startrowin=0, nrow=1)
    tb.putcell("CORR_TYPE", 0, np.array([6, 7], dtype=np.int32))  # RL LR
    tb.close()
    tb.open(real_ms_raw_copy + "/DATA_DESCRIPTION", nomodify=False)
    tb.putcol("POLARIZATION_ID", np.ones(tb.nrows(), dtype=np.int32))
    tb.close()

    out = run(real_ms_raw_copy, field="3C147")
    assert out["status"] == "ok", out
    entry = out["data"]["per_field"][0]
    assert entry["cross_amp"]["flag"] == "UNAVAILABLE"
    assert entry["par_amp"]["value"] > 0


class TestPartialBandPolClobber:
    """CR-6: Zero cross-hand samples retained (not stripped) + per-SpW partial clobber check."""

    def test_15_of_16_spws_zeroed_not_masked_by_one_polarized_spw(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from ms_inspect.tools import verify_model

        ms_dir = tmp_path / "pol16.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")
        (ms_dir / "DATA_DESCRIPTION").mkdir()

        # 16 DDIDs/SpWs; RR,RL,LR,LL = [5,6,7,8] on each DDID.
        # SpW 0 has RL=LR=0.5 Jy; SpWs 1..15 were clobbered to RL=LR=0.0!
        def make_dd_sub(dd):
            sub = MagicMock()
            sub.nrows.return_value = 4
            data = np.zeros((4, 2, 4), dtype=complex)
            data[0] = 5.0 * np.exp(1j * 0.3)
            data[3] = 5.0 * np.exp(-1j * 0.3)
            if dd == 0:
                data[1] = 0.5
                data[2] = 0.5
            flag = np.zeros((4, 2, 4), dtype=bool)
            sub.getcol.side_effect = lambda col, **kw: data if col == "MODEL_DATA" else flag
            return sub

        field_sub = MagicMock()
        field_sub.nrows.return_value = 64
        field_sub.getcol.return_value = np.repeat(np.arange(16), 4)

        main_tb = MagicMock()
        main_tb.__enter__.return_value = main_tb
        main_tb.colnames.return_value = ["DATA", "MODEL_DATA", "FLAG"]

        def query_fn(expr):
            if "DATA_DESC_ID ==" in expr:
                dd = int(expr.split("DATA_DESC_ID ==")[1].strip())
                return make_dd_sub(dd)
            return field_sub

        main_tb.query.side_effect = query_fn

        field_tb = MagicMock()
        field_tb.__enter__.return_value = field_tb
        field_tb.getcol.return_value = ["3C286"]

        dd_tb = MagicMock()
        dd_tb.__enter__.return_value = dd_tb
        dd_tb.getcol.return_value = list(range(16))

        def fake_open(path, **kw):
            p = str(path)
            if p.endswith("FIELD"):
                return field_tb
            if p.endswith("DATA_DESCRIPTION"):
                return dd_tb
            return main_tb

        with (
            patch.object(verify_model, "open_table", side_effect=fake_open),
            patch.object(verify_model, "corr_codes_by_ddid", return_value=[[5, 6, 7, 8]] * 16),
        ):
            res = verify_model.run(str(ms_dir), field="3C286", polcal_fields="3C286")

        pf = res["data"]["per_field"][0]
        # Because 15/16 SpWs have RL=LR=0, median cross_amp is 0.0 (NOT 0.5!) and status is SUSPECT!
        assert pf["cross_amp"]["value"] == 0.0
        assert pf["status"]["flag"] == "SUSPECT"
        assert pf["unpolarized_spws"]["value"] == list(range(1, 16))
        assert res["completeness_summary"] == "SUSPECT"

    def test_1_of_16_spws_zeroed_flagged_suspect_on_polcal(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from ms_inspect.tools import verify_model

        ms_dir = tmp_path / "pol_partial.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")
        (ms_dir / "DATA_DESCRIPTION").mkdir()

        # SpWs 0..14 polarized (RL=LR=0.5 Jy), SpW 15 clobbered to RL=LR=0.0!
        def make_dd_sub(dd):
            sub = MagicMock()
            sub.nrows.return_value = 4
            data = np.zeros((4, 2, 4), dtype=complex)
            data[0] = 5.0 * np.exp(1j * 0.3)
            data[3] = 5.0 * np.exp(-1j * 0.3)
            if dd != 15:
                data[1] = 0.5
                data[2] = 0.5
            flag = np.zeros((4, 2, 4), dtype=bool)
            sub.getcol.side_effect = lambda col, **kw: data if col == "MODEL_DATA" else flag
            return sub

        field_sub = MagicMock()
        field_sub.nrows.return_value = 64
        field_sub.getcol.return_value = np.repeat(np.arange(16), 4)

        main_tb = MagicMock()
        main_tb.__enter__.return_value = main_tb
        main_tb.colnames.return_value = ["DATA", "MODEL_DATA", "FLAG"]
        main_tb.query.side_effect = lambda expr: (
            make_dd_sub(int(expr.split("DATA_DESC_ID ==")[1].strip()))
            if "DATA_DESC_ID ==" in expr
            else field_sub
        )

        field_tb = MagicMock()
        field_tb.__enter__.return_value = field_tb
        field_tb.getcol.return_value = ["3C286"]

        dd_tb = MagicMock()
        dd_tb.__enter__.return_value = dd_tb
        dd_tb.getcol.return_value = list(range(16))

        def fake_open(path, **kw):
            p = str(path)
            if p.endswith("FIELD"):
                return field_tb
            if p.endswith("DATA_DESCRIPTION"):
                return dd_tb
            return main_tb

        with (
            patch.object(verify_model, "open_table", side_effect=fake_open),
            patch.object(verify_model, "corr_codes_by_ddid", return_value=[[5, 6, 7, 8]] * 16),
        ):
            res_pol = verify_model.run(str(ms_dir), field="3C286", polcal_fields="3C286")
            res_all = verify_model.run(str(ms_dir), field="3C286", polcal_fields="")

        pf_pol = res_pol["data"]["per_field"][0]
        assert pf_pol["cross_amp"]["value"] == 0.5
        assert pf_pol["unpolarized_spws"]["value"] == [15]
        assert pf_pol["status"]["flag"] == "SUSPECT"
        assert "partial-band" in pf_pol["status"]["note"]
        assert any("SpW(s) [15]" in w for w in res_pol["warnings"])

        # Non-polcal field is NOT flagged SUSPECT for cross-hands
        assert res_all["data"]["per_field"][0]["status"]["flag"] == "COMPLETE"

        # And when all 16 SpWs are polarized on polcal_fields, status is COMPLETE
        status_ok, _, reasons_ok = classify(
            5.0, 17.0, 0.5, True, unpolarized_spws=[], n_spws_checked=16, **_KW
        )
        assert status_ok == "COMPLETE" and reasons_ok == []
