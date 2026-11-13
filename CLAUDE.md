# CLAUDE.md -- radio-analyst

Project contract for Claude Code and contributors. Full developer reference and
the 61-tool inventory live in [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md);
architecture lives in [`design_docs/DESIGN.md`](design_docs/DESIGN.md).

## Project summary

Three MCP servers for CASA radio interferometric reduction (VLA/JVLA/EVLA,
MeerKAT, uGMRT), 61 tools total:

- **ms-inspect** -- read-only inspection and diagnostics (38 tools, port 8000)
- **ms-modify** -- calibration, flagging, and MS modification (19 tools, port 8001)
- **ms-create** -- ASDM ingestion, reduction logging, and reporting (4 tools, port 8002)

## Core contract -- do not violate

> **Tools measure. The Skill reasons.**

Every MCP tool must obey three rules:

1. **One question, one answer.** Return measurements and completeness flags;
   never suggest a next step and never chain to another tool.
2. **No gates.** Return derived scalars, rankings, and descriptive labels **with
   their inputs and constants surfaced**, never boolean verdicts (`*_pass`,
   `*_feasible`, `blocker`, `verdict`) or withheld values.
3. **Explicit uncertainty.** Tag every degraded or missing field with a
   `CompletionFlag` (`COMPLETE`, `INFERRED`, `PARTIAL`, `SUSPECT`,
   `UNAVAILABLE`). Never use silence to signal failure.

**One named exception:** `ms_workflow_status.next_recommended_step` gates strictly
on filesystem/column presence and fails visibly (`probe_failed_*` + `UNAVAILABLE`).
Do not add a second exception.

## Wire envelope & sidecar rules

- **`data` holds bare values** (`data["n_antennas"] == 27`, never `.value` wrappers).
- **`completeness_summary`** reports the worst-case `CompletionFlag` across all
  fields, preserved even when detail arrays are offloaded to sidecars.
- **`field_flags`** lists only non-`COMPLETE` or annotated dotted paths
  (`{"antennas[*].x_m": {"flag": "SUSPECT", "note": "..."}}`).
- **`provenance`** is omitted from MCP wire responses and logged to `events.jsonl`.
- **Sidecars** (`resolve_sidecar_path`) write under `<workdir>/sidecars/` or
  `RADIO_MCP_DIR/sidecars/` -- never next to `ms_path` (which may be read-only).

## Execution, ledger & CASA safety invariants

- **CASA table locks:** Open every table/MS/image exclusively via context
  managers in `src/ms_inspect/util/casa_context.py` (`open_msmd`, `open_table`,
  `open_ms`, `open_image`). Never call raw `tb.open()` / `tb.close()`.
- **Bounded-wait script runner:** Execute generated CASA scripts via
  `bash <plugin_or_repo>/scripts/plugin/run-step.sh <python> <script> --wait 240`
  (Bash `timeout=300000`). Re-run the exact same command on `status=running`;
  stop immediately on `status=crashed` or non-zero `rc`.
- **Automatic ledger:** Write tools append directly to `<workdir>/stage_log.jsonl`;
  `ms_reduction_log` and `ms_report` derive the replay recipe from `stage_log.jsonl`
  automatically without stage-agent `append` calls.
- **Stage bundles:** Regenerate `.claude/skills/radio-interferometry/bundles/*.md`
  with `pixi run gen-stage-bundles` whenever stage skill files or tool grants change.
- **Verification gates:** Run `pixi run check` and `pixi run test-unit` before committing.
