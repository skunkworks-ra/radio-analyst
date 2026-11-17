"""
Unit tests for ms_create/accounting.py on synthetic Claude Code session
transcripts: a Sonnet main session and two Haiku subagents. No CASA required.
"""

from __future__ import annotations

import io
import json

import pytest

from ms_create import accounting


def _asst(mid, model, blocks, usage):
    return {
        "type": "assistant",
        "message": {"id": mid, "model": model, "content": blocks, "usage": usage},
    }


def _write(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


@pytest.fixture
def transcript(tmp_path):
    main = tmp_path / "sess.jsonl"
    u = {
        "input_tokens": 10,
        "output_tokens": 100,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 0,
    }
    _write(
        main,
        [
            # one message split over two events: tool calls counted once each, last usage kept
            _asst(
                "m1",
                "claude-sonnet-5-5",
                [{"type": "tool_use", "id": "a1", "name": "Agent"}],
                {**u, "output_tokens": 1},
            ),
            _asst(
                "m1", "claude-sonnet-5-5", [{"type": "tool_use", "id": "a2", "name": "Agent"}], u
            ),
        ],
    )
    sub = tmp_path / "sess" / "subagents"
    sub.mkdir(parents=True)
    small = {
        "input_tokens": 2,
        "output_tokens": 20,
        "cache_read_input_tokens": 50_000,
        "cache_creation_input_tokens": 0,
    }
    big = {**small, "cache_read_input_tokens": 150_000}  # above Haiku's 100K tier
    _write(sub / "agent-x.jsonl", [_asst("p1", "claude-haiku-5-5", [], small)])
    (sub / "agent-x.meta.json").write_text(json.dumps({"agentType": "ra:precal-stage"}))
    _write(sub / "agent-y.jsonl", [_asst("c1", "claude-haiku-5-5", [], big)])
    (sub / "agent-y.meta.json").write_text(json.dumps({"agentType": "ra:calibrate-stage"}))
    return main


def test_tokens_tool_calls_and_list_price_cost(transcript):
    a = accounting.from_transcript(str(transcript))
    rows = {r["session"]: r for r in a["sessions"]}
    main = rows["main (orchestrator)"]
    assert main["messages"] == 1 and main["tool_calls"] == 2 and main["output_tokens"] == 100
    # Sonnet: 10*2 + 100*10 + 1000*0.05*2 = 1120 per 1e6
    assert main["cost_usd_estimate"] == round(1120 / 1e6, 4)
    pre, cal = rows["ra:precal-stage"], rows["ra:calibrate-stage"]
    assert pre["cost_usd_estimate"] == round((2 * 0.1 + 20 * 0.5 + 50_000 * 0.01) / 1e6, 4)
    # above the 100K tier: input 0.50, output 2.50
    assert cal["cost_usd_estimate"] == round((2 * 0.5 + 20 * 2.5 + 150_000 * 0.05) / 1e6, 4)
    assert set(a["model_cost_usd_estimate"]) == {"claude-sonnet-5-5", "claude-haiku-5-5"}


def test_cache_writes_priced_by_ttl():
    # orch_20261106/full2 main session (Sonnet, all writes 1-hour) and a
    # 5-minute Haiku message; Sonnet total equals the CLI's measured 1.4507101.
    sonnet = {
        "input_tokens": 48,
        "output_tokens": 57204,
        "cache_read_input_tokens": 2183021,
        "cache_creation_input_tokens": 165068,
        "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 165068},
    }
    assert round(accounting._cost("claude-sonnet-5-5", sonnet), 7) == 1.4507101
    haiku = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 1000,
        "cache_creation": {"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 0},
    }
    assert accounting._cost("claude-haiku-5-5", haiku) == pytest.approx(1000 * 0.1 * 1.25 / 1e6)
    # no TTL breakdown: all writes at the 5-minute rate
    del haiku["cache_creation"]
    assert accounting._cost("claude-haiku-5-5", haiku) == pytest.approx(1000 * 0.1 * 1.25 / 1e6)


def test_unknown_model_has_no_cost(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_asst("m", "some-other-model", [], {"input_tokens": 1})])
    a = accounting.from_transcript(str(p))
    assert a["sessions"][0]["cost_usd_estimate"] is None and a["total_cost_usd_estimate"] is None


def test_hook_uses_the_sessions_own_report_workdir(transcript, tmp_path, monkeypatch):
    wd = tmp_path / "run" / "work"
    wd.mkdir(parents=True)
    (wd / "report_inputs.json").write_text("{}")
    other = tmp_path / "other_run"  # an unrelated, newer report: must not be touched
    other.mkdir()
    (other / "report_inputs.json").write_text("{}")
    import ms_create.report as report

    calls = []
    monkeypatch.setattr(report, "run", lambda w, reuse_saved=False: calls.append((w, reuse_saved)))
    hook = {"transcript_path": str(transcript), "cwd": str(tmp_path)}

    # no ms_report call in the transcript: nothing written
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(hook)))
    assert accounting.main() == 0 and not (wd / "accounting.json").exists() and not calls

    call = _asst(
        "m9",
        "claude-sonnet-5-5",
        [
            {
                "type": "tool_use",
                "id": "r1",
                "name": "mcp__plugin_radio-analyst_ms-create__ms_report",
                "input": {"params": {"workdir": str(wd)}},
            }
        ],
        {},
    )
    with transcript.open("a") as fh:
        fh.write(json.dumps(call) + "\n")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(hook)))
    assert accounting.main() == 0
    assert (wd / "accounting.json").exists() and calls == [(str(wd), True)]
    assert not (other / "accounting.json").exists()
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert accounting.main() == 0


def test_opencode_session_and_child_exports_and_stringified_params(tmp_path, monkeypatch):
    """OpenCode session.json + session_*.json match Claude Code accounting + report rebuild."""
    wd = tmp_path / "opencode_work"
    wd.mkdir()
    (wd / "report_inputs.json").write_text("{}")

    main_doc = {
        "info": {
            "id": "ses_root",
            "agent": "orchestrate",
            "model": {"providerID": "nrp", "id": "glm-5"},
            "time": {"created": 1000},
        },
        "messages": [
            {
                "info": {
                    "id": "msg_u1",
                    "role": "user",
                },
                "parts": [{"type": "text", "text": "go"}],
            },
            {
                "info": {
                    "id": "msg_a1",
                    "role": "assistant",
                    "providerID": "nrp",
                    "modelID": "glm-5",
                    "tokens": {
                        "input": 12000,
                        "output": 250,
                        "reasoning": 400,
                        "cache": {"read": 0, "write": 0},
                    },
                },
                "parts": [
                    {"type": "tool", "callID": "c1", "tool": "task", "state": {"input": {}}},
                    {
                        "type": "tool",
                        "callID": "c2",
                        "tool": "ms-create_ms_report",
                        "state": {
                            # OpenCode models often pass params as a JSON-encoded string
                            "input": {"params": json.dumps({"workdir": str(wd)})}
                        },
                    },
                ],
            },
        ],
    }
    child_inspect = {
        "info": {
            "id": "ses_c1",
            "parentID": "ses_root",
            "agent": "inspect-stage",
            "model": {"providerID": "nrp", "id": "kimi"},
            "time": {"created": 2000},
        },
        "messages": [
            {
                "info": {
                    "id": "m_i1",
                    "role": "assistant",
                    "providerID": "nrp",
                    "modelID": "kimi",
                    "tokens": {
                        "input": 4000,
                        "output": 80,
                        "reasoning": 0,
                        "cache": {"read": 1000, "write": 0},
                    },
                },
                "parts": [
                    {
                        "type": "tool",
                        "callID": "ic1",
                        "tool": "ms-inspect_ms_field_list",
                        "state": {"input": {}},
                    }
                ],
            }
        ],
    }
    child_precal = {
        "info": {
            "id": "ses_c2",
            "parentID": "ses_root",
            "agent": "precal-stage",
            "model": {"providerID": "nrp", "id": "kimi"},
            "time": {"created": 3000},
        },
        "messages": [
            {
                "info": {
                    "id": "m_p1",
                    "role": "assistant",
                    "providerID": "nrp",
                    "modelID": "kimi",
                    "tokens": {
                        "input": 9000,
                        "output": 150,
                        "reasoning": 0,
                        "cache": {"read": 0, "write": 0},
                    },
                },
                "parts": [],
            }
        ],
    }
    unrelated_child = {
        "info": {
            "id": "ses_other",
            "parentID": "ses_someone_else",
            "agent": "calibrate-stage",
            "time": {"created": 1500},
        },
        "messages": [],
    }

    main_path = tmp_path / "session.json"
    main_path.write_text(json.dumps(main_doc))
    (tmp_path / "session_ses_c2.json").write_text(json.dumps(child_precal))
    (tmp_path / "session_ses_c1.json").write_text(json.dumps(child_inspect))
    (tmp_path / "session_ses_other.json").write_text(json.dumps(unrelated_child))

    acct = accounting.from_transcript(str(main_path))
    assert [r["session"] for r in acct["sessions"]] == [
        "main (orchestrator)",
        "inspect-stage",
        "precal-stage",
    ]
    assert acct["sessions"][0]["model"] == "nrp/glm-5"
    assert acct["sessions"][0]["input_tokens"] == 12000
    assert acct["sessions"][0]["output_tokens"] == 250
    assert acct["sessions"][0]["reasoning_tokens"] == 400
    assert acct["sessions"][0]["tool_calls"] == 2
    assert acct["sessions"][0]["cost_usd_estimate"] is None
    assert acct["sessions"][1]["cache_read_input_tokens"] == 1000
    assert acct["total_cost_usd_estimate"] is None

    import ms_create.report as report

    calls = []
    monkeypatch.setattr(report, "run", lambda w, reuse_saved=False: calls.append((w, reuse_saved)))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"transcript_path": str(main_path), "cwd": str(wd)})),
    )
    assert accounting.main() == 0
    assert (wd / "accounting.json").is_file()
    assert calls == [(str(wd), True)]
