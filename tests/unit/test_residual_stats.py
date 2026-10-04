"""Unit tests for ms_residual_stats (parallel hands, per channel)."""

from __future__ import annotations

import numpy as np

from ms_inspect.tools.residual_stats import _spw_stats


def test_spw_stats_per_channel_and_fully_flagged_channel():
    rng = np.random.default_rng(0)
    amp = np.abs(rng.normal(0, 1.0, (2, 3, 2000)))
    amp[:, 1, :] += 50.0  # one RFI channel
    flag = np.zeros_like(amp, dtype=bool)
    flag[:, 2, :] = True  # one fully flagged channel
    st = _spw_stats(amp, flag)
    assert st["chan_n_unflagged"] == [4000, 4000, 0]
    assert st["chan_median_amp"][1] > 40 * st["chan_median_amp"][0]
    assert st["chan_median_amp"][2] is None
    assert st["chan_robust_sigma"][2] is None
    assert st["n_flagged"]["value"] == 4000


def test_spw_stats_all_flagged():
    amp = np.ones((2, 2, 5))
    st = _spw_stats(amp, np.ones_like(amp, dtype=bool))
    assert st["median_amp"]["flag"] == "UNAVAILABLE"
    assert st["chan_median_amp"] == [None, None]


def test_run_parallel_hands_per_spw(real_ms_calibrated):
    from ms_inspect.tools.residual_stats import run

    out = run(real_ms_calibrated, field_id=0)
    assert out["status"] == "ok"
    spws = out["data"]["per_spw"]
    assert [s["spw_id"] for s in spws] == [0, 1]
    for s in spws:
        assert s["correlations_used"] == ["RR", "LL"]
        assert len(s["chan_median_amp"]) == 64


def _payload(n_spw=2, n_chan=4):
    from ms_inspect.tools.residual_stats import _CHAN_KEYS

    return {
        "per_spw": [
            {"spw_id": i, "median_amp": {"value": 1.0}, **{k: [1.0] * n_chan for k in _CHAN_KEYS}}
            for i in range(n_spw)
        ]
    }


def test_bound_under_limit_keeps_arrays(tmp_path):
    from ms_inspect.tools.residual_stats import _bound_chan_payload

    side = tmp_path / "side.json"
    out = _bound_chan_payload(_payload(), 100, str(side), [])
    assert out["per_chan_truncated"]["value"] is False
    assert "chan_median_amp" in out["per_spw"][0]
    assert not side.exists()


def test_bound_over_limit_drops_all_and_writes_sidecar(tmp_path):
    import json

    from ms_inspect.tools.residual_stats import _CHAN_KEYS, _bound_chan_payload

    side = tmp_path / "side.json"
    out = _bound_chan_payload(_payload(), 5, str(side), [])
    assert out["per_chan_truncated"]["flag"] == "PARTIAL"
    for e in out["per_spw"]:
        assert e["n_chan_omitted"] == 4
        assert not any(k in e for k in _CHAN_KEYS)
        assert e["median_amp"]["value"] == 1.0
    full = json.loads(side.read_text())
    assert len(full["per_spw"][0]["chan_median_amp"]) == 4


def test_bound_zero_disables(tmp_path):
    from ms_inspect.tools.residual_stats import _bound_chan_payload

    out = _bound_chan_payload(_payload(n_chan=5000), 0, str(tmp_path / "s.json"), [])
    assert out["per_chan_truncated"]["value"] is False
