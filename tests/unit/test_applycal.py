"""Unit tests for ms_applycal script generation."""

from __future__ import annotations

from pathlib import Path


def _gen(real_ms_raw, tmp_path, **kwargs) -> str:
    from ms_modify.applycal import run

    ct = tmp_path / "g.G"
    ct.mkdir(exist_ok=True)
    (ct / "table.info").write_text("Type = Calibration\n")
    out = run(
        ms_path=real_ms_raw,
        gaintable=[str(ct)],
        workdir=str(tmp_path),
        **{"field": "3C147", **kwargs},
    )
    assert out["status"] == "ok", out
    path = out["data"]["script_path"]
    return Path(path["value"] if isinstance(path, dict) else path).read_text()


def test_default_applymode_is_calflag(real_ms_raw, tmp_path):
    assert "applymode='calflag'" in _gen(real_ms_raw, tmp_path)


def test_calonly_still_explicitly_available(real_ms_raw, tmp_path):
    assert "applymode='calonly'" in _gen(real_ms_raw, tmp_path, applymode="calonly")
