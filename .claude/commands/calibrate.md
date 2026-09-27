---
description: Full calibration solve for a pre-cal-complete CASA MS (initial phase → delay → bandpass → gain → fluxscale → applycal). Follows skill 07-calibration-execution.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_correlator_config,
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
               mcp__plugin_radio-analyst_ms-inspect__ms_gaincal_snr_predict,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               Bash,
               Read,
               Write
---

Run the full calibration solve sequence on this MS: $ARGUMENTS

Load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read its `07-calibration-execution.md`
supporting file (a sibling of that skill's `SKILL.md`) before
starting. Execute the stages below in order; STOP and report if any
ms_calsol_stats outlier gate fails.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` — confirm pre-cal is complete.
   If `next_recommended_step` is not `delay_bandpass_gain`, STOP.

2. Gather placeholders via tool output (no hand-derivation):
   - `ms_field_list(calibrators.ms)` → flux_field, bp_field, phase_fields
   - `ms_spectral_window_list(calibrators.ms)` → suggested.center_channels_string,
     suggested.wide_channels_string, all_spw_string
   - `ms_correlator_config(calibrators.ms)` → corrstring_casa
   - `ms_antenna_list(calibrators.ms)` → recommended_minblperant
   - `ms_verify_priorcals(workdir)` → priorcals_list
   - `ms_refant(calibrators.ms, field=bp_field)` → refant

3. `ms_gaincal_snr_predict(calibrators.ms, field=bp_field, solint='int')`
   — predictive pre-flight. If > 20% of (antenna, SpW) pairs predict SNR < 3,
   relax solint before launching gaincal.

4. Initial phase (G0): `ms_gaincal(…, gaintype='G', calmode='p', solint='int',
   spw=center_channels_string, caltable=workdir/initial_phase.G0, execute=False)`
   → run. Then `ms_calsol_stats(initial_phase.G0)` — check outliers block.

5. Delay (K): `ms_gaincal(…, gaintype='K', solint='inf', combine='scan',
   gaintable=[priorcals + G0], caltable=workdir/delay.K, execute=False)` → run.
   `ms_calsol_stats(delay.K)` — delay_rms_ns outlier gate.

6. Bandpass (B): `ms_bandpass(…, solint='inf', combine='scan',
   spw=wide_channels_string, gaintable=[priorcals + K + G0],
   caltable=workdir/bandpass.B, execute=False)` → run.
   `ms_calsol_stats(bandpass.B)` — bandpass SNR per SpW.

7. Gain solve on flux cal: `ms_gaincal(…, field=flux_field, gaintype='G',
   calmode='ap', solint='inf', gaintable=[priorcals + K + B],
   caltable=workdir/gain.G, execute=False)` → run.

8. Gain solve on phase cals (append): same caltable, different field.
   `ms_gaincal(…, field=phase_fields, …, append=True, …)` → run.
   `ms_calsol_stats(gain.G)` — outliers block gate.

9. `ms_fluxscale(…, caltable=gain.G, fluxtable=workdir/gain.fluxscaled,
   reference=flux_field, transfer=phase_fields, execute=False)` → run.

10. Applycal — three invocations (flux cal, phase cals, target) per
    07-calibration-execution.md §Step 7. Use `ms_applycal` with
    appropriate `gainfield` and `interp` per call.

11. `ms_flag_summary(full MS, field=target_fields)` — post-applycal flag delta.

**Output:** summary of each solve (caltable, stats summary, outliers),
confirmation that CORRECTED_DATA is populated on the target fields, and
the forward hand-off for `/image`.
