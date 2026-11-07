# Orchestrator build plan (draft)

Branch `orchestrator`, off `min_viable` f7e419f. Design: `docs/architecture-review.md`
Parts B and C. Retry cap 5 per stage (his number, empirical).

Rules for the build: adversary (Sonnet) on this plan and on every change before
its commit; `pixi run check` and `pixi run test-unit` before each commit; no
constant copied from another file (import it from its single source); Haiku run
at the end, per `HAIKU_STAGE_METHOD.md`.

## Assumption on debug mode (his words: "keep the limited set of guessed params
but have a flag that would let the model turn it off when on retry")

- Default call: the task exposes a small curated parameter set with defaults.
  Nothing else is accepted.
- `debug=True`: every parameter in the task's CASA XML is accepted, and the
  curated defaults can be overridden. The script header and the stage log
  record `debug=True` and the parameters that were overridden.
- The tool does not decide when debug is allowed (a tool-side "only on retry"
  check would be a second state gate; CLAUDE.md allows one). The orchestrator
  passes `debug` to the stage agent as an explicit input, only on a retry, and
  the reason goes in the ledger. The retry cap (5) lives in one place: the
  orchestrator skill's stages file.

## Phase 1: generated task layer + shared guard

1. `src/ms_modify/task_spec.py`: parse `casatasks/__xml__/<task>.xml`, found via
   `importlib.util.find_spec("casatasks")` (no casatasks import). Per param: name,
   type, default, shortdescription, allowed values, subparam. Pure parsing, unit
   tested on a checked-in copy of one XML.
2. Curated set per task: the fields of the existing wrapper Input model
   (`ms_modify/server.py`) that are also XML params, with that model's defaults.
   Derived at import time, not copied. `ms_path` maps to `vis`.
3. `src/ms_modify/guard.py`, one module applied to every generated write:
   - output path check (`pathguard.validate_output_caltable`) for the task's
     output param (caltable / fluxtable / outputvis / imagename)
   - `.attemptN` rename (`SAFE_RM_TABLE_SNIPPET`)
   - flagdata manual empty-selection refusal (`manual_selection`)
   - `execute=False` script via `write_script`, `record_stage`
   - check after the run: solve tasks, output table exists with rows;
     applycal, CORRECTED_DATA present; split, outputvis exists; tclean, image
     exists
4. One MCP tool per task on ms-modify, named `casa_<task>`. Phase 1 tasks are the
   ones the Stokes I recipe calls through thin wrappers today: gaincal, bandpass,
   fluxscale, applycal, flagdata, tclean. Arguments: `vis`, `workdir`, curated
   params, `debug`, `debug_params` (dict, rejected unless `debug=True`, keys
   checked against the XML), `execute`.
5. The old wrappers stay registered in phase 1. Only the new agents are granted
   the `casa_*` tools.

## Decision 2026-11-06: option 1 (debug pass-through on existing wrappers)

The adversary found per-task checks in every "thin" wrapper (SpW coverage,
fluxscale field-ID mapping, applycal list lengths, tclean CORRECTED check and
stopcode, flagdata before/after). So the wrappers stay as the limited set, and
each gets `debug` + `debug_params={task: {param: value}}`, checked against the
casatasks XML (`debug_mode.py`). Items 1-5 above are replaced by this. Phase 4
is dropped: precal wrappers stay.

## Phase 1b: generated layer for the tasks with no wrapper

About 111 of the 127 casatasks have no wrapper. Two generic tools, not one per
task: `ms_casa_task_spec(task)` (read-only, params from the installed XML) and
`casa_task(task, params, workdir, execute=False)` through the generic guard
(path checks, `.attemptN`, script, stage log). No task-specific checks; behind
the grants, off by default. casatools are not generated: no XML, and they are
stateful objects that must go through `casa_context`.

## Phase 2: stage agents + orchestrator skill

6. Plugin `agents/`: `inspect.md`, `precal.md`, `calibrate.md`, `image.md`.
   `model: haiku`. `tools:` = the command's tool list, with the thin wrappers
   swapped for `casa_*`. `skills:` preloads the existing command
   (`radio-analyst:<stage>`), so the command text stays the single source.
7. Each stage returns a fixed HANDOFF block of raw tool fields (inspect already
   does; precal, calibrate, image get one).
8. `.claude/skills/orchestrate/SKILL.md` (Sonnet main session) + `stages.json`
   gets `accept` and `on_fail` per step. Every `accept` criterion points to the
   existing skill line it comes from; none invented. Retry cap 5. Orchestrator
   has read-only tools only. Depth 1.
9. Pass criteria leave skills 07, 10, 11 for the orchestrator skill; stage
   skills keep how to run the stage.

## Phase 3: Haiku run (after phase 4; numbered here for reading order)

10. Per `HAIKU_STAGE_METHOD.md`: fresh 3C391 extract, env rebuilt, orchestrator
    `claude -p --model sonnet`, stage agents haiku. Judged on raw tool output and
    files on disk. Adversary on the trace.

## Phase 4 (before the Haiku run): precal domain logic to parameter tools

11. setjy per-field standard, priorcals opacities, preflag command list, initial
    rflag thresholds move to read-only ms-inspect tools; precal writes go through
    `casa_*`. The one Haiku run comes after this, when the build is complete.

## Open, to test in phase 2

- Single MCP tool names in agent `tools:` (docs show only `mcp__server__*`).
- `claude -p` with plugin agents and the Agent tool, headless.
- Whether `skills:` accepts a plugin command name.
- opencode parity: after phase 3.
