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
               mcp__plugin_radio-analyst_ms-inspect__ms_casa_task_spec
---

# Orchestrate: one MS, four stages, each checked

Arguments: the MS path, `workdir=<dir>`, `online_flags=<path>|none`. If one is
missing, stop and ask for it.

You do not run CASA and you do not write to the MS. Stage agents do the work;
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

| # | Stage | Agent | Arguments |
|---|---|---|---|
| 1 | inspect | `radio-analyst:inspect-stage` | `<ms_path>` |
| 2 | precal | `radio-analyst:precal-stage` | `<ms_path> workdir=<workdir> online_flags=<...>`, the INSPECT HANDOFF lines, `pol_scope: off` |
| 3 | calibrate | `radio-analyst:calibrate-stage` | `<ms_path> workdir=<workdir>` |
| 4 | image | `radio-analyst:image-stage` | `<ms_path> workdir=<workdir>`, `stokes: I` |

## Skill excerpts: the stage gets only the lines it needs

A stage agent does not load the radio-interferometry skill. You cut the
sections its command uses and send them in its prompt. `{ri}` is the
radio-interferometry skill directory: the sibling `radio-interferometry/` of
this skill's base directory. Bash is for this command only:

```
awk -v H='<heading 1>|<heading 2>|...' 'BEGIN{n=split(H,a,"|")} /^## /{p=0; for(i=1;i<=n;i++) if(index($0,a[i])==1) p=1} p' {ri}/<file>
```

Each heading is the start of a `## ` line; the section runs to the next `## `.

| Stage | File | Headings |
|---|---|---|
| precal | `10-precal-workflow.md` | `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 5 —`, `## Step 6 —`, `## Step 8 —`, `## Decision gate` |
| precal, calibrate | `ledger.md` | the whole file (`cat`) |
| calibrate | `07b-gaincal-recovery.md` | the whole file (`cat`; Step 4b sends the stage there) |
| calibrate | `07-calibration-execution.md` | `## Execution protocol`, `## Placeholder reference`, `## Field selection`, `## solint guidance`, `## Calibration table naming`, `## Caltable solution flagging`, `## Drilling into`, `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 4b —`, `## Step 5 —`, `## Step 6 —`, `## Decision gate`, `## Antenna-set consistency`, `## Step 7 —`, `## Post-applycal assessment`, `## parang parameter` |
| image | `11-imaging.md` | `## Placeholder reference`, `## Step 0 —`, `## Step 0.5 —`, `## Step 1 —`, `## Step 2 —`, `## Step 3 —`, `## Step 4 —`, `## Step 5 —`, `## Step 6 —`, `## Step 7 —`, `## Step 8 —`, `## Step 9 —` |
| precal, calibrate, image | `SKILL.md` | `## Running generated scripts` |

Put the output at the end of the stage prompt, after the arguments and values,
as one block per file:

```
SKILL EXCERPTS (<file>, sections: <headings>)
<the command's output, verbatim>
END SKILL EXCERPTS
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

Record as `not_checked` with the reason: 07:655 (lost antennas flagged on both
MSs: no read-only tool measures it) and 07:656 (fluxscale flux vs
`flux_estimate`: copy the stage's value from the handoff into `value` and say
it is the stage's).

### 4. image (11-imaging.md:324-362, quality gates)

The radiometer estimate is the image stage's own number (commands/image.md
step 4); record that it comes from the handoff.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Image measures | `ms_image_stats(<imagename>.image.pbcor, psf_path, pb_level)` | status ok | retry |
| `residual_rms_jy` vs the radiometer estimate (11:355) | `ms_image_stats` | within 2x | > 3x: stop, the problem is in calibration (11:360); 2x to 3x: retry |
| `residual_dynamic_range` (11:356) | `ms_image_stats` | > 20 for a target | retry |
| `detection` label (11:364) | `ms_image_stats` | report it; not a pass/fail | none |

Record as `not_checked`: `beam_major_arcsec` and `peak_jy` (11:357-358) unless
the handoff gives the expected beam.

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

After image (or a stop), report: each stage, its attempts, the deciding check
of each, and the record files. Do not judge the science beyond the checks.
