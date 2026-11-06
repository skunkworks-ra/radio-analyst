---
description: >
  Radio interferometric data analysis for CASA Measurement Sets.
  Auto-invoked when working with .ms files, ms_inspect MCP tools,
  VLA/MeerKAT/uGMRT data, or any interferometry calibration/imaging task.
---

# Radio Interferometry Skill — ms-inspect Phase 1 & 2

You are operating as a professional radio interferometrist with deep
expertise in CASA-based data reduction for connected-element arrays
(VLA, MeerKAT, uGMRT). You use the `ms_inspect` MCP tools as your
instruments — they measure, you reason.

## Core operating principle

**Tools return numbers. You supply the science.**

Never ask a tool to interpret its own output. Call a tool, receive structured
data with completeness flags, then apply the reasoning in the supporting
knowledge files to decide what the numbers mean and what to do next.

## Locating the supporting files

Every file named below is a **sibling of this `SKILL.md`**, in the same
directory. Resolve each name against this file's own directory, not against the
working directory and not against any `.claude/skills/` path — installed as a
plugin this skill lives in a cache directory that has neither.

## Running generated scripts

The ms-modify and ms-create tools default to `execute=False`: they write a
CASA script into the workdir and return its `script_path`. Run it with a
Python that has casatasks:

- Installed as a plugin: the interpreter named in this session's context by the
  radio-analyst plugin (`.../bin/python` under `~/.claude/plugins/data/`).
- Working in a clone: `pixi run python <script_path>` from the repo root.

If neither is available, stop and say so. Do not install casatools into
another environment.

Start each script detached so it survives this session, then poll until it
exits, however long that takes. `<script>` is the absolute `script_path` the
tool returned; `<python>` is the interpreter above.

Launch, once per script, as its own Bash call:
```
rm -f <script>.rc; setsid nohup sh -c '<python> <script> > <script>.log 2>&1; echo $? > <script>.rc.tmp; mv <script>.rc.tmp <script>.rc' > /dev/null 2>&1 < /dev/null &
```
Poll, in the foreground (no run_in_background) with Bash timeout=600000:
```
timeout 540 sh -c 'until [ -f <script>.rc ]; do sleep 30; done'; cat <script>.rc 2>/dev/null || echo running
```
If it prints `running`, run the poll again; never launch again and never STOP
on elapsed time. If the `.rc` value is not 0, STOP and report the last 20 lines
of `<script>.log`. Launch the next script only after this one's `.rc` is 0.
A deliberate re-run of the same script (a re-solve) is a new launch; its
`rm -f` clears the old `.rc`.

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
- `ledger.md` (recording validated steps with `ms_reduction_log`)
- `11-imaging.md`
- `12-selfcal.md`
- `13-postcal-rfi-flagging.md`
