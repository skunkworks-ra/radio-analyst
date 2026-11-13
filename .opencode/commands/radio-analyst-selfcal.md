---
description: One pass of phase-only self-calibration on the target of a calibrated, imaged MS, with a before/after image comparison. Follows skill 12-selfcal.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_residual_stats,
               mcp__plugin_radio-analyst_ms-modify__ms_gaincal,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_plot_caltable_library,
               mcp__plugin_radio-analyst_ms-modify__ms_applycal,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               Bash,
               Read
---

Arguments: the MS path, `workdir=<dir>`, and `imagename=<prefix>` of the image
to improve (its tclean script is in `<workdir>/` and `stage_log.jsonl`). $ARGUMENTS

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry`
when installed as a plugin), then read only its `bundles/selfcal.md` file
(resolved relative to that skill's `SKILL.md` directory).

Every MCP tool takes one argument, `params`. Every "-> run" below: run the
script via `run-step.sh` (`--wait 240`), as the skill's "Running generated
scripts" section says, re-running on `status=running` until `status=done`.
Every write step is recorded automatically in `<workdir>/stage_log.jsonl`.
One pass only; do not iterate (12 Step 5).

1. `ms_workflow_status(ms_path, workdir)`: confirm the 12 Prerequisites.
2. Step 0: `ms_residual_stats` on each target pointing (IDs from
   `ms_field_list(ms_path)`). Report `p95_amp / median_amp` per SpW.
3. Step 1: `ms_gaincal` phase-only against MODEL_DATA, with the full target
   stack and `gainfield`/`interp` exactly as 12 Step 1 gives them
   (`caltable=workdir/pcal1.g`, `execute=False`) -> run. Then
   `ms_calsol_stats(pcal1.g, verbosity='full')` and
   `ms_plot_caltable_library([pcal1.g], workdir)`. Apply 12 Step 1's checks:
   if `abs(phase_mean_deg)` < 1 and `phase_rms_deg` < 1 on every antenna, stop
   here and report (no phase error to correct).
4. Step 2: `ms_applycal` on the target with the full stack plus `pcal1.g`, as
   12 Step 2 gives it -> run.
   If the arguments give `pol_tables:`, append those tables to the stack in
   steps 3 and 4, before `pcal1.g`, with `gainfield=''` and `interp='nearest'`
   (12 Steps 1 and 2). Without them this apply removes the polarisation
   calibration from CORRECTED.
5. Step 3: Read the script of the image to improve,
   `workdir/tclean_<prefix basename, '.' as '_'>.py`, and call `ms_tclean` with
   every parameter it used, `imagename=<prefix>_sc1` -> run.
6. Step 4: `ms_image_stats` on `<prefix>_sc1.image.pbcor` (`psf_path`,
   `pb_level`, `png_path=<prefix>_sc1.png`), and on the first image if its
   numbers were not already supplied.

**Output:** the 12 Step 4 before/after table (`rms_jy`, `residual_rms_jy`,
`dynamic_range`, `peak_jy`), the `pcal1.g` solution stats, and the PNG paths.
