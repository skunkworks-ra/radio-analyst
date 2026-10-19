"""
reduction_log.py — ms_reduction_log

A place to shuttle KNOWN-GOOD calls as a reduction proceeds. After a tool call
succeeds, append it here with the exact parameters that worked, the salient
output, and why it was done. The accumulated log is the replayable "working
path" through the data — the canonical recipe for this dataset, and the
artifact a cheaper model (or a future run) can replay step by step.

Only validated calls should be shuttled in: failed attempts and dead ends stay
out, so the ledger is the clean path, not the search for it.

Storage is a JSON-lines file `reduction_log.jsonl` in the workdir — one record
per line, append-only, trivially diffable and greppable.

Actions:
  append  — record one working call (tool, params, outputs, rationale, rule,
            script_path). `tool` is the write tool's own name, or 'manual' for
            work done off the tools; anything else is refused, so render can
            map every entry. A call not run with execute=True must name the
            script that was actually run; its sha256 is stored with it.
  render  — emit the ordered recipe and a replay Python script: each entry with
            a script re-runs that script (hash checked first), the rest call run()
  list    — compact summary (step, tool, rationale) of the recorded path
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.logs import write_script

TOOL_NAME = "ms_reduction_log"

_LOG_NAME = "reduction_log.jsonl"


def _log_path(workdir: str) -> Path:
    return Path(workdir) / _LOG_NAME


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# Maps the recorded tool name to the package module whose run() implements it.
# Steps whose tool name is not in this registry are emitted as MANUAL markers
# (e.g. ad-hoc casatasks bypasses), so the script is honest about what it can
# and cannot replay automatically.
_RUN_REGISTRY: dict[str, str] = {
    "ms_sdm_summary": "ms_create.sdm_summary",
    "ms_import_asdm": "ms_create.import_asdm",
    # NOTE: ms_set_intents is intentionally NOT registered — its entrypoint is
    # set_intents(), not run(), so it cannot be replayed via the run() convention
    # and is emitted as a MANUAL step. It is also a rare one-off (only for MSs
    # that lack scan intents).
    "ms_apply_preflag": "ms_modify.preflag",
    "ms_generate_priorcals": "ms_modify.priorcals",
    "ms_initial_bandpass": "ms_modify.initial_bandpass",
    "ms_apply_initial_rflag": "ms_modify.initial_rflag",
    "ms_setjy": "ms_modify.setjy",
    "ms_setjy_polcal": "ms_modify.setjy_polcal",
    "ms_gaincal": "ms_modify.gaincal",
    "ms_bandpass": "ms_modify.bandpass",
    "ms_fluxscale": "ms_modify.fluxscale",
    "ms_polcal": "ms_modify.polcal",
    "ms_applycal": "ms_modify.applycal",
    "ms_apply_rflag": "ms_modify.rflag",
    "ms_flag_caltable": "ms_modify.flag_caltable",
    "ms_tclean": "ms_modify.tclean",
}


# What append accepts: the replayable write tools, set_intents (replayed from its
# script), and 'manual' for off-tool work (a hand-edited or hand-written script).
_APPENDABLE = frozenset(_RUN_REGISTRY) | {"ms_set_intents", "manual"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_append(tool: str, params: dict, script_path: str, workdir: str) -> dict:
    """Refuse an entry render could not replay; return the script fields to store."""
    from ms_inspect.exceptions import ComputationError

    if tool not in _APPENDABLE:
        raise ComputationError(
            f"tool {tool!r} is not a replayable step. Use the write tool's own name "
            f"({', '.join(sorted(_APPENDABLE))}), one entry per call; 'manual' for work "
            "off the tools. Record checks in the outputs of the step they verify.",
            ms_path=workdir,
        )
    execute = params.get("execute", False)
    if not isinstance(execute, bool):
        raise ComputationError(
            f"params.execute must be the literal true/false passed to the tool, got {execute!r}.",
            ms_path=workdir,
        )
    if not script_path:
        if tool == "manual" or not execute:
            raise ComputationError(
                f"script_path is required for {tool!r} unless it ran with execute=true: "
                "name the script that was actually run (generated, edited, or your own).",
                ms_path=workdir,
            )
        return {}
    path = Path(script_path)
    if not path.is_absolute():
        path = Path(workdir) / path
    if not path.is_file():
        raise ComputationError(f"script_path does not exist: {path}", ms_path=workdir)
    return {"script_path": str(path.resolve()), "script_sha256": _sha256(path)}


_RUN_SCRIPT_HELPER = [
    "import hashlib",
    "import subprocess",
    "import sys",
    "",
    "",
    "def _run_script(path, sha256):",
    "    with open(path, 'rb') as fh:",
    "        if hashlib.sha256(fh.read()).hexdigest() != sha256:",
    "            sys.exit(f'{path} changed since it was recorded; not replaying')",
    "    subprocess.run([sys.executable, path], check=True)",
    "",
]


def _replay_script(records: list[dict]) -> str:
    """
    Render an EXECUTABLE replay of the recorded working calls.

    Each recognised step becomes ``importlib.import_module(mod).run(**params)``.
    Faithful replay requires the appended params to be the literal working
    kwargs (absolute paths, full gaintable lists) — abbreviated/placeholder
    params will not run as-is.
    """
    lines = [
        "#!/usr/bin/env python",
        '"""',
        "Auto-generated by ms_reduction_log render — executable replay of the",
        "working path. Run inside the project environment (pixi run python ...).",
        "Review before running: paths and selections are dataset-specific.",
        '"""',
        "import importlib",
        *_RUN_SCRIPT_HELPER,
        "",
    ]
    for r in records:
        tool = r.get("tool", "?")
        params = r.get("params", {})
        rationale = r.get("rationale")
        if rationale:
            lines.append(f"# step {r.get('step')}: {rationale}")
        mod = _RUN_REGISTRY.get(tool)
        if r.get("script_path"):
            lines.append(f"_run_script({r['script_path']!r}, {r.get('script_sha256')!r})  # {tool}")
        elif mod is None:
            lines.append(f"# MANUAL STEP — no run() mapping for {tool!r}:")
            lines.append(f"#   params = {params!r}")
        else:
            lines.append(f"importlib.import_module({mod!r}).run(")
            for k, v in params.items():
                lines.append(f"    {k}={v!r},")
            lines.append(")")
        lines.append("")
    return "\n".join(lines)


def run(
    action: str,
    workdir: str,
    tool: str = "",
    params: dict | None = None,
    outputs: dict | None = None,
    rationale: str = "",
    skill_rule: str = "",
    status: str = "ok",
    script_path: str = "",
) -> dict:
    """
    Append to / render / list the reduction working-calls ledger.

    Args:
        action:     'append', 'render', or 'list'.
        workdir:    Directory holding (or to hold) reduction_log.jsonl.
        tool:       (append) name of the tool/call that worked, e.g. 'ms_gaincal'.
        params:     (append) exact parameters that worked.
        outputs:    (append) salient outputs worth recording (paths, key numbers).
        rationale:  (append) why this step was done.
        skill_rule: (append) skill file / threshold cited, e.g. '07 Step 3'.
        status:     (append) outcome tag; default 'ok'. Only shuttle working calls.
        script_path: (append) the script that was run; required unless the call
                    ran with execute=True. Its sha256 is stored for replay.

    Returns:
        Standard envelope. append → n_records; render → recipe + replay_script;
        list → compact step/tool/rationale summary.
    """
    wd = Path(workdir)
    if not wd.is_dir():
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(f"workdir does not exist: {workdir}", ms_path=workdir)

    path = _log_path(workdir)

    if action == "append":
        script = _validate_append(tool, params or {}, script_path, workdir)
        records = _read_records(path)
        record = {
            "step": len(records) + 1,
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": tool,
            "params": params or {},
            "outputs": outputs or {},
            "rationale": rationale,
            "skill_rule": skill_rule,
            "status": status,
            **script,
        }
        with path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={
                "action": "append",
                "log_path": fmt_field(str(path)),
                "step_recorded": fmt_field(record["step"]),
                "n_records": fmt_field(len(records) + 1),
            },
            casa_calls=[f"append → {path}"],
        )

    records = _read_records(path)

    if action == "list":
        summary = [
            {
                "step": r.get("step"),
                "tool": r.get("tool"),
                "rationale": r.get("rationale"),
                "skill_rule": r.get("skill_rule"),
            }
            for r in records
        ]
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={"action": "list", "n_records": fmt_field(len(records)), "steps": summary},
            casa_calls=[f"read → {path}"],
        )

    if action == "render":
        script = _replay_script(records)
        script_path = wd / "reduction_replay.py"
        write_script(script_path, script)
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={
                "action": "render",
                "n_records": fmt_field(len(records)),
                "recipe": fmt_field(records),
                "replay_script": fmt_field(str(script_path)),
            },
            casa_calls=[f"read → {path}", f"write → {script_path}"],
        )

    from ms_inspect.exceptions import ComputationError

    raise ComputationError(
        f"Unknown action '{action}'; use 'append', 'render', or 'list'.",
        ms_path=workdir,
    )
