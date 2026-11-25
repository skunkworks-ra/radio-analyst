"""Unit tests for ms_field_list mosaic grouping and sky geometry helpers (no CASA required)."""

from __future__ import annotations

import math
from collections import Counter

import pytest

from ms_inspect.tools.fields import _detect_mosaic_groups, _format_j2000, _min_dish_diameter_m
from ms_inspect.util.formatting import field as fmt_field


def _make_field(
    fid: int,
    name: str,
    source_id: int,
    ra_deg: float | None,
    dec_deg: float | None,
    *,
    role: list[str] | None = None,
    nearest_phase_cal: str | None = "J0336+3218",
    separation_deg: float | None = 2.5,
    min_ghz: float = 1.0,
    max_ghz: float | None = None,
) -> dict:
    hi_ghz = max_ghz if max_ghz is not None else min_ghz * 2.0
    return {
        "field_id": fid,
        "name": name,
        "source_id": source_id,
        "ra_j2000_deg": fmt_field(ra_deg) if ra_deg is not None else fmt_field(None, "UNAVAILABLE"),
        "dec_j2000_deg": fmt_field(dec_deg)
        if dec_deg is not None
        else fmt_field(None, "UNAVAILABLE"),
        "intents": fmt_field(["OBSERVE_TARGET#UNSPECIFIED"]),
        "field_role": fmt_field(role if role is not None else ["target"]),
        "observing_frequency": fmt_field(
            {"min_ghz": min_ghz, "max_ghz": hi_ghz, "centre_ghz": 0.5 * (min_ghz + hi_ghz)}
        ),
        "calibrator_match": fmt_field(None, flag="UNAVAILABLE"),
        "vla_cal_match": fmt_field(None, flag="UNAVAILABLE"),
        "pol_calibrator": fmt_field(None, flag="UNAVAILABLE"),
        "nearest_phase_cal": nearest_phase_cal,
        "separation_deg": separation_deg,
    }


class TestMosaicGeometry:
    def test_ra_0_360_wrap_uses_circular_unwrapping(self):
        """A mosaic straddling RA=0h (359.2..0.4 deg) must unwrap across 0/360, not jump to 180 deg."""
        # Asymmetric distribution in RA: dense on the 359 side, single pointing at 0.4 deg.
        # Unwrapped bbox midpoint = 359.8 deg (mean would be ~359.65 deg).
        recs = [
            _make_field(0, "WRAP_1", 1, 359.2, 10.0),
            _make_field(1, "WRAP_2", 1, 359.4, 10.0),
            _make_field(2, "WRAP_3", 1, 359.6, 10.2),
            _make_field(3, "WRAP_4", 1, 0.4, 10.4),
        ]
        groups = _detect_mosaic_groups(recs, [1, 1, 1, 1], Counter({0: 1, 1: 1, 2: 1, 3: 1}))
        assert len(groups) == 1
        g = groups[0]

        assert g["ra_range_deg"] == [pytest.approx(359.2), pytest.approx(0.4)]
        assert g["dec_range_deg"] == [pytest.approx(10.0), pytest.approx(10.4)]
        assert g["bbox_center_ra_deg"] == pytest.approx(359.8, abs=1e-5)
        assert g["bbox_center_dec_deg"] == pytest.approx(10.2, abs=1e-5)
        assert g["bbox_center_j2000"] == _format_j2000(359.8, 10.2)
        assert g["bbox_center_j2000"] == "J2000 23h59m12.00s +10d12m00.0s"

        expected_ra_arcmin = 1.2 * math.cos(math.radians(10.2)) * 60.0
        assert g["extent_ra_arcmin"] == pytest.approx(expected_ra_arcmin, abs=0.01)
        assert g["extent_dec_arcmin"] == pytest.approx(24.0, abs=0.01)
        assert g["max_extent_arcmin"] == pytest.approx(expected_ra_arcmin, abs=0.01)
        # WRAP_3 at (359.6, 10.2) is closest to (359.8, 10.2)
        assert g["central_field_id"] == 2
        assert g["central_field_name"] == "WRAP_3"
        assert g["central_field_offset_arcmin"] == pytest.approx(
            0.2 * math.cos(math.radians(10.2)) * 60.0, abs=0.02
        )
        # First pointing WRAP_1 is at (359.2, 10.0), far from bbox center (359.8, 10.2)
        assert g["first_field_offset_arcmin"] > 35.0

    def test_non_uniform_mosaic_bbox_midpoint_vs_arithmetic_mean(self):
        """Non-uniform / L-shaped mosaic must center on the sky bounding-box midpoint, not the mean."""
        # 5 dense pointings near RA=50.0, Dec=30.0 plus 1 sparse corner at RA=51.6, Dec=31.2.
        # Arithmetic mean RA would be 50.267 deg; bbox midpoint RA is exactly 50.8 deg.
        coords = [
            (50.0, 30.0),
            (50.1, 30.0),
            (50.2, 30.1),
            (50.0, 30.2),
            (50.8, 30.6),  # observed pointing right at bbox midpoint
            (51.6, 31.2),
        ]
        recs = [
            _make_field(i, f"PER_FIELD_{55 + i}", 5, ra, dec) for i, (ra, dec) in enumerate(coords)
        ]
        groups = _detect_mosaic_groups(
            recs, [5] * len(recs), Counter({i: 2 for i in range(len(recs))})
        )
        assert len(groups) == 1
        g = groups[0]

        assert g["bbox_center_ra_deg"] == pytest.approx(50.8, abs=1e-6)
        assert g["bbox_center_dec_deg"] == pytest.approx(30.6, abs=1e-6)
        assert g["bbox_center_j2000"] == "J2000 03h23m12.00s +30d36m00.0s"
        assert g["central_field_id"] == 4
        assert g["central_field_name"] == "PER_FIELD_59"
        assert g["central_field_offset_arcmin"] == pytest.approx(0.0, abs=1e-3)
        # First pointing is at corner (50.0, 30.0) -> ~54.5' off center
        assert g["first_field_offset_arcmin"] > 50.0
        # Backwards-compatible nearest_phase_cal stays a plain string when uniform
        assert g["nearest_phase_cal"] == "J0336+3218"

    def test_24a376_span_and_j2000_formatting(self):
        """Verify J2000 formatting precision and extent math on 24A-376 bounding box."""
        recs = [
            _make_field(0, "PER_FIELD_55", 1, 50.770500, 30.393348),
            _make_field(1, "PER_FIELD_80", 1, 51.600665, 29.878836),
            _make_field(2, "PER_FIELD_109", 1, 52.430829, 31.320831),
        ]
        groups = _detect_mosaic_groups(recs, [1, 1, 1], Counter({0: 1, 1: 1, 2: 1}))
        assert len(groups) == 1
        g = groups[0]
        assert g["bbox_center_j2000"] == "J2000 03h26m24.16s +30d35m59.4s"
        assert g["extent_ra_arcmin"] == pytest.approx(85.75, abs=0.02)
        assert g["extent_dec_arcmin"] == pytest.approx(86.52, abs=0.02)
        assert g["max_extent_arcmin"] == pytest.approx(86.52, abs=0.02)
        assert g["first_field_offset_arcmin"] == pytest.approx(44.5, abs=0.3)


class TestMosaicSkyProximitySplit:
    def test_by_sid_splits_unrelated_targets_sharing_source_id_zero(self):
        """Unrelated single targets sharing SOURCE_ID=0 across the sky must NEVER merge."""
        recs = [
            _make_field(0, "NGC1234", 0, 50.0, 30.0),
            _make_field(1, "M87_CORE", 0, 187.7, 12.4),
            _make_field(2, "CYG_A", 0, 299.9, 40.7),
        ]
        groups = _detect_mosaic_groups(recs, [0, 0, 0], Counter({0: 1, 1: 1, 2: 1}))
        assert groups == []

    def test_by_sid_splits_two_disjoint_mosaics_sharing_source_id(self):
        """Two distinct sky clusters sharing SOURCE_ID=0 must split into two clean groups."""
        recs = [
            _make_field(0, "CLUSTA_1", 0, 50.0, 30.0),
            _make_field(1, "CLUSTA_2", 0, 50.3, 30.0),
            _make_field(2, "OUTLIER", 0, 120.0, -20.0),
            _make_field(3, "CLUSTB_1", 0, 250.0, 10.0),
            _make_field(4, "CLUSTB_2", 0, 250.2, 10.1),
            _make_field(5, "CLUSTB_3", 0, 250.4, 10.0),
        ]
        groups = _detect_mosaic_groups(recs, [0] * 6, Counter({i: 1 for i in range(6)}))
        assert len(groups) == 2
        assert [g["group_name"] for g in groups] == ["CLUSTA", "CLUSTB"]
        assert [g["field_ids"] for g in groups] == [[0, 1], [3, 4, 5]]

    def test_stem_single_linkage_allows_large_4deg_x_4deg_mosaic(self):
        """A 4 deg x 4 deg mosaic (diagonal 5.66 deg > 5.0 deg) with 1 deg spacing must group."""
        recs = []
        fid = 0
        for ix in range(5):
            for iy in range(5):
                recs.append(
                    _make_field(fid, f"WIDE_{fid + 1}", 100 + fid, 10.0 + ix * 1.0, 0.0 + iy * 1.0)
                )
                fid += 1
        sids = [r["source_id"] for r in recs]
        groups = _detect_mosaic_groups(recs, sids, Counter({i: 1 for i in range(fid)}))
        assert len(groups) == 1
        assert groups[0]["group_name"] == "WIDE"
        assert groups[0]["n_pointings"] == 25
        assert groups[0]["extent_ra_arcmin"] == pytest.approx(240.0, abs=0.2)
        assert groups[0]["extent_dec_arcmin"] == pytest.approx(240.0, abs=0.2)

    def test_stem_single_linkage_rejects_far_unrelated_fields_and_keeps_compact_cluster(self):
        """Stem-matched pointings separated by >2 deg must not merge across the sky."""
        recs = [
            _make_field(0, "SRC_1", 10, 40.0, 15.0),
            _make_field(1, "SRC_2", 11, 40.5, 15.0),
            _make_field(2, "SRC_3", 12, 41.0, 15.0),
            _make_field(3, "SRC_4", 13, 85.0, -10.0),  # unrelated far-away pointing
        ]
        sids = [r["source_id"] for r in recs]
        groups = _detect_mosaic_groups(recs, sids, Counter({i: 1 for i in range(4)}))
        assert len(groups) == 1
        assert groups[0]["field_ids"] == [0, 1, 2]
        assert groups[0]["n_pointings"] == 3

    def test_missing_coords_returns_none_geometry_cleanly(self):
        recs = [
            _make_field(0, "NOCOORD_1", 7, None, None),
            _make_field(1, "NOCOORD_2", 7, None, None),
        ]
        groups = _detect_mosaic_groups(recs, [7, 7], Counter({0: 1, 1: 1}))
        assert len(groups) == 1
        g = groups[0]
        assert g["bbox_center_ra_deg"] is None
        assert g["bbox_center_dec_deg"] is None
        assert g["bbox_center_j2000"] is None
        assert g["central_field_id"] is None
        assert g["central_field_name"] is None
        assert g["central_field_offset_arcmin"] is None
        assert g["extent_ra_arcmin"] is None
        assert g["extent_dec_arcmin"] is None
        assert g["max_extent_arcmin"] is None
        assert g["first_field_offset_arcmin"] is None


class TestPrimaryBeamMosaicGeneralization:
    def test_colocated_multi_eb_fields_are_not_classified_as_mosaic(self):
        """Multi-EB / concat single-pointing FIELD rows at identical (RA, Dec) stay single-pointing."""
        recs = [
            _make_field(0, "TARGET_1", 0, 150.0, 2.0, min_ghz=1.4),
            _make_field(1, "TARGET_2", 0, 150.0, 2.0, min_ghz=1.4),
            _make_field(2, "TARGET_3", 0, 150.0, 2.0, min_ghz=1.4),
        ]
        # Rejected both with dish diameter (PB-scaled threshold) and without (1 arcsec fallback).
        assert (
            _detect_mosaic_groups(
                recs, [0, 0, 0], Counter({0: 1, 1: 1, 2: 1}), min_dish_diam_m=25.0
            )
            == []
        )
        assert (
            _detect_mosaic_groups(
                recs, [0, 0, 0], Counter({0: 1, 1: 1, 2: 1}), min_dish_diam_m=None
            )
            == []
        )

    def test_high_freq_narrow_pb_fields_half_deg_apart_are_not_merged(self):
        """ALMA Band 6 (230 GHz, 12m -> PB ~ 0.007 deg): targets 0.5 deg apart with SOURCE_ID=0 split."""
        recs = [
            _make_field(0, "ORION_A", 0, 83.8, -5.4, min_ghz=230.0, max_ghz=245.0),
            _make_field(1, "ORION_B", 0, 84.3, -5.4, min_ghz=230.0, max_ghz=245.0),
            _make_field(2, "ORION_C", 0, 84.8, -5.4, min_ghz=230.0, max_ghz=245.0),
        ]
        groups = _detect_mosaic_groups(
            recs,
            [0, 0, 0],
            Counter({0: 1, 1: 1, 2: 1}),
            min_dish_diam_m=12.0,
        )
        assert groups == []

    def test_low_freq_wide_pb_mosaic_with_2p5_deg_steps_groups_as_one(self):
        """Low-freq wide-PB mosaic (PB ~ 2.5 deg at 316 MHz, 25m): 2.5 deg steps group as one mosaic."""
        recs = [
            _make_field(0, "PFIELD_1", 1, 100.0, 0.0, min_ghz=0.316, max_ghz=0.450),
            _make_field(1, "PFIELD_2", 1, 102.5, 0.0, min_ghz=0.316, max_ghz=0.450),
            _make_field(2, "PFIELD_3", 1, 105.0, 0.0, min_ghz=0.316, max_ghz=0.450),
        ]
        # With dish diameter: 1.5 * PB_FWHM (~3.75 deg) >= 2.5 deg -> single mosaic
        groups = _detect_mosaic_groups(
            recs,
            [1, 1, 1],
            Counter({0: 1, 1: 1, 2: 1}),
            min_dish_diam_m=25.0,
        )
        assert len(groups) == 1
        assert groups[0]["group_name"] == "PFIELD"
        assert groups[0]["field_ids"] == [0, 1, 2]
        assert groups[0]["n_pointings"] == 3

        # Fallback without dish diameter stays at 2.0 deg and splits 2.5 deg steps
        assert (
            _detect_mosaic_groups(
                recs,
                [1, 1, 1],
                Counter({0: 1, 1: 1, 2: 1}),
                min_dish_diam_m=None,
            )
            == []
        )

    def test_min_dish_diameter_ignores_flagged_rows_when_active_remain(self, monkeypatch):
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        from ms_inspect.tools import fields as fields_mod

        @contextmanager
        def fake_open_table(_path):
            tb = MagicMock()
            tb.getcol.side_effect = lambda col: (
                [7.0, 12.0, 12.0, 25.0] if col == "DISH_DIAMETER" else [True, False, False, False]
            )
            yield tb

        monkeypatch.setattr(fields_mod, "open_table", fake_open_table)
        # Flagged 7m antenna ignored since 3 unflagged active antennas remain -> 12.0 m
        assert _min_dish_diameter_m("/fake.ms") == pytest.approx(12.0)
