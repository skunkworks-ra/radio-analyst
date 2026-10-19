"""
scripts/plugin/reduce_hook.py and reduce_contract.py on fake hook payloads.

The hook logs only after the reduce skill is activated in that session, never
denies, and at Stop sends the model back once with the contract items still open.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "scripts" / "plugin"
sys.path.insert(0, str(PLUGIN))

import reduce_contract  # noqa: E402
import reduce_hook  # noqa: E402

MCP = "mcp__plugin_radio-analyst_ms-modify__"
INSPECT = "mcp__plugin_radio-analyst_ms-inspect__"

CONTRACT = {
    "cache": {
        "flags": {"tools": ["ms_flag_summary"], "invalidated_by": ["ms_apply_preflag"]},
        "always": {"tools": ["ms_workflow_status"], "invalidated_by": ["every action"]},
    },
    "stages": [
        {
            "stage": "precal",
            "steps": [
                {"id": "p1", "action": "ms_apply_preflag", "after": ["ms_flag_summary"]},
            ],
        },
        {
            "stage": "polcal",
            "optional": True,
            "steps": [{"id": "o1", "action": "ms_polcal", "after": []}],
        },
    ],
}


@pytest.fixture(autouse=True)
def _no_project_dir(monkeypatch):
    # set inside a Claude Code session; tests pass cwd explicitly instead
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


@pytest.fixture
def contract(tmp_path, monkeypatch):
    path = tmp_path / "stages.json"
    path.write_text(json.dumps(CONTRACT))
    monkeypatch.setattr(reduce_hook, "CONTRACT", path)
    return path


def ev(cwd, event, **kw):
    return {"hook_event_name": event, "session_id": "s1", "cwd": str(cwd), **kw}


def post(cwd, tool, inp=None, resp=None):
    return reduce_hook.handle(
        ev(cwd, "PostToolUse", tool_name=tool, tool_input=inp or {}, tool_response=resp or {})
    )


def log(cwd):
    return reduce_hook.read_log(Path(cwd) / reduce_hook.LOG_NAME)


def test_inactive_session_writes_nothing(tmp_path):
    post(tmp_path, MCP + "ms_apply_preflag", {"ms_path": "a.ms"})
    assert reduce_hook.handle(ev(tmp_path, "Stop")) is None
    assert not (tmp_path / reduce_hook.LOG_NAME).exists()


@pytest.mark.parametrize("prompt", ["/reduce ./input.ms", "/radio-analyst:reduce input.ms"])
def test_prompt_activates(tmp_path, prompt):
    reduce_hook.handle(ev(tmp_path, "UserPromptSubmit", prompt=prompt))
    assert [r["event"] for r in log(tmp_path)] == ["activate"]


def test_other_prompt_does_not_activate(tmp_path):
    reduce_hook.handle(ev(tmp_path, "UserPromptSubmit", prompt="reduce this ms please"))
    assert log(tmp_path) == []


def test_skill_call_activates_and_logs(tmp_path):
    post(tmp_path, "Skill", {"skill": "radio-analyst:reduce"})
    post(tmp_path, "Bash", {"command": "ls"})
    events = [(r["event"], r.get("tool")) for r in log(tmp_path)]
    assert events == [("activate", None), ("call", "Skill"), ("call", "Bash")]


def test_other_session_not_logged(tmp_path):
    post(tmp_path, "Skill", {"skill": "reduce"})
    reduce_hook.handle({**ev(tmp_path, "PostToolUse", tool_name="Bash"), "session_id": "s2"})
    assert all(r["session_id"] == "s1" for r in log(tmp_path))


def test_failure_and_error_envelope_are_not_ok(tmp_path):
    post(tmp_path, "Skill", {"skill": "reduce"})
    reduce_hook.handle(
        ev(tmp_path, "PostToolUseFailure", tool_name=MCP + "ms_setjy", tool_input={}, error="x")
    )
    post(tmp_path, MCP + "ms_gaincal", {}, [{"type": "text", "text": '{"status": "error"}'}])
    post(tmp_path, MCP + "ms_bandpass", {}, {"structuredContent": {"status": "ok"}})
    oks = [r["ok"] for r in log(tmp_path) if r["event"] == "call" and r["tool"].startswith("mcp")]
    assert oks == [False, False, True]


def test_stop_blocks_once_with_open_items(tmp_path, contract):
    post(tmp_path, "Skill", {"skill": "reduce"})
    post(tmp_path, MCP + "ms_apply_preflag", {"params": {"ms_path": "a.ms"}})
    out = reduce_hook.handle(ev(tmp_path, "Stop"))
    assert out["decision"] == "block"
    assert "ms_flag_summary: MISSING" in out["reason"]
    assert "no ms_reduction_log append" in out["reason"]
    assert "polcal" not in out["reason"]  # optional stage with no action: skipped
    assert reduce_hook.handle(ev(tmp_path, "Stop", stop_hook_active=True)) is None


def test_stop_waits_for_background_tasks(tmp_path, contract):
    post(tmp_path, "Skill", {"skill": "reduce"})
    assert reduce_hook.handle(ev(tmp_path, "Stop", background_tasks=[{"id": "b1"}])) is None


def test_stop_passes_when_contract_met(tmp_path, contract):
    post(tmp_path, "Skill", {"skill": "reduce"})
    post(tmp_path, MCP + "ms_apply_preflag", {"ms_path": "a.ms"})
    post(tmp_path, INSPECT + "ms_flag_summary", {"ms_path": "a.ms"})
    post(tmp_path, "mcp__plugin_radio-analyst_ms-create__ms_reduction_log", {"action": "append"})
    assert reduce_hook.handle(ev(tmp_path, "Stop")) is None


def test_edited_generated_script_is_reported(tmp_path, contract):
    script = tmp_path / "tclean.py"
    script.write_text("tclean(usemask='user')\n")
    post(tmp_path, "Skill", {"skill": "reduce"})
    resp = [{"type": "text", "text": json.dumps({"data": {"script_path": str(script)}})}]
    post(tmp_path, MCP + "ms_apply_preflag", {"ms_path": "a.ms"}, resp)
    script.write_text("tclean(usemask='pb')\n")
    out = reduce_hook.handle(ev(tmp_path, "Stop"))
    assert f"edited after generation: {script}" in out["reason"]


def _before_flag_summary(writer: str) -> str:
    """flag_summary at L1, a write at L2, then the step whose before-check is flag_summary."""
    calls = [
        reduce_contract.make_call(1, INSPECT + "ms_flag_summary", {"ms_path": "a.ms"}, True),
        reduce_contract.make_call(2, MCP + writer, {"ms_path": "a.ms"}, True),
        reduce_contract.make_call(3, MCP + "ms_polcal", {"ms_path": "a.ms"}, True),
    ]
    steps = [
        {"id": "x1", "action": writer},
        {"id": "x2", "action": "ms_polcal", "before": ["ms_flag_summary"]},
    ]
    contract = {"cache": CONTRACT["cache"], "stages": [{"stage": "x", "steps": steps}]}
    return "\n".join(reduce_contract.score(calls, contract)["lines"])


def test_check_cached_across_a_write_that_does_not_invalidate_it():
    assert "before ms_flag_summary: CACHED L1" in _before_flag_summary("ms_setjy")


def test_check_stale_after_an_invalidating_write():
    assert "before ms_flag_summary: STALE L1" in _before_flag_summary("ms_apply_preflag")


def test_hook_fails_open_on_bad_input():
    p = subprocess.run(
        [sys.executable, str(PLUGIN / "reduce_hook.py")],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    assert "reduce hook error" in p.stderr


def test_edited_script_cleared_by_a_ledger_entry_naming_it(tmp_path, contract):
    script = tmp_path / "tclean.py"
    script.write_text("tclean(usemask='user')\n")
    post(tmp_path, "Skill", {"skill": "reduce"})
    resp = [{"type": "text", "text": json.dumps({"data": {"script_path": str(script)}})}]
    post(tmp_path, MCP + "ms_apply_preflag", {"ms_path": "a.ms"}, resp)
    script.write_text("tclean(usemask='pb')\n")
    post(
        tmp_path,
        "mcp__plugin_radio-analyst_ms-create__ms_reduction_log",
        {"params": {"action": "append", "tool": "manual", "script_path": str(script)}},
    )
    out = reduce_hook.handle(ev(tmp_path, "Stop"))
    assert out is None or "edited after generation" not in out["reason"]


def test_selfcal_calls_are_not_counted_as_calibration_or_first_image():
    # real contract: G0, applycal and the first tclean must not pick up the selfcal calls
    contract = json.loads(reduce_contract.CONTRACT.read_text())
    mk = reduce_contract.make_call
    calls = [
        mk(
            1,
            MCP + "ms_gaincal",
            {"gaintype": "G", "calmode": "p", "caltable": "w/initial_phase.G0"},
            True,
        ),
        mk(2, MCP + "ms_applycal", {"gaintable": ["w/gain.fluxscaled"]}, True),
        mk(3, MCP + "ms_tclean", {"imagename": "w/img"}, True),
        mk(4, MCP + "ms_gaincal", {"gaintype": "G", "calmode": "p", "caltable": "w/pcal1.g"}, True),
        mk(5, MCP + "ms_applycal", {"gaintable": ["w/gain.fluxscaled", "w/pcal1.g"]}, True),
        mk(6, MCP + "ms_tclean", {"imagename": "w/img_sc1"}, True),
    ]
    lines = "\n".join(reduce_contract.score(calls, contract)["lines"])
    assert "c2 ms_gaincal(G0): L1 " in lines
    assert "c7 ms_applycal x3 (flux, phase, target): L2 " in lines
    assert "m2 ms_tclean: L3 " in lines
    assert "s1 ms_gaincal(selfcal): L4 " in lines
    assert "s2 ms_applycal(selfcal): L5 " in lines
    assert "s3 ms_tclean(selfcal): L6 " in lines


def test_selfcal_stage_skipped_when_not_chosen():
    contract = json.loads(reduce_contract.CONTRACT.read_text())
    lines = reduce_contract.score([], contract)["lines"]
    assert "[selfcal] skipped (optional, no action called)" in lines


def test_log_stays_put_when_the_model_changes_directory(tmp_path, monkeypatch):
    # run 20261019T065217Z: after `cd work`, the hook cwd moved and logging went silent
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    sub = tmp_path / "work"
    sub.mkdir()
    post(tmp_path, "Skill", {"skill": "reduce"})
    post(sub, MCP + "ms_apply_preflag", {"ms_path": "a.ms"})
    assert not (sub / reduce_hook.LOG_NAME).exists()
    assert [r.get("tool") for r in log(tmp_path)][-1] == MCP + "ms_apply_preflag"
