---
name: orchestrate
description: >
  Orchestrate a Stokes I continuum reduction of one CASA Measurement Set:
  inspect, precal, calibrate, image, each run by its own stage agent, each
  checked here before the next starts. Invoke when asked to orchestrate a
  reduction, or to run the stages with stage agents.
allowed-tools: Agent,
               Read,
               Write,
               Bash,
               mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_caltables,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_model,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_corrected_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_casa_task_spec,
               mcp__plugin_radio-analyst_ms-inspect__ms_residual_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_spw_amp_severity,
               mcp__plugin_radio-analyst_ms-modify__ms_casa_task,
               mcp__plugin_radio-analyst_ms-create__ms_report
---

# Orchestrate: one MS, four stages, each checked

Arguments: the MS path, `workdir=<dir>`, `online_flags=<path>|none`. If one is
missing, stop and ask for it.

You do not run CASA and you do not write to the MS. Two write tools are
granted for narrow uses: `ms_casa_task` only for `visstat` (read-only), and
`ms_report` only for the report at the end. Stage agents do the work;
you hand each one its inputs, read its handoff, check the result with the
read-only tools above, and decide what happens next. Every MCP tool takes one
argument, `params`.

**Retry cap: 5 attempts per stage.** On the 5th failed attempt, stop and ask
the user, with the record files of every attempt.

## The record: one JSON file per stage attempt

Before each next step, Write `{workdir}/orchestrator/{n:02d}_{stage}_try{k}.json`
(`n` counts every stage attempt from 01; `k` is the attempt number for that
stage). The files are the audit of your reasoning; write them even when the
stage fails. Keys:

```json
{
  "n": 1, "stage": "precal", "attempt": 1,
  "prompt": "<the exact prompt you gave the stage agent>",
  "handoff": "<the stage agent's handoff block, verbatim and whole; never abridged>",
  "checks": [
    {"criterion": "<the condition, as the source states it>",
     "source": "<skill file:line>",
     "tool": "<tool you called>", "tool_args": {"<the params you passed>": "..."},
     "field": "<field you read>",
     "value": "<value, copied from the tool output>",
     "result": "pass | fail | not_checked", "note": "<why not_checked>"}
  ],
  "decision": "next | retry | stop_ask_user",
  "reason": "<one or two sentences: which check decided it>",
  "change": "<on a retry: what the next attempt does differently>",
  "debug_params": {},
  "agent_id": "<the agent id the Agent tool returned, if it shows one>",
  "excerpts": ["<each excerpt command you ran for this prompt>"],
  "png_reviewed": "<image stage and selfcal: what the PNG shows, after you Read it; `not_viewed` if the image did not reach you>",
  "agent_usage": "<the usage the Agent tool reported for this call, verbatim>"
}
```

Copy values from tool output; never retype a number from memory. A check you
could not run is a row with `"result": "not_checked"` and the reason, never
left out. Token, cost
and time accounting is also extracted from the session transcript after the
run; `agent_usage` here is what you saw.

## Stages

Call each stage agent with the Agent tool, `subagent_type` as named. Give it a
prompt with the stage's arguments first (the stage command's own argument
line), then the values you hand it, one per line as `name: value`. This is a
Stokes I continuum reduction: scope values are fixed here, not left to the
stage.

Every stage prompt also carries `python: <path>`: the interpreter that runs the
generated scripts (the one this session's context names, or `pixi run python`
in a clone). Find it once; the stages do not search for it.

| # | Stage | Agent | Arguments |
|---|---|---|---|
| 1 | inspect | `radio-analyst:inspect-stage` | `<ms_path>` |
| 2 | precal | `radio-analyst:precal-stage` | `<ms_path> workdir=<workdir> online_flags=<...>`, the INSPECT HANDOFF lines, `pol_scope: off` |
| 3 | calibrate | `radio-analyst:calibrate-stage` | `<ms_path> workdir=<workdir>` |
| 4 | image | `radio-analyst:image-stage` | `<ms_path> workdir=<workdir>`, `stokes: I` |
| 4b | postcal (when section 4 B or C finds outliers) | `radio-analyst:postcal-stage` | `<ms_path> workdir=<workdir>`, `field: <target fields>` |
| 5 | selfcal (when section 4 says so) | `radio-analyst:selfcal-stage` | `<ms_path> workdir=<workdir> imagename=<prefix of the image to improve>` |

## Skill excerpts: the stage gets only the lines it needs

A stage agent does not load the radio-interferometry skill. You cut the
sections its command uses into files and send it the file paths. `{ri}` is the
radio-interferometry skill directory: the sibling `radio-interferometry/` of
this skill's base directory. Bash is for this command only:

```
awk -v H='<heading 1>|<heading 2>|...' 'BEGIN{n=split(H,a,"|")} /^## /{p=0; for(i=1;i<=n;i++) if(index($0,a[i])==1) p=1} p' {ri}/<file>
```

Each heading is the start of a `## ` line; the section runs to the next `## `.
Redirect the output of each `awk` or `cat` to
`{workdir}/orchestrator/ex_<stage>_<file stem>.txt` (for example
`ex_calibrate_07-calibration-execution.txt`; never under `/tmp`). Do not Read
the excerpt files yourself.

| Stage | File | Headings |
|---|---|---|
| precal | `10-precal-workflow.md` | `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 5 —`, `## Step 6 —`, `## Step 8 —`, `## Decision gate` |
| precal, calibrate | `ledger.md` | the whole file (`cat`) |
| calibrate | `07b-gaincal-recovery.md` | the whole file (`cat`; Step 4b sends the stage there) |
| calibrate | `07-calibration-execution.md` | `## Execution protocol`, `## Placeholder reference`, `## Field selection`, `## solint guidance`, `## Calibration table naming`, `## Caltable solution flagging`, `## Drilling into`, `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 4b —`, `## Step 5 —`, `## Step 6 —`, `## Decision gate`, `## Antenna-set consistency`, `## Step 7 —`, `## Post-applycal assessment`, `## parang parameter` |
| image | `11-imaging.md` | `## Placeholder reference`, `## Step 0 —`, `## Step 0.5 —`, `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 5 —`, `## Step 6 —`, `## Step 7 —`, `## Step 8 —`, `## Step 9 —` |
| selfcal | `12-selfcal.md` | `## Prerequisites`, `## Step 0 —`, `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 5 —` |
| selfcal, postcal | `ledger.md` | the whole file (`cat`) |
| precal, calibrate, image, selfcal, postcal | `SKILL.md` | `## Running generated scripts` |

Put one line per file at the end of the stage prompt, after the arguments and
values:

```
SKILL EXCERPT FILE: <path> (<file>, sections: <headings>)
```

Record the exact command(s) in the attempt's JSON under `"excerpts"`.

## Checks after each stage

Each row cites the radio-interferometry skill text it comes from (file:line).
Run the tool yourself with the arguments named; do not take the value from the
handoff. `{cal}` is `{workdir}/calibrators.ms`; `{ms}` is the MS you were given.
Where the skill says "Hard stop" or "stop", the row stops and asks the user.

### 1. inspect (commands/inspect.md, handoff block)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Handoff has all five lines; `cal_fields`, `bp_field` non-empty | handoff | all present | retry |
| `bp_field` is a field of the MS | `ms_field_list({ms})` field names | present | retry |

From the same `ms_field_list({ms})` read `bp_field`'s
`observing_frequency.centre_ghz` yourself; that is `bp_field_centre_ghz` below.

### 2. precal (10-precal-workflow.md:311-321, decision gate; :122 opacity row)

All four rows are "Hard stop" in the skill (10:317-320). Precal also cannot be
re-run on the same MS without undoing its flags, so a failed precal check stops.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| `gain_curves.gc` valid (10:317) | `ms_verify_priorcals({cal}, workdir)` `tables[].valid` | true | stop |
| `opacities.opac` valid when `bp_field_centre_ghz` >= 18 (10:318, :122) | same | true | stop |
| Initial bandpass caltables present (10:319) | `ms_verify_caltables({cal}, init_gain_table={workdir}/init_gain.g, bp_table={workdir}/BP0.b)` `caltables_valid` | true | stop |
| Bandpass model not the 1 Jy default (10:320) | `ms_verify_model({cal}, field=bp_field)` `per_field[].status` and `note` | not default | stop |
| Pre-calibration complete (commands/calibrate.md step 1) | `ms_workflow_status({ms}, workdir)` `next_recommended_step` | `delay_bandpass_gain` | stop |

### 3. calibrate (07-calibration-execution.md:646-663, decision gate; 11-imaging.md:54-68, coherence gate)

Read the phase calibrator fields from `ms_field_list({cal})`, the target fields
from `ms_field_list({ms})`, and the channel range from
`ms_spectral_window_list({cal})` `suggested.center_channels_string` (the same
in-band range the solves used, 11:57-58). That string is per SpW, e.g.
`0:5~58,1:5~58`; `ms_corrected_stats` takes one `chan_start`/`chan_end`. When
every SpW has the same range, pass it. When they differ, mark the three
coherence rows `not_checked` with the string as the reason.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| BP flagged fraction (07:652) | `ms_calsol_stats({workdir}/bandpass.B)` `overall_flagged_frac` | < 0.20 | stop: the fix is more RFI excision in precal (07:659), which this orchestrator does not run |
| Gain flagged fraction (07:653) | `ms_calsol_stats({workdir}/gain.G)` `overall_flagged_frac` | < 0.15 | stop, as above |
| Antennas lost (07:654) | `ms_calsol_stats` `n_antennas_lost` on `initial_phase.G0`, `delay.K`, `bandpass.B`, `gain.G` | ≤ 3 each | stop (07:662) |
| fluxscale done, `gain.fluxscaled` written (07:657) | `ms_workflow_status({ms}, workdir)` `final_solves_completed` | contains `"fluxscale"` | retry |
| CORRECTED on the target (commands/image.md step 1) | same, `corrected_populated_target` | true | retry |
| Phase cal coherence (11:66) | `ms_corrected_stats({cal}, field=<phase cals>, chan_start, chan_end)` `phase_rms_deg` | < 30 | retry, re-solve |
| Phase cal gains (11:67) | same, `amp_robust_std` vs `amp_median` | < ~20% | retry |
| Target not decorrelated (11:68) | `ms_corrected_stats({ms}, field=<targets>, chan_start, chan_end)` `amp_median`, `amp_robust_std` | `amp_median` > 0, std not ≫ median | retry |

Record the target's `phase_rms_deg` per pointing beside that row. 11:68 gives no
phase criterion for the target (a resolved source has structure phase), so it
is a number to report, not a pass/fail.

Record as `not_checked` with the reason: 07:655 (lost antennas flagged on both
MSs: no read-only tool measures it) and 07:656 (fluxscale flux vs
`flux_estimate`: copy the stage's value from the handoff into `value` and say
it is the stage's).

### 4. image (11-imaging.md:324-362, quality gates)

The image stage makes two images: a `hogbom` first pass and a `multiscale`
second pass (commands/image.md steps 4-5, 11-imaging.md Step 2). Run the checks
on the second-pass image; record the first-pass numbers beside them. The
radiometer estimate is the image stage's own number (commands/image.md step 4);
record that it comes from the handoff.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Image measures | `ms_image_stats(<imagename>.image.pbcor, psf_path, pb_level)` | status ok | retry |
| `residual_rms_jy` vs the radiometer estimate (11:355) | `ms_image_stats` | within 2x | over 2x: "When noise is not met" below |
| `residual_dynamic_range` (11:356) | `ms_image_stats` | > 20 for a target | retry |
| `detection` label (11:364) | `ms_image_stats` | report it; not a pass/fail | none |

Record as `not_checked`: `beam_major_arcsec` and `peak_jy` (11:357-358) unless
the handoff gives the expected beam.

#### When noise is not met

A dirty or lightly cleaned image of filled, extended emission cannot be at the
noise level: the residual comes down as cleaning goes deeper. So a residual over
2x the radiometer estimate is not, by itself, a calibration failure. Rule out
the sources of error first, in this order, then work on the image. Record each
step's numbers as checks. Run A, B and C in that order, each one even when it is
slow; a later step never stands in for an earlier one.

A. **Noise on the calibrator.** A point-source calibrator images to the noise
   when the calibration is good, so it is the representative noise test. Run the
   image stage on the phase calibrator: arguments `<ms_path> workdir=<workdir>`,
   `field: <phase cal>`, `stokes: I`, `passes: 1`, `imagename: <phase cal>_noise`
   (its own name, so the target images are not overwritten). Its `residual_rms_jy` within
   2x its own radiometer estimate (11:355) rules the calibration out. Over 2x:
   the calibration is suspect; stop and ask.
B. **Target amplitude against frequency.** `ms_spw_amp_severity({ms},
   datacolumn='CORRECTED_DATA', field=<targets>)`. Its per-channel
   `robust_sigma` is the 13 Step 3 measure (13:101-106, :143-148). The floor is
   the median `robust_sigma` of the SpWs with the lowest `severity`. Record, per
   SpW, the channels and half-SpWs over 13 Step 3's cut values; those values
   are the 24A-376 starting values (13:109-112), not a rule, so record the
   numbers and say so; note any residual RFI on that reading, then run C.
C. **Target amplitude against time.** `ms_casa_task(task='visstat', params={vis:
   {ms}, field: <targets>, axis: 'amp', datacolumn: 'corrected', useflags: true,
   reportingaxes: 'integration'}, workdir, execute=True)`; Read the file at its
   `data.result_path.value`. Record the median over integrations of the
   per-integration mean amplitude and of `npts`, and the five integrations with
   the largest mean, each with its time, its ratio to that median and its
   `npts` against the median `npts` (a mostly flagged integration's mean rests
   on few points). If B found residual RFI or integrations stand apart here,
   go to D.
D. **Flag, then check again.** Run stage 4b (postcal: rflag only on the
   target's CORRECTED data, no clip; his call, 2026-11-06) with `field: <target
   fields>`. Then run B and C again and record both. Then re-run the image
   stage with `imagename: <target>_rflag`, so the earlier images stay for
   comparison. Postcal flags once per reduction (one successful run; a retry
   after a non-zero `.rc` counts against the cap of 5 like any stage); if B or
   C still finds outliers after it, stop and ask. From here on, "the image" in
   the steps below is the `_rflag` set. No skill rule gives a
   cutoff: say so in the record. Note in the record that ms_casa_task was used
   for visstat only.

With A to C clear, the calibration and the data are ruled out, and the
remaining gap is the imaging. Work down this order, one step per attempt:

1. **Cleaning.** Read `converged` and `stopcode` for the image from
   `{workdir}/stage_log.jsonl` (the `tclean` line), and its `deconvolver` from
   its script `{workdir}/tclean_<prefix>.py`. Not converged, or the
   deconvolver was hogbom: retry the image stage with the change named
   (`deconvolver: multiscale`, then `deconvolver: asp` last: 11 Step 2; asp is
   expensive, say so in `reason`).
2. **Look at the image.** Read the PNG (`<prefix>.png`, the one `ms_image_stats`
   wrote) with the Read tool before deciding anything further. Write what you
   see into the record's `png_reviewed`: is the source structure clean, or are
   there stripes, rings or negative bowls around it?
3. **Selfcal, if the model is good.** This also covers 11:360 (over 3x: run
   `ms_residual_stats` before re-imaging). Apply 12 Step 0 (12:36-62): `dynamic_range`
   from `ms_image_stats` (< 30: selfcal unlikely to help, stop and ask; 30 and
   up: proceed), and `ms_residual_stats` on each target pointing (any SpW with
   `p95_amp / median_amp` > 10: RFI-dominated, stop and ask). If the PNG shows a
   clean model and both pass, run stage 5 (selfcal) with `imagename=` the
   prefix of the last target-field image (it wrote MODEL_DATA, which selfcal
   solves against; never the calibrator noise image).

### 4b. postcal (rflag only)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| rflag ran on the targets | handoff `scripts` (`.rc` 0) and `ms_workflow_status` | rc 0 | retry |
| Flagged fraction before and after, per target field | the stage's `ms_flag_summary` numbers, from the handoff | report it | none |

### 5. selfcal (12-selfcal.md:193-246)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Selfcal image measures | `ms_image_stats(<prefix>_sc1.image.pbcor, psf_path, pb_level)` | status ok | retry |
| `dynamic_range` change vs the image before (12:217-222) | `ms_image_stats`, both images | report it | < 10%: did not help, end; 10% or more: end and recommend more rounds to the user (12:235-246, one pass only); decreased: diverged, end and point at the `pcal1.g` solutions |

Read `<prefix>_sc1.png` and record `png_reviewed` as in section 4.

## Retries and debug mode

A retry must change something. The stage commands read few values from their
arguments (precal `pol_scope`, image `stokes` and `field`), so the change is
almost always a debug parameter on a named tool call. Before a retry, name it.
If you cannot, stop and ask the user instead of retrying: a re-run with the
same inputs gives the same answer.

The retry prompt is the stage's arguments, then:

```
retry: <k> of 5
failed_check: <criterion> (<source>): <tool>.<field> = <value>
change: <what is different this time>
debug: allowed | not allowed
debug_call: <tool name>   (only when debug is allowed)
debug_params: {<task>: {<param>: <value>}}   (only when debug is allowed)
```

Debug is allowed only on a retry, and only when the change is a CASA
parameter the stage tool does not expose (its own parameters come first).
`ms_casa_task_spec(task)` lists a task's parameters. Never debug on attempt 1.

## End

After the last stage (or a stop), build the report with
`ms_report(workdir, summary, decisions, caveats, image_path=<last .image.pbcor>)`.
It embeds every PNG in the workdir. Summary: each stage, its attempts and the
deciding check of each. Decisions: each retry, debug use and selfcal decision
with the numbers it rests on. Caveats: every `not_checked` row. Use backticks
only around short `name = value` items. Then say in chat where the report is.
Do not judge the science beyond the checks.
