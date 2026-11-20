"""Unit tests for ms_antenna_amp_stats (src/ms_inspect/tools/antenna_amp_stats.py)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pytest

from ms_inspect.exceptions import ComputationError
from ms_inspect.tools.antenna_amp_stats import (
    parse_scan_selection,
    run,
    summarize_antenna_amplitudes,
)


class TestParseScanSelection:
    def test_empty(self):
        assert parse_scan_selection("") == []
        assert parse_scan_selection("   ") == []

    def test_list_and_ranges(self):
        assert parse_scan_selection("5,1~3,3,10") == [1, 2, 3, 5, 10]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_scan_selection("abc")
        with pytest.raises(ValueError):
            parse_scan_selection("5~2")
        with pytest.raises(ValueError):
            parse_scan_selection("-1")


class TestSummarizeAntennaAmplitudes:
    def test_dead_unflagged_antenna_surfaces_first(self):
        names = ["ea01", "ea02", "ea13", "ea04", "ea05"]
        per_ant_means = [
            np.array([1.0, 1.05, 0.98]),
            np.array([1.02, 0.99, 1.01]),
            np.array([0.004, 0.005, 0.003]),  # ~200x lower, unflagged
            np.array([0.97, 1.03, 1.0]),
            np.array([], dtype=float),  # fully flagged
        ]
        unf = np.array([384, 384, 384, 384, 0], dtype=np.int64)
        tot = np.array([384, 384, 384, 384, 384], dtype=np.int64)

        out = summarize_antenna_amplitudes(names, per_ant_means, unf, tot)
        assert out["n_antennas"] == 5
        assert out["n_antennas_with_data"] == 4
        assert out["array_median_amp"] == pytest.approx(1.0, rel=0.05)

        rows = out["per_antenna"]
        # Lowest ratio first: ea13
        assert rows[0]["name"] == "ea13"
        assert rows[0]["amp_median"]["value"] == pytest.approx(0.004, abs=1e-6)
        assert rows[0]["amp_mad"]["value"] == pytest.approx(0.001, abs=1e-6)
        assert rows[0]["amp_iqr"]["value"] == pytest.approx(0.001, abs=1e-6)
        assert rows[0]["amp_min"]["value"] == pytest.approx(0.003, abs=1e-6)
        assert rows[0]["amp_max"]["value"] == pytest.approx(0.005, abs=1e-6)
        assert rows[0]["near_zero_fraction"]["value"] == 1.0
        assert rows[0]["ratio_to_array_median"]["value"] < 0.01
        assert rows[0]["unflagged_fraction"] == 1.0
        assert rows[1]["near_zero_fraction"]["value"] == 0.0
        assert out["near_zero_ratio"] == 0.05
        assert out["near_zero_cutoff_amp"] == pytest.approx(0.05, rel=0.05)

        # Fully flagged antenna is last with UNAVAILABLE flags
        assert rows[-1]["name"] == "ea05"
        assert rows[-1]["amp_median"]["value"] is None
        assert rows[-1]["amp_median"]["flag"] == "UNAVAILABLE"
        assert rows[-1]["amp_mad"]["flag"] == "UNAVAILABLE"
        assert rows[-1]["amp_iqr"]["flag"] == "UNAVAILABLE"
        assert rows[-1]["near_zero_fraction"]["flag"] == "UNAVAILABLE"
        assert rows[-1]["ratio_to_array_median"]["flag"] == "UNAVAILABLE"

    def test_strided_marks_partial_flag(self):
        out = summarize_antenna_amplitudes(
            ["ea01", "ea02"],
            [np.array([2.0]), np.array([2.0])],
            np.array([10, 10]),
            np.array([10, 10]),
            strided=True,
        )
        assert out["per_antenna"][0]["amp_median"]["flag"] == "PARTIAL"
        assert out["per_antenna"][0]["ratio_to_array_median"]["flag"] == "PARTIAL"

    def test_all_flagged_returns_unavailable(self):
        out = summarize_antenna_amplitudes(
            ["ea01", "ea02"],
            [np.empty(0), np.empty(0)],
            np.array([0, 0]),
            np.array([10, 10]),
        )
        assert out["n_antennas_with_data"] == 0
        assert out["array_median_amp"] is None
        assert out["per_antenna"][0]["amp_median"]["flag"] == "UNAVAILABLE"


class _FakeSubTable:
    def __init__(self, ant1, ant2, vis, flg, frow):
        self._ant1 = ant1
        self._ant2 = ant2
        self._vis = vis
        self._flg = flg
        self._frow = frow
        self.closed = False

    def nrows(self):
        return len(self._ant1)

    def getcol(self, name, startrow=0, nrow=-1, rowincr=1):
        stop = None if nrow < 0 else startrow + nrow * rowincr
        sl = slice(startrow, stop, rowincr)
        if name == "ANTENNA1":
            return self._ant1[sl]
        if name == "ANTENNA2":
            return self._ant2[sl]
        if name == "FLAG_ROW":
            return self._frow[sl]
        if name in ("DATA", "CORRECTED_DATA", "MODEL_DATA"):
            return self._vis[:, :, sl]
        if name == "FLAG":
            return self._flg[:, :, sl]
        raise KeyError(name)

    def close(self):
        self.closed = True


class _FakeMainTable:
    def __init__(
        self, sub: _FakeSubTable, cols=("DATA", "FLAG", "FLAG_ROW", "ANTENNA1", "ANTENNA2")
    ):
        self._sub = sub
        self._cols = list(cols)
        self.queries: list[str] = []

    def colnames(self):
        return self._cols

    def query(self, q: str):
        self.queries.append(q)
        return self._sub


class _FakeSubtableMeta:
    def __init__(self, cols: dict, n: int | None = None):
        self._cols = cols
        self._n = n

    def nrows(self):
        if self._n is not None:
            return self._n
        return len(next(iter(self._cols.values())))

    def getcol(self, name):
        return self._cols[name]


class TestRunMocked:
    def test_run_detects_dead_antenna_and_excludes_autocorr(self, tmp_path):
        ms_dir = tmp_path / "test.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")

        # 4 antennas: ea01, ea02, ea03 (healthy ~10 Jy), ea13 (dead ~0.05 Jy)
        # Include 3 cross-correlations touching ea13 + 3 healthy cross-correlations
        ant1 = np.array([0, 0, 1, 0, 1, 2])
        ant2 = np.array([1, 2, 2, 3, 3, 3])
        n_rows = len(ant1)
        vis = np.zeros((4, 8, n_rows), dtype=np.complex128)
        # Parallel hands at indices 0, 3; cross hands at 1, 2 (garbage large to verify parallel-only)
        vis[0, :, :3] = 10.0 + 0j
        vis[3, :, :3] = 10.0 + 0j
        vis[0, :, 3:] = 0.05 + 0j
        vis[3, :, 3:] = 0.05 + 0j
        vis[1, :, :] = 999.0 + 0j
        vis[2, :, :] = 999.0 + 0j
        flg = np.zeros((4, 8, n_rows), dtype=bool)
        frow = np.zeros(n_rows, dtype=bool)

        sub = _FakeSubTable(ant1, ant2, vis, flg, frow)
        main_tb = _FakeMainTable(sub)
        ant_tb = _FakeSubtableMeta({"NAME": ["ea01", "ea02", "ea03", "ea13"]})
        field_tb = _FakeSubtableMeta({"NAME": ["J1331+3030", "3C391"]})
        spw_tb = _FakeSubtableMeta({}, n=1)
        dd_tb = _FakeSubtableMeta({"SPECTRAL_WINDOW_ID": [0]})

        @contextmanager
        def fake_open_table(path: str):
            if path.endswith("/ANTENNA"):
                yield ant_tb
            elif path.endswith("/FIELD"):
                yield field_tb
            elif path.endswith("/SPECTRAL_WINDOW"):
                yield spw_tb
            elif path.endswith("/DATA_DESCRIPTION"):
                yield dd_tb
            else:
                yield main_tb

        with (
            patch("ms_inspect.tools.antenna_amp_stats.open_table", fake_open_table),
            patch(
                "ms_inspect.tools.antenna_amp_stats.parallel_corr_by_ddid",
                return_value=[[(0, "RR"), (3, "LL")]],
            ),
        ):
            env = run(str(ms_dir), field="J1331+3030", scans="2,3", datacolumn="DATA")

        assert env["status"] == "ok"
        assert sub.closed
        assert "FIELD_ID IN [0]" in main_tb.queries[0]
        assert "SCAN_NUMBER IN [2,3]" in main_tb.queries[0]
        assert "ANTENNA1 != ANTENNA2" in main_tb.queries[0]

        data = env["data"]
        assert data["datacolumn"] == "DATA"
        assert data["selected_fields"] == ["J1331+3030"]
        assert data["selected_scans"] == [2, 3]
        assert data["per_antenna"][0]["name"] == "ea13"
        assert data["per_antenna"][0]["amp_median"]["value"] == pytest.approx(0.05)
        assert data["per_antenna"][0]["ratio_to_array_median"]["value"] == pytest.approx(0.005)
        assert data["per_antenna"][0]["unflagged_fraction"] == 1.0

    def test_missing_datacolumn_raises(self, tmp_path):
        ms_dir = tmp_path / "test.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")

        sub = _FakeSubTable(
            np.array([]),
            np.array([]),
            np.zeros((2, 4, 0)),
            np.zeros((2, 4, 0), bool),
            np.array([], bool),
        )
        main_tb = _FakeMainTable(sub, cols=("DATA", "FLAG"))
        ant_tb = _FakeSubtableMeta({"NAME": ["ea01"]})
        field_tb = _FakeSubtableMeta({"NAME": ["J1331+3030"]})
        spw_tb = _FakeSubtableMeta({}, n=1)
        dd_tb = _FakeSubtableMeta({"SPECTRAL_WINDOW_ID": [0]})

        @contextmanager
        def fake_open_table(path: str):
            if path.endswith("/ANTENNA"):
                yield ant_tb
            elif path.endswith("/FIELD"):
                yield field_tb
            elif path.endswith("/SPECTRAL_WINDOW"):
                yield spw_tb
            elif path.endswith("/DATA_DESCRIPTION"):
                yield dd_tb
            else:
                yield main_tb

        with (
            patch("ms_inspect.tools.antenna_amp_stats.open_table", fake_open_table),
            patch(
                "ms_inspect.tools.antenna_amp_stats.parallel_corr_by_ddid",
                return_value=[[(0, "RR")]],
            ),
            pytest.raises(ComputationError, match="CORRECTED_DATA column not present"),
        ):
            run(str(ms_dir), datacolumn="CORRECTED_DATA")

    def test_invalid_datacolumn_or_max_rows_raises(self, tmp_path):
        ms_dir = tmp_path / "test.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")
        with pytest.raises(ComputationError, match="Unsupported datacolumn"):
            run(str(ms_dir), datacolumn="BOGUS")
        with pytest.raises(ComputationError, match="max_rows"):
            run(str(ms_dir), max_rows=0)
