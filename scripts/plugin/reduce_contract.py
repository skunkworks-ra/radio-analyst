"""Score MCP calls against the reduce contract (.claude/skills/reduce/stages.json).

Shared by scripts/dev/score_run.py (reads a run's trace.jsonl) and
scripts/plugin/reduce_hook.py (reads the session's hook log). Stdlib only.

A call is a dict: line (order), tool (bare ms_* name), input (params unwrapped), ok.
"""

import json
import re
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / ".claude/skills/reduce/stages.json"
TOOL_RE = re.compile(r"ms_[a-z_]+")
TARGET_KEYS = ("caltable_path", "image_path")


def make_call(line: int, name: str, inp, ok) -> dict:
    inp = inp if isinstance(inp, dict) else {}
    if isinstance(inp.get("params"), dict):
        inp = inp["params"]
    return {"line": line, "tool": name.split("__")[-1], "input": inp, "ok": ok}


def calls_from_trace(trace: Path) -> list[dict]:
    """MCP calls from claude -p stream-json, ok from the matching tool_result."""
    calls, by_id = [], {}
    for n, line in enumerate(trace.open(), 1):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = ev.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if b.get("type") == "tool_use" and b.get("name", "").startswith("mcp__"):
                c = make_call(n, b["name"], b.get("input"), None)
                calls.append(c)
                by_id[b["id"]] = c
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                by_id[b["tool_use_id"]]["ok"] = not b.get("is_error", False)
    return calls


def base(name: str) -> str:
    m = TOOL_RE.match(name)
    return m.group(0) if m else name


def matches(call: dict, rule: dict) -> bool:
    return all(re.search(rx, str(call["input"].get(k, ""))) for k, rx in rule.items())


def target(call: dict) -> str | None:
    for k in TARGET_KEYS:
        if k in call["input"]:
            return str(call["input"][k])
    return None


def _class(tool: str, cache: dict) -> tuple[str, list[str]]:
    for cls, spec in cache.items():
        if isinstance(spec, dict) and tool in spec.get("tools", []):
            return cls, [base(t) for t in spec["invalidated_by"]]
    return "unclassified", []


def _invalidates(c, cls, inv, tgt, ms, actions) -> bool:
    if cls == "always":
        return c["tool"] in actions
    if cls == "caltable":
        if c["tool"] == "ms_flag_caltable":
            return tgt is not None and target(c) == tgt
        out = c["input"].get("fluxtable" if c["tool"] == "ms_fluxscale" else "caltable", "")
        return c["tool"] in actions and tgt is not None and str(out) == tgt
    if cls == "image":
        name = str(c["input"].get("imagename", ""))
        return c["tool"] == "ms_tclean" and bool(name) and tgt is not None and tgt.startswith(name)
    return c["tool"] in inv and c["input"].get("ms_path") in (None, ms)


def _check(calls, tool, lo, hi, cache, actions, want_target=None) -> str:
    """OK / CACHED / STALE / MISSING for one check that must hold over (lo, hi)."""
    cls, inv = _class(tool, cache)
    for c in reversed(calls):
        if c["line"] >= hi or c["tool"] != tool or not c["ok"]:
            continue
        if want_target and target(c) is not None and target(c) != want_target:
            continue
        if c["line"] > lo:
            return f"OK L{c['line']}"
        later = [x for x in calls if c["line"] < x["line"] < hi and x["ok"]]
        ms = c["input"].get("ms_path")
        if not any(_invalidates(x, cls, inv, target(c), ms, actions) for x in later):
            return f"CACHED L{c['line']}"
        return f"STALE L{c['line']}"
    return "MISSING"


def score(calls: list[dict], contract: dict) -> dict:
    """Per-step report lines, the open items, and totals."""
    cache = contract["cache"]
    all_steps = [s for st in contract["stages"] for s in st["steps"]]
    actions = {base(s["action"]) for s in all_steps if s.get("action")}

    # the call that worked for each action step: last ok call matching tool + match rules
    found = {}
    for s in all_steps:
        if s.get("action"):
            hits = [c for c in calls if c["tool"] == base(s["action"]) and c["ok"]]
            hits = [c for c in hits if matches(c, s.get("match", {}))]
            found[s["id"]] = hits[-1] if hits else None

    lines, open_items = [], []
    # an optional stage with none of its actions called is skipped, not scored
    skipped = [
        st["stage"]
        for st in contract["stages"]
        if st.get("optional") and not any(found.get(x["id"]) for x in st["steps"])
    ]
    for name in skipped:
        lines.append(f"[{name}] skipped (optional, no action called)")
    stage_of = {s["id"]: st["stage"] for st in contract["stages"] for s in st["steps"]}
    steps = [s for s in all_steps if stage_of[s["id"]] not in skipped]
    found = {k: v for k, v in found.items() if k in {s["id"] for s in steps}}

    end = (calls[-1]["line"] + 1) if calls else 1
    # windows are in time: a check belongs between its action and the next write action
    writes = sorted(c["line"] for c in calls if c["tool"] in actions and c["ok"])
    ledger = [
        c
        for c in calls
        if c["tool"] == "ms_reduction_log" and c["ok"] and c["input"].get("action") == "append"
    ]
    n_chk = n_ok = 0
    for i, s in enumerate(steps):
        act = found.get(s["id"])
        if act:
            hi = next((ln for ln in writes if ln > act["line"]), end)
        else:
            nxt = next((found[t["id"]] for t in steps[i + 1 :] if found.get(t["id"])), None)
            hi = nxt["line"] if nxt else end
        prev_line = max((ln for ln in writes if ln < (act["line"] if act else hi)), default=0)
        tag = f"[{stage_of[s['id']]}] {s['id']} {s.get('action') or '-'}"
        when = f"  when: {s['when']}" if s.get("when") else ""
        if s.get("action"):
            n_calls = sum(
                c["tool"] == base(s["action"]) and matches(c, s.get("match", {})) for c in calls
            )
            head = f"L{act['line']} ({n_calls} calls)" if act else "NOT CALLED"
        else:
            head = "checks only"
        lines.append(f"{tag}: {head}{when}")
        if s.get("action") and not act:
            open_items.append(f"{tag}: not called{when}")
            continue
        lo = act["line"] if act else prev_line
        cal = (str(act["input"].get("caltable", "")) or None) if act else None
        img = (str(act["input"].get("imagename", "")) or None) if act else None
        for side, (wlo, whi) in (("before", (prev_line, lo)), ("after", (lo, hi))):
            for chk in s.get(side, []):
                tool = base(chk)
                st = _check(calls, tool, wlo, whi, cache, actions, cal if side == "after" else None)
                if side == "after" and tool == "ms_image_stats" and img:
                    hits = [
                        c for c in calls if c["tool"] == tool and c["ok"] and lo < c["line"] < hi
                    ]
                    own = [c for c in hits if (target(c) or "").startswith(img)]
                    if own:
                        st = f"OK L{own[-1]['line']}"
                    elif hits:
                        st = f"OTHER IMAGE L{hits[-1]['line']} {target(hits[-1])} (ms_tclean imagename {img})"
                    else:
                        st = "MISSING"
                n_chk += 1
                good = st.startswith(("OK", "CACHED"))
                n_ok += good
                lines.append(f"    {side:6} {chk}: {st}")
                if not good:
                    open_items.append(f"{tag} {side}: {chk}: {st}")
        if act:
            led = [c for c in ledger if lo < c["line"] < hi]
            lines.append(f"    ledger: {'L' + str(led[0]['line']) if led else 'MISSING'}")
            if not led:
                open_items.append(f"{tag}: no ms_reduction_log append after it")

    n_act = sum(1 for v in found.values() if v)
    return {
        "lines": lines,
        "open": open_items,
        "actions": (n_act, len(found)),
        "checks": (n_ok, n_chk),
    }
