"""
stage_decision.py -- ms_record_stage_decision

Writes ``{workdir}/orchestrator/{seq:02d}_{stage}_try{attempt}.json`` directly
as a validated MCP tool call, using the exact schema produced by
``ms_create.audit_hook``.

Why a tool call instead of assistant prose XML:
- In headless runners (`opencode run`, `claude -p`), emitting prose
  `<stage_decision>...</stage_decision>` without a tool call triggers
  `step_finish reason="stop"` and terminates the session mid-reduction.
- Recording the decision via an MCP tool call always returns control to the
  orchestrator model, eliminating early-exit stops on `"next"` / `"retry"`
  decisions while writing the audit JSON immediately on disk.
- On Stop / SessionEnd, `scripts/plugin/audit_hook.sh` still enriches the same
  JSON file with the full transcript `prompt`, `handoff`, `checks`, `agent_id`,
  and `agent_usage` (and remains backwards-compatible with XML blocks).

No CASA dependency.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_record_stage_decision"

VALID_STAGES: tuple[str, ...] = (
    "inspect",
    "precal",
    "calibrate",
    "polcal",
    "image",
    "postcal",
    "selfcal",
    "image_iquv",
)

VALID_DECISIONS: tuple[str, ...] = (
    "next",
    "retry",
    "stop_ask_user",
)


def _safe_stage_slug(stage: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", stage.strip()).strip("_")
    return slug or "stage"


def run(
    seq: int,
    stage: str,
    attempt: int,
    workdir: str,
    decision: str,
    deciding_metric: str,
    reason: str,
    debug_directive: dict | None = None,
    png_reviewed: str | None = None,
) -> dict:
    """Validate and write ``{workdir}/orchestrator/{seq:02d}_{stage}_try{attempt}.json``."""
    if seq < 1:
        raise ComputationError(f"seq must be >= 1, got {seq}.", ms_path="")
    if attempt < 1 or attempt > 5:
        raise ComputationError(f"try/attempt must be in 1..5, got {attempt}.", ms_path="")

    stage_clean = stage.strip()
    if stage_clean not in VALID_STAGES:
        raise ComputationError(
            f"Unsupported stage={stage!r}; expected one of {list(VALID_STAGES)}.",
            ms_path="",
        )

    decision_clean = decision.strip()
    if decision_clean not in VALID_DECISIONS:
        raise ComputationError(
            f"Unsupported decision={decision!r}; expected one of {list(VALID_DECISIONS)}.",
            ms_path="",
        )

    metric_clean = deciding_metric.strip()
    if not metric_clean:
        raise ComputationError("deciding_metric must be a non-empty string.", ms_path="")

    reason_clean = reason.strip()
    if not reason_clean:
        raise ComputationError("reason must be a non-empty string.", ms_path="")

    wd_path = Path(workdir).expanduser().resolve()
    if not wd_path.is_dir():
        raise ComputationError(f"workdir does not exist: {workdir}", ms_path="")

    if debug_directive is not None and not isinstance(debug_directive, dict):
        raise ComputationError("debug_directive must be null or a JSON object.", ms_path="")

    safe_stage = _safe_stage_slug(stage_clean)
    orch_dir = wd_path / "orchestrator"
    orch_dir.mkdir(parents=True, exist_ok=True)
    out_file = orch_dir / f"{seq:02d}_{safe_stage}_try{attempt}.json"

    record: dict[str, object] = {
        "n": int(seq),
        "stage": stage_clean,
        "attempt": int(attempt),
        "workdir": str(wd_path),
        "prompt": "",
        "handoff": "",
        "checks": [],
        "decision": decision_clean,
        "deciding_metric": metric_clean,
        "reason": reason_clean,
        "debug_directive": debug_directive,
        "agent_id": None,
        "png_reviewed": png_reviewed,
        "agent_usage": None,
    }

    payload = json.dumps(record, indent=2) + "\n"
    tmp_file = out_file.with_suffix(".json.tmp")
    tmp_file.write_text(payload)
    tmp_file.replace(out_file)

    data = {
        "record_path": fmt_field(str(out_file)),
        "seq": fmt_field(int(seq)),
        "stage": fmt_field(stage_clean),
        "attempt": fmt_field(int(attempt)),
        "decision": fmt_field(decision_clean),
        "workdir": fmt_field(str(wd_path)),
        "recorded": fmt_field(True),
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path="",
        data=data,
        warnings=[],
        casa_calls=[],
    )
