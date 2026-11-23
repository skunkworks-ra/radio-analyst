---
name: orchestrate
description: >
  Orchestrate a continuum reduction of one CASA Measurement Set (or raw ASDM/SDM),
  Stokes I by default or IQUV on request: optional import, inspect, precal,
  calibrate, polcal (IQUV only), pre-imaging target RFI triage / postcal, image,
  each run by its own stage agent, each checked here before the next starts.
  Invoke when asked to orchestrate a reduction, or to run the stages with stage agents.
allowed-tools: Agent,
               Read,
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
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-inspect__ms_radiometer_estimate,
               mcp__plugin_radio-analyst_ms-inspect__ms_vis_amp_time_stats,
               mcp__plugin_radio-analyst_ms-create__ms_record_stage_decision,
               mcp__plugin_radio-analyst_ms-create__ms_report
---

# Orchestrate: one MS (or raw SDM), staged and verified

Arguments: either an existing MS path + `online_flags=<path>|none` OR
`sdm_path=<asdm_dir>` (which runs Stage 0 `import-stage` first to produce `{ms}`
and `online_flags`), plus `workdir=<dir>`, and optionally `stokes=I|IQUV` and
any explicit user science/imaging constraints (`field`, `spw`, `spw_mode`, `cell`, `imsize`,
`deconvolver`, `pblimit`, `pbmask`, `nsigma`, `cube_width`).
If the input path (`<ms_path>` or `sdm_path`) or `workdir` (or `online_flags`
when starting from an existing MS) is missing, stop and ask for it. `stokes`
defaults to `I`. `IQUV` adds the polcal stage and an IQUV cube; every Stokes I
stage and check runs as for `I`.

You do not run CASA, you do not run Bash, and you do not write files directly.
Only two bookkeeping write tools are granted: `ms_record_stage_decision` (after
every stage attempt) and `ms_report` (for the HTML report at the end).
Stage agents do the work; you hand each one its inputs, read its handoff, check
the result with the read-only tools above, and decide what happens next. Every
MCP tool takes one argument, `params` (and returns bare values under `data` plus
non-`COMPLETE` entries in `field_flags`).

**Retry cap: 5 attempts per stage.** On the 5th failed attempt, stop and ask
the user, summarizing every attempt's deciding check.

## The record: call `ms_record_stage_decision` after every stage attempt

After checking each stage attempt (whether proceeding, retrying, or stopping),
call the `ms_record_stage_decision` tool (`ms-create_ms_record_stage_decision`
in OpenCode) instead of writing prose `<stage_decision>` XML (`seq` counts every
stage attempt starting at `1`; `try` is the attempt number `1..5` for that
stage; use `"stage": "image_iquv"` for stage 6 so its attempt counter stays
separate from Stokes I `image`). The tool validates every field and writes
`{workdir}/orchestrator/{seq:02d}_{stage}_try{try}.json` directly alongside
`<workdir>/events.jsonl` and `<workdir>/stage_log.jsonl` (and the `Stop` /
`SessionEnd` audit hook `scripts/plugin/audit_hook.sh` enriches it with full
handoff and check provenance) -- you do NOT call `Write` and do NOT emit prose
`<stage_decision>` XML.

**Never end a turn with text-only output after a `"next"` or `"retry"` decision.**
Because `ms_record_stage_decision` is a tool call, control always returns to you
after it completes -- immediately invoke the next `Agent` / `task(...)` stage
call (or diagnostic / `ms_report` tool call). Only end a turn with plain text
(no tool call) when `decision` is `"stop_ask_user"` or after the final
`ms_report` has completed.

Example tool call:

```
ms_record_stage_decision(
    seq=1,
    stage="precal",
    try=1,
    workdir="<workdir>",
    decision="next",
    deciding_metric="ms_workflow_status.next_recommended_step = delay_bandpass_gain (commands/calibrate.md:48)",
    reason="Priorcals, BP0.b, and bandpass model verified.",
    debug_directive=None,
    png_reviewed=None,
)
```

Required arguments in every `ms_record_stage_decision` call:
- `seq`: integer `1, 2, ...` across all stage attempts in this run
- `stage`: `"import" | "inspect" | "precal" | "calibrate" | "polcal" | "postcal" | "image" | "selfcal" | "image_iquv"`
- `try`: integer attempt counter (`1..5`) for this `stage`
- `workdir`: exact `workdir` path string
- `decision`: `"next" | "retry" | "stop_ask_user"`
- `deciding_metric`: exact `"<tool>.<field> = <value> vs <threshold> (<source>)"` copied from tool output (never retyped from memory; list any `not_checked` checks in `reason` and for final `caveats`)
- `reason`: 1 to 2 sentences stating which check decided it (and on a retry, what changes next)
- `debug_directive`: `null`, or `{"call": "<tool>", "params": {...}}` when `debug: allowed` on a retry
- `png_reviewed`: `null` on non-imaging stages; on `image`, `selfcal`, and `image_iquv`, 1 sentence stating what the PNG shows after you `Read` it (`"not_viewed"` if the image did not reach you)

## Stages

Call each stage agent with the Agent tool, `subagent_type` as named (in OpenCode,
pass the `task` tool's `subagent_type` without the `radio-analyst:` prefix, for
example `inspect-stage`). Give it a prompt with the stage's arguments first (the
stage command's own argument line), then the values you hand it, one per line as
`name: value`. Scope values are fixed here from `stokes`, not left to the stage.

Every stage prompt also carries `python: <path>` (and, if named in this session's
context, `run_step: <path>`): the interpreter and `run-step.sh` wrapper that run
the generated scripts (the ones this session's context names, or
`.pixi/envs/default/bin/python` and `scripts/plugin/run-step.sh` in a clone).
Find them once from context; the stages do not search for them.

| # | Stage | Agent | Arguments |
|---|---|---|---|
| 0 | import (when starting from `sdm_path`) | `radio-analyst:import-stage` | `sdm_path=<asdm_dir> workdir=<workdir>` (plus `ms_name:`, `spw:`, or `spw_mode: continuum\|all` if requested) |
| 1 | inspect | `radio-analyst:inspect-stage` | `<ms_path>` |
| 2 | precal | `radio-analyst:precal-stage` | `<ms_path> workdir=<workdir> online_flags=<...>`, the INSPECT HANDOFF lines, `pol_scope: off` when `stokes=I`; no `pol_scope` line when `stokes=IQUV`, so precal decides |
| 3 | calibrate | `radio-analyst:calibrate-stage` | `<ms_path> workdir=<workdir>` |
| 3b | polcal (`stokes=IQUV` only) | `radio-analyst:polcal-stage` | `<ms_path> workdir=<workdir>`, `angle_cal: <the precal handoff's angle_cal>` (plus any user `spw:` / `constraints:`) |
| 3c | postcal (pre-imaging, when section 3c RFI triage detects target outliers) | `radio-analyst:postcal-stage` | `<ms_path> workdir=<workdir>`, `field: <target fields>` |
| 4 | image | `radio-analyst:image-stage` | `<ms_path> workdir=<workdir>`, `stokes: I`, plus EVERY explicit user imaging constraint (`field:`, `spw:`, `cell:`, `imsize:`, `deconvolver:`, `pblimit:`, `pbmask:`, `nsigma:`, `constraints:`) |
| 4b | postcal (post-imaging fallback, if 3c did not run and section 4 B or C finds outliers) | `radio-analyst:postcal-stage` | `<ms_path> workdir=<workdir>`, `field: <target fields>` |
| 5 | selfcal (when section 4 says so) | `radio-analyst:selfcal-stage` | `<ms_path> workdir=<workdir> imagename=<prefix of the image to improve>`; with `stokes=IQUV`, `pol_tables: <kcross.K, dterms.D, and polangle.X if solved, full paths>` |
| 6 | image, IQUV cube (`stokes=IQUV` only, last) | `radio-analyst:image-stage` | `<ms_path> workdir=<workdir>`, `stokes: IQUV`, `imagename: <prefix of the last target image>`, plus any explicit user constraints (`spw:`, `cell:`, `imsize:`, `pblimit:`, `pbmask:`, `nsigma:`, `cube_width:`, `constraints:`) |

**User constraint forwarding (mandatory):** Whenever the user prompt states
explicit constraints (`field`, `spw`, `cell`, `imsize`, `deconvolver`,
`pblimit`, `pbmask`, `nsigma`, `cube_width`, or continuum-SPW selection), pass
each constraint verbatim as a `name: value` line (and any free-form requirements
as `constraints: <text>`) to the relevant stage agent. Never silently drop or
override user parameters across stage handoffs.

## Skill excerpts: static stage bundles

A stage agent does not load the full `radio-interferometry` skill. Pre-built
single-file bundles live under `{ri}/bundles/`, where `{ri}` is the sibling
`radio-interferometry/` directory of this skill's base directory. Do **not**
`Read` the bundle files yourself in the orchestrator -- pass the static path
at the end of each stage prompt (`inspect` takes none):

| Stage | Bundle path |
|---|---|
| import | `{ri}/bundles/import.md` |
| precal | `{ri}/bundles/precal.md` |
| calibrate | `{ri}/bundles/calibrate.md` |
| polcal | `{ri}/bundles/polcal.md` |
| image | `{ri}/bundles/image.md` |
| postcal | `{ri}/bundles/postcal.md` |
| selfcal | `{ri}/bundles/selfcal.md` |
| image, IQUV cube | `{ri}/bundles/image_iquv.md` |

Note: `07b-gaincal-recovery.md` is deferred by design -- `bundles/calibrate.md`
instructs `calibrate-stage` to `Read` `{ri}/07b-gaincal-recovery.md` only when a
Step 4b post-flight check fails.

Put one line at the end of the stage prompt, after the arguments and values:

```
SKILL EXCERPT FILE: <path>
```

## Checks after each stage

Each row cites the radio-interferometry skill text it comes from (file:line).
Run the tool yourself with the arguments named; do not take the value from the
handoff. `{cal}` is `{workdir}/calibrators.ms`; `{ms}` is the MS you were given.
Where the skill says "Hard stop" or "stop", the row stops and asks the user.

### 0. import (commands/import.md, 10-precal-workflow.md Step 0)

Run only when starting from `sdm_path=<asdm_dir>`. Use the handoff's `ms_path`
as `{ms}` and `online_flags` as `online_flags` for Stages 1--6.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Handoff complete | handoff `status:`, `ms_path:`, `online_flags:`, `continuum_spws:`, `full_stokes:` | `status: completed`, `ms_path` and `online_flags` non-empty | retry |
| MS valid on disk | `ms_workflow_status(<handoff ms_path>, workdir)` `ms_valid` | true | retry |
| Spectral windows populated (and continuum-only if split requested) | `ms_spectral_window_list(<handoff ms_path>)` `n_spws`, per-SPW widths | `n_spws > 0` matching requested SPW scope | retry |

### 1. inspect (commands/inspect.md, handoff block)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Handoff has all five lines; `cal_fields`, `bp_field` non-empty | handoff | all present | retry |
| `bp_field` is a field of the MS | `ms_field_list({ms})` field names | present | retry |

From the same `ms_field_list({ms})` read `bp_field`'s
`observing_frequency.centre_ghz` yourself; that is `bp_field_centre_ghz` below.

### 2. precal (10-precal-workflow.md:311-321, decision gate; :123 opacity row)

All four rows are "Hard stop" in the skill (10:317-320). Precal also cannot be
re-run on the same MS without undoing its flags, so a failed precal check stops.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| `gain_curves.gc` valid (10:317) | `ms_verify_priorcals({cal}, workdir)` `tables[].valid` | true | stop |
| `opacities.opac` valid when `bp_field_centre_ghz` >= 18 (10:318, :123) | same | true | stop |
| Initial bandpass caltables present (10:319) | `ms_verify_caltables({cal}, init_gain_table={workdir}/init_gain.g, bp_table={workdir}/BP0.b)` `caltables_valid` | true | stop |
| Bandpass model not the 1 Jy default (10:320) | `ms_verify_model({cal}, field=bp_field)` `per_field[].status` and `note`; with `pol_scope: on`, `field=<bp_field>,<angle_cal>` and `polcal_fields=<angle_cal>` | not default; the angle cal's cross-hands present | stop |
| Pre-calibration complete (commands/calibrate.md step 1) | `ms_workflow_status({ms}, workdir)` `next_recommended_step` | `delay_bandpass_gain` | stop |
| Polarisation scope (`stokes=IQUV` only; commands/precal.md step 6) | handoff `pol_scope:` and `angle_cal:` lines | `pol_scope: on` with an `angle_cal` | line missing: stop. `off`: stop and ask the user whether a Stokes I only reduction is acceptable, with the reason from the line. On yes, continue with `stokes=I`; record the user's answer in `reason` |

### 3. calibrate (07-calibration-execution.md:647-664, decision gate; 11-imaging.md:55-69, coherence gate)

Read the phase calibrator fields from `ms_field_list({cal})`, the target fields
from `ms_field_list({ms})`, and the channel range from
`ms_spectral_window_list({cal})` `suggested.center_channels_string` (the same
in-band range the solves used, 11:58-59). That string is per SpW, e.g.
`0:5~58,1:5~58`; `ms_corrected_stats` takes one `chan_start`/`chan_end`. When
every SpW has the same range, pass it. When they differ, mark the three
coherence rows `not_checked` with the string as the reason.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| BP flagged fraction (07:653) | `ms_calsol_stats({workdir}/bandpass.B)` `overall_flagged_frac` | < 0.20 | stop: the fix is more RFI excision in precal (07:660), which this orchestrator does not run |
| Gain flagged fraction (07:654) | `ms_calsol_stats({workdir}/gain.G)` `overall_flagged_frac` | < 0.15 | stop, as above |
| Antennas lost (07:655) | `ms_calsol_stats` `n_antennas_lost` on `initial_phase.G0`, `delay.K`, `bandpass.B`, `gain.G` | <= 3 each | stop (07:663) |
| fluxscale done, `gain.fluxscaled` written (07:658) | `ms_workflow_status({ms}, workdir)` `final_solves_completed` | contains `"fluxscale"` | retry |
| CORRECTED on the target (commands/image.md step 1) | same, `corrected_populated_target` (and `products_recorded.applycal` includes `{ms}`) | true | retry |
| Phase cal coherence (11:67) | `ms_corrected_stats({cal}, field=<phase cals>, chan_start, chan_end)` `phase_rms_deg` | < 30 | retry, re-solve |
| Phase cal gains (11:68) | same, `amp_robust_std` vs `amp_median` | < ~20% | retry |
| Target not decorrelated (11:69) | `ms_corrected_stats({ms}, field=<targets>, chan_start, chan_end)` `amp_median`, `amp_robust_std` | `amp_median` > 0, std not >> median | retry |

Record the target's `phase_rms_deg` per pointing beside that row. 11:69 gives no
phase criterion for the target (a resolved source has structure phase), so it
is a number to report, not a pass/fail.

Note as `not_checked` for final `caveats`: 07:656 (lost antennas flagged on both
MSs: no read-only tool measures it) and 07:657 (fluxscale flux vs
`flux_estimate`: note the stage's reported value from the handoff).

### 3b. polcal (09-polcal-execution.md, "Decision summary")

`stokes=IQUV` only. Rows cite the skill heading, not a line.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Pol solves and the pol apply on the target recorded (commands/polcal.md steps 4-7) | `ms_workflow_status({ms}, workdir, stokes='IQUV')` `next_recommended_step` | `postcal_target_rfi` or `first_image` | retry |
| Kcross amplitude (09 "Decision summary") | `ms_calsol_stats({workdir}/kcross.K)` `delay_abs_max_ns` | < 2 | pass, and put it in the caveats ("Flag in summary") |
| D-term median amplitude (09 "Decision summary") | `ms_calsol_stats({workdir}/dterms.D)` `amp_median` | < 0.05 | 0.05 to 0.10: pass, and put it in the caveats. Over 0.10: stop and ask; 09 names no action there, so this stop is our rule: say so |
| D-term outlier antennas (09 "Decision summary") | same, `outliers.amp_outliers_n_antennas` and `amp_outliers_by_antenna` | report it | none |
| PA coverage of the leakage cal (09 "PA coverage for a `Df+QU` solve") | `ms_pol_cal_conditions({cal})` `leakage_calibrator.pa_spread_deg` | report it | none |
| Xf solved | same `ms_workflow_status` call, `polcal_solves_completed` | report whether it holds `Xf` | none |

Note as `not_checked` for `caveats`, with the reason that no tool measures them:
the Xf PA residual and the `Df+QU` recovered Q/U (09 "Decision summary").

### 3c. Pre-imaging target CORRECTED_DATA RFI triage (before Stage 4)

Run right after Stage 3 `calibrate` passes (for `stokes=I`), or right after
Stage 3b `polcal` passes (for `stokes=IQUV`), **before** launching Stage 4
`image`. Imaging unflagged target RFI wastes a full `tclean` pass, causes
`stopcode=6` divergence, and inflates residual RMS even when calibration is
spotless; on clean data this check is a fast read-only no-op.

Run both read-only tools on the target fields:
1. `ms_spw_amp_severity({ms}, datacolumn='CORRECTED_DATA', field=<targets>, workdir=workdir)`
2. `ms_vis_amp_time_stats({ms}, field=<targets>, datacolumn='CORRECTED_DATA', top_k=5)`

Trigger `radio-analyst:postcal-stage` (conservative `rflag` only on target
`CORRECTED_DATA`, NEVER amplitude clip) BEFORE Stage 4 `image` if ANY of these
sky-cancelling adjacent-channel spectrum or time-outlier indicators is measured:
- `chan_diff_std_over_mad >= 1.5` OR `max_spw_chan_diff_std_over_mad >= 1.8` in `ms_spw_amp_severity`, OR
- `chan_diff_gt10sigma_frac >= 0.001` (`>= 0.1%` >10-sigma adjacent-channel outliers), OR
- `spw_rms_ratio >= 1.5` (`max_spw_rms / median_spw_rms`), OR
- Any well-populated integration (`npts >= 0.25 * median_npts`) in `ms_vis_amp_time_stats.top_outliers` has `ratio_to_median >= 2.0`.

If NONE of these hold (clean target spectrum, e.g. `chan_diff_std_over_mad ~ 1.02`
on clean C-band or L-band), skip `postcal-stage` and proceed directly to Stage 4
`image`. If `postcal-stage` runs here:
- Verify it against the Section 4b checks (`rc 0`, before/after `ms_flag_summary`,
  AND after-flagging `ms_spw_amp_severity` proving `chan_diff_std_over_mad < 1.5`,
  `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001`, and
  `spw_rms_ratio < 1.5`).
- Call `ms_record_stage_decision(stage="postcal", ...)` with the before/after
  spectrum numbers, and proceed to Stage 4 `image`.
- Postcal runs at most once per reduction (unless a retry is required because
  default `5.0/5.0` still left `chan_diff_std_over_mad >= 1.5`); if it already
  cleaned the spectrum in 3c, do not repeat it in Section 4 Step D.

### 4. image (11-imaging.md:327-365, quality gates)

The image stage makes an initial shallow pass (`hogbom`, or `mtmfs nterms=2`
with `specmode='mfs'` and `nsigma=5.0` when `fractional_span > 0.2` on a mosaic)
followed by adaptive masked `multiscale` / `mtmfs` passes (commands/image.md
steps 4-5, 11-imaging.md Step 2). Run the checks on the final image
(`.image.pbcor`, or `.image.tt0.pbcor` / `.image.pbcor.tt0` + `.psf.tt0` for
`mtmfs`) using `pb_level=0.1` (or user `pbmask`); report the first-pass numbers
beside them. Compute the radiometer prediction directly with
`ms_radiometer_estimate({ms}, field=<targets>, spw=<user spw or ''>, stokes='I', weighting='briggs', robust=0.5)`
(`thermal_rms_jy`, `fractional_span`).

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Image measures | `ms_image_stats(<imagename>.image.pbcor, psf_path, pb_level)` | status ok | retry |
| `tclean` convergence & deliverable hygiene (11 Step 8 & 9) | Read last `tclean` entry in `{workdir}/stage_log.jsonl`: `measurement.converged`, `measurement.stopcode`, and verify delivered product prefix | `converged == true` (`stopcode` is `2` or `8`) AND no rejected/diverged image listed or left unquarantined in `{workdir}` | **HARD FAIL** on `stopcode=1`, `5`, or `6`: NEVER accept or ship. Quarantine/move `<rejected>.*` into `{workdir}/rejected/` before retrying; keep Phase A shallow (`nsigma=5.0`), mask inside `PB >= 0.1`, verify clean target spectrum and full `imsize` (NEVER raise `threshold` above `~3--5x` rms) |
| `.model` positivity (Stokes I, 11 Step 9) | `ms_image_stats`: `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac` | Predominantly positive (`model_neg_to_pos_flux_ratio < 0.25`, `model_neg_to_pos_peak_ratio < 0.25`) | Negative-dominated or surging negative `.model`: quarantine rejected image and retry `image-stage` with tighter mask/scales or revert to cleaner earlier round (programmatic check; does not require vision) |
| Deconvolution convergence inside `PB >= 0.1` (11 Step 2 & 9) | `ms_image_stats`: `residual_out_mask_peak_snr`, `residual_in_mask_peak_snr`, `residual_in_to_out_rms_ratio`, `residual_in_model_rms_ratio` | `< 5.0`, `< 3.5`, `< 1.5`, `< 1.5` (quick-look `usemask='pb'` with `residual_in_model_rms_ratio > 1.5` or `residual_rms_jy > 1.3 * thermal_rms_jy` MUST run masked deep clean) | unmasked flux outside mask (`>= 5.0`) or uncleaned flux inside mask/model (`>= 3.5` or ratio `>= 1.5`): retry `image-stage` with `ms_make_mask` (`pb_level=0.1`) or Phase C deep clean (`nsigma=1.5`) BEFORE blaming calibration/RFI |
| Outer-PB residual probe (`0 < PB < 0.1`, 11 Step 2 & 9) | `ms_image_stats`: `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, `residual_outer_pb_peak_j2000` | Report always; **trigger Version-1 baby-peel probe** whenever `residual_outer_pb_peak_snr >= 20` AND science-PB RMS `> 1.3 * thermal_rms_jy` | When triggered: cross-match `(ra_deg, dec_deg)` against `ms_field_list` (if phasecal, include pointing), else retry `image-stage` to run Version-1 baby-peel probe (before/after dirty mosaic RMS) -- keep peeled MS if science-PB RMS improves, else keep unpeeled and report probe delta |
| `residual_out_mask_rms_jy` (else `residual_rms_jy`) vs `thermal_rms_jy` (11 Step 9) | `ms_image_stats` vs `ms_radiometer_estimate` | within 2x | over 2x after deconvolution converges: "When noise is not met" below |
| `residual_dynamic_range` (11 Step 9) | `ms_image_stats` | > 20 for a target | retry |
| Negative clean bowl (11 Step 9) | `ms_image_stats`: `flat_noise_min_jy`, `negative_to_peak_ratio` (flat-noise `.image`) | `negative_to_peak_ratio <= 0.05` (Stokes I) | > 0.05 (severe if > 0.10): negative clean bowl; check mask/`nsigma`/threshold and `.model` positivity, retry `image-stage` with tighter masking/threshold (or run "When noise is not met" if off-source RMS > 2x) |
| Visual PNG inspection (optional when vision available, 11 Step 9) | `Read(<prefix>.png)` from `ms_image_stats` `png_path` | Do not assume vision -- programmatic `.model` positivity and residual stats are primary; open PNG if vision is available | visible stripes, rings, or negative bowls: do not accept; run "When noise is not met" or retry `image-stage` with a concrete change |
| `detection` label (11 Step 9) | `ms_image_stats` | report it; not a pass/fail | none |

Note as `not_checked` unless the handoff gives the expected beam:
`beam_major_arcsec` and `peak_jy` (11 Step 9).

#### When noise is not met

**No bailout or rationalization on unresolved noise or bowls.** Never accept a
target image and proceed to `ms_report` while `residual_out_mask_rms_jy` (or
`residual_rms_jy` if unmasked) `> 2x thermal_rms_jy`, flat-noise
`negative_to_peak_ratio > 0.10`, or `Read(<prefix>.png)` shows severe stripes,
rings, or negative bowls. "Products exist", "stage status completed",
"deliverable just says produce mosaic", perceived time constraints, or
speculating that `thermal_rms_jy` is "optimistic" / "only for point sources"
are NEVER a pass. If you suspect `thermal_rms_jy` is unreachable, **Check A
(calibrator noise image) is the mandatory empirical test -- never skip Check A
to jump straight to B/C and bail out.** You MUST either resolve deconvolution
first (Check 0), execute Checks A -> B -> C in strict order and follow through
(postcal, re-image, or selfcal) until the gate passes, or emit
`decision: "stop_ask_user"` with the diagnostic numbers explaining why it could
not be resolved.

0. **Deconvolution convergence first (from `ms_image_stats` + `stage_log.jsonl`).**
   Before running Checks A--C, check whether deconvolution itself stalled:
   `residual_out_mask_peak_snr >= 5.0` (unmasked emission outside mask),
   `residual_in_mask_peak_snr >= 3.5` or `residual_in_to_out_rms_ratio >= 1.5`
   (uncleaned flux inside mask), flat-noise `negative_to_peak_ratio > 0.05`,
   `converged` false in `stage_log.jsonl`, or `deconvolver` still `hogbom`. If
   any of these hold, retry `radio-analyst:image-stage` first with the concrete
   imaging fix (continue mask growth with `atrous_do=True` / `thresh_pix=4.0,
   thresh_isl=2.5`, run Phase C deep clean at `nsigma=1.5` inside the fixed
   mask, or switch to `multiscale` / `asp` last).

Once deconvolution is converged, rule out calibration and data errors in this
strict order, running A, B, and C in order even when slow; a later step NEVER
stands in for an earlier one:

A. **Noise on the calibrator.** A point-source calibrator images to the noise
   when the calibration is good, so it is the representative noise test. Invoke
   the `radio-analyst:image-stage` subagent via the Agent/task tool (never call
   `ms_tclean` yourself -- the orchestrator does not execute scripts) with
   arguments `<ms_path> workdir=<workdir>`, `field: <phase cal>`, `stokes: I`,
   `passes: 1`, `imagename: <phase cal>_noise` (its own name, so the target
   images are not overwritten), plus its `SKILL EXCERPT FILE:` line
   (`{ri}/bundles/image.md`). Compare its `residual_rms_jy` against
   `ms_radiometer_estimate({ms}, field=<phase cal>, stokes='I',
   weighting='briggs', robust=0.5)` `thermal_rms_jy` (11 Step 9): within 2x
   rules the calibration out. Over 2x: the calibration is suspect; stop and ask.
B. **Target amplitude against frequency.** `ms_spw_amp_severity({ms},
   datacolumn='CORRECTED_DATA', field=<targets>)`. Its per-channel
   `robust_sigma` is the 13 Step 3 measure (13:101-106, :143-148). The floor is
   the median `robust_sigma` of the SpWs with the lowest `severity`. Note, per
   SpW, the channels and half-SpWs over 13 Step 3's cut values; those values
   are the 24A-376 starting values (13:109-112), not a rule, so note the
   numbers and say so; note any residual RFI on that reading, then run C.
C. **Target amplitude against time.** `ms_vis_amp_time_stats({ms},
   field=<targets>, datacolumn='CORRECTED_DATA', top_k=5)`. Read `median_amp`,
   `median_npts`, and the `top_outliers` entries (`utc`, `amp_mean`,
   `ratio_to_median`, and `npts` against `median_npts` -- a mostly flagged
   integration's mean rests on few points). If B found residual RFI or
   integrations stand apart here, go to D.
D. **Flag, then check again.** If Stage 3c did not already run `postcal-stage`,
   run stage 4b (postcal: rflag only on the target's CORRECTED data, no clip)
   with `field: <target fields>`. Then run B and C again and note both. Then
   re-run the image stage with `imagename: <target>_rflag`, so the earlier images
   stay for comparison. Postcal flags once per reduction (one successful run
   across 3c + 4b combined; a retry after a non-zero `.rc` counts against the
   cap of 5 like any stage); if 3c already ran or if B or C still finds outliers
   after postcal, stop and ask. From here on, "the image" in the steps below is
   the `_rflag` set. No skill rule gives a cutoff: say so in `reason`.

With A to C clear, the calibration and the data are ruled out, and the
remaining gap is the imaging. Work down this order, one step per attempt:

1. **Cleaning and masking.** Read `converged` and `stopcode` for the image from
   `{workdir}/stage_log.jsonl` (the `tclean` line), and its `deconvolver` and
   masking parameters from `{workdir}/tclean_<prefix>.py`. If a negative bowl is
   present (`negative_to_peak_ratio > 0.05` or visible bowl in `<prefix>.png`),
   or if cleaning did not converge, or the deconvolver was hogbom: retry
   `radio-analyst:image-stage` with a concrete change (tighter masking/`nsigma`/
   `threshold` to eliminate the bowl, `deconvolver: multiscale`, or
   `deconvolver: asp` last: 11 Step 2; asp is expensive, say so in `reason`).
2. **Verify the image visually.** Confirm `Read(<prefix>.png)` from the primary
   check table (re-Read after any retry) and pass what you see in
   `ms_record_stage_decision(..., png_reviewed=...)`: is the source structure
   clean, or are there stripes, rings or negative bowls around it? Never run
   selfcal against a bowled model.
3. **Selfcal, if the model is good.** Apply 12 Step 0 (12:36-62): `dynamic_range`
   from `ms_image_stats` (< 30: selfcal unlikely to help, stop and ask; 30 and
   up: proceed), and `ms_residual_stats` on each target pointing (any SpW with
   `p95_amp / median_amp` > 10: RFI-dominated, stop and ask). If the PNG shows a
   clean, bowl-free model and both pass, run stage 5 (selfcal) with `imagename=`
   the prefix of the last target-field image (it wrote MODEL_DATA, which selfcal
   solves against; never the calibrator noise image).

### 4b. postcal (rflag only)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| rflag ran on the targets | handoff `scripts` (`.rc` 0) and `ms_workflow_status` | rc 0 | retry |
| Flagged fraction before and after, per target field | the stage's `ms_flag_summary` numbers, from the handoff | report it | none |
| Target spectrum clean after rflag | `ms_spw_amp_severity({ms}, datacolumn='CORRECTED_DATA', field=<targets>, workdir=workdir)` | `chan_diff_std_over_mad < 1.5`, `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001`, `spw_rms_ratio < 1.5` | retry once with tighter thresholds (`timedevscale=4.0, freqdevscale=4.0`) or stop and ask |

### 5. selfcal (12-selfcal.md:193-246)

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Selfcal image measures | `ms_image_stats(<prefix>_sc1.image.pbcor, psf_path, pb_level)` | status ok | retry |
| `dynamic_range` change vs the image before (12:217-224) | `ms_image_stats`, both images | report it | < 10%: did not help, end; 10% or more: end and recommend more rounds to the user (12:235-246, one pass only); decreased: diverged, end and point at the `pcal1.g` solutions |

With `stokes=IQUV`, one more row: selfcal's applycal rebuilds CORRECTED on the
target, so it must carry the polarisation tables again.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Pol tables in selfcal's apply (12 Step 2) | the last `applycal` line for `{ms}` in `{workdir}/stage_log.jsonl` (Read it), `measurement.pol_types` | holds `Kcross` and `Df` | retry, with the `pol_tables:` line |

Read `<prefix>_sc1.png` and record `png_reviewed` as in section 4.

### 6. image, IQUV cube (11-imaging.md, "Polarization frequency cubes")

`stokes=IQUV` only, after every Stokes I stage. The cube is one hogbom pass with
`savemodel='none'`, so the Stokes I model in MODEL_DATA stays as it was.

| Check | Tool, field | Pass | On fail |
|---|---|---|---|
| Cube measures | `ms_image_stats(<prefix>_iquv.image.pbcor, psf_path, pb_level)` | status ok, `planes` present | retry |
| Stokes V near the noise (11 "Quality gates (per-plane)") | same, `planes`: V `peak_jy` / `rms_jy` per plane | report it | V over 5 times its rms in every plane: stop and ask. 11 gives no number, so 5 is our rule: say so |
| Q and U present (same table) | same, Q and U `peak_jy` per plane | report it | none |

Read `<prefix>_iquv.png` and record `png_reviewed` as in section 4.

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
`ms_casa_task_spec(task)` lists a task's parameters (pass `param_names=[...]`
when checking specific parameter names). Never debug on attempt 1.

To choose a value that no skill or stage command gives, call
`ms_casa_task_spec(task)` (with `param_names=[...]` when known), Read its
`docs_path`, then Read only the one piece you need.

## End

Before calling `ms_report`, verify: if target `residual_out_mask_rms_jy` (or
`residual_rms_jy` when unmasked) exceeded `2x thermal_rms_jy` after
deconvolution converged, Check A (calibrator noise image) was executed and the
noise ladder was either resolved or closed with `decision: "stop_ask_user"`
(never silently accepted).

After the last stage (or a stop), build the report with
`ms_report(workdir, summary, decisions, caveats, image_path=<last .image.pbcor>)`.
It embeds every PNG in the workdir and derives replay steps from `stage_log.jsonl`.
Summary: each stage, its attempts and the deciding check of each. Decisions:
each retry, debug use and selfcal decision with the numbers it rests on.
Caveats: every `not_checked` row. Use backticks only around short
`name = value` items. Then say in chat where the report is. Do not judge the
science beyond the checks.
