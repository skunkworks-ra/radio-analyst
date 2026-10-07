"""Unit tests for ms_postcal_flag flag-call construction (no CASA required)."""

from __future__ import annotations

import pytest

from ms_modify.postcal_flag import (
    _build_flag_calls,
    _parse_spw_ids,
    check_clip_policy,
    match_field_names,
    model_is_default,
)


def test_call_order_and_membership():
    calls = _build_flag_calls(
        field="J1454,SN1006",
        keep_spw="0,1,2",
        drop_spw="3,8,9",
        datacolumn="corrected",
        clipmax=100.0,
        clip_thresholds=None,
        uvrange="",
        timedevscale=5.0,
        freqdevscale=5.0,
        timecutoff=4.0,
        freqcutoff=4.0,
    )
    # clip must come first (before the autoflaggers see the data)
    assert calls[0]["mode"] == "clip"
    assert calls[0]["clipminmax"] == [0.0, 100.0]
    assert calls[1]["mode"] == "tfcrop"
    assert calls[2]["mode"] == "rflag"
    # the drop-tier manual flag comes last
    assert calls[-1]["mode"] == "manual"
    assert calls[-1]["spw"] == "3,8,9"
    # keep_spw scopes the autoflaggers, not the manual drop
    assert calls[1]["spw"] == "0,1,2" and calls[2]["spw"] == "0,1,2"


def test_per_field_spw_corr_residual_clip_calls():
    calls = _build_flag_calls(
        field="3C147,3C138",
        keep_spw="0,4",
        drop_spw="",
        datacolumn="residual",
        clipmax=None,
        clip_thresholds={"3C147|4|RR": 2.5, "3C147|0|LL": 1.2, "3C138|0|RR": 1.6},
        uvrange="",
        timedevscale=5.0,
        freqdevscale=5.0,
        timecutoff=4.0,
        freqcutoff=4.0,
    )
    clips = [c for c in calls if c["mode"] == "clip"]
    # one clip per field|spw|corr key, each scoped to its own field and correlation
    assert len(clips) == 3
    by = {(c["field"], c["spw"], c["correlation"]): c["clipminmax"][1] for c in clips}
    assert by == {("3C147", "4", "RR"): 2.5, ("3C147", "0", "LL"): 1.2, ("3C138", "0", "RR"): 1.6}
    assert all(c["datacolumn"] == "residual" for c in clips)
    # clips precede the autoflaggers
    assert [c["mode"] for c in calls][:3] == ["clip"] * 3


NAMES = ["J0336+3218", "PER_FIELD_55", "PER_FIELD_56", "0542+498=3C147", "0521+166=3C138"]


def test_match_field_names_exact_wildcard_id_range():
    assert match_field_names(NAMES, "0542+498=3C147") == [3]
    assert match_field_names(NAMES, "PER_FIELD_*") == [1, 2]
    assert match_field_names(NAMES, "0,4") == [0, 4]
    assert match_field_names(NAMES, "1~2,J0336+3218") == [0, 1, 2]


def test_match_field_names_unmatched_token_raises():
    # the old code fell through to EVERY field when a wildcard matched nothing
    with pytest.raises(ValueError, match="matches no field"):
        match_field_names(NAMES, "3C147")
    with pytest.raises(ValueError, match="matches no field"):
        match_field_names(NAMES, "PER_FIELD_55,NOPE_*")
    with pytest.raises(ValueError):
        match_field_names(NAMES, "")


def test_clip_policy_requires_residual():
    check_clip_policy("corrected", None, None)  # no clip requested: fine
    check_clip_policy("residual", 7.0, None)
    check_clip_policy("RESIDUAL_DATA", None, 2.0)
    with pytest.raises(ValueError, match="residual"):
        check_clip_policy("corrected", 5.0, None)
    with pytest.raises(ValueError, match="residual"):
        check_clip_policy("data", None, 10.0)


def test_model_is_default():
    assert model_is_default(1.0, 0.0)  # unwritten MODEL (J0336 in this run)
    assert model_is_default(1.03, 0.5)
    assert not model_is_default(18.7, 0.0)  # 3C147 setjy model
    assert not model_is_default(1.0, 25.0)  # ~1 Jy but structured phase: a real model


def test_parse_spw_ids():
    assert _parse_spw_ids("0,1,2,4,10") == [0, 1, 2, 4, 10]
    assert _parse_spw_ids("0:5~10,1") == [1]  # channel syntax skipped
    # inclusive ranges are expanded, mixable with plain ids, sorted + de-duped
    assert _parse_spw_ids("0~7") == [0, 1, 2, 3, 4, 5, 6, 7]
    assert _parse_spw_ids("0~7,9~15") == [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]
    assert _parse_spw_ids("16,20~28") == [16, 20, 21, 22, 23, 24, 25, 26, 27, 28]
    assert _parse_spw_ids("9~15,8") == [8, 9, 10, 11, 12, 13, 14, 15]
    assert _parse_spw_ids("") == []


def test_no_clip_no_drop_omits_those_calls():
    calls = _build_flag_calls(
        field="SN1006",
        keep_spw="",
        drop_spw="",
        datacolumn="corrected",
        clipmax=None,
        clip_thresholds=None,
        uvrange="",
        timedevscale=5.0,
        freqdevscale=5.0,
        timecutoff=4.0,
        freqcutoff=4.0,
    )
    modes = [c["mode"] for c in calls]
    assert "clip" not in modes
    assert "manual" not in modes
    # no spw clause when keep_spw is empty
    assert all("spw" not in c for c in calls)
    assert modes == ["tfcrop", "rflag"]


def test_generated_script_never_uses_list_mode():
    from ms_modify.postcal_flag import _build_script

    calls = _build_flag_calls(
        field="SN1006",
        keep_spw="0,1",
        drop_spw="3",
        datacolumn="corrected",
        clipmax=100.0,
        clip_thresholds=None,
        uvrange="",
        timedevscale=5.0,
        freqdevscale=5.0,
        timecutoff=4.0,
        freqcutoff=4.0,
    )
    script = _build_script("/data/x.ms", calls)
    # inpfile is the only list-mode marker; its absence proves the switch.
    assert "inpfile" not in script
    assert "flagmanager" in script and "before_postcal_flag" in script
    assert "action='apply'" in script
    assert "flagbackup=False" in script and "flagbackup=True" not in script
