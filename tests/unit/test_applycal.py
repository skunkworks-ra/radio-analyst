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


def test_applycal_rejects_unknown_literal_field_like_mosaic_group(tmp_path, monkeypatch):
    import contextlib

    import pytest

    from ms_inspect.exceptions import ComputationError
    from ms_modify import applycal

    ms = tmp_path / "mosaic.ms"
    ms.mkdir()
    (ms / "table.info").write_text("Type = Measurement Set\n")
    ct = tmp_path / "gain.fluxscaled"
    ct.mkdir()
    (ct / "table.info").write_text("Type = Calibration\n")
    wd = tmp_path / "work"
    wd.mkdir()

    class _FakeMsmd:
        def fieldnames(self):
            return ["J1331+3030", "J1822-0938", "3C391 C1", "3C391 C2"]

    @contextlib.contextmanager
    def _fake_open_msmd(_path):
        yield _FakeMsmd()

    monkeypatch.setattr(applycal, "open_msmd", _fake_open_msmd)

    with pytest.raises(ComputationError, match=r"mosaic_groups\[\]\.field_names"):
        applycal.run(ms_path=str(ms), field="3C391", gaintable=[str(ct)], workdir=str(wd))
    assert not list(wd.glob("applycal_*.py"))

    ok_names = applycal.run(
        ms_path=str(ms), field="3C391 C1,3C391 C2", gaintable=[str(ct)], workdir=str(wd)
    )
    assert ok_names["status"] == "ok"

    ok_glob = applycal.run(ms_path=str(ms), field="3C391*", gaintable=[str(ct)], workdir=str(wd))
    assert ok_glob["status"] == "ok"


def test_cross_calibrator_gainfield_guard_scoped_to_g_and_t_jones(
    real_ms_raw, real_caltable_copy, tmp_path
):
    import shutil

    import numpy as np

    from ms_inspect.util.casa_context import open_table
    from ms_modify import applycal

    wd = tmp_path / "work"
    wd.mkdir()

    # Build a real multi-field G Jones table containing solutions for BOTH field 0 (3C147)
    # and field 1 (J1331+3030).
    multi_g = tmp_path / "multi_gain.G"
    shutil.copytree(real_caltable_copy, multi_g)
    with open_table(str(multi_g), read_only=False) as tb:
        tb.putkeyword("VisCal", "G Jones")
        fids = np.asarray(tb.getcol("FIELD_ID"), dtype=int)
        assert len(fids) >= 2
        fids[: len(fids) // 2] = 0
        fids[len(fids) // 2 :] = 1
        tb.putcol("FIELD_ID", fids)

    # 1. Multi-field G Jones with empty gainfield='' -> warns on linear mixing.
    res_empty = applycal.run(
        ms_path=real_ms_raw,
        field="3C147",
        gaintable=[str(multi_g)],
        gainfield=[""],
        workdir=str(wd),
    )
    assert any("Cross-calibrator gainfield" in w and "G Jones" in w for w in res_empty["warnings"])
    assert not any("np.str_" in w for w in res_empty["warnings"])

    # 2. Multi-field G Jones naming a DIFFERENT calibrator -> warns on mismatch.
    res_other = applycal.run(
        ms_path=real_ms_raw,
        field="3C147",
        gaintable=[str(multi_g)],
        gainfield=["J1331+3030"],
        workdir=str(wd),
    )
    assert any(
        "Cross-calibrator gainfield" in w and "J1331+3030" in w for w in res_other["warnings"]
    )

    # 3. Multi-field G Jones naming the SAME calibrator -> no cross-calibrator warning.
    res_self = applycal.run(
        ms_path=real_ms_raw,
        field="3C147",
        gaintable=[str(multi_g)],
        gainfield=["3C147"],
        workdir=str(wd),
    )
    assert not any("Cross-calibrator gainfield" in w for w in res_self["warnings"])

    # 4. T Jones is also guarded.
    multi_t = tmp_path / "multi_gain.T"
    shutil.copytree(multi_g, multi_t)
    with open_table(str(multi_t), read_only=False) as tb:
        tb.putkeyword("VisCal", "T Jones")
    res_t = applycal.run(
        ms_path=real_ms_raw,
        field="3C147",
        gaintable=[str(multi_t)],
        gainfield=["J1331+3030"],
        workdir=str(wd),
    )
    assert any("Cross-calibrator gainfield" in w and "T Jones" in w for w in res_t["warnings"])

    # 5. Single-field G Jones (field 0 only): applying to field 1 (target) with gainfield='3C147'
    #    and applying to field 0 with gainfield='' (selfcal pattern) must NOT warn.
    single_g = tmp_path / "single_gain.G"
    shutil.copytree(real_caltable_copy, single_g)
    with open_table(str(single_g), read_only=False) as tb:
        tb.putkeyword("VisCal", "G Jones")
        tb.putcol("FIELD_ID", np.zeros(tb.nrows(), dtype=int))

    res_target = applycal.run(
        ms_path=real_ms_raw,
        field="J1331+3030",
        gaintable=[str(single_g)],
        gainfield=["3C147"],
        workdir=str(wd),
    )
    assert not any("Cross-calibrator gainfield" in w for w in res_target["warnings"])

    res_selfcal = applycal.run(
        ms_path=real_ms_raw,
        field="3C147",
        gaintable=[str(single_g)],
        gainfield=[""],
        workdir=str(wd),
    )
    assert not any("Cross-calibrator gainfield" in w for w in res_selfcal["warnings"])

    # 6. B Jones, K Jones, Df Jones, Xf Jones tables must NEVER warn.
    for viscal, suffix in (
        ("B Jones", "B"),
        ("K Jones", "K"),
        ("Df Jones", "D"),
        ("Xf Jones", "X"),
    ):
        non_gt = tmp_path / f"cal.{suffix}"
        shutil.copytree(multi_g, non_gt)
        with open_table(str(non_gt), read_only=False) as tb:
            tb.putkeyword("VisCal", viscal)
        for gf in ("", "J1331+3030"):
            res_non = applycal.run(
                ms_path=real_ms_raw,
                field="3C147",
                gaintable=[str(non_gt)],
                gainfield=[gf],
                workdir=str(wd),
            )
            assert not any("Cross-calibrator gainfield" in w for w in res_non["warnings"]), (
                f"Unexpected cross-cal warning for {viscal} with gainfield={gf!r}: {res_non['warnings']}"
            )
