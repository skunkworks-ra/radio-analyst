"""
Unit tests for ms_smearing_limits.

No CASA required: the arithmetic is tested through compute_limits, and run()
is tested with _read_inputs replaced.
"""

from __future__ import annotations

import math

import pytest

from ms_inspect.tools import smearing
from ms_inspect.tools.smearing import (
    AIRY_R10_LAMBDA_OVER_D,
    TIME_COEFF_S2,
    bandwidth_loss,
    compute_limits,
    largest_divisor_at_most,
    time_loss,
)

# VLA D-config, C-band, two 64 x 2 MHz SpWs, 1 s dumps (3C391 test data).
VLA_D_C = {
    "nu_min_hz": 4.535e9,
    "nu_max_hz": 7.563e9,
    "max_baseline_m": 1031.21,
    "dish_diameter_m": 25.0,
    "dump_time_s": 1.0,
    "spws": [
        {"spw_id": 0, "nchan": 64, "channel_width_hz": 2e6},
        {"spw_id": 1, "nchan": 64, "channel_width_hz": 2e6},
    ],
}


def _limits(**over):
    kw = {
        **VLA_D_C,
        "max_time_loss": 0.10,
        "max_bandwidth_loss": 0.05,
        "max_timebin_s": 30.0,
    }
    kw.update(over)
    return compute_limits(**kw)


# --- constants --------------------------------------------------------------


def test_airy_constant_is_the_ten_percent_point():
    special = pytest.importorskip("scipy.special")
    u = AIRY_R10_LAMBDA_OVER_D * math.pi
    assert (2 * special.j1(u) / u) ** 2 == pytest.approx(0.1, abs=1e-4)


def test_time_coefficient_matches_bridle_schwab():
    # Synthesis Imaging II eq. 18-43 quotes 1.22e-9 s^-2.
    assert pytest.approx(1.22e-9, rel=0.01) == TIME_COEFF_S2


# --- compute_limits ---------------------------------------------------------


def test_limits_sit_exactly_at_the_stated_losses():
    lim = _limits()
    assert time_loss(lim["x"], lim["tau_max_s"]) == pytest.approx(0.10)
    beta_x = lim["dnu_max_hz"] * math.radians(lim["r10_arcmin"] / 60) * 1031.21 / 299_792_458.0
    assert bandwidth_loss(beta_x) == pytest.approx(0.05)


def test_vla_d_cband_values():
    lim = _limits()
    assert lim["x"] == pytest.approx(59.8, abs=0.1)
    assert lim["tau_max_s"] == pytest.approx(150.8, abs=0.5)
    assert lim["dnu_max_hz"] == pytest.approx(61.1e6, rel=0.01)
    assert lim["suggested_timebin_s"] == 30.0
    for spw in lim["per_spw"]:
        assert spw["max_width_channels"] == 30
        assert spw["suggested_width_channels"] == 16
        assert spw["suggested_output_nchan"] == 4
        assert spw["bandwidth_loss_at_suggested"] < 0.05


def test_timebin_is_capped_and_never_exceeds_the_cap():
    lim = _limits(max_timebin_s=30.0)
    assert lim["tau_max_s"] > 30.0
    assert lim["suggested_timebin_s"] == 30.0


def test_smearing_limit_wins_when_shorter_than_cap():
    # A-config-like baselines: x grows ~36x, tau_max falls well below 30 s.
    lim = _limits(max_baseline_m=36_400.0)
    assert lim["tau_max_s"] < 30.0
    assert lim["suggested_timebin_s"] == math.floor(lim["tau_max_s"])
    assert lim["time_loss_at_suggested"] <= 0.10


def test_timebin_rounds_down_to_whole_dumps():
    lim = _limits(dump_time_s=4.0, max_timebin_s=30.0)
    assert lim["suggested_timebin_s"] == 28.0
    assert lim["suggested_timebin_n_dumps"] == 7


def test_dump_longer_than_limit_gives_no_averaging():
    lim = _limits(dump_time_s=40.0)
    assert lim["suggested_timebin_n_dumps"] == 0
    assert lim["suggested_timebin_s"] == 0.0


def test_wider_band_shortens_the_time_limit():
    # The PB radius follows nu_min and the beam follows nu_max, so doubling
    # nu_max at fixed nu_min halves tau_max.
    narrow = _limits(nu_max_hz=4.535e9)
    wide = _limits(nu_max_hz=9.07e9)
    assert wide["tau_max_s"] == pytest.approx(narrow["tau_max_s"] / 2, rel=1e-6)


def test_bandwidth_limit_in_hz_does_not_depend_on_nu_max():
    assert _limits(nu_max_hz=9.07e9)["dnu_max_hz"] == pytest.approx(_limits()["dnu_max_hz"])


def test_width_is_a_divisor_of_nchan():
    lim = _limits(spws=[{"spw_id": 0, "nchan": 63, "channel_width_hz": 2e6}])
    spw = lim["per_spw"][0]
    assert 63 % spw["suggested_width_channels"] == 0
    assert spw["suggested_width_channels"] == 21


def test_channel_already_wider_than_limit_gives_width_one():
    lim = _limits(spws=[{"spw_id": 0, "nchan": 16, "channel_width_hz": 128e6}])
    assert lim["per_spw"][0]["suggested_width_channels"] == 1


@pytest.mark.parametrize(
    ("n", "limit", "expected"),
    [(64, 30, 16), (64, 64, 64), (64, 0, 1), (63, 10, 9), (7, 6, 1), (1, 5, 1)],
)
def test_largest_divisor_at_most(n, limit, expected):
    assert largest_divisor_at_most(n, limit) == expected


# --- run() ------------------------------------------------------------------


def _fake_ms(tmp_path):
    ms = tmp_path / "fake.ms"
    ms.mkdir()
    (ms / "table.info").write_text("Type = Measurement Set\n")
    return ms


def test_run_reports_inputs_and_suggestions(tmp_path, monkeypatch):
    monkeypatch.setattr(smearing, "_read_inputs", lambda ms, calls: dict(VLA_D_C))
    res = smearing.run(str(_fake_ms(tmp_path)))
    d = res["data"]
    assert d["suggested_timebin_s"]["value"] == 30.0
    assert d["inputs"]["max_timebin_s"] == 30.0
    assert d["inputs"]["max_baseline_m"] == 1031.21
    assert d["constants"]["airy_r10_lambda_over_d"] == AIRY_R10_LAMBDA_OVER_D
    assert [s["suggested_width_channels"]["value"] for s in d["per_spw"]] == [16, 16]
    assert res["warnings"] == []


def test_run_warns_when_no_time_averaging_is_possible(tmp_path, monkeypatch):
    monkeypatch.setattr(
        smearing, "_read_inputs", lambda ms, calls: {**VLA_D_C, "dump_time_s": 40.0}
    )
    res = smearing.run(str(_fake_ms(tmp_path)))
    assert any("not possible" in w for w in res["warnings"])


def test_run_marks_missing_dump_time_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        smearing, "_read_inputs", lambda ms, calls: {**VLA_D_C, "dump_time_s": None}
    )
    d = smearing.run(str(_fake_ms(tmp_path)))["data"]
    assert d["suggested_timebin_s"]["flag"] == "UNAVAILABLE"
    assert d["suggested_timebin_s"]["value"] is None


def test_input_model_rejects_cap_above_30s():
    from pydantic import ValidationError

    from ms_inspect.server import SmearingLimitsInput

    with pytest.raises(ValidationError):
        SmearingLimitsInput(ms_path="/x.ms", max_timebin_s=31.0)
