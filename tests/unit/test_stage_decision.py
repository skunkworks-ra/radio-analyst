"""Unit tests for ms_record_stage_decision and audit_hook tool-call enrichment."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ms_create import audit_hook, server, stage_decision
from ms_inspect.exceptions import ComputationError

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRecordStageDecisionTool:
    def test_writes_audit_hook_compatible_json(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()

        res = stage_decision.run(
            seq=2,
            stage="precal",
            attempt=1,
            workdir=str(wd),
            decision="next",
            deciding_metric="ms_workflow_status.next_recommended_step = delay_bandpass_gain",
            reason="All precal tables verified.",
            debug_directive=None,
            png_reviewed=None,
        )
        assert res["status"] == "ok"
        out_path = Path(res["data"]["record_path"]["value"])
        assert out_path == wd / "orchestrator" / "02_precal_try1.json"
        assert out_path.is_file()

        rec = json.loads(out_path.read_text())
        expected_keys = {
            "n",
            "stage",
            "attempt",
            "workdir",
            "prompt",
            "handoff",
            "checks",
            "decision",
            "deciding_metric",
            "reason",
            "debug_directive",
            "agent_id",
            "png_reviewed",
            "agent_usage",
        }
        assert set(rec.keys()) == expected_keys
        assert rec["n"] == 2
        assert rec["stage"] == "precal"
        assert rec["attempt"] == 1
        assert rec["workdir"] == str(wd.resolve())
        assert rec["decision"] == "next"
        assert rec["deciding_metric"] == (
            "ms_workflow_status.next_recommended_step = delay_bandpass_gain"
        )
        assert rec["reason"] == "All precal tables verified."
        assert rec["debug_directive"] is None
        assert rec["png_reviewed"] is None

    def test_pydantic_input_accepts_try_alias_and_attempt_name(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()

        by_try = server.RecordStageDecisionInput.model_validate(
            {
                "seq": 1,
                "stage": "inspect",
                "try": 1,
                "workdir": str(wd),
                "decision": "next",
                "deciding_metric": "ms_field_list.n_fields = 9",
                "reason": "Inspect handoff checked.",
            }
        )
        assert by_try.attempt == 1

        by_attempt = server.RecordStageDecisionInput.model_validate(
            {
                "seq": 1,
                "stage": "inspect",
                "attempt": 2,
                "workdir": str(wd),
                "decision": "retry",
                "deciding_metric": "ms_field_list.n_fields = 0",
                "reason": "Retry inspect.",
                "debug_directive": {"call": "ms_field_list", "params": {}},
                "png_reviewed": None,
            }
        )
        assert by_attempt.attempt == 2

    def test_mcp_schema_exposes_try_and_no_output_schema(self):
        tools = asyncio.run(server.mcp.list_tools())
        tool = next(t for t in tools if t.name == "ms_record_stage_decision")
        assert tool.outputSchema is None
        defs = tool.inputSchema.get("$defs") or {}
        rec_schema = defs.get("RecordStageDecisionInput", {})
        props = rec_schema.get("properties", {})
        assert "try" in props
        assert "seq" in props and "stage" in props and "decision" in props

    def test_validation_rejects_bad_stage_decision_and_missing_workdir(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()

        with pytest.raises(ComputationError, match="Unsupported stage"):
            stage_decision.run(1, "bogus", 1, str(wd), "next", "m=1", "ok")
        with pytest.raises(ComputationError, match="Unsupported decision"):
            stage_decision.run(1, "precal", 1, str(wd), "proceed", "m=1", "ok")
        with pytest.raises(ComputationError, match="workdir does not exist"):
            stage_decision.run(1, "precal", 1, str(tmp_path / "missing"), "next", "m=1", "ok")
        with pytest.raises(ComputationError, match="try/attempt"):
            stage_decision.run(1, "precal", 6, str(wd), "next", "m=1", "ok")


class TestAuditHookToolCallEnrichment:
    def test_audit_hook_sh_enriches_tool_recorded_stage_decisions(self, tmp_path):
        """audit_hook.sh enriches ms_record_stage_decision calls with handoff + checks."""
        wd = tmp_path / "work_enrich"
        wd.mkdir()
        export_file = tmp_path / "session.json"

        # Simulate live run: tool already wrote minimal 01_precal_try1.json during the session.
        stage_decision.run(
            seq=1,
            stage="precal",
            attempt=1,
            workdir=str(wd),
            decision="next",
            deciding_metric="ms_workflow_status.next_recommended_step = delay_bandpass_gain",
            reason="Precal verified via tool call.",
        )

        doc = {
            "info": {"id": "ses_root"},
            "messages": [
                {
                    "info": {"id": "msg_1", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_precal",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "precal-stage",
                                    "prompt": f"/data/obs.ms workdir={wd}",
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
                            "callID": "call_wf",
                            "tool": "ms-inspect_ms_workflow_status",
                            "state": {
                                "input": {"ms_path": "/data/obs.ms", "workdir": str(wd)},
                                "output": json.dumps(
                                    {"next_recommended_step": "delay_bandpass_gain"}
                                ),
                                "metadata": {},
                            },
                        }
                    ],
                },
                {
                    "info": {"id": "msg_3", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_dec_1",
                            "tool": "ms-create_ms_record_stage_decision",
                            "state": {
                                "input": {
                                    "params": {
                                        "seq": 1,
                                        "stage": "precal",
                                        "try": 1,
                                        "workdir": str(wd),
                                        "decision": "next",
                                        "deciding_metric": (
                                            "ms_workflow_status.next_recommended_step = "
                                            "delay_bandpass_gain"
                                        ),
                                        "reason": "Precal verified via tool call.",
                                        "debug_directive": None,
                                        "png_reviewed": None,
                                    }
                                },
                                "output": json.dumps({"status": "ok"}),
                                "metadata": {},
                            },
                        }
                    ],
                },
                {
                    "info": {"id": "msg_4", "role": "assistant"},
                    "parts": [
                        {
                            "type": "tool",
                            "callID": "call_cal",
                            "tool": "task",
                            "state": {
                                "input": {
                                    "subagent_type": "calibrate-stage",
                                    "prompt": f"/data/obs.ms workdir={wd}",
                                },
                                "output": "STAGE HANDOFF: calibrate\nstatus: completed",
                                "metadata": {"sessionId": "ses_cal_1"},
                            },
                        }
                    ],
                },
                {
                    # Backwards-compatibility: legacy XML decision later in same transcript still works.
                    "info": {"id": "msg_5", "role": "assistant"},
                    "parts": [
                        {
                            "type": "text",
                            "text": (
                                '<stage_decision>{"seq": 2, "stage": "calibrate", "try": 1, '
                                f'"workdir": "{wd}", "decision": "next", '
                                '"deciding_metric": "phase_rms_deg = 3.2", '
                                '"reason": "Legacy XML fallback still parsed."}</stage_decision>'
                            ),
                        }
                    ],
                },
            ],
        }
        export_file.write_text(json.dumps(doc, indent=2))

        hook_script = REPO_ROOT / "scripts" / "plugin" / "audit_hook.sh"
        plugin_data = tmp_path / "plugin_data"
        plugin_data.mkdir()
        (plugin_data / "env.prefix").write_text(str(Path(sys.executable).resolve().parent.parent))

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

        # Also check idempotency via direct python call.
        written = audit_hook.build_audit_records_from_transcript(export_file)
        assert [p.name for p in written] == ["01_precal_try1.json", "02_calibrate_try1.json"]

        r1 = json.loads((wd / "orchestrator" / "01_precal_try1.json").read_text())
        assert r1["stage"] == "precal"
        assert r1["decision"] == "next"
        assert r1["handoff"] == "STAGE HANDOFF: precal\nstatus: completed"
        assert r1["agent_id"] == "ses_precal_1"
        assert [c["tool"] for c in r1["checks"]] == ["ms_workflow_status"]

        r2 = json.loads((wd / "orchestrator" / "02_calibrate_try1.json").read_text())
        assert r2["stage"] == "calibrate"
        assert r2["handoff"] == "STAGE HANDOFF: calibrate\nstatus: completed"
        assert r2["agent_id"] == "ses_cal_1"
