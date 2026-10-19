"""
Unit tests for ms_create/reduction_log.py — JSONL working-calls ledger.

No CASA required.
"""

from __future__ import annotations

import json

import pytest

from ms_create.reduction_log import _RUN_REGISTRY, run


class TestRunRegistry:
    """The replay registry maps recorded tool names to modules. Every mapped
    module must be importable and expose run(), or render() silently emits a
    broken replay line instead of a runnable call."""

    def test_every_registry_module_imports_and_has_run(self):
        import importlib

        for tool, mod_name in _RUN_REGISTRY.items():
            mod = importlib.import_module(mod_name)
            assert hasattr(mod, "run"), f"{mod_name} (for {tool}) has no run()"

    def test_replayable_pipeline_tools_are_registered(self):
        # Core steps exercised in a real reduction must be replayable, not
        # emitted as MANUAL markers.
        for tool in (
            "ms_initial_bandpass",
            "ms_apply_initial_rflag",
            "ms_apply_rflag",
            "ms_flag_caltable",
        ):
            assert tool in _RUN_REGISTRY


class TestReductionLog:
    def test_append_then_list(self, tmp_path):
        wd = str(tmp_path)
        r1 = run(
            "append",
            wd,
            tool="ms_gaincal",
            params={"field": "3C286", "execute": True},
            rationale="initial phase",
        )
        assert r1["data"]["step_recorded"]["value"] == 1
        r2 = run(
            "append",
            wd,
            tool="ms_bandpass",
            params={"spw": "0", "execute": True},
            rationale="bandpass",
        )
        assert r2["data"]["n_records"]["value"] == 2
        lst = run("list", wd)
        steps = lst["data"]["steps"]
        assert [s["tool"] for s in steps] == ["ms_gaincal", "ms_bandpass"]
        assert steps[0]["rationale"] == "initial phase"

    def test_jsonl_on_disk(self, tmp_path):
        wd = str(tmp_path)
        run(
            "append",
            wd,
            tool="ms_setjy",
            params={"standard": "Perley-Butler 2017", "execute": True},
        )
        log = tmp_path / "reduction_log.jsonl"
        assert log.exists()
        rec = json.loads(log.read_text().splitlines()[0])
        assert rec["tool"] == "ms_setjy"
        assert rec["params"]["standard"] == "Perley-Butler 2017"
        assert rec["step"] == 1

    def test_render_emits_replay(self, tmp_path):
        wd = str(tmp_path)
        run(
            "append",
            wd,
            tool="ms_gaincal",
            params={"field": "3C286", "solint": "int", "execute": True},
            rationale="G0",
        )
        out = run("render", wd)
        assert out["data"]["n_records"]["value"] == 1
        assert len(out["data"]["recipe"]["value"]) == 1
        replay = tmp_path / "reduction_replay.py"
        assert replay.exists()
        text = replay.read_text()
        # Executable form: importlib.import_module('ms_modify.gaincal').run(...)
        assert "importlib.import_module('ms_modify.gaincal').run(" in text
        assert "field='3C286'" in text
        assert "G0" in text  # rationale comment

    def test_render_marks_unmapped_as_manual(self, tmp_path):
        # a ledger written before append refused unknown names still renders
        rec = {"step": 1, "tool": "setjy(manual,pol)", "params": {"polangle_deg": 33}}
        (tmp_path / "reduction_log.jsonl").write_text(json.dumps(rec) + "\n")
        run("render", str(tmp_path))
        text = (tmp_path / "reduction_replay.py").read_text()
        assert "MANUAL STEP" in text
        assert "importlib.import_module" not in text

    def test_list_empty(self, tmp_path):
        out = run("list", str(tmp_path))
        assert out["data"]["n_records"]["value"] == 0
        assert out["data"]["steps"] == []

    def test_unknown_action_raises(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError):
            run("frobnicate", str(tmp_path))

    def test_missing_workdir_raises(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError):
            run("list", str(tmp_path / "nope"))


class TestAppendRefusesWhatRenderCannotReplay:
    """Run 20261019T050652Z: free-text tool names ('ms_gaincal (G0)', 'ms_applycal x3')
    and prose execute values left 8 of 14 write steps MANUAL in the replay."""

    @pytest.mark.parametrize("tool", ["ms_gaincal (G0)", "ms_applycal x3", "ms_refant", ""])
    def test_unknown_or_read_tool_refused(self, tmp_path, tool):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="not a replayable step"):
            run("append", str(tmp_path), tool=tool, params={"execute": True})
        assert not (tmp_path / "reduction_log.jsonl").exists()

    def test_prose_execute_refused(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="literal true/false"):
            run("append", str(tmp_path), tool="ms_gaincal", params={"execute": "script then run"})

    @pytest.mark.parametrize("tool", ["ms_gaincal", "manual"])
    def test_script_required_unless_executed(self, tmp_path, tool):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="script_path is required"):
            run("append", str(tmp_path), tool=tool, params={"execute": False})

    def test_missing_script_refused(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="does not exist"):
            run("append", str(tmp_path), tool="ms_gaincal", script_path="nope.py")

    def test_script_recorded_with_hash_and_replayed(self, tmp_path):
        import hashlib

        script = tmp_path / "gaincal_G0.py"
        script.write_text("print('G0')\n")
        wd = str(tmp_path)
        run("append", wd, tool="ms_gaincal", params={"execute": False}, script_path="gaincal_G0.py")
        run("append", wd, tool="manual", script_path=str(script), rationale="hand flag")
        rec = json.loads((tmp_path / "reduction_log.jsonl").read_text().splitlines()[0])
        assert rec["script_path"] == str(script.resolve())
        assert rec["script_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()
        run("render", wd)
        text = (tmp_path / "reduction_replay.py").read_text()
        assert text.count(f"_run_script({str(script.resolve())!r}") == 2
        assert "MANUAL STEP" not in text

    def test_replay_runs_scripts_and_stops_on_a_changed_one(self, tmp_path):
        import subprocess
        import sys

        out = tmp_path / "ran.txt"
        script = tmp_path / "step.py"
        script.write_text(f"open({str(out)!r}, 'a').write('x')\n")
        run("append", str(tmp_path), tool="manual", script_path=str(script))
        run("render", str(tmp_path))
        replay = tmp_path / "reduction_replay.py"
        assert subprocess.run([sys.executable, str(replay)]).returncode == 0
        assert out.read_text() == "x"
        script.write_text("pass\n")
        p = subprocess.run([sys.executable, str(replay)], capture_output=True, text=True)
        assert p.returncode != 0 and "changed since it was recorded" in p.stderr
