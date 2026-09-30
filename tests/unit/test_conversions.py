"""
Unit tests for util/conversions.py — pure conversion and formatting utilities.

No CASA dependency.
"""

from __future__ import annotations

import math
from datetime import UTC

import numpy as np
import pytest

from ms_inspect.util.conversions import (
    angular_resolution_arcsec,
    baseline_length_klambda,
    baseline_length_m,
    baselines_m,
    corr_codes_to_labels,
    deg_to_rad,
    ecef_to_geodetic,
    greenwich_sidereal_rad,
    hz_to_human,
    is_full_stokes,
    largest_angular_scale_arcsec,
    mjd_seconds_to_unix,
    mjd_seconds_to_utc,
    polarization_basis,
    projected_uv_m,
    rad_to_deg,
    rad_to_dms,
    rad_to_hms,
    seconds_to_human,
    spherical_to_ecef,
)

# ---------------------------------------------------------------------------
# Correlation type codes
# ---------------------------------------------------------------------------


class TestCorrCodesToLabels:
    def test_circular(self):
        assert corr_codes_to_labels([5, 6, 7, 8]) == ["RR", "RL", "LR", "LL"]

    def test_linear(self):
        assert corr_codes_to_labels([9, 10, 11, 12]) == ["XX", "XY", "YX", "YY"]

    def test_stokes(self):
        assert corr_codes_to_labels([1, 2, 3, 4]) == ["I", "Q", "U", "V"]

    def test_unknown_code(self):
        result = corr_codes_to_labels([999])
        assert result == ["UNKNOWN(999)"]

    def test_empty(self):
        assert corr_codes_to_labels([]) == []


class TestPolarizationBasis:
    def test_circular(self):
        assert polarization_basis(["RR", "RL", "LR", "LL"]) == "circular"

    def test_linear(self):
        assert polarization_basis(["XX", "XY", "YX", "YY"]) == "linear"

    def test_stokes(self):
        assert polarization_basis(["I", "Q", "U", "V"]) == "stokes"

    def test_mixed(self):
        assert polarization_basis(["RR", "XX"]) == "mixed"

    def test_partial_circular(self):
        assert polarization_basis(["RR", "LL"]) == "circular"

    def test_partial_linear(self):
        assert polarization_basis(["XX", "YY"]) == "linear"


class TestIsFullStokes:
    def test_full_circular(self):
        assert is_full_stokes(["RR", "RL", "LR", "LL"]) is True

    def test_full_linear(self):
        assert is_full_stokes(["XX", "XY", "YX", "YY"]) is True

    def test_full_stokes_iquv(self):
        assert is_full_stokes(["I", "Q", "U", "V"]) is True

    def test_partial(self):
        assert is_full_stokes(["RR", "LL"]) is False

    def test_empty(self):
        assert is_full_stokes([]) is False


# ---------------------------------------------------------------------------
# Time conversions
# ---------------------------------------------------------------------------


class TestMJDConversions:
    def test_known_epoch(self):
        # MJD 58000.0 = 2017-09-04 00:00:00 UTC
        mjd_sec = 58000.0 * 86400.0
        result = mjd_seconds_to_utc(mjd_sec)
        assert result.startswith("2017-09-04 00:00:00")
        assert result.endswith("UTC")

    def test_unix_conversion(self):
        # MJD 0 = 1858-11-17 → unix should be negative
        assert mjd_seconds_to_unix(0.0) < 0

    def test_round_trip_consistency(self):
        mjd_sec = 58000.0 * 86400.0
        unix_ts = mjd_seconds_to_unix(mjd_sec)
        # Should be consistent with the UTC string
        from datetime import datetime

        dt = datetime.fromtimestamp(unix_ts, tz=UTC)
        assert dt.year == 2017
        assert dt.month == 9
        assert dt.day == 4


# ---------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------


class TestHzToHuman:
    def test_ghz(self):
        assert hz_to_human(1.4e9) == "1.4000 GHz"

    def test_mhz(self):
        assert hz_to_human(327e6) == "327.0000 MHz"

    def test_khz(self):
        assert hz_to_human(15e3) == "15.0000 kHz"

    def test_hz(self):
        assert hz_to_human(50.0) == "50.00 Hz"


# Frequency → band name moved to util/telescope.py — see tests/unit/test_telescope.py.


# ---------------------------------------------------------------------------
# Angle conversions
# ---------------------------------------------------------------------------


class TestAngleConversions:
    def test_rad_to_deg_and_back(self):
        assert abs(rad_to_deg(math.pi) - 180.0) < 1e-10
        assert abs(deg_to_rad(180.0) - math.pi) < 1e-10

    def test_rad_to_hms_zero(self):
        result = rad_to_hms(0.0)
        assert result == "00h00m00.00s"

    def test_rad_to_hms_known(self):
        # 6h = 90 degrees = pi/2 radians
        result = rad_to_hms(math.pi / 2)
        assert result.startswith("06h00m")

    def test_rad_to_dms_positive(self):
        # +45 degrees
        result = rad_to_dms(math.radians(45.0))
        assert result.startswith("+45d00m")

    def test_rad_to_dms_negative(self):
        # -30 degrees
        result = rad_to_dms(math.radians(-30.0))
        assert result.startswith("-30d00m")

    def test_rad_to_dms_zero(self):
        result = rad_to_dms(0.0)
        assert result.startswith("+00d00m")


# ---------------------------------------------------------------------------
# Coordinate conversions
# ---------------------------------------------------------------------------


class TestECEFToGeodetic:
    def test_vla_site(self):
        # VLA centre approximate ECEF: (-1601185, -5041977, 3554876)
        lat, lon, h = ecef_to_geodetic(-1601185.0, -5041977.0, 3554876.0)
        # VLA is at ~34.08° N, ~-107.62° W, ~2100 m
        assert abs(lat - 34.08) < 0.1
        assert abs(lon - (-107.62)) < 0.1
        assert abs(h - 2100) < 200  # rough altitude check

    def test_equator_prime_meridian(self):
        # Point on equator at prime meridian, at sea level
        # ECEF: (a, 0, 0) where a = 6378137
        lat, lon, _ = ecef_to_geodetic(6378137.0, 0.0, 0.0)
        assert abs(lat) < 0.01
        assert abs(lon) < 0.01

    def test_north_pole(self):
        # ECEF: (0, 0, b) where b ~ 6356752
        lat, lon, _ = ecef_to_geodetic(0.0, 0.0, 6356752.3)
        assert abs(lat - 90.0) < 0.01


class TestBaselineLengthM:
    def test_same_point(self):
        assert baseline_length_m((0, 0, 0), (0, 0, 0)) == 0.0

    def test_known_distance(self):
        # 3-4-5 triangle
        d = baseline_length_m((0, 0, 0), (3, 4, 0))
        assert abs(d - 5.0) < 1e-10

    def test_3d(self):
        d = baseline_length_m((1, 2, 3), (4, 6, 3))
        assert abs(d - 5.0) < 1e-10


class TestBaselinesM:
    def test_pairs_follow_combinations_order(self):
        import itertools

        pos = [[0, 3, 0, 1], [0, 4, 6, 2], [0, 0, 8, 3]]
        ant_i, ant_j, lengths = baselines_m(pos)
        assert list(zip(ant_i.tolist(), ant_j.tolist(), strict=True)) == list(
            itertools.combinations(range(4), 2)
        )
        for i, j, d in zip(ant_i, ant_j, lengths, strict=True):
            a = tuple(p[i] for p in pos)
            b = tuple(p[j] for p in pos)
            assert abs(d - baseline_length_m(a, b)) < 1e-12

    def test_one_antenna_has_no_baselines(self):
        _, _, lengths = baselines_m([[1.0], [2.0], [3.0]])
        assert lengths.size == 0


class TestSphericalToEcef:
    def test_axes(self):
        x, y, z = spherical_to_ecef(0.0, 0.0, 10.0)
        assert (x, y, z) == (10.0, 0.0, 0.0)
        x, y, z = spherical_to_ecef(0.0, math.pi / 2, 10.0)
        assert abs(x) < 1e-12 and abs(z - 10.0) < 1e-12


_J2000_MJD_S = 51544.5 * 86400.0  # 2000-01-01 12:00 UTC
_SIX_SIDEREAL_HOURS_S = 6 * 3600.0 / 1.00273790935


class TestGreenwichSidereal:
    def test_j2000_epoch(self):
        # GMST at J2000.0 is 280.46061837 deg. UT1-UTC (0.36 s) and the
        # equation of the equinoxes (under 1.2 s) keep GAST within 0.01 deg.
        deg = math.degrees(float(greenwich_sidereal_rad([_J2000_MJD_S])[0]))
        assert abs(deg - 280.46061837) < 0.01

    @pytest.mark.filterwarnings("ignore:ERFA function")
    def test_past_the_bundled_iers_tables(self):
        # 2050: no IERS data. Takes UT1 = UTC instead of raising.
        rad = greenwich_sidereal_rad([70000.0 * 86400.0])
        assert 0.0 <= float(rad[0]) < 2 * math.pi


class TestProjectedUv:
    def test_toward_the_pole_keeps_the_equatorial_part(self):
        b = np.array([[300.0, 400.0, 1000.0]])
        times = _J2000_MJD_S + np.array([0.0, 7200.0, 30000.0])
        uv = projected_uv_m(b, 1.0, math.pi / 2, times)
        assert uv.shape == (3, 1)
        assert np.allclose(uv, 500.0)

    def test_polar_baseline_scales_with_cos_dec(self):
        b = np.array([[0.0, 0.0, 1000.0]])
        uv = projected_uv_m(b, 0.3, math.radians(60.0), [_J2000_MJD_S])
        assert abs(float(uv[0, 0]) - 500.0) < 1e-9

    def test_east_west_baseline_rotates_with_hour_angle(self):
        # At dec 0 an ITRF-Y baseline projects to |B cos H|; six sidereal
        # hours later to |B sin H|. The squares add up to B^2.
        b = np.array([[0.0, 1000.0, 0.0]])
        times = [_J2000_MJD_S + 1234.0, _J2000_MJD_S + 1234.0 + _SIX_SIDEREAL_HOURS_S]
        uv = projected_uv_m(b, 0.7, 0.0, times)[:, 0]
        assert abs(uv[0] ** 2 + uv[1] ** 2 - 1.0e6) < 1.0


# ---------------------------------------------------------------------------
# Angular scale
# ---------------------------------------------------------------------------


class TestAngularScale:
    def test_resolution_basic(self):
        # 1 km baseline at 1.4 GHz → λ ≈ 0.214 m → θ ≈ 44 arcsec
        res = angular_resolution_arcsec(1000.0, 1.4e9)
        assert 40 < res < 50

    def test_resolution_zero_baseline(self):
        assert math.isnan(angular_resolution_arcsec(0.0, 1.4e9))

    def test_resolution_zero_freq(self):
        assert math.isnan(angular_resolution_arcsec(1000.0, 0.0))

    def test_las_basic(self):
        las = largest_angular_scale_arcsec(100.0, 1.4e9)
        assert las > 0

    def test_las_zero_inputs(self):
        assert math.isnan(largest_angular_scale_arcsec(0.0, 1.4e9))
        assert math.isnan(largest_angular_scale_arcsec(100.0, 0.0))

    def test_baseline_klambda(self):
        # 1 km at 1.4 GHz: λ ≈ 0.214 m → 1000/0.214/1000 ≈ 4.67 kλ
        kl = baseline_length_klambda(1000.0, 1.4e9)
        assert 4.5 < kl < 5.0

    def test_baseline_klambda_zero_freq(self):
        assert math.isnan(baseline_length_klambda(1000.0, 0.0))


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------


class TestSecondsToHuman:
    def test_hours(self):
        assert seconds_to_human(3661.5) == "1h 1m 1.5s"

    def test_minutes(self):
        assert seconds_to_human(125.3) == "2m 5.3s"

    def test_seconds_only(self):
        assert seconds_to_human(3.14) == "3.14s"

    def test_zero(self):
        assert seconds_to_human(0.0) == "0.00s"
