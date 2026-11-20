"""
Unit tests for replay ledger deduplication, flag backups, preflag retries, and audit hook.

Covers:
1. ms_set_intents TOOL_NAME, next_script_path, and reduction_log deduplication.
2. Dependency-aware stage_log deduplication and scriptless tools in reduction_log.
3. Versioned flag backups, script-collision guards, applycal flagbackup=True,
   preflag retry idempotency, and workflow_status missing-calibrators.ms recovery.
4. Audit hook subagent window isolation and OpenCode transcript support
   (both `opencode export` JSON and `opencode run --format json` JSONL).
"""

from __future__ import annotations

import ast
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from ms_create import audit_hook, reduction_log
from ms_inspect.exceptions import ComputationError
from ms_inspect.tools import workflow_status
from ms_inspect.util.stage_log import STAGE_LOG_NAME, read_stage_log
from ms_modify import (
    applycal,
    casa_task,
    casa_tool,
    debug_mode,
    flag_caltable,
    flag_data,
    initial_rflag,
    intents,
    pathguard,
    postcal_flag,
    preflag,
    rflag,
    server,
    setjy_polcal,
)


def _make_ms(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "table.info").write_text("Type = Measurement Set\n")
    return path


def _make_caltable(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "table.info").write_text("Type = Calibration\n")
    return path


def _append_stage_entries(wd: Path, entries: list[dict[str, Any]]) -> None:
    log_file = wd / STAGE_LOG_NAME
    with log_file.open("a") as fh:
        for idx, raw in enumerate(entries):
            rec = {
                "at": f"2026-11-16T00:00:{idx:02d}Z",
                "exists": True,
                **raw,
            }
            fh.write(json.dumps(rec) + "\n")


@contextmanager
def _fake_casatasks_module(**funcs: Any):
    mod = types.ModuleType("casatasks")
    for name, fn in funcs.items():
        setattr(mod, name, fn)
    prev = sys.modules.get("casatasks")
    sys.modules["casatasks"] = mod
    try:
        yield mod
    finally:
        if prev is None:
            sys.modules.pop("casatasks", None)
        else:
            sys.modules["casatasks"] = prev


# ---------------------------------------------------------------------------
# 1. ms_set_intents + pathguard helpers
# ---------------------------------------------------------------------------


class TestSetIntentsAndPathguard:
    def test_intents_tool_name_and_next_script_path(self, tmp_path, monkeypatch):
        assert intents.TOOL_NAME == "ms_set_intents"

        ms = _make_ms(tmp_path / "obs.ms")
        wd = tmp_path / "work"
        wd.mkdir()

        class _FakeMsmd:
            def fieldnames(self):
                return ["3C286", "TARGET"]

            def phasecenter(self, fid):
                return {"m0": {"value": 0.5 + fid * 0.1}, "m1": {"value": 0.2}}

            def intentsforfield(self, _fid):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        class _FakeSpwTb:
            def getcell(self, _col, _row):
                return [1.4e9, 1.5e9]

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(intents, "open_msmd", lambda _p: _FakeMsmd())
        monkeypatch.setattr(intents, "open_table", lambda _p, **_k: _FakeSpwTb())
        monkeypatch.setattr(intents, "vla_cone_search", lambda *_a, **_k: None)

        r1 = intents.set_intents(str(ms), execute=False, workdir=str(wd))
        r2 = intents.set_intents(str(ms), execute=False, workdir=str(wd))

        assert r1["tool"] == "ms_set_intents"
        assert r1["data"]["script_path"] == str(wd / "set_intents.py")
        assert r2["data"]["script_path"] == str(wd / "set_intents_2.py")
        assert (wd / "set_intents.py").is_file()
        assert (wd / "set_intents_2.py").is_file()

    def test_set_intents_deduplicated_in_reduction_log(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(wd / "obs.ms")

        _append_stage_entries(
            wd,
            [
                {
                    "stage": "intents",
                    "product": "obs.ms",
                    "params": {"ms_path": "obs.ms", "workdir": str(wd)},
                },
                {
                    "stage": "set_intents",
                    "product": "",
                    "params": {
                        "ms_path": str(ms),
                        "workdir": str(wd),
                        "pol_leakage_fields": ["J1822-0938"],
                    },
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert len(recs) == 1
        assert recs[0]["tool"] == "ms_set_intents"
        assert recs[0]["params"]["pol_leakage_fields"] == ["J1822-0938"]
        assert recs[0]["params"]["execute"] is True

    def test_next_flag_version_checks_list_and_flags_dir(self, tmp_path):
        ms = _make_ms(tmp_path / "cal.ms")
        assert pathguard.next_flag_version(str(ms), "before_rflag") == "before_rflag"

        fv = tmp_path / "cal.ms.flagversions"
        fv.mkdir()
        (fv / "FLAG_VERSION_LIST").write_text("before_rflag : initial backup\n")
        assert pathguard.next_flag_version(str(ms), "before_rflag") == "before_rflag_2"

        (fv / "flags.before_rflag_2").mkdir()
        assert pathguard.next_flag_version(str(ms), "before_rflag") == "before_rflag_3"


# ---------------------------------------------------------------------------
# 2. Dependency-aware deduplication & scriptless tools in reduction_log
# ---------------------------------------------------------------------------


class TestReductionLogDeduplication:
    def test_casa_tool_dict_and_list_args_and_subtable_parent_ms(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        src_ms = _make_ms(tmp_path / "raw.ms")
        cal_ms = _make_ms(wd / "calibrators.ms")

        grp_dict = [
            {
                "stage": "ms_casa_tool",
                "product": str(wd / "copy1.tab"),
                "params": {
                    "tool": "table",
                    "calls": [{"method": "open", "args": {"tablename": f"{cal_ms}/STATE"}}],
                },
            }
        ]
        grp_list = [
            {
                "stage": "ms_casa_tool",
                "product": str(wd / "copy2.tab"),
                "params": {
                    "tool": "table",
                    "calls": [{"method": "open", "args": [f"{cal_ms}/ANTENNA"]}],
                },
            }
        ]
        t_dict = reduction_log._group_ms_targets(grp_dict, wd)
        t_list = reduction_log._group_ms_targets(grp_list, wd)
        assert str(cal_ms.resolve()) in t_dict
        assert f"{cal_ms.resolve()}/STATE" in t_dict
        assert str(cal_ms.resolve()) in t_list
        assert f"{cal_ms.resolve()}/ANTENNA" in t_list

        # Recreating calibrators.ms via preflag retry wipes earlier subtable copy on calibrators.ms
        _append_stage_entries(
            wd,
            [
                {
                    "stage": "preflag",
                    "product": str(src_ms),
                    "params": {"ms_path": str(src_ms), "workdir": str(wd), "cal_fields": "0"},
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(src_ms), "workdir": str(wd), "cal_fields": "0"},
                },
                grp_dict[0],
                {
                    "stage": "preflag",
                    "product": str(src_ms),
                    "params": {"ms_path": str(src_ms), "workdir": str(wd), "cal_fields": "0,1"},
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(src_ms), "workdir": str(wd), "cal_fields": "0,1"},
                },
            ],
        )
        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == ["ms_apply_preflag"]
        assert recs[0]["params"]["cal_fields"] == "0,1"

    def test_subset_solve_and_casa_task_caltable_deduplication(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        cal_ms = _make_ms(wd / "calibrators.ms")

        _append_stage_entries(
            wd,
            [
                # Partial priorcals crash (only 2 tables) superseded by 3-table priorcals
                {
                    "stage": "priorcals",
                    "product": "gain_curves.gc",
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd)},
                },
                {
                    "stage": "priorcals",
                    "product": "opacities.opac",
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd)},
                },
                {
                    "stage": "priorcals",
                    "product": str(wd / "gain_curves.gc"),
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd), "debug": False},
                },
                {
                    "stage": "priorcals",
                    "product": str(wd / "opacities.opac"),
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd), "debug": False},
                },
                {
                    "stage": "priorcals",
                    "product": str(wd / "requantizer.rq"),
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd), "debug": False},
                },
                # Superseded caltable-producing ms_casa_task:gencal
                {
                    "stage": "ms_casa_task:gencal",
                    "product": "antpos.cal",
                    "params": {
                        "task": "gencal",
                        "params": {
                            "vis": str(cal_ms),
                            "caltable": "antpos.cal",
                            "caltype": "antpos",
                        },
                        "workdir": str(wd),
                    },
                },
                {
                    "stage": "ms_casa_task:gencal",
                    "product": str(wd / "antpos.cal"),
                    "params": {
                        "task": "gencal",
                        "params": {
                            "vis": str(cal_ms),
                            "caltable": str(wd / "antpos.cal"),
                            "caltype": "antpos",
                            "parameter": [0.01],
                        },
                        "workdir": str(wd),
                    },
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == ["ms_generate_priorcals", "ms_casa_task"]
        assert len(recs[0]["outputs"]["products"]) == 3
        assert recs[1]["params"]["params"]["parameter"] == [0.01]

    def test_tclean_deduplicates_hogbom_to_mtmfs_on_canonical_imagename(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(wd / "target.ms")

        _append_stage_entries(
            wd,
            [
                {
                    "stage": "tclean",
                    "product": str(wd / "target_cont.image"),
                    "params": {
                        "ms_path": str(ms),
                        "imagename": "target_cont",
                        "deconvolver": "hogbom",
                        "savemodel": "none",
                        "workdir": str(wd),
                    },
                },
                {
                    "stage": "tclean",
                    "product": str(wd / "target_cont.image.tt0"),
                    "params": {
                        "ms_path": str(ms),
                        "imagename": str(wd / "target_cont"),
                        "deconvolver": "mtmfs",
                        "nterms": 2,
                        "savemodel": "modelcolumn",
                        "workdir": str(wd),
                    },
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert len(recs) == 1
        assert recs[0]["params"]["deconvolver"] == "mtmfs"

    def test_setjy_and_setjy_polcal_deduplication(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        cal_ms = _make_ms(wd / "calibrators.ms")

        _append_stage_entries(
            wd,
            [
                # First setjy (usescratch=False) immediately superseded by usescratch=True
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": "calibrators.ms",
                        "workdir": str(wd),
                        "usescratch": False,
                        "exclude_fields": "3C286",
                    },
                },
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "workdir": str(wd),
                        "usescratch": True,
                        "exclude_fields": "3C286",
                    },
                },
                # First setjy_polcal superseded by second setjy_polcal before polcal runs
                {
                    "stage": "setjy_polcal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "polindex_deg": 2},
                },
                {
                    "stage": "setjy_polcal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "polindex_deg": 3},
                },
                # MODEL_DATA consumer
                {
                    "stage": "polcal",
                    "product": str(wd / "Df0.D"),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "caltable": "Df0.D"},
                },
                # Later setjy_polcal after MODEL_DATA consumer: both 2nd and 3rd must survive
                {
                    "stage": "setjy_polcal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "polindex_deg": 4},
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == [
            "ms_setjy",
            "ms_setjy_polcal",
            "ms_polcal",
            "ms_setjy_polcal",
        ]
        assert recs[0]["params"]["usescratch"] is True
        assert recs[1]["params"]["polindex_deg"] == 3
        assert recs[3]["params"]["polindex_deg"] == 4

    def test_corrected_consumer_and_applycal_retention_scenarios(self, tmp_path):
        # Scenario A: Solve 1 -> applycal -> tclean(savemodel='none') + gencal -> Solve 2 -> applycal
        # Neither tclean(savemodel='none') nor gencal is a CORRECTED_DATA mutator, so Solve 1 and
        # the first applycal are dropped.
        wd_a = tmp_path / "work_a"
        wd_a.mkdir()
        ms_a = _make_ms(wd_a / "target.ms")
        _append_stage_entries(
            wd_a,
            [
                {
                    "stage": "gaincal",
                    "product": "gain.G",
                    "params": {"ms_path": str(ms_a), "caltable": "gain.G", "solint": "60s"},
                },
                {
                    "stage": "applycal",
                    "product": str(ms_a),
                    "params": {
                        "ms_path": str(ms_a),
                        "field": "TARGET",
                        "gaintable": ["gain.G"],
                    },
                },
                {
                    "stage": "tclean",
                    "product": str(wd_a / "check.image"),
                    "params": {
                        "ms_path": str(ms_a),
                        "imagename": "check",
                        "savemodel": "none",
                    },
                },
                {
                    "stage": "ms_casa_task:gencal",
                    "product": str(wd_a / "antpos.cal"),
                    "params": {
                        "task": "gencal",
                        "params": {"vis": str(ms_a), "caltable": str(wd_a / "antpos.cal")},
                        "workdir": str(wd_a),
                    },
                },
                {
                    "stage": "gaincal",
                    "product": str(wd_a / "gain.G"),
                    "params": {
                        "ms_path": str(ms_a),
                        "caltable": str(wd_a / "gain.G"),
                        "solint": "inf",
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(ms_a),
                    "params": {
                        "ms_path": str(ms_a),
                        "field": "TARGET",
                        "gaintable": [str(wd_a / "gain.G")],
                    },
                },
            ],
        )
        recs_a = reduction_log.load_effective_records(wd_a)
        gaincals_a = [r for r in recs_a if r["tool"] == "ms_gaincal"]
        applycals_a = [r for r in recs_a if r["tool"] == "ms_applycal"]
        assert len(gaincals_a) == 1 and gaincals_a[0]["params"]["solint"] == "inf"
        assert len(applycals_a) == 1

        # Scenario B: Selfcal (applycal -> tclean(savemodel='modelcolumn') -> gaincal(selfcal.G) -> applycal)
        wd_b = tmp_path / "work_b"
        wd_b.mkdir()
        ms_b = _make_ms(wd_b / "target.ms")
        _append_stage_entries(
            wd_b,
            [
                {
                    "stage": "applycal",
                    "product": str(ms_b),
                    "params": {"ms_path": str(ms_b), "field": "TARGET", "gaintable": ["flux.G"]},
                },
                {
                    "stage": "tclean",
                    "product": str(wd_b / "pass1.image"),
                    "params": {
                        "ms_path": str(ms_b),
                        "imagename": "pass1",
                        "savemodel": "modelcolumn",
                    },
                },
                {
                    "stage": "gaincal",
                    "product": str(wd_b / "selfcal1.G"),
                    "params": {"ms_path": str(ms_b), "caltable": "selfcal1.G", "field": "TARGET"},
                },
                {
                    "stage": "applycal",
                    "product": str(ms_b),
                    "params": {
                        "ms_path": str(ms_b),
                        "field": "TARGET",
                        "gaintable": ["flux.G", "selfcal1.G"],
                    },
                },
            ],
        )
        recs_b = reduction_log.load_effective_records(wd_b)
        assert [r["tool"] for r in recs_b] == [
            "ms_applycal",
            "ms_tclean",
            "ms_gaincal",
            "ms_applycal",
        ]

        # Scenario C: Stokes IQUV (7a applycal -> polcal -> 5a applycal on same (ms, field))
        wd_c = tmp_path / "work_c"
        wd_c.mkdir()
        cal_c = _make_ms(wd_c / "calibrators.ms")
        _append_stage_entries(
            wd_c,
            [
                # Back-to-back retry of 7a before polcal: first 7a dropped, second 7a kept!
                {
                    "stage": "applycal",
                    "product": str(cal_c),
                    "params": {
                        "ms_path": str(cal_c),
                        "field": "3C286",
                        "gaintable": ["K0.K", "BP.B", "G.flux"],
                        "applymode": "calonly",
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(cal_c),
                    "params": {
                        "ms_path": str(cal_c),
                        "field": "3C286",
                        "gaintable": ["K0.K", "BP.B", "G.flux"],
                        "applymode": "calflag",
                    },
                },
                {
                    "stage": "polcal",
                    "product": str(wd_c / "Df.D"),
                    "params": {"ms_path": str(cal_c), "field": "3C286", "caltable": "Df.D"},
                },
                {
                    "stage": "applycal",
                    "product": str(cal_c),
                    "params": {
                        "ms_path": str(cal_c),
                        "field": "3C286",
                        "gaintable": ["K0.K", "BP.B", "G.flux", "Df.D"],
                        "applymode": "calflag",
                    },
                },
            ],
        )
        recs_c = reduction_log.load_effective_records(wd_c)
        assert [r["tool"] for r in recs_c] == ["ms_applycal", "ms_polcal", "ms_applycal"]
        assert recs_c[0]["params"]["applymode"] == "calflag"
        assert len(recs_c[0]["params"]["gaintable"]) == 3
        assert len(recs_c[2]["params"]["gaintable"]) == 4

    def test_flag_caltable_filtering_and_external_preservation(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(wd / "cal.ms")

        _append_stage_entries(
            wd,
            [
                # External caltable (no solve in stage_log): preserved!
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "external.G"),
                    "params": {"caltable_path": "external.G", "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                # Solve 1 -> flag_caltable -> Solve 2 (unconsumed): Solve 1 + flag 1 dropped!
                {
                    "stage": "bandpass",
                    "product": str(wd / "BP.B"),
                    "params": {"ms_path": str(ms), "caltable": "BP.B", "solint": "60s"},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP.B"),
                    "params": {"caltable_path": "BP.B", "mode": None, "sigma": 4.0},
                    "measurement": {"mode": "tfcrop"},
                },
                {
                    "stage": "bandpass",
                    "product": str(wd / "BP.B"),
                    "params": {"ms_path": str(ms), "caltable": "BP.B", "solint": "inf"},
                },
                # Two auto-routed flag_caltable calls (params['mode'] is None) + one manual flag
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP.B"),
                    "params": {"caltable_path": "BP.B", "mode": None, "sigma": 5.0},
                    "measurement": {"mode": "tfcrop"},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP.B"),
                    "params": {"caltable_path": "BP.B", "mode": None, "sigma": 6.0},
                    "measurement": {"mode": "tfcrop"},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP.B"),
                    "params": {
                        "caltable_path": "BP.B",
                        "mode": "manual",
                        "antenna": "ea05",
                        "reason": "dead ant",
                    },
                    "measurement": {"mode": "manual"},
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == [
            "ms_flag_caltable",  # external.G
            "ms_bandpass",  # BP.B (solint='inf')
            "ms_flag_caltable",  # BP.B auto (sigma=6.0)
            "ms_flag_caltable",  # BP.B manual
        ]
        assert recs[0]["params"]["caltable_path"] == "external.G"
        assert recs[1]["params"]["solint"] == "inf"
        assert recs[2]["params"]["sigma"] == 6.0
        assert recs[3]["params"]["mode"] == "manual"

    def test_scriptless_tools_never_require_or_emit_execute(self, tmp_path):
        assert reduction_log._run_supports_execute("ms_casa_tool") is False
        assert reduction_log._run_supports_execute("ms_sdm_summary") is False
        assert reduction_log._run_supports_execute("ms_gaincal") is True

        wd = tmp_path / "work"
        wd.mkdir()

        # append accepts scriptless tools without script_path and without execute=True
        reduction_log.run(
            "append",
            str(wd),
            tool="ms_sdm_summary",
            params={"asdm_path": "/data/obs.sdm"},
            rationale="inspect SDM",
        )
        reduction_log.run(
            "append",
            str(wd),
            tool="ms_casa_tool",
            params={
                "tool": "table",
                "calls": [{"method": "open", "args": {"tablename": "/data/obs.ms"}}],
                "workdir": str(wd),
            },
            rationale="copy table",
        )

        # Also test stage_log entries carrying a stray execute key
        _append_stage_entries(
            wd,
            [
                {
                    "stage": "ms_casa_tool",
                    "product": str(wd / "copy.tab"),
                    "params": {
                        "tool": "table",
                        "calls": [{"method": "open", "args": {"tablename": "/data/obs.ms"}}],
                        "workdir": str(wd),
                        "allow_write": True,
                        "execute": True,
                    },
                }
            ],
        )

        out = reduction_log.run("render", str(wd))
        recipe = out["data"]["recipe"]["value"]
        for r in recipe:
            if r["tool"] in ("ms_casa_tool", "ms_sdm_summary"):
                assert "execute" not in r["params"]

        replay_src = (wd / "reduction_replay.py").read_text()
        assert "execute=" not in replay_src


# ---------------------------------------------------------------------------
# 3. casa_task & casa_tool state safety
# ---------------------------------------------------------------------------


class TestCasaTaskAndCasaToolSafety:
    def test_casa_task_read_only_skips_stage_log_and_flagcmd_versions_backup(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(wd / "obs.ms")

        calls_made: list[tuple[str, dict]] = []
        fv_dir = wd / "obs.ms.flagversions"
        fv_dir.mkdir()

        def _fake_visstat(**kw):
            calls_made.append(("visstat", kw))
            return {"amp": {"rms": 0.01}}

        def _fake_flagmanager(**kw):
            calls_made.append(("flagmanager", kw))
            if kw.get("mode") == "save":
                (fv_dir / f"flags.{kw['versionname']}").mkdir(exist_ok=True)

        def _fake_flagcmd(**kw):
            calls_made.append(("flagcmd", kw))
            return {}

        with _fake_casatasks_module(
            visstat=_fake_visstat, flagmanager=_fake_flagmanager, flagcmd=_fake_flagcmd
        ):
            r1 = casa_task.run("visstat", {"vis": str(ms), "axis": "amp"}, str(wd), execute=True)
            r2 = casa_task.run("visstat", {"vis": str(ms), "axis": "amp"}, str(wd), execute=False)
            assert r1["data"]["script_path"]["value"] == str(wd / "casa_task_visstat.py")
            assert r2["data"]["script_path"]["value"] == str(wd / "casa_task_visstat_2.py")
            assert "_record_stage" not in (wd / "casa_task_visstat.py").read_text()
            assert read_stage_log(wd) == []

            casa_task.run("flagcmd", {"vis": str(ms), "inpmode": "list"}, str(wd), execute=True)
            casa_task.run("flagcmd", {"vis": str(ms), "inpmode": "list"}, str(wd), execute=True)

        fm_saves = [kw["versionname"] for name, kw in calls_made if name == "flagmanager"]
        assert fm_saves == ["before_ms_casa_task_flagcmd", "before_ms_casa_task_flagcmd_2"]
        entries = read_stage_log(wd)
        assert len(entries) == 2
        assert all(e["stage"] == "ms_casa_task:flagcmd" for e in entries)

    def test_casa_tool_truncates_failed_call_and_records_once(self, tmp_path, monkeypatch):
        wd = tmp_path / "work"
        wd.mkdir()
        src_ms = _make_ms(tmp_path / "src.ms")
        dest_copy = wd / "sub.copy"

        class _FakeTableTool:
            def open(self, tablename="", nomodify=True):
                return True

            def copy(self, newtablename="", deep=True, **_kw):
                Path(newtablename).mkdir(parents=True, exist_ok=True)
                return None

            def close(self):
                return True

            def done(self):
                return True

            def putcol(self, **_kw):
                raise RuntimeError("column shape mismatch")

        monkeypatch.setattr(casa_tool, "_new_instance", lambda _t: _FakeTableTool())

        # Read-only sequence records zero stage_log lines
        casa_tool.run(
            "table",
            [
                {"method": "open", "args": {"tablename": str(src_ms)}},
                {"method": "close"},
            ],
            str(wd),
            allow_write=False,
        )
        assert read_stage_log(wd) == []

        # Mutating sequence that fails at index 4 records exactly ONE line with truncated calls
        res = casa_tool.run(
            "table",
            [
                {"method": "open", "args": {"tablename": str(src_ms)}},
                {"method": "copy", "args": {"newtablename": str(dest_copy)}},
                {"method": "close"},
                {"method": "open", "args": {"tablename": str(dest_copy), "nomodify": False}},
                {"method": "putcol", "args": {"columnname": "DATA", "value": [1]}},
            ],
            str(wd),
            allow_write=True,
        )
        assert res["data"]["failed_call"]["index"] == 4
        entries = read_stage_log(wd)
        assert len(entries) == 1
        assert entries[0]["stage"] == "ms_casa_tool"
        assert len(entries[0]["params"]["calls"]) == 4
        assert all(c["method"] != "putcol" for c in entries[0]["params"]["calls"])


# ---------------------------------------------------------------------------
# 4. Flag backups, script collision guards, and applycal flagbackup=True
# ---------------------------------------------------------------------------


class TestFlagBackupsScriptCollisionsAndApplycal:
    def test_initial_rflag_rflag_postcal_flag_version_backups(self, tmp_path, monkeypatch):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(tmp_path / "cal.ms")
        fv_dir = tmp_path / "cal.ms.flagversions"
        fv_dir.mkdir()

        @contextmanager
        def _fake_tb(_p, **_k):
            class _T:
                def colnames(self):
                    return ["DATA", "MODEL_DATA", "CORRECTED_DATA"]

            yield _T()

        monkeypatch.setattr(initial_rflag, "open_table", _fake_tb)

        saved_versions: list[str] = []

        def _fake_fm(**kw):
            if kw.get("mode") == "save":
                ver = kw["versionname"]
                saved_versions.append(ver)
                (fv_dir / f"flags.{ver}").mkdir(exist_ok=True)

        def _fake_fd(**kw):
            if kw.get("mode") == "summary":
                return {"flagged": 10, "total": 100}
            return {}

        with _fake_casatasks_module(flagmanager=_fake_fm, flagdata=_fake_fd):
            # initial_rflag keeps initial_rflag.py unchanged, increments flag version
            ir1 = initial_rflag.run(str(ms), str(wd), field="3C147", execute=True)
            ir2 = initial_rflag.run(str(ms), str(wd), field="3C147", execute=True)
            assert ir1["data"]["script_path"]["value"] == str(wd / "initial_rflag.py")
            assert ir2["data"]["script_path"]["value"] == str(wd / "initial_rflag.py")
            ir_src = (wd / "initial_rflag.py").read_text()
            assert "flagmanager" in ir_src and "before_initial_rflag" in ir_src

            # rflag increments both script_path and flag version
            rf1 = rflag.run(str(ms), str(wd), field="3C147", execute=True)
            rf2 = rflag.run(str(ms), str(wd), field="3C147", execute=True)
            assert rf1["data"]["script_path"]["value"] == str(wd / "apply_rflag.py")
            assert rf2["data"]["script_path"]["value"] == str(wd / "apply_rflag_2.py")

            # postcal_flag increments both script_path and flag version
            pf1 = postcal_flag.run(str(ms), str(wd), field="3C147", execute=True)
            pf2 = postcal_flag.run(str(ms), str(wd), field="3C147", execute=True)
            assert pf1["data"]["script_path"]["value"] == str(wd / "postcal_flag.py")
            assert pf2["data"]["script_path"]["value"] == str(wd / "postcal_flag_2.py")
            pf_src = (wd / "postcal_flag.py").read_text()
            assert "flagmanager" in pf_src and "before_postcal_flag" in pf_src

        assert saved_versions == [
            "before_initial_rflag",
            "before_initial_rflag_2",
            "before_rflag",
            "before_rflag_2",
            "before_postcal_flag",
            "before_postcal_flag_2",
        ]

    def test_flag_data_flag_caltable_setjy_polcal_script_collision_guards(
        self, tmp_path, monkeypatch
    ):
        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(tmp_path / "obs.ms")
        ct = _make_caltable(tmp_path / "BP.B")

        d1 = flag_data.run(str(ms), str(wd), reason="bad ant", antenna="ea02")
        d2 = flag_data.run(str(ms), str(wd), reason="bad scan", scan="5")
        assert d1["data"]["script_path"]["value"] == str(wd / "flag_data.py")
        assert d2["data"]["script_path"]["value"] == str(wd / "flag_data_2.py")

        monkeypatch.setattr(flag_caltable, "_read_viscal_type", lambda _p: "B")
        monkeypatch.setattr(
            flag_caltable,
            "_read_intervals",
            lambda _p: {"min": 10, "median": 10.0, "max": 10, "n_groups": 1},
        )
        fc1 = flag_caltable.run(str(ct), str(wd))
        fc2 = flag_caltable.run(str(ct), str(wd))
        assert fc1["data"]["script_path"]["value"] == str(wd / "flag_caltable.py")
        assert fc2["data"]["script_path"]["value"] == str(wd / "flag_caltable_2.py")

        monkeypatch.setattr(setjy_polcal, "_read_band_range_ghz", lambda _p: (4.5, 6.5))
        monkeypatch.setattr(setjy_polcal, "_read_obs_year", lambda _p: 2019.5)
        sp1 = setjy_polcal.run(str(ms), "3C286", str(wd))
        sp2 = setjy_polcal.run(str(ms), "3C286", str(wd))
        assert sp1["data"]["script_path"]["value"] == str(wd / "setjy_polcal.py")
        assert sp2["data"]["script_path"]["value"] == str(wd / "setjy_polcal_2.py")

    def test_applycal_flagbackup_default_true_script_collision_and_skill_doc(
        self, tmp_path, monkeypatch
    ):
        assert server.ApplycalInput.model_fields["flagbackup"].default is True

        wd = tmp_path / "work"
        wd.mkdir()
        ms = _make_ms(tmp_path / "target.ms")
        gt = _make_caltable(wd / "gain.G")

        @contextmanager
        def _fake_tb(_p, **_k):
            class _T:
                def colnames(self):
                    return ["DATA", "CORRECTED_DATA"]

            yield _T()

        monkeypatch.setattr(applycal, "open_table", _fake_tb)
        monkeypatch.setattr(applycal, "describe_numeric_fields", lambda *_a: [])
        monkeypatch.setattr(applycal, "pol_types", lambda _g: [])

        apply_kwargs_seen: list[dict] = []
        with _fake_casatasks_module(applycal=lambda **kw: apply_kwargs_seen.append(kw)):
            a1 = applycal.run(str(ms), "TARGET", [str(gt)], str(wd), execute=True)
            a2 = applycal.run(str(ms), "TARGET", [str(gt)], str(wd), execute=False)

        assert a1["data"]["flagbackup"] is True
        assert apply_kwargs_seen[0]["flagbackup"] is True
        assert a1["data"]["script_path"]["value"] == str(wd / "applycal_target_TARGET.py")
        assert a2["data"]["script_path"]["value"] == str(wd / "applycal_target_TARGET_2.py")

        skill_doc = (
            Path(__file__).resolve().parents[2]
            / ".claude/skills/radio-interferometry/07-calibration-execution.md"
        ).read_text()
        sec_7b = skill_doc.split("### 7b")[1].split("### 7c")[0]
        sec_7c = skill_doc.split("### 7c")[1].split("## Post-applycal")[0]
        assert "flagbackup = False" in sec_7b
        assert "flagbackup = True" in sec_7c


# ---------------------------------------------------------------------------
# 5. Preflag idempotency & workflow_status missing calibrators.ms
# ---------------------------------------------------------------------------


class TestPreflagAndWorkflowStatus:
    def test_preflag_script_imports_debug_inject_and_ast_order(self, tmp_path):
        ms = _make_ms(tmp_path / "obs.ms")
        wd = tmp_path / "work"
        wd.mkdir()

        res = preflag.run(str(ms), str(wd), cal_fields="3C286")
        script = Path(res["data"]["script_path"]["value"]).read_text()
        first_import = next(
            ln for ln in script.splitlines() if ln.startswith("from casatasks import ")
        )
        assert first_import == "from casatasks import flagdata, flagmanager, split"
        assert "flagbackup=False" in script

        injected = debug_mode.inject(script, {"flagdata": {"timecutoff": 4.0}})
        compile(injected, "<preflag_debug>", "exec")

        tree = ast.parse(script)
        rec_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_record_stage"
        ]
        assert [len(c.args) for c in rec_calls] == [4, 3]

    def test_preflag_execute_split_failure_leaves_clean_stage_log_and_retry_restores_and_archives(
        self, tmp_path
    ):
        ms = _make_ms(tmp_path / "obs.ms")
        fv_dir = tmp_path / "obs.ms.flagversions"
        wd = tmp_path / "work"
        wd.mkdir()

        events: list[tuple[str, dict]] = []
        fail_split = True

        def _fake_fm(**kw):
            events.append(("flagmanager", kw))
            if kw.get("mode") == "save":
                fv_dir.mkdir(exist_ok=True)
                (fv_dir / f"flags.{kw['versionname']}").mkdir(exist_ok=True)

        def _fake_fd(**kw):
            events.append(("flagdata", kw))
            if kw.get("mode") == "summary":
                return {"flagged": 25, "total": 100}
            return {}

        def _fake_split(**kw):
            events.append(("split", kw))
            if fail_split:
                raise RuntimeError("bad field selection")
            _make_ms(Path(kw["outputvis"]))

        with _fake_casatasks_module(flagdata=_fake_fd, flagmanager=_fake_fm, split=_fake_split):
            # Attempt 1: split fails -> zero stage_log lines recorded!
            with pytest.raises(ComputationError, match="split to calibrators.ms failed"):
                preflag.run(str(ms), str(wd), cal_fields="BAD", execute=True)
            assert read_stage_log(wd) == []

            # Simulate a stale partial calibrators.ms left behind on disk before retry
            stale = _make_ms(wd / "calibrators.ms")
            (stale / "marker.txt").write_text("attempt1")

            # Attempt 2: restores before_preflag, archives stale calibrators.ms, records 2 lines
            fail_split = False
            events.clear()
            out = preflag.run(str(ms), str(wd), cal_fields="3C286", execute=True)

        assert out["status"] == "ok"
        assert events[0][0] == "flagmanager" and events[0][1]["mode"] == "restore"
        assert events[0][1]["versionname"] == "before_preflag"
        assert events[1][0] == "flagdata" and events[1][1]["flagbackup"] is False
        assert (wd / "calibrators.ms.attempt1" / "marker.txt").read_text() == "attempt1"
        assert (wd / "calibrators.ms" / "table.info").is_file()
        stage_lines = read_stage_log(wd)
        assert len(stage_lines) == 2
        assert [e["product"] for e in stage_lines] == [str(ms), str(wd / "calibrators.ms")]

    def test_archive_cal_ms_refuses_unsafe_paths(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        src_ms = _make_ms(wd / "calibrators.ms")
        # Equal to src_ms
        with pytest.raises(RuntimeError, match="Refusing to archive"):
            preflag._archive_cal_ms(str(src_ms), str(src_ms), str(wd))
        # Wrong basename
        other = _make_ms(wd / "other.ms")
        with pytest.raises(RuntimeError, match="Refusing to archive"):
            preflag._archive_cal_ms(str(other), str(tmp_path / "raw.ms"), str(wd))
        # Outside workdir
        outside = _make_ms(tmp_path / "calibrators.ms")
        with pytest.raises(RuntimeError, match="Refusing to archive"):
            preflag._archive_cal_ms(str(outside), str(tmp_path / "raw.ms"), str(wd))

    def test_workflow_status_reruns_preflag_when_calibrators_ms_missing_before_priorcals(
        self, tmp_path, monkeypatch
    ):
        ms = _make_ms(tmp_path / "obs.ms")
        (ms / "STATE").mkdir()
        wd = tmp_path / "work"
        wd.mkdir()

        class _FakeTb:
            def nrows(self):
                return 2

            def colnames(self):
                return ["DATA"]

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(workflow_status, "open_table", lambda *_a, **_k: _FakeTb())
        _append_stage_entries(
            wd,
            [
                {"stage": "set_intents", "product": str(ms)},
                {"stage": "preflag", "product": str(ms), "measurement": {"flagged_fraction": 0.1}},
            ],
        )

        res = workflow_status.run(str(ms), str(wd))
        assert res["data"]["next_recommended_step"] == "apply_preflag"
        assert any(
            "preflag is recorded complete in the stage log, but calibrators.ms is not present" in w
            for w in res["warnings"]
        )


# ---------------------------------------------------------------------------
# 6. Audit hook window isolation & OpenCode transcript support
# ---------------------------------------------------------------------------


class TestAuditHookIsolationAndOpenCode:
    def test_workdir_regex_and_stage_slug_validation(self):
        for sample in (
            "Run inspect with workdir=/var/mnt/fast/w1",
            '{"workdir": "/var/mnt/fast/w1", "ms_path": "x"}',
            "workdir = '/var/mnt/fast/w1'",
        ):
            m = audit_hook._WORKDIR_ARG_RE.search(sample)
            assert m is not None and m.group(1) == "/var/mnt/fast/w1"

        assert audit_hook._stage_from_subagent_type("radio-analyst:calibrate-stage") == "calibrate"
        assert audit_hook._stage_from_subagent_type("image-stage") == "image"
        for non_stage in ("self", "research", "Explore", "diagnostic-scientist", "foo-stage", ""):
            assert audit_hook._stage_from_subagent_type(non_stage) is None

    def test_claude_code_non_stage_subagents_never_steal_checks_and_aux_runs_recorded(
        self, tmp_path
    ):
        wd = tmp_path / "work"
        wd.mkdir()
        transcript = tmp_path / "cc_session.jsonl"

        events = [
            # Unconsumed precal window: must NOT be stolen by calibrate decision
            {
                "type": "assistant",
                "message": {
                    "id": "m0",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_precal",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "radio-analyst:precal-stage",
                                "prompt": f"precal workdir={wd}",
                            },
                        }
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_precal",
                            "content": "PRECAL_HANDOFF",
                        }
                    ]
                },
            },
            # Primary image-stage run 1
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_img1",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "radio-analyst:image-stage",
                                "prompt": f"image pass 1 workdir={wd}",
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "tu_chk1",
                            "name": "mcp__ms-inspect__ms_image_stats",
                            "input": {"imagename": "t.image", "workdir": str(wd)},
                        },
                        # Interleaved non-stage Explore subagent: must NOT push a window!
                        {
                            "type": "tool_use",
                            "id": "tu_explore",
                            "name": "Agent",
                            "input": {"subagent_type": "Explore", "prompt": "check skill docs"},
                        },
                        {
                            "type": "tool_use",
                            "id": "tu_read1",
                            "name": "Read",
                            "input": {"file_path": str(wd / "residual.png")},
                        },
                        # Second image-stage run before stage_decision -> aux_runs
                        {
                            "type": "tool_use",
                            "id": "tu_img2",
                            "name": "Task",
                            "input": {
                                "subagent_type": "image-stage",
                                "prompt": f"image pass 2 mtmfs workdir={wd}",
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "tu_chk2",
                            "name": "mcp__ms-inspect__ms_image_stats",
                            "input": {"imagename": "t.image.tt0", "workdir": str(wd)},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "toolUseResult": {"agentId": "ag_img1", "usage": {"total_tokens": 100}},
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_img1",
                            "content": "IMG_HANDOFF_1",
                        },
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_chk1",
                            "content": json.dumps({"rms": 1e-4}),
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_explore",
                            "content": "DOC_NOTES",
                        },
                        {"type": "tool_result", "tool_use_id": "tu_read1", "content": "PNG"},
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_img2",
                            "content": "IMG_HANDOFF_2\nagentId: ag_img2",
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_chk2",
                            "content": json.dumps({"rms": 5e-5}),
                        },
                    ]
                },
            },
            # Decision 1: stage "calibrate" has NO calibrate-stage window -> must NOT steal precal!
            # Decision 2: stage "image_selfcal" must NOT prefix-match image-stage!
            # Decision 3: stage "image_iquv" matches both image-stage windows -> primary + aux_runs!
            {
                "type": "assistant",
                "message": {
                    "id": "m2",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '<stage_decision>{"stage": "calibrate", "decision": "proceed", '
                                '"reason": "pre-done"}</stage_decision>\n'
                                '<stage_decision>{"stage": "image_selfcal", "decision": "skip", '
                                '"reason": "no prefix match"}</stage_decision>\n'
                                '<stage_decision>{"stage": "image_iquv", "decision": "accept", '
                                '"reason": "clean image"}</stage_decision>'
                            ),
                        }
                    ],
                },
            },
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        written = audit_hook.build_audit_records_from_transcript(transcript)
        assert len(written) == 3

        cal_rec = json.loads((wd / "orchestrator/01_calibrate_try1.json").read_text())
        assert cal_rec["prompt"] == ""
        assert cal_rec["handoff"] == ""
        assert cal_rec["checks"] == []

        sc_rec = json.loads((wd / "orchestrator/02_image_selfcal_try1.json").read_text())
        assert sc_rec["prompt"] == ""
        assert sc_rec["handoff"] == ""

        img_rec = json.loads((wd / "orchestrator/03_image_iquv_try1.json").read_text())
        assert img_rec["prompt"] == f"image pass 1 workdir={wd}"
        assert img_rec["handoff"] == "IMG_HANDOFF_1"
        assert [c["tool_args"]["imagename"] for c in img_rec["checks"]] == [
            "t.image",
            "t.image.tt0",
        ]
        assert img_rec["png_reviewed"] == f"viewed: {wd / 'residual.png'}"
        assert len(img_rec["aux_runs"]) == 1
        assert img_rec["aux_runs"][0]["handoff"].startswith("IMG_HANDOFF_2")
        assert img_rec["aux_runs"][0]["agent_id"] == "ag_img2"

    def test_opencode_export_json_transcript(self, tmp_path):
        wd = tmp_path / "work_oc1"
        wd.mkdir()
        export_file = tmp_path / "opencode_export.json"

        doc = {
            "info": {"id": "ses_1"},
            "messages": [
                {
                    "info": {"id": "msg_1", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_task_1",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "calibrate-stage",
                                    "prompt": f'{{"workdir": "{wd}"}}',
                                },
                                "output": "CALIBRATE HANDOFF",
                                "metadata": {"sessionId": "ses_cal_1"},
                            },
                        },
                        {
                            "type": "tool",
                            "callID": "call_research",
                            "tool": "task",
                            "state": {
                                "input": {"subagent_type": "research", "prompt": "check notes"},
                                "output": "notes",
                                "metadata": {},
                            },
                        },
                        {
                            "type": "tool",
                            "callID": "call_stats",
                            "tool": "ms-inspect_ms_calsol_stats",
                            "state": {
                                "input": {"caltable": str(wd / "BP.B"), "workdir": str(wd)},
                                "output": json.dumps({"flagged_frac": 0.02}),
                                "metadata": {},
                            },
                        },
                        {
                            "type": "tool",
                            "callID": "call_read",
                            "tool": "read",
                            "state": {
                                "input": {"filePath": str(wd / "bp_plot.png")},
                                "output": "binary png",
                                "metadata": {},
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                '<stage_decision>{"stage": "calibrate", "decision": "proceed", '
                                '"deciding_metric": "flagged_frac=0.02", "reason": "good"}'
                                "</stage_decision>"
                            ),
                        },
                    ],
                }
            ],
        }
        export_file.write_text(json.dumps(doc, indent=2))

        written = audit_hook.build_audit_records_from_transcript(export_file)
        assert len(written) == 1
        rec = json.loads(written[0].read_text())
        assert rec["stage"] == "calibrate"
        assert rec["handoff"] == "CALIBRATE HANDOFF"
        assert rec["agent_id"] == "ses_cal_1"
        assert len(rec["checks"]) == 1
        assert rec["checks"][0]["tool"] == "ms_calsol_stats"
        assert rec["checks"][0]["output"] == {"flagged_frac": 0.02}
        assert rec["png_reviewed"] == f"viewed: {wd / 'bp_plot.png'}"

    def test_opencode_run_format_json_jsonl_transcript(self, tmp_path):
        wd = tmp_path / "work_oc2"
        wd.mkdir()
        jsonl_file = tmp_path / "opencode_run.jsonl"

        lines = [
            {
                "type": "tool_use",
                "part": {
                    "callID": "c1",
                    "tool": "task",
                    "state": {
                        "input": {
                            "subagent_type": "inspect-stage",
                            "prompt": f"inspect workdir='{wd}'",
                        },
                        "output": "INSPECT HANDOFF",
                        "metadata": {"sessionId": "ses_insp_1"},
                    },
                },
            },
            {
                "type": "tool_use",
                "part": {
                    "callID": "c2",
                    "tool": "ms-inspect_ms_field_list",
                    "state": {
                        "input": {"ms_path": "/data/obs.ms", "workdir": str(wd)},
                        "output": json.dumps({"n_fields": 4}),
                        "metadata": {},
                    },
                },
            },
            {
                "type": "text",
                "part": {
                    "id": "txt_1",
                    "text": (
                        '<stage_decision>{"stage": "inspect", "decision": "proceed", '
                        '"reason": "intents verified"}</stage_decision>'
                    ),
                },
            },
        ]
        jsonl_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

        written = audit_hook.build_audit_records_from_transcript(jsonl_file)
        assert len(written) == 1
        rec = json.loads(written[0].read_text())
        assert rec["stage"] == "inspect"
        assert rec["handoff"] == "INSPECT HANDOFF"
        assert rec["agent_id"] == "ses_insp_1"
        assert len(rec["checks"]) == 1
        assert rec["checks"][0]["tool"] == "ms_field_list"
        assert rec["checks"][0]["output"] == {"n_fields": 4}

    def test_opencode_same_turn_stage_decision_with_tool_calls_via_audit_hook_sh(self, tmp_path):
        """<stage_decision> emitted in the SAME assistant turn as next/retry task() or ms_report."""
        import os
        import subprocess
        import sys

        wd = tmp_path / "work_same_turn"
        wd.mkdir()
        export_file = tmp_path / "session.json"

        doc = {
            "info": {"id": "ses_root"},
            "messages": [
                {
                    "info": {"id": "msg_1", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_precal_1",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "precal-stage",
                                    "prompt": f"/data/3c391.ms workdir={wd}",
                                },
                                "output": "STAGE HANDOFF: precal\nstatus: completed",
                                "metadata": {"sessionId": "ses_precal_1"},
                            },
                        }
                    ],
                },
                {
                    "info": {"id": "msg_2", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_wf_1",
                            "tool": "ms-inspect_ms_workflow_status",
                            "state": {
                                "input": {"ms_path": "/data/3c391.ms", "workdir": str(wd)},
                                "output": json.dumps(
                                    {"next_recommended_step": "delay_bandpass_gain"}
                                ),
                                "metadata": {},
                            },
                        }
                    ],
                },
                {
                    # Same assistant turn: <stage_decision> (decision=next) + task(calibrate-stage)
                    "info": {"id": "msg_3", "role": "assistant"},
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                "<stage_decision>"
                                + json.dumps(
                                    {
                                        "seq": 1,
                                        "stage": "precal",
                                        "try": 1,
                                        "workdir": str(wd),
                                        "decision": "next",
                                        "deciding_metric": "ms_workflow_status.next_recommended_step = delay_bandpass_gain",
                                        "reason": "Precal verified; launching calibrate-stage.",
                                        "debug_directive": None,
                                        "png_reviewed": None,
                                    }
                                )
                                + "</stage_decision>"
                            ),
                        },
                        {
                            "type": "tool",
                            "callID": "call_cal_1",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "calibrate-stage",
                                    "prompt": f"/data/3c391.ms workdir={wd}",
                                },
                                "output": "STAGE HANDOFF: calibrate try 1",
                                "metadata": {"sessionId": "ses_cal_1"},
                            },
                        },
                    ],
                },
                {
                    "info": {"id": "msg_4", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_calsol_1",
                            "tool": "ms-inspect_ms_calsol_stats",
                            "state": {
                                "input": {"caltable": str(wd / "gain.G"), "workdir": str(wd)},
                                "output": json.dumps({"flagged_frac": 0.42}),
                                "metadata": {},
                            },
                        }
                    ],
                },
                {
                    # Same assistant turn: <stage_decision> (decision=retry) + task(calibrate-stage retry)
                    "info": {"id": "msg_5", "role": "assistant"},
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                "<stage_decision>"
                                + json.dumps(
                                    {
                                        "seq": 2,
                                        "stage": "calibrate",
                                        "try": 1,
                                        "workdir": str(wd),
                                        "decision": "retry",
                                        "deciding_metric": "ms_calsol_stats.flagged_frac = 0.42",
                                        "reason": "Too many flagged gain solutions; retrying with longer solint.",
                                        "debug_directive": None,
                                        "png_reviewed": None,
                                    }
                                )
                                + "</stage_decision>"
                            ),
                        },
                        {
                            "type": "tool",
                            "callID": "call_cal_2",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "calibrate-stage",
                                    "prompt": f"/data/3c391.ms workdir={wd}\nretry: 2 of 5",
                                },
                                "output": "STAGE HANDOFF: calibrate try 2",
                                "metadata": {"sessionId": "ses_cal_2"},
                            },
                        },
                    ],
                },
                {
                    "info": {"id": "msg_6", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_calsol_2",
                            "tool": "ms-inspect_ms_calsol_stats",
                            "state": {
                                "input": {"caltable": str(wd / "gain.G"), "workdir": str(wd)},
                                "output": json.dumps({"flagged_frac": 0.04}),
                                "metadata": {},
                            },
                        }
                    ],
                },
                {
                    # Same assistant turn: <stage_decision> (decision=next) + ms_report
                    "info": {"id": "msg_7", "role": "assistant"},
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                "<stage_decision>"
                                + json.dumps(
                                    {
                                        "seq": 3,
                                        "stage": "calibrate",
                                        "try": 2,
                                        "workdir": str(wd),
                                        "decision": "next",
                                        "deciding_metric": "ms_calsol_stats.flagged_frac = 0.04",
                                        "reason": "Calibration passed on retry 2.",
                                        "debug_directive": None,
                                        "png_reviewed": None,
                                    }
                                )
                                + "</stage_decision>"
                            ),
                        },
                        {
                            "type": "tool",
                            "callID": "call_report_1",
                            "tool": "ms-create_ms_report",
                            "state": {
                                "input": {"workdir": str(wd)},
                                "output": json.dumps({"report_path": str(wd / "report.html")}),
                                "metadata": {},
                            },
                        },
                    ],
                },
            ],
        }
        export_file.write_text(json.dumps(doc, indent=2))

        # Execute scripts/plugin/audit_hook.sh end-to-end as OpenCode / Claude Code hooks do.
        repo_root = Path(__file__).resolve().parents[2]
        hook_script = repo_root / "scripts" / "plugin" / "audit_hook.sh"
        plugin_data = tmp_path / "plugin_data"
        plugin_data.mkdir()
        py_prefix = Path(sys.executable).resolve().parent.parent
        (plugin_data / "env.prefix").write_text(str(py_prefix) + "\n")

        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(plugin_data)
        proc = subprocess.run(
            ["bash", str(hook_script)],
            input=json.dumps({"transcript_path": str(export_file), "cwd": str(wd)}),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

        orch_dir = wd / "orchestrator"
        names = sorted(p.name for p in orch_dir.glob("*.json"))
        assert names == [
            "01_precal_try1.json",
            "02_calibrate_try1.json",
            "03_calibrate_try2.json",
        ]

        r1 = json.loads((orch_dir / "01_precal_try1.json").read_text())
        assert r1["stage"] == "precal"
        assert r1["decision"] == "next"
        assert r1["agent_id"] == "ses_precal_1"
        assert r1["handoff"] == "STAGE HANDOFF: precal\nstatus: completed"
        assert [c["tool"] for c in r1["checks"]] == ["ms_workflow_status"]

        r2 = json.loads((orch_dir / "02_calibrate_try1.json").read_text())
        assert r2["stage"] == "calibrate"
        assert r2["attempt"] == 1
        assert r2["decision"] == "retry"
        assert r2["agent_id"] == "ses_cal_1"
        assert r2["handoff"] == "STAGE HANDOFF: calibrate try 1"
        assert len(r2["checks"]) == 1
        assert r2["checks"][0]["output"] == {"flagged_frac": 0.42}

        r3 = json.loads((orch_dir / "03_calibrate_try2.json").read_text())
        assert r3["stage"] == "calibrate"
        assert r3["attempt"] == 2
        assert r3["decision"] == "next"
        assert r3["agent_id"] == "ses_cal_2"
        assert r3["handoff"] == "STAGE HANDOFF: calibrate try 2"
        assert [c["tool"] for c in r3["checks"]] == ["ms_calsol_stats"]
        assert r3["checks"][0]["output"] == {"flagged_frac": 0.04}

    def test_opencode_run_jsonl_same_turn_stage_decision_with_next_stage_call(self, tmp_path):
        """opencode run --format json step with <stage_decision> text + task() tool_use."""
        wd = tmp_path / "work_oc_jsonl_same"
        wd.mkdir()
        jsonl_file = tmp_path / "trace.jsonl"

        lines = [
            {
                "type": "tool_use",
                "part": {
                    "callID": "c_precal",
                    "tool": "task",
                    "state": {
                        "input": {
                            "subagent_type": "precal-stage",
                            "prompt": f"/data/3c391.ms workdir={wd}",
                        },
                        "output": "PRECAL HANDOFF",
                        "metadata": {"sessionId": "ses_p1"},
                    },
                },
            },
            {
                "type": "tool_use",
                "part": {
                    "callID": "c_wf",
                    "tool": "ms-inspect_ms_workflow_status",
                    "state": {
                        "input": {"ms_path": "/data/3c391.ms", "workdir": str(wd)},
                        "output": json.dumps({"next_recommended_step": "delay_bandpass_gain"}),
                        "metadata": {},
                    },
                },
            },
            # Single step: text <stage_decision> + immediate task(calibrate-stage) -> tool-calls
            {"type": "step_start", "part": {"id": "s_next"}},
            {
                "type": "text",
                "part": {
                    "id": "txt_precal_dec",
                    "text": (
                        '<stage_decision>{"seq": 1, "stage": "precal", "try": 1, '
                        f'"workdir": "{wd}", "decision": "next", '
                        '"reason": "precal verified"}</stage_decision>'
                    ),
                },
            },
            {
                "type": "tool_use",
                "part": {
                    "callID": "c_cal",
                    "tool": "task",
                    "state": {
                        "input": {
                            "subagent_type": "calibrate-stage",
                            "prompt": f"/data/3c391.ms workdir={wd}",
                        },
                        "output": "CALIBRATE HANDOFF",
                        "metadata": {"sessionId": "ses_c1"},
                    },
                },
            },
            {"type": "step_finish", "part": {"reason": "tool-calls"}},
            {
                "type": "text",
                "part": {
                    "id": "txt_cal_dec",
                    "text": (
                        '<stage_decision>{"seq": 2, "stage": "calibrate", "try": 1, '
                        f'"workdir": "{wd}", "decision": "next", '
                        '"reason": "calibrate verified"}</stage_decision>'
                    ),
                },
            },
        ]
        jsonl_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

        written = audit_hook.build_audit_records_from_transcript(jsonl_file)
        assert [p.name for p in written] == ["01_precal_try1.json", "02_calibrate_try1.json"]
        r1 = json.loads(written[0].read_text())
        r2 = json.loads(written[1].read_text())
        assert r1["handoff"] == "PRECAL HANDOFF"
        assert [c["tool"] for c in r1["checks"]] == ["ms_workflow_status"]
        assert r2["handoff"] == "CALIBRATE HANDOFF"
        assert r2["checks"] == []


# ---------------------------------------------------------------------------
# 7. Adversary regression suite (Areas 1, 2, 5)
# ---------------------------------------------------------------------------


class TestAdversaryRegressions:
    def test_set_intents_relative_and_tilde_paths_outside_workdir_deduplicate(
        self, tmp_path, monkeypatch
    ):
        ms = _make_ms(tmp_path / "obs.ms")
        (ms / "STATE").mkdir()
        wd = tmp_path / "work"
        wd.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

        class _FakeMsmd:
            def fieldnames(self):
                return ["3C286", "TARGET"]

            def phasecenter(self, fid):
                return {"m0": {"value": 0.5 + fid * 0.1}, "m1": {"value": 0.2}}

            def intentsforfield(self, _fid):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        class _FakeSpwTb:
            def getcell(self, _col, _row):
                return [1.4e9, 1.5e9]

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(intents, "open_msmd", lambda _p: _FakeMsmd())
        monkeypatch.setattr(intents, "open_table", lambda _p, **_k: _FakeSpwTb())
        monkeypatch.setattr(intents, "vla_cone_search", lambda *_a, **_k: None)

        res = intents.set_intents("~/obs.ms", execute=False, workdir="work")
        script_file = Path(res["data"]["script_path"])
        script_text = script_file.read_text()
        assert f"ms_path = {str(ms.resolve())!r}" in script_text
        assert "~/obs.ms" not in script_text

        # Even if a legacy script recorded relative 'obs.ms' outside wd and a retry
        # recorded absolute str(ms.resolve()), load_effective_records deduplicates them.
        _append_stage_entries(
            wd,
            [
                {
                    "stage": "set_intents",
                    "product": "obs.ms",
                    "script_path": str(script_file),
                    "script_sha256": "deadbeef",
                },
                {
                    "stage": "set_intents",
                    "product": str(ms.resolve()),
                    "params": {
                        "ms_path": str(ms.resolve()),
                        "workdir": str(wd.resolve()),
                        "pol_leakage_fields": ["J1822-0938"],
                    },
                },
            ],
        )
        recs = reduction_log.load_effective_records(wd)
        assert len(recs) == 1
        assert recs[0]["tool"] == "ms_set_intents"
        assert recs[0]["params"]["pol_leakage_fields"] == ["J1822-0938"]

    def test_skill_13_two_pass_retains_upstream_g0_gain_and_flag_caltable(self, tmp_path):
        def _round_entries(cal_ms: Path, wd: Path, solint_g: str) -> list[dict[str, Any]]:
            return [
                {
                    "stage": "gaincal",
                    "product": str(wd / "init_phase.G0"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "init_phase.G0"),
                        "calmode": "p",
                        "solint": "int",
                    },
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "init_phase.G0"),
                    "params": {"caltable_path": str(wd / "init_phase.G0"), "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                {
                    "stage": "gaincal",
                    "product": str(wd / "delay.K"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "delay.K"),
                        "gaintype": "K",
                        "gaintable": [str(wd / "init_phase.G0")],
                    },
                },
                {
                    "stage": "bandpass",
                    "product": str(wd / "BP.B"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "BP.B"),
                        "gaintable": [str(wd / "init_phase.G0"), str(wd / "delay.K")],
                    },
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP.B"),
                    "params": {"caltable_path": str(wd / "BP.B"), "mode": None},
                    "measurement": {"mode": "tfcrop"},
                },
                {
                    "stage": "gaincal",
                    "product": str(wd / "gain.G"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "gain.G"),
                        "solint": solint_g,
                        "gaintable": [str(wd / "delay.K"), str(wd / "BP.B")],
                    },
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "gain.G"),
                    "params": {"caltable_path": str(wd / "gain.G"), "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                {
                    "stage": "fluxscale",
                    "product": str(wd / "flux.G"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "gain.G"),
                        "fluxtable": str(wd / "flux.G"),
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "field": "3C286",
                        "gaintable": [
                            str(wd / "delay.K"),
                            str(wd / "BP.B"),
                            str(wd / "flux.G"),
                        ],
                    },
                },
            ]

        # Case A: Genuine Skill 13 two-pass with postcal_flag between Round 1 and Round 2
        wd_two = tmp_path / "skill13_two_pass"
        wd_two.mkdir()
        cal_two = _make_ms(wd_two / "calibrators.ms")
        _append_stage_entries(
            wd_two,
            [
                *_round_entries(cal_two, wd_two, "60s"),
                {
                    "stage": "postcal_flag",
                    "product": str(cal_two),
                    "params": {
                        "ms_path": str(cal_two),
                        "field": "3C286",
                        "datacolumn": "residual",
                    },
                },
                *_round_entries(cal_two, wd_two, "inf"),
            ],
        )
        recs_two = reduction_log.load_effective_records(wd_two)
        # 9 steps in Round 1 + 1 postcal_flag + 9 steps in Round 2 = 19 steps!
        assert len(recs_two) == 19
        assert recs_two[0]["outputs"]["product"] == str(wd_two / "init_phase.G0")
        assert recs_two[1]["tool"] == "ms_flag_caltable"
        assert recs_two[5]["outputs"]["product"] == str(wd_two / "gain.G")
        assert recs_two[5]["params"]["solint"] == "60s"
        assert recs_two[6]["tool"] == "ms_flag_caltable"
        assert recs_two[9]["tool"] == "ms_postcal_flag"
        assert recs_two[15]["params"]["solint"] == "inf"

        # Case B: Pure retry WITHOUT postcal_flag drops Round 1 completely (only 9 steps survive)
        wd_retry = tmp_path / "skill13_retry_only"
        wd_retry.mkdir()
        cal_retry = _make_ms(wd_retry / "calibrators.ms")
        _append_stage_entries(
            wd_retry,
            [
                *_round_entries(cal_retry, wd_retry, "60s"),
                *_round_entries(cal_retry, wd_retry, "inf"),
            ],
        )
        recs_retry = reduction_log.load_effective_records(wd_retry)
        assert len(recs_retry) == 9
        gain_steps = [
            r
            for r in recs_retry
            if r["tool"] == "ms_gaincal" and r["outputs"].get("product") == str(wd_retry / "gain.G")
        ]
        assert len(gain_steps) == 1 and gain_steps[0]["params"]["solint"] == "inf"

    def test_stokes_iquv_retains_7a_7b_7c_and_5a_5b_while_dropping_7c_retry(self, tmp_path):
        wd = tmp_path / "iquv_work"
        wd.mkdir()
        full_ms = _make_ms(tmp_path / "full.ms")
        cal_ms = _make_ms(wd / "calibrators.ms")

        stokes_i_tables = [str(wd / "delay.K"), str(wd / "BP.B"), str(wd / "flux.G")]
        iquv_tables = [*stokes_i_tables, str(wd / "kcross.K"), str(wd / "Df.D"), str(wd / "Xf.X")]

        _append_stage_entries(
            wd,
            [
                {
                    "stage": "gaincal",
                    "product": str(wd / "delay.K"),
                    "params": {"ms_path": str(cal_ms), "caltable": str(wd / "delay.K")},
                },
                {
                    "stage": "bandpass",
                    "product": str(wd / "BP.B"),
                    "params": {"ms_path": str(cal_ms), "caltable": str(wd / "BP.B")},
                },
                {
                    "stage": "fluxscale",
                    "product": str(wd / "flux.G"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "gain.G"),
                        "fluxtable": str(wd / "flux.G"),
                    },
                },
                # 7a + 7b on calibrators.ms
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "field": "3C286",
                        "gaintable": stokes_i_tables,
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "field": "J1822-0938",
                        "gaintable": stokes_i_tables,
                    },
                },
                # 7c bad retry + 7c good on full_ms (TARGET)
                {
                    "stage": "applycal",
                    "product": str(full_ms),
                    "params": {
                        "ms_path": str(full_ms),
                        "field": "TARGET",
                        "gaintable": stokes_i_tables,
                        "applymode": "calonly",
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(full_ms),
                    "params": {
                        "ms_path": str(full_ms),
                        "field": "TARGET",
                        "gaintable": stokes_i_tables,
                        "applymode": "calflag",
                    },
                },
                # Polcal solves on calibrators.ms ONLY (full_ms has zero activity here)
                {
                    "stage": "gaincal",
                    "product": str(wd / "kcross.K"),
                    "params": {
                        "ms_path": str(cal_ms),
                        "caltable": str(wd / "kcross.K"),
                        "gaintype": "KCROSS",
                    },
                },
                {
                    "stage": "polcal",
                    "product": str(wd / "Df.D"),
                    "params": {"ms_path": str(cal_ms), "caltable": str(wd / "Df.D")},
                },
                {
                    "stage": "polcal",
                    "product": str(wd / "Xf.X"),
                    "params": {"ms_path": str(cal_ms), "caltable": str(wd / "Xf.X")},
                },
                # 5a on calibrators.ms + 5b on full_ms (TARGET)
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "field": "3C286",
                        "gaintable": iquv_tables,
                    },
                },
                {
                    "stage": "applycal",
                    "product": str(full_ms),
                    "params": {
                        "ms_path": str(full_ms),
                        "field": "TARGET",
                        "gaintable": iquv_tables,
                        "flagbackup": False,
                    },
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        target_applies = [
            r
            for r in recs
            if r["tool"] == "ms_applycal" and r["params"].get("ms_path") == str(full_ms)
        ]
        # 7c bad ('calonly') dropped; 7c good ('calflag', 3 tables) + 5b (6 tables) BOTH kept!
        assert len(target_applies) == 2
        assert target_applies[0]["params"]["applymode"] == "calflag"
        assert len(target_applies[0]["params"]["gaintable"]) == 3
        assert len(target_applies[1]["params"]["gaintable"]) == 6

    def test_preflag_retry_wipes_mutating_casa_tool_split_and_orphaned_flag_caltable(
        self, tmp_path
    ):
        wd = tmp_path / "preflag_wipe"
        wd.mkdir()
        raw_ms = _make_ms(tmp_path / "raw.ms")
        cal_ms = _make_ms(wd / "calibrators.ms")

        _append_stage_entries(
            wd,
            [
                # External caltable unrelated to calibrators.ms: preserved
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "external.G"),
                    "params": {"caltable_path": str(wd / "external.G"), "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                # preflag(1)
                {
                    "stage": "preflag",
                    "product": str(raw_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd), "cal_fields": "0"},
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd), "cal_fields": "0"},
                },
                # Mutating ms_casa_tool copying calibrators.ms/STATE -> wd/copy1.tab and editing copy1.tab
                {
                    "stage": "ms_casa_tool",
                    "product": str(wd / "copy1.tab"),
                    "params": {
                        "tool": "table",
                        "allow_write": True,
                        "calls": [
                            {"method": "open", "args": {"tablename": f"{cal_ms}/STATE"}},
                            {"method": "copy", "args": {"newtablename": str(wd / "copy1.tab")}},
                            {"method": "close"},
                            {
                                "method": "open",
                                "args": {"tablename": str(wd / "copy1.tab"), "nomodify": False},
                            },
                            {"method": "putcell", "args": {"columnname": "CAL"}},
                        ],
                    },
                    "measurement": {"written_paths": [str(wd / "copy1.tab")]},
                },
                # ms_casa_task:split reading calibrators.ms -> wd/sub.ms
                {
                    "stage": "ms_casa_task:split",
                    "product": str(wd / "sub.ms"),
                    "params": {
                        "task": "split",
                        "params": {"vis": str(cal_ms), "outputvis": str(wd / "sub.ms")},
                        "workdir": str(wd),
                    },
                },
                # bandpass on calibrators.ms -> BP0.b + orphaned flag_caltable(BP0.b)
                {
                    "stage": "bandpass",
                    "product": str(wd / "BP0.b"),
                    "params": {"ms_path": str(cal_ms), "caltable": str(wd / "BP0.b")},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(wd / "BP0.b"),
                    "params": {"caltable_path": str(wd / "BP0.b"), "mode": None},
                    "measurement": {"mode": "tfcrop"},
                },
                # preflag(2) recreating calibrators.ms
                {
                    "stage": "preflag",
                    "product": str(raw_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd), "cal_fields": "0,1"},
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd), "cal_fields": "0,1"},
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == ["ms_flag_caltable", "ms_apply_preflag"]
        assert recs[0]["outputs"]["product"] == str(wd / "external.G")
        assert recs[1]["params"]["cal_fields"] == "0,1"

    def test_audit_hook_non_stage_workdir_poisoning_and_container_default_workdir_fallback(
        self, tmp_path
    ):
        # (a) Non-stage subagents ('self', '', 'Explore', 'research') mentioning workdir=/nonexistent
        #     must NOT poison inferred_workdir before a real *-stage prompt.
        host_wd = tmp_path / "host_wd"
        host_wd.mkdir()
        cc_file = tmp_path / "poison_test.jsonl"
        cc_events = [
            {
                "type": "assistant",
                "message": {
                    "id": "m_poison",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t_self",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "self",
                                "prompt": "check workdir=/nonexistent/container/path",
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "t_empty",
                            "name": "Task",
                            "input": {
                                "subagent_type": "",
                                "prompt": "explore workdir=/also/nonexistent",
                            },
                        },
                        {
                            "type": "tool_use",
                            "id": "t_precal",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "radio-analyst:precal-stage",
                                "prompt": f"run precal workdir={host_wd}",
                            },
                        },
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t_self", "content": "ok"},
                        {"type": "tool_result", "tool_use_id": "t_empty", "content": "ok"},
                        {"type": "tool_result", "tool_use_id": "t_precal", "content": "PRECAL_OK"},
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "m_dec",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '<stage_decision>{"stage": "precal", "decision": "proceed", '
                                '"reason": "clean"}</stage_decision>'
                            ),
                        }
                    ],
                },
            },
        ]
        cc_file.write_text("\n".join(json.dumps(e) for e in cc_events) + "\n")
        written_a = audit_hook.build_audit_records_from_transcript(cc_file)
        assert len(written_a) == 1
        assert json.loads(written_a[0].read_text())["handoff"] == "PRECAL_OK"

        # (b) Containerized OpenCode trace with '/work/run/wd' in task prompt, MCP args, AND
        #     <stage_decision> must fall back to default_workdir=host_wd2 on the host.
        host_wd2 = tmp_path / "host_wd_container"
        host_wd2.mkdir()
        oc_trace = tmp_path / "container_trace.jsonl"
        oc_lines = [
            {
                "type": "tool_use",
                "part": {
                    "callID": "oc_t1",
                    "tool": "task",
                    "state": {
                        "input": {
                            "subagent_type": "calibrate-stage",
                            "prompt": "calibrate workdir=/work/run/wd",
                        },
                        "output": "CONTAINER_CAL_HANDOFF",
                        "metadata": {"sessionId": "ses_cont_1"},
                    },
                },
            },
            {
                "type": "tool_use",
                "part": {
                    "callID": "oc_t2",
                    "tool": "ms-inspect_ms_calsol_stats",
                    "state": {
                        "input": {"caltable": "/work/run/wd/BP.B", "workdir": "/work/run/wd"},
                        "output": json.dumps({"flagged": 0.01}),
                        "metadata": {},
                    },
                },
            },
            {
                "type": "text",
                "part": {
                    "id": "oc_txt1",
                    "text": (
                        '<stage_decision>{"stage": "calibrate", "workdir": "/work/run/wd", '
                        '"decision": "proceed", "reason": "container run"}</stage_decision>'
                    ),
                },
            },
        ]
        oc_trace.write_text("\n".join(json.dumps(x) for x in oc_lines) + "\n")
        written_b = audit_hook.build_audit_records_from_transcript(
            oc_trace, default_workdir=host_wd2
        )
        assert len(written_b) == 1
        rec_b = json.loads(written_b[0].read_text())
        assert rec_b["workdir"] == str(host_wd2.resolve())
        assert rec_b["handoff"] == "CONTAINER_CAL_HANDOFF"
        assert rec_b["checks"][0]["tool"] == "ms_calsol_stats"

    def test_dropped_applycal_does_not_keep_dead_upstream_solves(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        cal_ms = _make_ms(wd / "calibrators.ms")
        g1 = _make_caltable(wd / "gain.G")
        k0 = _make_caltable(wd / "delay.K")
        bp = _make_caltable(wd / "bp.B")

        # Case A: applycal([G1]) superseded immediately by applycal([K0]) before postcal_flag
        _append_stage_entries(
            wd,
            [
                {
                    "stage": "gaincal",
                    "product": str(k0),
                    "params": {"ms_path": str(cal_ms), "caltable": str(k0), "gaintype": "K"},
                },
                {
                    "stage": "gaincal",
                    "product": str(g1),
                    "params": {"ms_path": str(cal_ms), "caltable": str(g1), "solint": "60s"},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(g1),
                    "params": {"caltable_path": str(g1), "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "gaintable": [str(g1)]},
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "gaintable": [str(k0)]},
                },
                {
                    "stage": "postcal_flag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "datacolumn": "corrected"},
                },
                {
                    "stage": "gaincal",
                    "product": str(g1),
                    "params": {"ms_path": str(cal_ms), "caltable": str(g1), "solint": "inf"},
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        tools_and_solints = [(r["tool"], r["params"].get("solint")) for r in recs]
        assert ("ms_gaincal", "60s") not in tools_and_solints
        assert all(r["tool"] != "ms_flag_caltable" for r in recs)
        assert ("ms_gaincal", "inf") in tools_and_solints

        # Case B: applycal([G1, BP]) dropped because BP was re-solved before postcal_flag
        wd_b = tmp_path / "work_b"
        wd_b.mkdir()
        _append_stage_entries(
            wd_b,
            [
                {
                    "stage": "gaincal",
                    "product": str(g1),
                    "params": {"ms_path": str(cal_ms), "caltable": str(g1), "solint": "60s"},
                },
                {
                    "stage": "flag_caltable",
                    "product": str(g1),
                    "params": {"caltable_path": str(g1), "mode": None},
                    "measurement": {"mode": "rflag"},
                },
                {
                    "stage": "bandpass",
                    "product": str(bp),
                    "params": {"ms_path": str(cal_ms), "caltable": str(bp)},
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(cal_ms),
                        "field": "3C286",
                        "gaintable": [str(g1), str(bp)],
                    },
                },
                {
                    "stage": "bandpass",
                    "product": str(bp),
                    "params": {"ms_path": str(cal_ms), "caltable": str(bp)},
                },
                {
                    "stage": "applycal",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "gaintable": [str(bp)]},
                },
                {
                    "stage": "postcal_flag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "field": "3C286", "datacolumn": "corrected"},
                },
                {
                    "stage": "gaincal",
                    "product": str(g1),
                    "params": {"ms_path": str(cal_ms), "caltable": str(g1), "solint": "inf"},
                },
            ],
        )
        recs_b = reduction_log.load_effective_records(wd_b)
        solints_b = [(r["tool"], r["params"].get("solint")) for r in recs_b]
        assert ("ms_gaincal", "60s") not in solints_b
        assert all(r["tool"] != "ms_flag_caltable" for r in recs_b)
        assert ("ms_gaincal", "inf") in solints_b

    def test_inplace_casa_tool_does_not_poison_raw_ms_and_handles_thems(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        raw_ms = _make_ms(tmp_path / "raw.ms")
        cal_ms = _make_ms(wd / "calibrators.ms")

        _append_stage_entries(
            wd,
            [
                {
                    "stage": "preflag",
                    "product": str(raw_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd)},
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(raw_ms), "workdir": str(wd)},
                },
                # In-place ms_casa_tool reading wiped cal_ms and mutating raw_ms (no copy/create)
                {
                    "stage": "ms_casa_tool",
                    "product": str(raw_ms),
                    "params": {
                        "tool": "table",
                        "allow_write": True,
                        "calls": [
                            {"method": "open", "args": {"tablename": str(cal_ms)}},
                            {"method": "close"},
                            {
                                "method": "open",
                                "args": {"tablename": str(raw_ms), "nomodify": False},
                            },
                            {"method": "putcell", "args": {"columnname": "FLAG"}},
                        ],
                    },
                },
                # In-place ms tool using 'thems' on cal_ms
                {
                    "stage": "ms_casa_tool",
                    "product": str(cal_ms),
                    "params": {
                        "tool": "ms",
                        "allow_write": True,
                        "calls": [{"method": "open", "args": {"thems": str(cal_ms)}}],
                    },
                },
                # Retry preflag from raw_ms
                {
                    "stage": "preflag",
                    "product": str(raw_ms),
                    "params": {
                        "ms_path": str(raw_ms),
                        "workdir": str(wd),
                        "quack_interval_s": 10.0,
                    },
                },
                {
                    "stage": "preflag",
                    "product": str(cal_ms),
                    "params": {
                        "ms_path": str(raw_ms),
                        "workdir": str(wd),
                        "quack_interval_s": 10.0,
                    },
                },
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == ["ms_apply_preflag"]
        assert recs[0]["params"]["quack_interval_s"] == 10.0

    def test_setjy_exclude_fields_none_and_rflag_residual_model_consumer(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        cal_ms = _make_ms(wd / "calibrators.ms")

        # 1) exclude_fields=None deduplicates against exclude_fields=""
        _append_stage_entries(
            wd,
            [
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "exclude_fields": None},
                },
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "exclude_fields": ""},
                },
            ],
        )
        assert len(reduction_log.load_effective_records(wd)) == 1

        # 2) rflag(datacolumn='residual') preserves preceding setjy
        wd2 = tmp_path / "work2"
        wd2.mkdir()
        _append_stage_entries(
            wd2,
            [
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "standard": "Perley-Butler 2013"},
                },
                {
                    "stage": "rflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "datacolumn": "residual"},
                },
                {
                    "stage": "setjy",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "standard": "Perley-Butler 2017"},
                },
            ],
        )
        recs2 = reduction_log.load_effective_records(wd2)
        assert [r["tool"] for r in recs2] == ["ms_setjy", "ms_apply_rflag", "ms_setjy"]

    def test_initial_bandpass_self_apply_retained_across_initial_rflag(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        cal_ms = _make_ms(wd / "calibrators.ms")
        ig = _make_caltable(wd / "init_phase.g")
        ibp = _make_caltable(wd / "init_bp.b")

        ib_params_1 = {"ms_path": str(cal_ms), "workdir": str(wd), "ref_ant": "ea01"}
        ib_params_2 = {"ms_path": str(cal_ms), "workdir": str(wd), "ref_ant": "ea02"}
        _append_stage_entries(
            wd,
            [
                {"stage": "initial_bandpass", "product": str(ig), "params": ib_params_1},
                {"stage": "initial_bandpass", "product": str(ibp), "params": ib_params_1},
                {"stage": "initial_bandpass", "product": str(cal_ms), "params": ib_params_1},
                {
                    "stage": "initial_rflag",
                    "product": str(cal_ms),
                    "params": {"ms_path": str(cal_ms), "workdir": str(wd), "field": "3C147"},
                },
                {"stage": "initial_bandpass", "product": str(ig), "params": ib_params_2},
                {"stage": "initial_bandpass", "product": str(ibp), "params": ib_params_2},
                {"stage": "initial_bandpass", "product": str(cal_ms), "params": ib_params_2},
            ],
        )

        recs = reduction_log.load_effective_records(wd)
        assert [r["tool"] for r in recs] == [
            "ms_initial_bandpass",
            "ms_apply_initial_rflag",
            "ms_initial_bandpass",
        ]
        assert recs[0]["params"]["ref_ant"] == "ea01"
        assert recs[2]["params"]["ref_ant"] == "ea02"
