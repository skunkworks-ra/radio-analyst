"""
Unit tests for the CASA-free logic in tools/pol_cal_conditions.py.

What these cover: the two pure decision helpers — the frequency-dependent
effective role of a catalogued source, and the Df poltype derived from source
knowledge alone — plus the constants the tool ships as provenance.

What they do NOT cover: anything that opens an MS. The field enumeration,
the PA-spread ranking, and the absence of the gate fields on a real payload
are exercised in tests/integration/test_tools.py::TestPolCalConditionsReal.
"""

from __future__ import annotations

import math

from ms_inspect.tools.pol_cal_conditions import (
    PA_SPREAD_NRAO_RECOMMENDED_DEG,
    PA_SPREAD_PRACTICAL_FLOOR_DEG,
    _df_poltype_from_source_knowledge,
)
from ms_inspect.util.pol_calibrators import (
    LOW_POL_FRAC_PCT,
    effective_role_at_band,
    lookup_pol,
)


class TestEffectiveRoleAtBand:
    def test_uncatalogued_source_is_unknown(self):
        assert effective_role_at_band(None, 1.5) == "unknown"

    def test_unreadable_band_is_unknown(self):
        entry = lookup_pol("3C286")
        assert entry is not None
        assert effective_role_at_band(entry, float("nan")) == "unknown"

    def test_3c286_is_polarized_at_l_band(self):
        """3C286 has ~10% polarization with a defined EVPA — angle-cal regime."""
        entry = lookup_pol("3C286")
        assert entry is not None
        assert effective_role_at_band(entry, 1.5) == "angle_known_pol"

    def test_3c84_is_a_zero_pol_leakage_cal_at_l_band(self):
        """NRAO: 3C84 is 'low polarization (<1%)' at the low bands."""
        entry = lookup_pol("3C84")
        assert entry is not None
        assert effective_role_at_band(entry, 1.5) == "leakage_zero_pol"

    def test_role_is_frequency_dependent_for_3c147(self):
        """3C147 is low-pol below ~10 GHz and polarized above it — not a fixed role."""
        entry = lookup_pol("3C147")
        assert entry is not None
        low = effective_role_at_band(entry, 1.5)
        high = effective_role_at_band(entry, 22.0)
        assert low == "leakage_zero_pol"
        assert high != "leakage_zero_pol"


class TestDfPoltypeFromSourceKnowledge:
    def test_zero_pol_source_gives_df(self):
        poltype, basis = _df_poltype_from_source_knowledge("leakage_zero_pol")
        assert poltype == "Df"
        assert "leakage_zero_pol" in basis

    def test_known_pol_source_gives_df(self):
        for role in ("angle_known_pol", "known_pol"):
            poltype, basis = _df_poltype_from_source_knowledge(role)
            assert poltype == "Df"
            assert role in basis

    def test_unknown_pol_source_gives_df_qu(self):
        poltype, basis = _df_poltype_from_source_knowledge("unknown")
        assert poltype == "Df+QU"
        assert "solved jointly" in basis

    def test_poltype_does_not_depend_on_pa_coverage(self):
        """The helper takes no PA argument at all — coverage cannot change the poltype.

        This is the regression the rename was for: the old code returned None
        below a PA threshold, which conflated 'how well constrained' with
        'which poltype applies'.
        """
        import inspect

        params = inspect.signature(_df_poltype_from_source_knowledge).parameters
        assert list(params) == ["role_at_band"]

    def test_unrecognised_role_returns_none_with_a_stated_reason(self):
        poltype, basis = _df_poltype_from_source_knowledge("something_new")
        assert poltype is None
        assert "something_new" in basis


class TestConstants:
    def test_reference_levels_are_ordered_and_finite(self):
        assert math.isfinite(PA_SPREAD_NRAO_RECOMMENDED_DEG)
        assert math.isfinite(PA_SPREAD_PRACTICAL_FLOOR_DEG)
        assert PA_SPREAD_PRACTICAL_FLOOR_DEG < PA_SPREAD_NRAO_RECOMMENDED_DEG

    def test_low_pol_cut_matches_the_nrao_wording(self):
        assert LOW_POL_FRAC_PCT == 1.0


class TestCircularPaSpanAndWrapping:
    """CR-1: Northern-transit +-180 deg branch cut and feed-PA wrapping."""

    def test_circular_span_cases(self):
        import pytest

        from ms_inspect.tools.geometry import circular_span_deg

        # Single point / identical angles -> 0.0
        assert circular_span_deg([45.0]) == pytest.approx(0.0)
        assert circular_span_deg([45.0, 45.0]) == pytest.approx(0.0)
        # Southern transit -> 60.0
        assert circular_span_deg([-30.0, 0.0, 30.0]) == pytest.approx(60.0)
        # Northern meridian branch-cut (+177 to -177) -> 6.0, NOT 354.0
        assert circular_span_deg([177.0, -177.0]) == pytest.approx(6.0)
        # Wide multi-scan northern track -> 200.0
        assert circular_span_deg([80.0, 130.0, 177.0, -177.0, -130.0, -80.0]) == pytest.approx(
            200.0
        )

    def test_pa_spread_deg_northern_transit_at_vla(self):
        """3C84 (+41.51 deg) transiting north of VLA (+34.079 deg) crosses +-180 deg."""
        from astropy.time import Time

        from ms_inspect.tools.pol_cal_conditions import _pa_spread_deg

        vla_lat = 34.078749
        vla_lon = -107.618283
        dec_3c84_rad = math.radians(41.5117)
        # Pick an arbitrary UTC epoch and align RA to local apparent sidereal time
        # so two scans sit at HA = -1.5 deg and HA = +1.5 deg across transit.
        import astropy.units as u

        t0 = Time("2024-06-01T12:00:00", scale="utc")
        lst_rad = float(t0.sidereal_time("apparent", vla_lon * u.deg).rad)
        ra_rad = lst_rad
        # Sidereal offset ~ +-360 s (~ +-1.5 deg HA)
        mjd_s_mid = float(t0.mjd) * 86400.0
        t_list = [mjd_s_mid - 360.0, mjd_s_mid + 360.0]

        spread = _pa_spread_deg(ra_rad, dec_3c84_rad, t_list, vla_lat, vla_lon)
        assert spread is not None
        assert 5.0 < spread < 35.0  # True short arc across transit, never ~335-355 deg!

        # Fewer than 2 scans returns None
        assert _pa_spread_deg(ra_rad, dec_3c84_rad, [mjd_s_mid], vla_lat, vla_lon) is None

    def test_wrap_angle_pm180_feed_pa(self):
        import pytest

        from ms_inspect.tools.geometry import wrap_angle_pm180

        # ALT-AZ offset is -90 deg: pa_sky = -150 -> -240 wraps to +120.0
        assert wrap_angle_pm180(-150.0 - 90.0) == pytest.approx(120.0)
        # Boundary -180 maps to +180 in (-180, +180]
        assert wrap_angle_pm180(-90.0 - 90.0) == pytest.approx(180.0)
        assert wrap_angle_pm180(180.0) == pytest.approx(180.0)
        # -179.5 stays -179.5
        assert wrap_angle_pm180(-89.5 - 90.0) == pytest.approx(-179.5)
        # -180.5 wraps to +179.5
        assert wrap_angle_pm180(-90.5 - 90.0) == pytest.approx(179.5)

    def test_run_parallactic_angle_vs_time_northern_transit_and_feed_wrap(self, tmp_path):
        from unittest.mock import patch

        import astropy.units as u
        from astropy.time import Time

        from ms_inspect.tools import geometry

        ms_dir = tmp_path / "north.ms"
        ms_dir.mkdir()
        (ms_dir / "table.info").write_text("Type = Measurement Set\n")

        vla_lat, vla_lon, vla_h = 34.078749, -107.618283, 2124.0
        dec_3c147 = math.radians(49.852)
        t0 = Time("2024-06-01T12:00:00", scale="utc")
        ra_rad = float(t0.sidereal_time("apparent", vla_lon * u.deg).rad)
        mjd_s = float(t0.mjd) * 86400.0
        scans = [
            {
                "scan": 1,
                "field_id": 0,
                "t_start_mjd_s": mjd_s - 400.0,
                "t_mid_mjd_s": mjd_s - 300.0,
                "t_end_mjd_s": mjd_s - 200.0,
            },
            {
                "scan": 2,
                "field_id": 0,
                "t_start_mjd_s": mjd_s + 200.0,
                "t_mid_mjd_s": mjd_s + 300.0,
                "t_end_mjd_s": mjd_s + 400.0,
            },
        ]

        with (
            patch.object(
                geometry, "_read_field_coords", return_value=(["3C147"], [(ra_rad, dec_3c147)], [])
            ),
            patch.object(geometry, "_read_scan_times_and_fields", return_value=(scans, [])),
            patch.object(
                geometry, "_read_array_centre", return_value=(vla_lat, vla_lon, vla_h, [])
            ),
            patch.object(geometry, "_read_mount_types", return_value=["ALT-AZ"]),
        ):
            res = geometry.run_parallactic_angle_vs_time(str(ms_dir))

        f0 = res["data"]["fields"][0]
        # Scan 1 (HA < 0, east of northern transit) has PA_sky near -175 deg;
        # Scan 2 (HA > 0, west of northern transit) jumps across +-180 to +175 deg!
        assert f0["pa_sky_start_deg"]["value"] < -150.0
        assert f0["pa_sky_end_deg"]["value"] > 150.0
        # Circular span across northern transit is small (~10 deg), NOT ~350 deg!
        assert 5.0 < f0["pa_sky_range_deg"]["value"] < 35.0
        assert f0["pa_feed_range_deg"]["value"] == f0["pa_sky_range_deg"]["value"]
        # Feed PA is wrapped into (-180, +180] (+95.08 deg) rather than dropping to -264.92 deg!
        assert -180.0 < f0["pa_feed_start_deg"]["value"] <= 180.0
        assert -180.0 < f0["pa_feed_end_deg"]["value"] <= 180.0
