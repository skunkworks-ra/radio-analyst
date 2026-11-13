---
description: Polarization calibration sequence on a calibrated MS (Kcross -> D-terms -> Xf -> applycal-with-parang). Follows skill 09-polcal-execution.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_parallactic_angle_vs_time,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_model,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy_polcal,
               mcp__plugin_radio-analyst_ms-modify__ms_gaincal,
               mcp__plugin_radio-analyst_ms-modify__ms_polcal,
               mcp__plugin_radio-analyst_ms-modify__ms_flag_caltable,
               mcp__plugin_radio-analyst_ms-modify__ms_applycal,
               mcp__plugin_radio-analyst_ms-inspect__ms_calsol_stats,
               Bash,
               Read
---

Run polarization calibration on this MS: $ARGUMENTS

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read only its `bundles/polcal.md` file (resolved
relative to that skill's `SKILL.md` directory) before starting, skipping the
files the skill lists under "Start here".
Prerequisite: delay.K, bandpass.B, gain.G and gain.fluxscaled exist, and
CORRECTED is on the target -- run `/calibrate` first if not.

Arguments: the MS path (the full MS, holding the target) and `workdir=<dir>`.
The solves run on `{workdir}/calibrators.ms`; only the target apply writes to the
full MS. Every write step is recorded automatically in `<workdir>/stage_log.jsonl`.
Every MCP tool takes one argument, `params`.
Every "-> run" below: run the script via `run-step.sh` (`--wait 240`), as the
skill's "Running generated scripts" section says, re-running on `status=running`
until `status=done`.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir, stokes='IQUV')` -- confirm calibration
   is complete. If `next_recommended_step` is neither `polcal` nor
   `applycal_pol_target`, STOP. Exception: `first_image` with a `retry:` line
   in the arguments means redo the polcal: continue.

2. `ms_pol_cal_conditions(calibrators.ms)` -- measure the conditions, then decide.
   Apply 09-polcal-execution.md Reading the conditions:
   - Angle standard (`pol_angle_calibrator.category == 'A'`) present
     -> Steps 4-7, Xf included, whatever the PA coverage.
   - No angle standard -> Steps 4, 5 and 7 only; report that absolute EVPA is
     uncalibrated and which claims that rules out.
   - `variability_warning` set -> proceed, and annotate EVPA results with it.
   - For the D-terms, take `recommended_df_poltype` with its basis, and read
     `pa_spread_deg` against the coverage table. Below ~30 deg state the coverage
     alongside every polarisation number; consider a better-covered field from
     `leakage_cal_candidates` and say so if you switch.
   If the arguments give `angle_cal:`, that is the angle cal (precal set its
   polarised model); use it. Placeholders (09 Placeholder reference): `ms_verify_priorcals(calibrators.ms,
   workdir)` -> priorcals_list; `ms_refant(calibrators.ms, field=<angle cal>)` ->
   refant; `ms_field_list` on calibrators.ms and on the full MS -> calibrator,
   phase and target fields.

3. The angle cal's polarised model was set in precal (10 Step 4). Confirm it
   with `ms_verify_model(calibrators.ms, field=<all cals>, polcal_fields=<angle cal>)`.
   Run `ms_setjy_polcal` here only if precal ran without polarisation in scope,
   and then redo the calibration solve: it was made against a Stokes-I model.

4. Cross-hand delay on calibrators.ms: `ms_gaincal(..., field=angle_cal,
   gaintype='KCROSS', solint='inf', combine='scan', smodel=[1, 0, 1, 0],
   gaintable=[priorcals + K + B + G], caltable=workdir/kcross.K, execute=False)`
   -> run. `ms_calsol_stats(kcross.K)` -- report `delay_abs_max_ns` (09: < 2 ns).

5. D-term leakage on calibrators.ms: `ms_polcal(..., field=leakage_cal,
   poltype=<recommended_df_poltype: 'Df' for a known- or zero-pol source, 'Df+QU'
   for an unknown-pol one>, solint='inf', combine='scan',
   gaintable=[priorcals + K + B + G + kcross], caltable=workdir/dterms.D,
   execute=False)` -> run. Then `ms_flag_caltable(dterms.D, sigma=5.0)` before it
   is used (09 Step 3). `ms_calsol_stats(dterms.D)` -- report `amp_median` and
   `outliers.amp_outliers_n_antennas`.

6. Position angle on calibrators.ms (only if an angle standard was observed):
   `ms_polcal(..., field=angle_cal, poltype='Xf', solint='inf', combine='scan',
   gaintable=[priorcals + K + B + G + kcross + dterms],
   caltable=workdir/polangle.X, execute=False)` -> run.

7. One applycal step, after every polarisation solve, with `parang=True`
   (mandatory), one call per field type as 09-polcal-execution.md Step 5:
   priorcals -> K -> B -> `gain.fluxscaled` -> kcross -> dterms -> polangle (when
   solved), with the gainfield and interp that step gives. Each calibrator on
   calibrators.ms (5a), the target on the full MS (5b). Never `gain.G` here: it
   leaves the target off the flux scale.

**Output:** summary of each polcal step, `delay_abs_max_ns` for kcross.K,
`amp_median` and outlier antennas for dterms.D, whether Xf was solved and why,
confirmation that CORRECTED_DATA on the target holds the polarisation apply,
and the forward hand-off for `/image` with `stokes='IQUV'`.
