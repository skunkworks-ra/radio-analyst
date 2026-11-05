---
description: Full calibration solve for a pre-cal-complete CASA MS (initial phase → delay → bandpass → gain → fluxscale → applycal). Follows skill 07-calibration-execution.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-modify__ms_gaincal,
               mcp__plugin_radio-analyst_ms-modify__ms_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_fluxscale,
               mcp__plugin_radio-analyst_ms-modify__ms_applycal,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats_detail,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_plot,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-inspect__ms_plot_caltable_library,
               mcp__plugin_radio-analyst_ms-inspect__ms_phase_cal_lookup,
               mcp__plugin_radio-analyst_ms-modify__ms_flag_caltable,
               mcp__plugin_radio-analyst_ms-modify__ms_flag_data,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               Bash,
               Read
---

Run the full calibration solve sequence on this MS: $ARGUMENTS

Load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read only its `07-calibration-execution.md` and
`ledger.md` supporting files (siblings of that skill's `SKILL.md`) before
starting. Skip the files the skill lists under "Start here"; calibrate does not
use them. Execute the stages below in order; STOP and report if any
ms_calsol_stats outlier gate fails. Record each validated write step with
`ms_reduction_log`, as `ledger.md` says.
Every MCP tool takes one argument, `params`: `{"ms_path": ..., ...}`.
The tools in allowed-tools above are granted for this stage, `ms_flag_summary` included,
even if an earlier stage denied one of them: call them.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` — confirm pre-cal is complete.
   If `next_recommended_step` is not `delay_bandpass_gain`, STOP.

2. Gather placeholders via tool output (no hand-derivation):
   - `ms_field_list(calibrators.ms)` → flux_field, bp_field, phase_fields
   - `ms_spectral_window_list(calibrators.ms)` → suggested.center_channels_string,
     suggested.wide_channels_string, all_spw_string
   - `ms_antenna_list(calibrators.ms)` → recommended_minblperant
   - `ms_verify_priorcals(workdir)` → priorcals_list
   - `ms_refant(calibrators.ms, field=<each calibrator>)` → refant healthy on all of them

3. Initial phase (G0): `ms_gaincal(…, gaintype='G', calmode='p', solint='int',
   spw=center_channels_string, caltable=workdir/initial_phase.G0, execute=False)`
   → run. Then `ms_calsol_stats(initial_phase.G0)` — check outliers block.

4. Delay (K): `ms_gaincal(…, gaintype='K', solint='inf', combine='scan',
   gaintable=[priorcals + G0], caltable=workdir/delay.K, execute=False)` → run.
   `ms_calsol_stats(delay.K)` — delay_rms_ns outlier gate.

5. Bandpass (B): `ms_bandpass(…, solint='inf', combine='scan',
   spw=all_spw_string, gaintable=[priorcals + G0 + K],
   interp=['' per priorcal, '', 'nearest,nearestflag'],
   caltable=workdir/bandpass.B, execute=False)` → run.
   `ms_calsol_stats(bandpass.B)` — bandpass SNR per SpW. Then
   `ms_flag_caltable(bandpass.B, sigma=5.0)` before it is used (07 Step 3).

6. Gain solve on all calibrators in one call (skill 07 Step 4, which has the
   interp list):
   `ms_gaincal(…, field='<flux_field>,<phase_fields>', gaintype='G',
   calmode='ap', solint='inf', gaintable=[priorcals + K + B],
   target_fields='<phase_fields>', caltable=workdir/gain.G, execute=False)` → run.
   calibrators.ms holds no target fields, so name the phase calibrators as the
   transfer fields.

7. `ms_calsol_stats(gain.G)` — outliers block gate. (ms_gaincal has no append:
   a second call on the same caltable archives the first.) A named bad
   solution: flag its data with `ms_flag_data` and re-solve, not the caltable
   (07 "Flagging by hand").

8. `ms_fluxscale(…, caltable=gain.G, fluxtable=workdir/gain.fluxscaled,
   reference=flux_field, transfer=phase_fields, execute=False)` → run.

9. Applycal — flux cal, then each phase cal in its own call, then target, per
   07-calibration-execution.md §Step 7. Use `ms_applycal` with
   appropriate `gainfield` and `interp` per call. Around each invocation run
   the flag-jump check (07 "Flag jump at applycal"):
   `ms_flag_summary` on the fields that invocation writes, before and after it
   (calibrators.ms for the calibrators, the full MS for the target). A jump of
   15 percentage points or more on any field: find the cause, flag it, re-solve,
   and apply again, as that section says.

**Output:** summary of each solve (caltable, stats summary, outliers), the
flag fraction before and after each applycal, confirmation that CORRECTED_DATA
is populated on the target fields, and the forward hand-off for `/image`.
