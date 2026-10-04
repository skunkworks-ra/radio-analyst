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


def test_script_name_includes_ms_and_is_safe(tmp_path):
    from ms_modify.applycal import _script_path

    a = _script_path(tmp_path, "3C147", "/data/a.ms")
    b = _script_path(tmp_path, "3C147", "/data/b.ms")
    assert a != b
    assert a.name == "applycal_a_3C147.py"
    star = _script_path(tmp_path, "J*", "/data/a.ms")
    assert "*" not in star.name
    assert star != _script_path(tmp_path, "J?", "/data/a.ms")


def test_long_field_lists_with_shared_prefix_do_not_collide(tmp_path):
    from ms_modify.applycal import _script_path

    base = ",".join(f"PER_FIELD_{i}" for i in range(10))
    one = _script_path(tmp_path, base + ",X", "/data/a.ms")
    two = _script_path(tmp_path, base + ",Y", "/data/a.ms")
    assert one != two
    assert len(one.name) <= len("applycal_a_") + 40 + len(".py")
