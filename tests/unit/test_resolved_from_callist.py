"""
Unit tests for ms_field_list's resolved status from the VLA calibrator list.

A calibrator that is not in the bundled catalogue takes resolved_source from
the VLA calibrator list at the band of its centre frequency. A UV limit gives
True and a warning with the uvrange. Whether that uvrange leaves usable data
depends on the array: the warning counts the baselines inside it. 3C84 is the
reference case: no limits at C-band, uvmin 12 klambda at L-band, which leaves
nothing in a D-like array and everything in an A-like one.

No CASA dependency.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_field_roles import FakeMsmd, _patch, _rec

from ms_inspect.tools import fields as fields_mod
from ms_inspect.tools.fields import _resolved_from_callist
from ms_inspect.tools.fields import run as field_list_run
from ms_inspect.util.array_config import array_baselines as _array_baselines
from ms_inspect.util.formatting import field
from ms_inspect.util.telescope import profile_from_name

VLA = profile_from_name("EVLA")


def _band(q="PPPP", uvmin=None, uvmax=None):
    return {
        "qual_A": q[0],
        "qual_B": q[1],
        "qual_C": q[2],
        "qual_D": q[3],
        "flux_jy": 1.0,
        "uvmin_kl": uvmin,
        "uvmax_kl": uvmax,
    }


MATCH_3C84 = {
    "value": {
        "name": "0319+415",
        "alt_name": "3C84",
        "bands": {"L": _band("PPXX", uvmin=12.0), "C": _band(), "U": _band()},
    },
    "flag": "COMPLETE",
}


def _freq(lo, hi):
    return {"min_ghz": lo, "max_ghz": hi, "centre_ghz": (lo + hi) / 2, "n_spw": 1}


_VLA_CENTRE_ECEF = np.array([-1601185.4, -5041977.5, 3554875.9])


def _y_array(arm_m):
    """
    A 27-antenna Y: 9 per arm, radii spaced geometrically from arm_m/50 to
    arm_m, arms 120 degrees apart. ECEF metres, shape [3, 27]. Only baseline
    lengths matter, so the plane's orientation is arbitrary.
    """
    radii = arm_m / 50 * 50 ** (np.arange(9) / 8)
    xy = [
        (r * math.cos(az), r * math.sin(az))
        for az in np.radians([5.0, 125.0, 245.0])
        for r in radii
    ]
    offsets = np.array([[x, y, 0.0] for x, y in xy]).T
    return _VLA_CENTRE_ECEF[:, None] + offsets


def _array(arm_m):
    return _array_baselines(FakeMsmd([], antenna_ecef=_y_array(arm_m)))


# At 1.5 GHz, 12 klambda is 2.4 km. D-like arms (0.6 km) reach 1.04 km;
# C-like arms (1.9 km) reach it only between the outer antennas; A-like arms
# (21 km) reach it from every antenna.
D_LIKE, C_LIKE, A_LIKE = _array(600.0), _array(1900.0), _array(21000.0)


# --- _resolved_from_callist -------------------------------------------------


def test_c_band_no_limits_is_unresolved_without_warning():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(4.5, 7.6), VLA)
    assert res["value"] is False and res["flag"] == "INFERRED"
    assert "P/P/P/P" in res["note"]
    assert warn is None


def test_l_band_limit_warns_with_uvrange():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA)
    assert res["value"] is True and res["flag"] == "INFERRED"
    assert "uvrange='>12klambda'" in warn
    assert "PPXX" not in warn and "config" not in warn
    assert "not counted" in res["note"]


def test_l_band_d_like_array_leaves_no_data():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA, D_LIKE)
    assert res["value"] is True
    assert "0 of 351 baselines" in res["note"]
    assert "do not use this field as a calibrator" in warn
    assert "pass uvrange" not in warn


def test_l_band_c_like_array_names_lost_antennas():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA, C_LIKE)
    assert "pass uvrange='>12klambda'" in warn
    assert "24 of 27 antennas have fewer than 4 baselines" in warn
    # The outer antenna of each arm keeps its baselines; the inner ones do not.
    assert "ea09" not in warn and "ea01" in warn


def test_l_band_a_like_array_keeps_every_antenna():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA, A_LIKE)
    assert "pass uvrange='>12klambda'" in warn
    assert "antennas" not in warn


def test_c_band_ignores_the_array():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(4.5, 7.6), VLA, D_LIKE)
    assert res["value"] is False and warn is None


def test_baselines_without_data_are_not_counted():
    class HalfDead(FakeMsmd):
        def baselines(self):
            n = 27
            return [[i != 0 and j != 0 for j in range(n)] for i in range(n)]

    # In the C-like array ea01 is a lost antenna; without data it is not one.
    array = _array_baselines(HalfDead([], antenna_ecef=_y_array(1900.0)))
    assert array["length_m"].size == 26 * 25 // 2
    _, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA, array)
    assert "23 of 26 antennas" in warn
    assert "ea01" not in warn


def test_array_positions_round_trip_through_msmd():
    ecef = _y_array(21000.0)
    array = _array_baselines(FakeMsmd([], antenna_ecef=ecef))
    direct = np.linalg.norm(ecef[:, 0] - ecef[:, 26])
    assert abs(array["length_m"][25] - direct) < 1e-6


def test_uvmax_gives_upper_uvrange():
    match = {"value": {"name": "x", "bands": {"X": _band(uvmax=400.0)}}, "flag": "COMPLETE"}
    res, warn = _resolved_from_callist(match, _freq(8.0, 9.0), VLA)
    assert res["value"] is True
    assert "uvrange='<400klambda'" in warn


def test_both_limits_give_one_range():
    match = {
        "value": {"name": "x", "bands": {"X": _band(uvmin=100.0, uvmax=400.0)}},
        "flag": "COMPLETE",
    }
    _, warn = _resolved_from_callist(match, _freq(8.0, 9.0), VLA)
    assert "uvrange='100~400klambda'" in warn


def test_all_x_without_limit_says_do_not_use():
    match = {"value": {"name": "x", "bands": {"L": _band("XXXX")}}, "flag": "COMPLETE"}
    res, warn = _resolved_from_callist(match, _freq(1.0, 2.0), VLA, A_LIKE)
    assert res["value"] is False
    assert "graded X in every configuration" in warn
    assert "do not use this field as a calibrator" in warn


def test_all_x_overrides_a_usable_uvrange():
    match = {"value": {"name": "x", "bands": {"L": _band("XXXX", uvmin=12.0)}}, "flag": "COMPLETE"}
    res, warn = _resolved_from_callist(match, _freq(1.0, 2.0), VLA, A_LIKE)
    assert res["value"] is True
    assert "282 of 351 baselines" in res["note"]
    assert "graded X in every configuration" in warn and "pass uvrange" not in warn


PARTIAL_X = {"value": {"name": "x", "bands": {"C": _band("PPXX")}}, "flag": "COMPLETE"}


def _cfg(name, flag="COMPLETE"):
    return field(name, flag=flag)


def test_partial_x_at_this_config_says_do_not_use():
    res, warn = _resolved_from_callist(PARTIAL_X, _freq(4.5, 7.6), VLA, None, _cfg("D"))
    assert res["value"] is False
    assert "graded X in configuration D" in warn
    assert "this MS is in D (COMPLETE)" in warn
    assert "do not use this field as a calibrator" in warn


def test_partial_x_at_other_config_is_silent():
    res, warn = _resolved_from_callist(PARTIAL_X, _freq(4.5, 7.6), VLA, None, _cfg("A"))
    assert res["value"] is False and warn is None
    assert "P/P/X/X" in res["note"]


def test_partial_x_hybrid_takes_the_worse_half():
    match = {"value": {"name": "x", "bands": {"C": _band("XSSS")}}, "flag": "COMPLETE"}
    _, warn = _resolved_from_callist(match, _freq(4.5, 7.6), VLA, None, _cfg("BnA"))
    assert "graded X in configuration A, and this MS is in BnA" in warn


def test_partial_x_inferred_config_is_named():
    _, warn = _resolved_from_callist(
        PARTIAL_X, _freq(4.5, 7.6), VLA, None, _cfg("C", flag="INFERRED")
    )
    assert "this MS is in C (INFERRED)" in warn


@pytest.mark.parametrize("config", [None, field(None, flag="UNAVAILABLE")])
def test_partial_x_unknown_config_names_the_x_configs(config):
    _, warn = _resolved_from_callist(PARTIAL_X, _freq(4.5, 7.6), VLA, None, config)
    assert "graded X in configuration C/D" in warn
    assert "configuration of this MS is unknown" in warn


def test_ku_band_maps_to_callist_u():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(13.0, 15.0), VLA)
    assert res["flag"] == "INFERRED" and res["value"] is False
    assert warn is None


def test_band_from_centre_not_edges():
    # Both edges sit in band gaps (0.99 GHz below L; 2.02 GHz in the L/S overlap).
    res, _ = _resolved_from_callist(MATCH_3C84, _freq(0.99, 2.02), VLA)
    assert res["value"] is True
    assert "band L" in res["note"]


@pytest.mark.parametrize(
    "match, freq, telescope",
    [
        ({"value": None, "flag": "UNAVAILABLE"}, _freq(4.5, 7.6), VLA),
        (MATCH_3C84, _freq(4.5, 7.6), profile_from_name("MeerKAT")),
        (MATCH_3C84, _freq(4.5, 7.6), None),
        (MATCH_3C84, None, VLA),
        (MATCH_3C84, _freq(2.5, 3.5), VLA),  # S-band: no list entry
    ],
)
def test_unavailable_has_no_warning(match, freq, telescope):
    res, warn = _resolved_from_callist(match, freq, telescope)
    assert res["value"] is None and res["flag"] == "UNAVAILABLE"
    assert res["note"]
    assert warn is None


# --- ms_field_list.run ------------------------------------------------------

_3C84_POS = (49.9506671, 41.5116953)
_L_BAND = {"spws_for_field": {0: [0]}, "chan_freqs": {0: [1.0e9, 1.5e9, 2.0e9]}}


def _run_3c84(monkeypatch, intents):
    _patch(monkeypatch, [("3C84", intents, *_3C84_POS)], **_L_BAND)
    return field_list_run("fake.ms")


def test_run_bandpass_field_gets_uvrange_warning(monkeypatch):
    result = _run_3c84(monkeypatch, ["CALIBRATE_BANDPASS#ON_SOURCE"])
    assert _rec(result, "3C84")["resolved_source"]["value"] is True
    assert any("uvrange='>12klambda'" in w for w in result["warnings"])


def test_run_d_like_array_says_do_not_use(monkeypatch):
    _patch(
        monkeypatch,
        [("3C84", ["CALIBRATE_BANDPASS#ON_SOURCE"], *_3C84_POS)],
        antenna_ecef=_y_array(600.0),
        **_L_BAND,
    )
    result = field_list_run("fake.ms")
    assert any("do not use this field" in w for w in result["warnings"])


def test_run_partial_x_uses_the_inferred_config(monkeypatch):
    # 3C84 at K band is X in A only, with no UV limit; a D-like array is not A.
    k_band = {"spws_for_field": {0: [0]}, "chan_freqs": {0: [20.0e9, 22.0e9, 24.0e9]}}
    for arm_m, warns in [(600.0, False), (21000.0, True)]:
        _patch(
            monkeypatch,
            [("3C84", ["CALIBRATE_BANDPASS#ON_SOURCE"], *_3C84_POS)],
            antenna_ecef=_y_array(arm_m),
            **k_band,
        )
        text = " ".join(field_list_run("fake.ms")["warnings"])
        assert ("graded X in configuration A" in text) is warns


def test_run_field_without_role_still_warns(monkeypatch):
    result = _run_3c84(monkeypatch, [])
    assert any("uvrange='>12klambda'" in w for w in result["warnings"])


def test_run_target_only_field_does_not_warn(monkeypatch):
    result = _run_3c84(monkeypatch, ["OBSERVE_TARGET#ON_SOURCE"])
    assert _rec(result, "3C84")["resolved_source"]["value"] is True
    assert not any("uvrange" in w for w in result["warnings"])


def test_run_telescope_read_failure_is_unavailable(monkeypatch):
    _patch(monkeypatch, [("3C84", ["CALIBRATE_BANDPASS#ON_SOURCE"], *_3C84_POS)], **_L_BAND)

    def boom(_p):
        raise RuntimeError("no OBSERVATION table")

    monkeypatch.setattr(fields_mod, "resolve_telescope", boom)
    rec = _rec(field_list_run("fake.ms"), "3C84")
    assert rec["resolved_source"]["flag"] == "UNAVAILABLE"


def test_run_catalogue_fields_do_not_read_telescope(monkeypatch):
    _patch(monkeypatch, [("3C286", ["CALIBRATE_FLUX#ON_SOURCE"], 202.78, 30.51)], **_L_BAND)

    def boom(_p):
        raise AssertionError("telescope read for a catalogue field")

    monkeypatch.setattr(fields_mod, "resolve_telescope", boom)
    rec = _rec(field_list_run("fake.ms"), "3C286")
    assert rec["resolved_source"]["flag"] == "COMPLETE"
