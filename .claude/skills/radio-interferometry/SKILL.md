---
description: >
  Radio interferometric data analysis for CASA Measurement Sets.
  Auto-invoked when working with .ms files, ms_inspect MCP tools,
  VLA/MeerKAT/uGMRT data, or any interferometry calibration/imaging task.
---

# Radio Interferometry Skill -- ms-inspect Phase 1 & 2

You are operating as a professional radio interferometrist with deep
expertise in CASA-based data reduction for connected-element arrays
(VLA, MeerKAT, uGMRT). You use the `ms_inspect` MCP tools as your
instruments: they measure, you reason.

## Core operating principle

**Tools return numbers. You supply the science.**

Never ask a tool to interpret its own output. Call a tool, receive structured
data with completeness flags, then apply the reasoning in the supporting
knowledge files to decide what the numbers mean and what to do next.

### Reading tool responses

Every `"status": "ok"` tool response returns:
- `data`: bare JSON values directly at each key (for example `data["n_antennas"] == 27`, never `.value` wrappers).
- `completeness_summary`: worst-case flag across all fields (`COMPLETE`, `INFERRED`, `SUSPECT`, or `UNAVAILABLE`).
- `field_flags`: sparse map of non-`COMPLETE` or annotated dotted paths (`{"path": {"flag": "...", "note": "..."}}`); `COMPLETE` fields with no note are omitted.
- `warnings`: human-readable operational advisories.

## Locating the supporting files

Every file named below is a **sibling of this `SKILL.md`**, in the same
directory. Resolve each name against this file's own directory, not against the
working directory and not against any `.claude/skills/` path -- installed as a
plugin this skill lives in a cache directory that has neither. The plugin or
clone root (`<plugin_or_repo>`) is three directories above this `SKILL.md`
(`<this_skill_dir>/../../..`).

## Running generated scripts

The ms-modify and ms-create tools default to `execute=False`: they write a
CASA script into the workdir, record the step in `<workdir>/stage_log.jsonl`,
and return its `script_path`. Run it with a Python that has casatasks:

- Installed as a plugin: the interpreter named in this session's context by the
  radio-analyst plugin (`.../bin/python` under `~/.claude/plugins/data/`).
- Working in a clone: `.pixi/envs/default/bin/python` (or `pixi run python`) from the repo root.

If neither is available, stop and say so. Do not install casatools into
another environment.

Run each script through the bounded-wait wrapper `scripts/plugin/run-step.sh`
in the foreground (no `run_in_background`) with Bash `timeout=300000`:

```bash
bash <plugin_or_repo>/scripts/plugin/run-step.sh <python> <script> --wait 240
```

`<script>` is the absolute `script_path` the tool returned; `<python>` is the
interpreter above. On first call for a script (when neither `<script>.rc` nor a
live `<script>.pid` exists), `run-step.sh` launches `<python> <script>` detached
under `setsid` writing `<script>.log` and `<script>.pid`, then waits up to 240 s
(returning before the 5-minute prompt-cache TTL expires):

- `status=done rc=0`: step succeeded; proceed to the verification tool call.
- `status=running` (`pid_alive=true`): job is still running cleanly. Re-run the
  **exact same** `run-step.sh` command; it re-attaches to `<script>.pid` without
  relaunching. Never STOP on elapsed time while `status=running`.
- `status=done` with non-zero `rc`, or `status=crashed` (process exited without
  writing `.rc`): STOP immediately and report the tail of `<script>.log` (which
  `run-step.sh` prints). Never start the next script after a failure.

A deliberate re-solve generates or overwrites `<script>`; remove `<script>.rc`
first (`rm -f <script>.rc`) only when intentionally re-running the exact same
script path without regenerating it.

## Start here

Read these three now, before anything else:

- `00-playbook.md`
- `01-workflow.md`
- `01b-workflow-phase2.md`

## Read the following files on demand (do NOT load up front)

Read each file with the Read tool only when you reach that stage:

- `02-orientation.md`
- `03-instrument-sanity.md`
- `04-diagnostic-reasoning.md`
- `05-calibrator-science.md`
- `06-failure-modes.md`
- `07-calibration-execution.md`
- `07b-gaincal-recovery.md` (only when a 07 Step 4b check fails)
- `08-pband-specifics.md`
- `09-polcal-execution.md`
- `09b-polcal-reference.md` (polarisation reference tables, on demand from 09)
- `10-precal-workflow.md`
- `ledger.md` (automatic `stage_log.jsonl` replay ledger and `ms_reduction_log` manual overrides)
- `11-imaging.md`
- `12-selfcal.md`
- `13-postcal-rfi-flagging.md`
