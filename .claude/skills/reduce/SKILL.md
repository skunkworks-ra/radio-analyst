---
name: reduce
description: >
  End-to-end reduction of a CASA Measurement Set, raw data to a first image:
  inspect, pre-calibration, calibration, optional post-cal flagging and
  polarisation, imaging. Invoke when asked to take an MS through to an image.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_observation_info,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_scan_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_scan_intent_summary,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_correlator_config,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_baseline_lengths,
               mcp__plugin_radio-analyst_ms-inspect__ms_elevation_vs_time,
               mcp__plugin_radio-analyst_ms-inspect__ms_parallactic_angle_vs_time,
               mcp__plugin_radio-analyst_ms-inspect__ms_shadowing_report,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_flag_fraction,
               mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_import,
               mcp__plugin_radio-analyst_ms-modify__ms_set_intents,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_preflag,
               mcp__plugin_radio-analyst_ms-inspect__ms_online_flag_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-modify__ms_generate_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_model,
               mcp__plugin_radio-analyst_ms-modify__ms_initial_bandpass,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_caltables,
               mcp__plugin_radio-analyst_ms-inspect__ms_plot_caltable_library,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_initial_rflag,
               mcp__plugin_radio-analyst_ms-inspect__ms_residual_stats,
               mcp__plugin_radio-analyst_ms-modify__ms_gaincal,
               mcp__plugin_radio-analyst_ms-inspect__ms_gaincal_snr_predict,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               mcp__plugin_radio-analyst_ms-modify__ms_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_flag_caltable,
               mcp__plugin_radio-analyst_ms-modify__ms_fluxscale,
               mcp__plugin_radio-analyst_ms-modify__ms_applycal,
               mcp__plugin_radio-analyst_ms-modify__ms_postcal_flag,
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy_polcal,
               mcp__plugin_radio-analyst_ms-modify__ms_polcal,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_corrected_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               Bash,
               Read,
               Write,
               Edit
---

# Reduce: one MS from raw data to a first image

Load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin) first. It holds the science; this skill holds the order
and the checks. Read each of its stage files when you reach that stage.

## The contract: `stages.json`

`stages.json` is a sibling of this file. Read it now. It lists the stages in
order, and each stage's steps. A step is a `before` list of checks, an
`action` (a write tool), and an `after` list of checks. Its `source` names the
command step or skill section it comes from.

1. Run the `before` checks, then the action, then the `after` checks, before
   the next action. The checks are how you know the action worked; the skill
   file for the stage says how to read them.
2. Then append the call that worked to the ledger with `ms_reduction_log`,
   as 00-playbook.md "Record every step" says: one entry per write call, the
   tool's own name, literal params, and the `script_path` that ran.
3. Do not re-run a check whose earlier result is still valid. `cache` in
   `stages.json` says which actions invalidate which checks. Each MS is its own
   target: a split (`calibrators.ms`, `working.ms`) starts uncached.
4. `optional` stages (polcal, postcal_flag, selfcal) may be skipped. Say so in the report.
   Selfcal is never automatic: after the first image, assess it with 12-selfcal.md Step 0
   (`ms_image_stats` and `ms_residual_stats`), then decide, and report the decision and
   the numbers it rests on either way.

## Stage order

| Stage | Read | Command with the step detail |
|---|---|---|
| inspect | 01-workflow.md, 01b-workflow-phase2.md, 04-diagnostic-reasoning.md | inspect.md |
| precal | 10-precal-workflow.md | precal.md |
| calibrate | 07-calibration-execution.md | calibrate.md |
| postcal_flag (optional) | 13-postcal-rfi-flagging.md | none |
| polcal (optional) | 09-polcal-execution.md | polcal.md |
| image | 11-imaging.md | image.md |
| selfcal (optional, your decision) | 12-selfcal.md | none |

## Work off the tools when you need to, and record it

You may edit a generated script or run your own CASA code when the science
needs it. Then record it: a ledger entry with `script_path` set to the script
that ran (`tool='manual'` for your own code), and the change in `rationale`.
Read-only diagnostic scripts need no entry. The ledger must be enough to
replay the reduction: replay re-runs each recorded script in order. Measure the image you report
with `ms_image_stats` on the image the recorded step produced.

## At the end

When you stop, a hook scores your calls against `stages.json` and returns any
open items: a check not run, an action not called, a step not in the ledger,
a generated script edited without a record. Do them, or say in the report why
each was skipped. It does not block anything else.

Then build the report with the `report` skill (`radio-analyst:report` installed
as a plugin).
