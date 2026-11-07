"""
Unit tests for ms_create/accounting.py on a small synthetic stream-json
transcript: one Sonnet main session, two Haiku stage agents.
"""

from __future__ import annotations

import json

from ms_create.accounting import from_claude_stream


def _asst(mid, model, blocks, usage, parent=None):
    return {
        "type": "assistant",
        "parent_tool_use_id": parent,
        "message": {"id": mid, "model": model, "content": blocks, "usage": usage},
    }


def test_sessions_tool_calls_and_cost_split(tmp_path):
    u = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 0,
    }
    ev = [
        # main message split over two events: one Agent call per event
        _asst(
            "m1",
            "S",
            [
                {
                    "type": "tool_use",
                    "id": "a1",
                    "name": "Agent",
                    "input": {"subagent_type": "x:precal-stage"},
                }
            ],
            u,
        ),
        _asst(
            "m1",
            "S",
            [
                {
                    "type": "tool_use",
                    "id": "a2",
                    "name": "Agent",
                    "input": {"subagent_type": "x:image-stage"},
                }
            ],
            u,
        ),
        _asst(
            "p1",
            "H",
            [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            {**u, "cache_read_input_tokens": 300},
            parent="a1",
        ),
        _asst(
            "i1",
            "H",
            [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}],
            {**u, "cache_read_input_tokens": 100},
            parent="a2",
        ),
        {
            "type": "result",
            "num_turns": 3,
            "duration_ms": 1000,
            "total_cost_usd": 1.2,
            "modelUsage": {
                "S": {
                    "costUSD": 1.0,
                    "outputTokens": 50,
                    "inputTokens": 1,
                    "cacheReadInputTokens": 100,
                    "cacheCreationInputTokens": 0,
                },
                "H": {"costUSD": 0.2},
            },
        },
    ]
    p = tmp_path / "orch.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in ev))
    a = from_claude_stream(str(p))
    rows = {r["session"]: r for r in a["sessions"]}
    main = rows["main (orchestrator)"]
    assert main["tool_calls"] == 2 and main["messages"] == 1
    assert main["tokens_exact"] and main["output_tokens"] == 50 and main["cost_usd_estimate"] == 1.0
    pre, img = rows["x:precal-stage"], rows["x:image-stage"]
    assert not pre["tokens_exact"]
    assert round(pre["cost_usd_estimate"] + img["cost_usd_estimate"], 4) == 0.2
    assert pre["cost_usd_estimate"] > img["cost_usd_estimate"]
