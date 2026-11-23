---
description: Post-calibration rflag on the target's CORRECTED data (rflag only, no clip), verifying target spectrum cleanliness before and after via ms_spw_amp_severity and ms_flag_summary.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-inspect__ms_spw_amp_severity,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_rflag,
               Bash,
               Read
---

Arguments: the MS path, `workdir=<dir>`, and `field: <target fields>`. $ARGUMENTS
If `field:` is missing, STOP and ask for it: rflag must be scoped to the target
fields, whose CORRECTED is valid after the final applycal.

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry`
when installed as a plugin), then read only its `bundles/postcal.md` file
(resolved relative to that skill's `SKILL.md` directory).

Every MCP tool takes one argument, `params`. Every "-> run" below: run the
script via `run-step.sh` (`--wait 240`), as the skill's "Running generated
scripts" section says, re-running on `status=running` until `status=done`.
Every write step is recorded automatically in `<workdir>/stage_log.jsonl`.

1. **Before flagging:**
   - `ms_flag_summary(ms_path, field=<field>)`: flagged fraction before.
   - `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field=<field>, workdir=workdir)`:
     record `chan_diff_std_over_mad`, `max_spw_chan_diff_std_over_mad`,
     `chan_diff_gt10sigma_frac`, `spw_rms_ratio`, and per-SpW `chan_diff_rms`
     before flagging.
2. `ms_apply_rflag(ms_path, workdir, field=<field>, datacolumn='corrected',
   execute=False)` with the tool's default thresholds (or stricter thresholds if
   a retry specifies them) -> run. It saves flag version `before_rflag` first (a
   second run auto-versions `before_rflag_2`). CASA's default `extendflags=True`
   applies, so rflag also grows its flags in time and frequency; report that.
3. **After flagging (prove the target spectrum is clean):**
   - `ms_flag_summary(ms_path, field=<field>)`: flagged fraction after.
   - `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field=<field>, workdir=workdir)`:
     record after-flagging `chan_diff_std_over_mad`,
     `max_spw_chan_diff_std_over_mad`, `chan_diff_gt10sigma_frac`,
     `spw_rms_ratio`, and per-SpW `chan_diff_rms`. Clean target spectra have
     `chan_diff_std_over_mad < 1.5`, `max_spw_chan_diff_std_over_mad < 1.8`,
     `chan_diff_gt10sigma_frac < 0.001`, and `spw_rms_ratio < 1.5`.

**Output:** before and after flagged fractions per field, before and after
`ms_spw_amp_severity` adjacent-channel spectrum metrics (`chan_diff_std_over_mad`,
`max_spw_chan_diff_std_over_mad`, `chan_diff_gt10sigma_frac`, `spw_rms_ratio`),
the thresholds used, and the flag version name.
