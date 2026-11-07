# Architecture review: tools, tasks, MCPs, skills, and agents (draft)

Date: 2026-11-06. Branch `min_viable` (HEAD f7e419f) against `main`.
Status: draft for discussion. Read from code; nothing here is a run result.
Every claim points to a file or command. Judgements are labelled with a
confidence. Sonnet was the adversary on parts 1 to 3.

---

## Part A. Where things are, and where they should be

### 1. What min_viable is, relative to main

**The tool surface has not changed.** `grep -c '@mcp.tool' src/*/server.py`
gives 34 in ms-inspect, 17 in ms-modify, and 4 in ms-create. The same counts
hold at v0.1.0, v0.1.1, and min_viable.

**The tags differ in packaging only.** v0.1.0 to v0.1.1 is 6 commits: plugin
layout, launcher paths, docs. No tool changed.

**min_viable is 37 commits ahead of main and 1 behind.**
`git diff --stat main...min_viable` shows 55 files, +1314 and -1991 lines. Most
of it is in the skill and the commands, not in `src/`:

- removes the `wildcat/` skill tree, 12 files (4ab5523)
- shrinks skill 10 (precal) by about half; rewrites skill 07 (calibration)
- each command declares the tools it may call (8882860)
- inspect hands precal four values from two tools, not a field-role table
  (b98be27, 9e1a3af, 2c78bf0)
- cuts cues: "precal: cull to tools whose output feeds a later step"
  (c937ba0); drops the `ms_verify_caltables`, `ms_flag_summary`, and
  `ms_residual_stats` cues (f23f51e, eb749d4); drops the K SNR gate (d49f2ab)
- generated scripts run detached and are polled, with no time limit (f7e419f)

**Code changes are small and targeted:**

- `fields.py`, `phase_cal_catalog.py`: a VLA calibrator list match is a phase
  cal at any scan count; identity radius; flux estimate (callist row at the
  band, else a power law between bracketing bands)
- `setjy_polcal.py`, `polcal_setjy_fit.py`: `reffreq_ghz` defaults to the band
  centre; the fit uses the band plus the nearest node each side
- `intents.py`: `ms_set_intents` is replayable and refuses a missing workdir
- `calsol_plot.py`: one fixed time axis and one fixed frequency axis across
  antennas

**The 1 commit on main and not on min_viable** is 1f911cc (phase cal expected
flux, #15). min_viable has bb93635 with the same subject line. Whether the two
patches are identical is not checked.

In one line: min_viable keeps the tools and puts the prompt on a diet. It
removes text and cues the model was not using, and scopes each command to the
tools whose output feeds a later step.

### 2. Should the CASA layer be generated from casadocs?

#### What is cheap about it

No scraping is needed. The installed `casatasks` ships a typed parameter spec
for every task:

```
casatasks/__xml__/          -> 127 task XML files
gaincal.xml                 -> 38 <param> entries
inspect.signature(gaincal)  -> 38 parameters
```

A generator could read these and emit one MCP tool per task, with names,
types, defaults, and docstring. It tracks the installed CASA version and
cannot drift. For comparison, `src/ms_modify/server.py` is 2080 lines of
hand-written schema and docstring for 17 tools.

#### What a raw generated layer would lose

These live in the current wrappers, not in CASA:

1. **Output path checks.** `pathguard.py:validate_output_caltable` refuses an
   output caltable that is the MS, is an existing MS, or is outside the
   workdir (pathguard.py lines 21, 27, 32 of the function block).
2. **No destruction of the last attempt.** `SAFE_RM_TABLE_SNIPPET` renames a
   previous caltable to `.attemptN` instead of deleting it.
3. **Empty-selection refusal.** `manual_selection.py:5-7`: "flagdata(mode='manual')
   with every selection empty flags the whole target". The wrapper refuses;
   CASA does not.
4. **A replayable record.** Every write tool defaults to `execute=False`,
   writes a self-contained script into the workdir, and calls `record_stage`.
   With `ms_reduction_log`, the reduction is replayable.
5. **Verification after the fact.** `applycal.py:307-322`: "applycal returns
   None; a clean return proves only that it did not raise. Measure the column
   instead of trusting the return." The tool confirms CORRECTED_DATA exists.
6. **Domain logic a parameter schema cannot express:**
   - `ms_setjy`: flux standard resolved per field from that field's own
     frequency (`setjy.py:11-18`, the Ceres plus Perley-Butler case)
   - `ms_set_intents`: intents from calibrator catalogue matching
   - `ms_setjy_polcal`: the polarised model fit
   - `ms_postcal_flag`: SpW severity triage into one list-mode pass
   - `ms_gaincal`: `spwmap` and `gainfield` length checks against the gain
     tables (`gaincal.py:175-190`)

#### How thin are the wrappers?

Sonnet's split. A judgement, not a count of anything:

- About 4 of 17 are thin: `ms_bandpass`, `ms_fluxscale`, `ms_apply_rflag`,
  `ms_applycal`. Even these carry the path check, the stage log, and (for
  applycal) the column check. Replaceable with nothing lost: closer to 0 to 2.
- About 13 of 17 carry their own logic: set_intents, setjy, setjy_polcal,
  initial_bandpass, postcal_flag, apply_initial_rflag, flag_caltable,
  flag_data, polcal, gaincal, tclean, apply_preflag, generate_priorcals.

#### The design that keeps both

Split by layer, not generated versus hand-written:

| Layer | Source | Holds |
|---|---|---|
| Task schema | generated from `casatasks/__xml__` | parameter names, types, defaults, docstrings |
| Guard | hand-written, one shared module | path check, `.attemptN` rename, empty-selection refusal, `execute=False` script, stage log, ledger, verification after the fact |
| Domain tools | hand-written | per-field setjy, set_intents, setjy_polcal fit, postcal_flag, initial_bandpass |
| Measurement tools | hand-written, read-only | numbers with their inputs and CompletionFlags |
| Skill | prose | thresholds, decisions, the science goal |

The schema layer is regenerated per CASA release. The guard is written once
and wraps every generated write tool. Domain tools stay as they are.

#### The cost to weigh

A generated layer exposes about 127 tasks and their parameters. min_viable's
direction is the opposite: fewer tools and fewer cues per command. If a
generated layer exists, it belongs behind the per-command grants as an escape
hatch, off by default. Whether exposing it changes model behaviour is an open
question; nothing in the repo tests it.

Judgement: keep the wrappers, generate the schemas under them, and move the
guards into one shared module (70%). Superseded by Part C, section 12: use the
generated layer for the writes, with the guard and the domain logic moved out.

### 3. Where things sit against the contract today

The contract in `CLAUDE.md`: tools measure, the skill reasons, no gates in
tools, inputs travel with outputs. Four places deviate.

#### 3a. A gate inside a tool

`gaincal_snr_predict.py:190-195`:

```python
if frac == 0:
    hint = "all_pass"
elif frac < 0.2:
    hint = "tighten_solint"
else:
    hint = "exclude_antennas_or_relax"
```

A verdict (`all_pass`) and a next-step suggestion, with the 0.2 cutoff
hardcoded. The inputs (`n_below`, `n_with_snr`) are available, so the skill
could apply its own cutoff. The label breaks rule 2 as `CLAUDE.md` states it.

#### 3b. A threshold refusal inside a tool

`flag_caltable.py:132-150`: in auto-routed mode, a time-axis table with a
median below `min_intervals` (default 10) solution intervals per antenna is
refused. It fails loudly and ships the numbers (median, min, max), and an
explicit `mode` downgrades it to a warning. So it is the loud kind of gate in
`CLAUDE.md`'s terms, not the silent kind. It still withholds an action because
a constant was not met. Worth deciding on purpose whether it stays.

#### 3c. Arithmetic done by the model in the skill

`07-calibration-execution.md:678-692` asks the model to:

1. read N from `ms_antenna_list`
2. run `ms_calsol_stats` on each table in the applycal stack
3. build `surviving = set(ant_names) - set(antennas_lost)` per table
4. intersect those sets
5. compute `fraction = len(common) / N`, then act on a table of fractions

That is measurement written as prose. One read-only tool that takes the
applycal stack and returns per-table lost sets, the common set, and the
fraction, with N attached, makes it a number the skill reads.

#### 3d. A formula in the skill that the tools already hold

`11-imaging.md:231-237` gives the model the VLA OSS natural-weighting noise
equation to evaluate by hand (SEFD, efficiency, N antennas, integration time,
bandwidth), then `threshold = 3 * sigma`. `CLAUDE.md` lists
`ms_gaincal_snr_predict` as using an SEFD table plus MS metadata, so the inputs
are already in the tools. A read-only noise estimate would hand the skill the
number with its inputs. The threshold choice (3 sigma) stays in the skill.

#### Things that look like gates but are not

- `workflow_status.next_recommended_step`: the one named exception in
  `CLAUDE.md`. Gates on filesystem state; a failed probe returns
  `probe_failed_*` / `UNAVAILABLE`.
- `recommended_minblperant` (`antennas.py`): a labelled suggested parameter,
  permitted.
- Precondition refusals in write tools (`applycal.py`, `gaincal.py`): input
  validation (table exists, list lengths match), not a scientific claim.
- `pol_cal_conditions.recommended_df_poltype`: chosen from catalogue role with
  the basis attached. Borderline (Sonnet, 55% acceptable).

### 4. What should be where

Reasoning from the code, not from results.

**Measure in tools.** Anything that is arithmetic over the MS or a caltable
belongs in a read-only tool that returns the number, its inputs, and a
CompletionFlag. Two pieces of arithmetic sit in the skill today (3c, 3d).
Moving them out takes error-prone work away from the model and makes each
step's number checkable.

**Guard in the write layer.** Overwriting the MS, flagging everything through
an empty selection, deleting the previous attempt, a task returning cleanly but
doing nothing: these belong in one shared guard around every write, hand-written
or generated. They are not science gates. They have no tolerance to tune.

**Decide in the skill.** Thresholds, what counts as good enough, when to stop
and ask. The tools hand over numbers with their inputs, so the skill can apply
a different tolerance for a different science goal.

**Keep tasks wrapped where the wrapper holds knowledge.** Per-field setjy,
intents from catalogues, the polarised model fit. A generated schema cannot
carry these.

**Keep the visible surface small.** min_viable's direction is that each command
sees only the tools whose output feeds a later step. A generated task layer
fits that only if it sits behind the grants.

**Verify after each solve rather than gate before it.** The write tools already
do this in one place (applycal's column check). The extension: a read-only
measurement after each solve (gaincal, bandpass, fluxscale, applycal, tclean)
whose numbers the skill compares against its own tolerance. That is the shape
of "model driven but not off the rails": the model chooses, the guards prevent
damage, the measurements show what the choice produced.

---

## Part B. Orchestrator and stage subagents

### 5. The proposal

Sonnet orchestrator. One Haiku subagent per stage. Each stage agent gets only
its stage's skill file and tools, and hands back a fixed block of numbers.
Judgement: 65% that this reduces drift relative to one long Haiku session. Not
measured.

### 6. The pieces already exist

| Piece | Where it is now | Role as a subagent |
|---|---|---|
| Stage order and checks | `.claude/skills/reduce/stages.json` | the orchestrator's script |
| Tools per stage | each command's `allowed-tools` (8882860) | the stage agent's `tools:` |
| Science per stage | skill files 10, 07, 09, 11 | the stage agent's `skills:` preload |
| Fixed handoff | the inspect handoff block (b98be27) | every stage agent's return format |
| State probe | `ms_workflow_status`, stage log, ledger | how the orchestrator verifies a stage without trusting its summary |
| The manual version | `HAIKU_STAGE_METHOD.md` | Opus coordinates, Sonnet adversary checks, Haiku runs one stage at a time with `--resume` |

The last row is the same pattern done by hand. The subagent version formalises
it: each stage becomes one agent definition, and `--resume` is replaced by an
explicit handoff.

### 7. Drift recorded in STATE.md, and what removes each kind

These are what STATE.md records from the Haiku stage runs. Trace observations,
not rates.

| Drift in the trace | Fix in the agent design |
|---|---|
| Called ungranted tools on its own initiative (S2: `ms_calsol_stats`, `ms_flag_summary`) | `tools:` limits what the agent can call at all |
| Substituted its own choice (S3 polcal: Df on J1331/3C286, not the skill's J0319/3C84) | the orchestrator passes the choice as an explicit input; the stage agent does not choose it |
| Summary numbers differed from raw (S2: "I 7.63 Jy" vs log 6.6197 Jy) | the handoff is raw tool fields only; the orchestrator re-reads them with read-only tools |
| Context from one stage bleeding into the next | each subagent starts fresh with one skill file |

### 8. Who does what

1. **Stage agent (Haiku).** Runs one stage from `stages.json`: action, checks,
   ledger entry. Recovers inside the stage only where the skill names the
   recovery (for example 07b gaincal recovery). Returns the handoff block and
   stops. Never decides scope.
2. **Orchestrator (Sonnet).** Holds the science goal and the user's tolerance.
   Reads each handoff, verifies it with read-only inspect tools, and chooses:
   next stage, re-run the stage with changed inputs, skip an optional stage, or
   stop and ask. Cross-stage calls live here: polcal in scope, which leakage
   cal, whether a D-term level is acceptable. No write tools.
3. **Tools.** Unchanged: they measure. Part A section 3 matters more here,
   because the orchestrator can only verify what a tool measures.
4. **Guards.** Plugin-level hooks, not per-agent hooks (see section 9).

So "the skill reasons" splits in two: stage agents reason inside one stage, the
orchestrator reasons across stages and about the science goal.

### 9. What the docs say, and what must be tested

**Claude Code** (code.claude.com/docs/en/sub-agents.md,
plugins/components.md, hooks.md, headless.md; read 2026-11-06):

- Agent frontmatter includes `tools`, `disallowedTools`, `model`, `skills`
  ("The full content of each listed skill is injected into the subagent's
  context at startup"), `maxTurns`, `effort`.
- A plugin can ship agents in `agents/`, named `radio-analyst:<name>`.
- Plugin agents ignore `permissionMode`, `hooks`, `mcpServers`, and
  `initialPrompt`. Guards have to live in the plugin's `hooks.json`.
- Nesting: "a subagent can spawn subagents of its own, up to three layers
  below the main conversation."
- SubagentStop can block a subagent from stopping (exit 2 or decision
  "block"). That could enforce "the handoff block is present": process only,
  not a science value. SubagentStart cannot block.
- `--agent <name>` runs the main session as an agent; settings key `agent`.

Test first:

- The docs show `tools: mcp__server__*` for a whole server. Listing single
  MCP tool names in `tools:` has no example. Per-stage grants depend on it.
- `claude -p --agent` is not documented. Haiku runs are headless.

**opencode** (opencode.ai/docs/agents, opencode.ai/docs/config; read
2026-11-06):

- `mode: primary | subagent | all`; per-agent `model`, `steps`,
  `permissions`, `system`. Markdown agents in `.opencode/agents/<name>.md`.
- V2 schema: legacy `tools`, `prompt`, `permission`, `maxSteps` are not to be
  used in new configs.
- A primary's `subagent` permission (resource = agent ID) controls which
  agents it may launch.
- `experimental.subagent_depth` defaults to 1: a subagent cannot launch
  another.
- Per-agent restriction of MCP tools is not documented on the pages read.
  The permissions page (opencode.ai/docs/permissions) was not read.

Design rule from this: depth 1 only (orchestrator, then stage agents). It works
in both.

### 10. Where this sits in the current work

This is the next layer on the stage-cutting work, not a side track. Each stage
agent's definition is the cut command. Per STATE.md: precal ran clean,
calibrate ran, polcal stopped before applycal, image not run with Haiku yet.
Converting one stage tests the idea without dropping that thread.

### 11. Smallest test (needs his go)

One agent, `agents/inspect.md`: model haiku, `tools:` the two inspect tools by
single name, the inspect command text as body. Sonnet calls it once on the
fixture MS (`/var/mnt/fast/radio_analyst_runs/fixture_3c391_inspect/`).
Compare its handoff with what the existing inspect command gives on the same
MS. This answers both open questions in section 9 in one run.

---

## Part C. Generated write layer and an orchestrator skill

Decided in discussion, 2026-11-06: use the generated layer for writes, and give
the orchestrator its own skill. This part supersedes the Part A section 2
judgement.

### 12. Using the generated layer for writes

What each ms-modify write tool calls
(`grep 'from casatasks import' src/ms_modify/*.py`):

- 16 of 17 end in plain CASA tasks: gaincal, bandpass, applycal, polcal,
  fluxscale, flagdata, flagmanager, setjy, gencal, plotweather, split, tclean.
- 1 does not: `ms_set_intents` writes the STATE subtable row by row with the
  table tool (`intents.py:253-262`: `tb.removerows`, `tb.addrows`,
  `tb.putcell`). No CASA task does this, so it stays custom.

Two conditions make the generated layer safe.

**Condition 1: one shared guard around every generated write.** It holds:

- output path checks (`pathguard.py:validate_output_caltable`)
- `.attemptN` rename of the previous table (`SAFE_RM_TABLE_SNIPPET`)
- empty-selection refusal (`manual_selection.py`)
- `execute=False`, the script, the stage log, the ledger
- the check after the run (for example CORRECTED_DATA present, as in
  `applycal.py:307-322`)
- list-length checks such as `spwmap` and `gainfield` against the gain tables
  (`gaincal.py:175-190`)

Without it, raw `flagdata` with an empty selection flags the whole MS again
(`manual_selection.py:5-7`).

**Condition 2: each wrapper's domain logic becomes a read-only tool that
returns parameter values.**

| Wrapper today | Becomes a measurement tool returning | Stage agent then calls |
|---|---|---|
| `ms_setjy` per-field standard | the standard per field, from that field's frequency | generated `setjy` |
| `ms_setjy_polcal` polarised fit | `fluxdensity`, `spix`, `polindex`, `polangle`, `reffreq` | generated `setjy` |
| `ms_generate_priorcals` opacities | zenith opacities per SpW (from `plotweather`) | generated `gencal` |
| `ms_postcal_flag` clip levels | per-SpW clip levels (from `ms_spw_amp_severity`) | generated `flagdata`, list mode |
| `ms_initial_bandpass`, `ms_apply_preflag` (composites) | nothing new | a sequence of generated calls, written in the stage skill |

This fits the contract better than today: tools measure (a labelled suggested
parameter value is permitted, `CLAUDE.md` rule 2 table), writes are plain CASA
plus the guard, the skill orders them.

Cost: a composite becomes 3 or more calls (`ms_initial_bandpass` becomes
gaincal, bandpass, applycal). More calls for Haiku inside a stage. Whether a
small fresh context per stage offsets that is not tested.

### 13. The orchestrator skill

The split that removes the most drift: **the stage agent never judges its own
result.** It runs, measures, and reports raw fields. The orchestrator skill
holds the pass criteria. The "is this good" text moves out of skills 07, 10,
and 11 into the orchestrator skill; the stage skills keep how to run the stage.

Per stage, the orchestrator skill holds:

1. **Inputs** handed to the stage agent, every choice explicit (for example
   "leakage cal = J0319").
2. **Required measurements** afterwards: tool and fields.
3. **Pass criteria**, taken from the existing skill text with a pointer to the
   source line (for example antenna fraction >= 0.50, `07:690`). No new
   thresholds are invented.
4. **On failure**: what changes on retry (from 07b recovery and the like), the
   retry cap, and when to stop and ask the user.

Structure: `stages.json` already has `before` and `after` per step. Add
`accept` and `on_fail` per step. The orchestrator skill is `stages.json` plus a
short SKILL.md that says how to read it.

### 14. Open

- Retry cap per stage: no existing source. Needs his number.
