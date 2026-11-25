---
description: Post-calibration rflag on the target's CORRECTED data (rflag only, no clip), verifying target spectrum cleanliness before and after via ms_spw_amp_severity and ms_flag_summary.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-inspect__ms_spw_amp_severity,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_rflag,
               Bash,
               Read
---

Arguments: the MS path, `workdir=<dir>`, `field: <target fields>`, and optional
`spw: <continuum_spws>` (`""` when all SPWs are continuum; required when
spectral-line / maser SPWs are present so `rflag` is scoped strictly to
continuum SPWs). $ARGUMENTS
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

1. **Scope strictly to continuum SPWs (`specmode='mfs'`) & measure before flagging:**
   - Automatic `freqdev` `rflag` and `surviving_spws` dropping apply **strictly
     to continuum SPWs**. Explicitly **exempt spectral-line / maser SPWs and
     rest-frequency line windows**, where genuine narrow astronomical line
     derivatives trigger `chan_diff_*`.
   - `ms_flag_summary(ms_path, field=<field>)`: flagged fraction before.
   - `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field=<field>, spw=<continuum_spws or ''>, workdir=workdir)`:
     record `chan_diff_std_over_mad`, `max_spw_chan_diff_std_over_mad`,
     `chan_diff_gt10sigma_frac`, `spw_noise_density_ratio`, `spw_rms_ratio`,
     and `per_spw` (`centre_freq_ghz`, `unflagged_fraction`,
     `chan_diff_std_over_mad`, `chan_diff_gt10sigma_frac`,
     `chan_diff_noise_density`, `chan_diff_rms`) before flagging.
2. **Bounded `rflag` (`<= 2` rounds max on continuum SPWs; NO destructive whole-SPW flagging):**
   - Round 1: `ms_apply_rflag(ms_path, workdir, field=<field>,
     spw=<continuum_spws>, datacolumn='corrected', execute=False)` (pass
     `spw=""` when all SPWs are continuum, or the explicit continuum SPW list
     when spectral-line / maser SPWs are present) with default thresholds
     (`5.0 / 5.0`, or retry-specified thresholds) -> run. It saves flag version
     `before_rflag` first (a second run auto-versions `before_rflag_2`). CASA's
     default `extendflags=True` applies; report that.
   - Re-run `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA',
     field=<field>, spw=<continuum_spws or ''>, workdir=workdir)`.
   - Round 2 (optional, ONLY if cleanable RFI outliers remain on candidate
     continuum SPWs): run at most ONE stricter pass via `ms_apply_rflag(ms_path,
     workdir, field=<field>, spw=<continuum_spws>, datacolumn='corrected',
     timedevscale=4.0, freqdevscale=4.0, execute=False)` -> run. **HARD CAP:
     never run more than 2 `rflag` rounds in `postcal`, never run automatic
     `freqdev` `rflag` on spectral-line / maser SPWs or rest-frequency line
     windows, never spin on persistently RFI-saturated or
     atmospheric-absorption-dominated SPWs, and never destructively flag whole
     SPWs.**
3. **Per-SPW triage & surviving SPW verification (continuum SPWs only):**
   - `ms_flag_summary(ms_path, field=<field>)`: flagged fraction after.
   - Inspect `per_spw` from `ms_spw_amp_severity`: identify any persistently
     RFI-saturated, atmospheric-absorption-dominated, or >95%-flagged continuum
     SPWs (never auto-drop spectral-line / maser SPWs) and build
     `<surviving_spws>` in valid CASA SPW syntax (comma-separated clean
     continuum SPW IDs, e.g. `2,3,4,5`, or `0~15` / `""` empty string when every
     SPW is clean -- **NEVER** write the word `all`, which `parse_spw_selection`
     and CASA `MSSelection` reject).
   - Call `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA',
     field=<field>, spw=<surviving_spws>, workdir=workdir)` to verify the
     surviving continuum SPWs pass the SEFD-invariant within-SPW Gaussianity
     spectrum gate:
     - `chan_diff_std_over_mad < 1.5`
     - `max_spw_chan_diff_std_over_mad < 1.8`
     - `chan_diff_gt10sigma_frac < 0.001`
     - Treat bandwidth-normalized `spw_noise_density_ratio` (from
       `chan_diff_noise_density = chan_diff_rms * sqrt(chan_width_hz)`) /
       `spw_rms_ratio` strictly as a secondary smoothness diagnostic
       (discontinuous single-SPW jump vs smooth `T_sys(nu)` / atmospheric /
       sky-temperature gradient), not a hard gate.

**Output:** before and after flagged fractions per field, before and after
`ms_spw_amp_severity` adjacent-channel spectrum metrics (both full-band and on
`spw=<surviving_spws>`), the thresholds and number of `rflag` rounds used
(`<= 2`), the flag version name, and an explicit
`surviving_spws: <valid CASA SPW syntax, e.g. 2,3,4,5 or 0~15 or "" -- NEVER the word all>`
line in the handoff for downstream `image`, `selfcal`, and `image_iquv`.
