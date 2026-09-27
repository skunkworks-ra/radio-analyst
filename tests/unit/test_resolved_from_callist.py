"""
Unit tests for ms_field_list's resolved status from the VLA calibrator list.

A calibrator that is not in the bundled catalogue takes resolved_source from
the VLA calibrator list at the band of its centre frequency. A UV limit gives
True and a warning with the uvrange. 3C84 is the reference case: P in every
config at C-band, uvmin 12 klambda and X in C/D at L-band.

No CASA dependency.
"""

from __future__ import annotations

import pytest
from test_field_roles import _patch, _rec

from ms_inspect.tools import fields as fields_mod
from ms_inspect.tools.fields import _resolved_from_callist
from ms_inspect.tools.fields import run as field_list_run
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


# --- _resolved_from_callist -------------------------------------------------


def test_c_band_no_limits_is_unresolved_without_warning():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(4.5, 7.6), VLA)
    assert res["value"] is False and res["flag"] == "INFERRED"
    assert "P/P/P/P" in res["note"]
    assert warn is None


def test_l_band_limit_and_x_grade_warn_with_uvrange():
    res, warn = _resolved_from_callist(MATCH_3C84, _freq(1.0, 2.0), VLA)
    assert res["value"] is True and res["flag"] == "INFERRED"
    assert "uvrange='>12klambda'" in warn
    assert "config CD" in warn


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


def test_x_grade_without_limit_warns_but_is_unresolved():
    match = {"value": {"name": "x", "bands": {"C": _band("PPXX")}}, "flag": "COMPLETE"}
    res, warn = _resolved_from_callist(match, _freq(4.5, 7.6), VLA)
    assert res["value"] is False
    assert "uvrange" not in warn and "config CD" in warn


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
