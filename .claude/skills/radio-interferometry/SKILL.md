---
description: >
  Radio interferometric data analysis for CASA Measurement Sets.
  Auto-invoked when working with .ms files, ms_inspect MCP tools,
  VLA/MeerKAT/uGMRT data, or any interferometry calibration/imaging task.
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
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_caltables,
               mcp__plugin_radio-analyst_ms-inspect__ms_rfi_channel_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-inspect__ms_online_flag_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_residual_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats_detail,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_plot,
               mcp__plugin_radio-analyst_ms-create__ms_sdm_summary,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               mcp__plugin_radio-analyst_ms-modify__ms_set_intents,
               mcp__plugin_radio-analyst_ms-modify__ms_initial_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_rflag,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_preflag,
               mcp__plugin_radio-analyst_ms-modify__ms_generate_priorcals,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy_polcal,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_initial_rflag,
               mcp__plugin_radio-analyst_ms-modify__ms_gaincal,
               mcp__plugin_radio-analyst_ms-modify__ms_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_fluxscale,
               mcp__plugin_radio-analyst_ms-modify__ms_applycal,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_phase_cal_lookup,
               Bash,
               Read,
               Write,
               Edit
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

Run CASA tasks only through the tools and the scripts they generate. Do not
call casatasks from Bash, from `python -c`, or from a script you write
yourself. The tool calls are the record of every parameter choice in the
reduction; a task run outside them leaves no trace of what was chosen. If no
tool exposes the step or the option you need, say which tool and which option
is missing, then continue with what the tools provide.

To change a parameter, call the tool again with the new value. Do not edit a
generated script, even to fix a path; call the tool again with the corrected
argument.

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
- `11-imaging.md`
- `12-selfcal.md`
- `13-postcal-rfi-flagging.md`
