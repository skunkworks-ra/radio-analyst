"""
accounting.py — per-session accounting of a Claude Code headless run.

Reads the stream-json transcript of `claude -p --output-format stream-json`
and writes `accounting.json` for ms_report's "Cost and sessions" table.

What is measured and what is estimated:
  - Tool calls, messages and cache tokens per session are MEASURED from the
    stream (subagent messages carry the parent Agent call's id in
    `parent_tool_use_id`). The stream's output_tokens are not final, so they are
    a lower bound, except for a model's only session, which takes exact counts
    from the CLI's modelUsage.
  - Cost per model is MEASURED: the CLI's own `modelUsage[model].costUSD` in
    the final `result` event.
  - Cost per session is an ESTIMATE: each model's measured cost split over that
    model's sessions by a token weight (input 1, output OUTPUT_WEIGHT, cache
    read CACHE_READ_WEIGHT, cache write CACHE_WRITE_WEIGHT, relative to input).
    Output tokens are not in the weight: the stream does not carry a session's
    real output (it holds about 1.5% of it), so splitting by output would
    follow noise. List prices alone did not reproduce the measured totals
    (full2, list-price estimate over measured: Sonnet 1.15, Haiku 0.55; the
    Haiku tier above 100K-token prompts is one reason), so only the split is
    estimated and every model's total stays the measured one. A model with one
    session (the orchestrator) gets its exact cost.

No CASA dependency.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

#: Token weights relative to an input token, for splitting a model's measured
#: cost across its sessions: list-price ratios (cache read 0.1x, 5-minute cache
#: write 1.25x). Output is left out; see the module docstring.
CACHE_READ_WEIGHT = 0.1
CACHE_WRITE_WEIGHT = 1.25

ACCOUNTING_NAME = "accounting.json"


def from_claude_stream(jsonl_path: str) -> dict:
    """Per-session tokens and cost from a Claude Code stream-json transcript."""
    events = [
        json.loads(line) for line in Path(jsonl_path).read_text().splitlines() if line.strip()
    ]
    agent_type: dict[str, str] = {}
    # One message arrives as several events (one per content block), all with
    # the same message id: tool calls are counted over every event, and the
    # usage is the last event's (it carries the message's final counts).
    per_msg: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message", {})
        blocks = msg.get("content", [])
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                agent_type[block["id"]] = block.get("input", {}).get("subagent_type", "")
        m = per_msg.setdefault(
            msg.get("id"),
            {
                "key": ev.get("parent_tool_use_id") or "main",
                "tool_ids": set(),
                "usage": {},
                "model": None,
            },
        )
        m["tool_ids"].update(b.get("id") for b in blocks if b.get("type") == "tool_use")
        m["usage"] = msg.get("usage") or m["usage"]
        m["model"] = msg.get("model") or m["model"]
    sessions: dict[str, dict] = defaultdict(
        lambda: {
            "messages": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "models": set(),
        }
    )
    for m in per_msg.values():
        s = sessions[m["key"]]
        u = m["usage"]
        s["messages"] += 1
        s["tool_calls"] += len(m["tool_ids"])
        s["input_tokens"] += u.get("input_tokens") or 0
        s["output_tokens"] += u.get("output_tokens") or 0
        s["cache_read_tokens"] += u.get("cache_read_input_tokens") or 0
        s["cache_write_tokens"] += u.get("cache_creation_input_tokens") or 0
        if m["model"]:
            s["models"].add(m["model"])

    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    model_cost = {m: u.get("costUSD") for m, u in (result.get("modelUsage") or {}).items()}
    # The stream's per-message output_tokens are not final (it under-counts
    # output); a model with a single session takes its exact counts from the
    # CLI's modelUsage. Elsewhere output_tokens is a lower bound.
    model_usage = result.get("modelUsage") or {}
    n_sessions: dict[str, int] = defaultdict(int)
    for s_ in sessions.values():
        if len(s_["models"]) == 1:
            n_sessions[next(iter(s_["models"]))] += 1
    for s_ in sessions.values():
        mu = model_usage.get(next(iter(s_["models"]))) if len(s_["models"]) == 1 else None
        s_["tokens_exact"] = bool(mu) and n_sessions[next(iter(s_["models"]))] == 1
        if s_["tokens_exact"]:
            s_["input_tokens"] = mu.get("inputTokens", s_["input_tokens"])
            s_["output_tokens"] = mu.get("outputTokens", s_["output_tokens"])
            s_["cache_read_tokens"] = mu.get("cacheReadInputTokens", s_["cache_read_tokens"])
            s_["cache_write_tokens"] = mu.get("cacheCreationInputTokens", s_["cache_write_tokens"])

    def weight(s: dict) -> float:
        return (
            s["input_tokens"]
            + CACHE_READ_WEIGHT * s["cache_read_tokens"]
            + CACHE_WRITE_WEIGHT * s["cache_write_tokens"]
        )

    by_model: dict[str, float] = defaultdict(float)
    for s in sessions.values():
        if len(s["models"]) == 1:
            by_model[next(iter(s["models"]))] += weight(s)

    rows = []
    for key, s in sessions.items():
        model = next(iter(s["models"])) if len(s["models"]) == 1 else ",".join(sorted(s["models"]))
        total = model_cost.get(model)
        share = weight(s) / by_model[model] if by_model.get(model) else None
        rows.append(
            {
                "session": "main (orchestrator)" if key == "main" else agent_type.get(key, key),
                "tool_use_id": None if key == "main" else key,
                "model": model,
                **{k: v for k, v in s.items() if k != "models"},
                "cost_usd_estimate": round(total * share, 4)
                if total is not None and share is not None
                else None,
            }
        )
    return {
        "source": str(jsonl_path),
        "num_turns": result.get("num_turns"),
        "duration_s": (result.get("duration_ms") or 0) / 1000,
        "total_cost_usd": result.get("total_cost_usd"),
        "model_cost_usd": model_cost,
        "permission_denials": [d.get("tool_name") for d in result.get("permission_denials", [])],
        "sessions": rows,
        "note": (
            "Per-model cost is measured (CLI modelUsage). A session that is its model's "
            "only one has exact tokens and cost. For the others, output_tokens is a lower "
            "bound (the stream holds only part of it), the stream also misses some cache "
            "tokens (so those rows need not sum to the model's totals), and cost splits "
            "the model's measured cost by input-side tokens (accounting.py): an estimate."
        ),
    }


def write(jsonl_path: str, workdir: str) -> Path:
    """Write <workdir>/accounting.json from a stream-json transcript."""
    out = Path(workdir) / ACCOUNTING_NAME
    out.write_text(json.dumps(from_claude_stream(jsonl_path), indent=1))
    return out
