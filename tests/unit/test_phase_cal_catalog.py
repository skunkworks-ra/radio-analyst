"""
Unit tests for the PhaseCalList.txt parser in util/phase_cal_catalog.py.

UVMIN and UVMAX are told apart by column: a row may carry either limit alone.
The real 3C84 (0319+415) block has a UVMIN at L-band and a UVMAX at Q-band.

No CASA dependency.
"""

from __future__ import annotations

import math

import pytest

from ms_inspect.util.phase_cal_catalog import _get_catalog, _load_catalog

HEADER = "BAND        A B C D    FLUX(Jy)    UVMIN(kL)  UVMAX(kL)"

BLOCK_3C84 = f"""\
0319+415   J2000  B 03h19m48.160102s  41d30'42.103050"  Aug01  3C84
0316+413   B1950  B 03h16m29.567300s  41d19'51.916000"
-----------------------------------------------------
{HEADER}
=====================================================
 90cm    P  S X X X          8           13
 20cm    L  P P X X      23.9            12
  6cm    C  P P P P      23.3
3.7cm    X  P P P P      21.70                       visplot
0.7cm    Q  X S S S      9.00                 1800   visplot
"""


def _bands(text: str) -> dict:
    return _load_catalog(text)["0319+415"].bands


def test_uvmin_only_row():
    b = _bands(BLOCK_3C84)["L"]
    assert (b.uvmin_kl, b.uvmax_kl) == (12.0, None)


def test_uvmax_only_row():
    b = _bands(BLOCK_3C84)["Q"]
    assert (b.uvmin_kl, b.uvmax_kl) == (None, 1800.0)


def test_no_limits_and_trailing_text():
    for code in ("C", "X"):
        b = _bands(BLOCK_3C84)[code]
        assert (b.uvmin_kl, b.uvmax_kl) == (None, None)


def test_both_limits_row():
    text = BLOCK_3C84 + "3.7cm    X  S S X X       0.84          100         400\n"
    b = _bands(text)["X"]
    assert (b.uvmin_kl, b.uvmax_kl) == (100.0, 400.0)


def _grades(band) -> str:
    return "".join(getattr(band, f"quality_{c}") for c in "ABCD")


def test_grades_per_configuration():
    # One grade per array configuration A/B/C/D, in column order. 3C84 is
    # unusable (X) in the compact configurations at P and L band, where its
    # UVMIN cuts most baselines, and in A at Q band.
    bands = _bands(BLOCK_3C84)
    grades = {code: _grades(bands[code]) for code in ("P", "L", "C", "Q")}
    assert grades == {"P": "SXXX", "L": "PPXX", "C": "PPPP", "Q": "XSSS"}


def test_bundled_file_3c84():
    bands = _get_catalog()["0319+415"].bands
    assert (bands["L"].uvmin_kl, bands["L"].uvmax_kl) == (12.0, None)
    assert (bands["Q"].uvmin_kl, bands["Q"].uvmax_kl) == (None, 1800.0)
    assert _grades(bands["L"]) == "PPXX"
    assert _grades(bands["K"]) == "XSSS"


# --- flux at frequency and the no-substitution match ------------------------

# J1822-0938 (1822-096) has rows at P, L, X, Q and none at C.
J1822_RA, J1822_DEC = 275.6196008, -9.6491208


def test_flux_at_frequency_brackets_with_power_law():
    from ms_inspect.util.phase_cal_catalog import BAND_NOMINAL_GHZ, flux_at_frequency

    est = flux_at_frequency({"P": 13.0, "L": 5.6, "X": 1.3, "Q": 0.2}, 4.6)
    assert [d["band"] for d in est["inputs"]] == ["L", "X"]
    nu_l, nu_x = BAND_NOMINAL_GHZ["L"], BAND_NOMINAL_GHZ["X"]
    alpha = math.log(1.3 / 5.6) / math.log(nu_x / nu_l)
    assert est["spectral_index"] == pytest.approx(alpha, abs=1e-4)
    assert est["flux_jy"] == pytest.approx(5.6 * (4.6 / nu_l) ** alpha, abs=1e-3)


def test_flux_at_frequency_no_extrapolation():
    from ms_inspect.util.phase_cal_catalog import flux_at_frequency

    assert flux_at_frequency({"L": 5.6, "X": 1.3}, 0.3) is None
    assert flux_at_frequency({"L": 5.6, "X": 1.3}, 20.0) is None
    assert flux_at_frequency({"L": 5.6}, 1.0) is None


def test_lookup_keeps_position_match_without_band_row():
    from ms_inspect.util.phase_cal_catalog import lookup_nearest

    m = lookup_nearest(J1822_RA, J1822_DEC, band_code="C", array_config="C")
    assert m.entry.iau_name == "1822-096"
    assert m.band is None
    assert m.separation_deg * 3600 < 1.0


def test_lookup_keeps_position_match_graded_x():
    from ms_inspect.util.phase_cal_catalog import lookup_nearest

    # 1822-096 is graded X at L in A configuration.
    m = lookup_nearest(J1822_RA, J1822_DEC, band_code="L", array_config="A")
    assert m.entry.iau_name == "1822-096"
    assert m.quality == "X"


def test_lookup_identity_respects_max_sep():
    from ms_inspect.util.phase_cal_catalog import lookup_nearest

    m = lookup_nearest(J1822_RA, J1822_DEC + 3 / 3600, band_code="C", max_sep_deg=1 / 3600)
    assert m is None


def test_expected_flux_row_power_law_and_neighbour():
    from ms_inspect.util.phase_cal_catalog import expected_flux, get_source

    keys = {"flux_jy", "freq_ghz", "band", "spectral_index", "inputs"}
    v, flag, _ = expected_flux(get_source("1331+305"), 4.6)  # band from frequency: C
    assert (flag, v["flux_jy"], v["band"]) == ("COMPLETE", 7.47, "C")
    assert set(v) == keys
    v, flag, _ = expected_flux(get_source("1331+305"), 4.6, identity_exact=False)
    assert flag == "INFERRED"
    v, flag, _ = expected_flux(get_source("1822-096"), 4.598, band_code="C")
    assert flag == "INFERRED" and set(v) == keys
    assert v["flux_jy"] == pytest.approx(2.1227, abs=1e-3)
    v, flag, _ = expected_flux(get_source("1822-096"), 4.598, position_match=False)
    assert (v, flag) == (None, "UNAVAILABLE")


def _vla():
    from ms_inspect.util.telescope import profile_from_name

    return profile_from_name("EVLA")


def _match(name: str, flag: str = "COMPLETE") -> dict:
    return {"value": {"name": name, "bands": {}}, "flag": flag}


C_FREQ = {"centre_ghz": 4.6, "min_ghz": 4.5, "max_ghz": 4.7}


def test_field_list_flux_estimate():
    from ms_inspect.tools.fields import _vla_flux_estimate

    out = _vla_flux_estimate(_match("1822-096"), C_FREQ, _vla())
    assert out["flag"] == "INFERRED"
    assert 1.3 < out["value"]["flux_jy"] < 5.6
    out = _vla_flux_estimate(_match("1331+305"), C_FREQ, _vla())
    assert (out["flag"], out["value"]["flux_jy"]) == ("COMPLETE", 7.47)
    out = _vla_flux_estimate(_match("1331+305", flag="INFERRED"), C_FREQ, _vla())
    assert out["flag"] == "INFERRED"


def test_field_list_flux_estimate_vla_only():
    from ms_inspect.tools.fields import _vla_flux_estimate
    from ms_inspect.util.telescope import profile_from_name

    for tel in (profile_from_name("MeerKAT"), None):
        out = _vla_flux_estimate(_match("1331+305"), C_FREQ, tel)
        assert (out["value"], out["flag"]) == (None, "UNAVAILABLE")
