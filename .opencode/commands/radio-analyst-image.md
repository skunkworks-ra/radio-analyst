---
description: First-pass continuum or cube imaging of a calibrated CASA MS with derived tclean parameters and image-quality assessment. Follows skill 11-imaging.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_observation_info,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_baseline_lengths,
               mcp__plugin_radio-analyst_ms-inspect__ms_scan_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_radiometer_estimate,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               Bash,
               Read
---

Run first-pass imaging on this calibrated MS: $ARGUMENTS

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read its `bundles/image.md` file (and
`bundles/image_iquv.md` if imaging `stokes='IQUV'`), resolved relative to that
skill's `SKILL.md` directory, before starting.
Prerequisite: CORRECTED_DATA populated on the target field(s) -- run
`/calibrate` (and `/polcal` for IQUV) first if not.

Every write step is recorded automatically in `<workdir>/stage_log.jsonl`.
Every "-> run" below: run the script via `run-step.sh` (`--wait 240`), as the
skill's "Running generated scripts" section says, re-running on `status=running`
until `status=done`.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` -- confirm CORRECTED is populated.

2. **Step 0 -- field and Stokes** per 11-imaging.md Step 0. If the arguments give
   `stokes:`, `field:`, `deconvolver:`, `imagename:` or `passes: 1`, use them.
   `<name>` below is the `imagename:` given, else the target name. `passes: 1`:
   the first pass only, with `savemodel='none'` so the field's MODEL_DATA is not
   overwritten; `on_source_s` and `thermal_rms_jy` from `ms_radiometer_estimate`
   are for the field imaged. Otherwise: the run's named targets (else all target
   fields, a mosaic for pointings of one source).
   Stokes: `stokes: I` from the arguments runs steps 3-7 for Stokes I.
   `stokes: IQUV` from the arguments runs steps 3, 4 and 8. With no `stokes:`, run
   steps 3-7 for Stokes I, then step 8 if polcal ran. State both in the report.

3. Gather placeholders from tool outputs (no hand math):
   - `ms_radiometer_estimate(ms_path, field, spw='', stokes, weighting='briggs', robust=0.5)` -> `telescope_name`, `center_freq_hz`, `total_bw_hz`, `eff_bw_hz`, `n_ant_unflagged`, `on_source_s`, `thermal_rms_jy`
   - `ms_antenna_list(ms_path)` -> `dish_diameter_m`, `n_antennas`
   - `ms_baseline_lengths(ms_path)` -> `max_baseline_m`, `resolution_arcsec_range`
   - `ms_spectral_window_list(ms_path)` -> per-SPW edges and widths (when running step 8)

4. Derive tclean parameters per 11-imaging.md Steps 1-7:
   - specmode (Step 1): `'mfs'` unless user asks for a cube
   - deconvolver (Step 2), two passes. First pass: `'hogbom'` (`'mtmfs'` with `nterms=2`
     if `total_bw_hz / center_freq_hz > 0.2`). Second pass: `'multiscale'` with `scales` per Step 2 (for mtmfs,
     keep `'mtmfs'` and add `scales`). If the arguments give `deconvolver:`, the
     second pass uses it (`'asp'` is the last resort: `ms_tclean` warns it is
     expensive). Report the scales with the beam (arcsec) and cell they came
     from, so they can be recomputed.
   - cell (Step 3): `1 / (max_baseline_lambda * 3)`, rounded to 1 sf
   - imsize (Step 4): primary-beam diameter (`3 * pb_fwhm_arcsec`, or mosaic extent + `3 * pb_fwhm_arcsec`) / cell, rounded up to composite number
   - Fresnel check (Step 5) -> `wprojplanes`
   - gridder (Step 6): `'mosaic'` for a first-pass mosaic (A-configuration: memory
     check first), `'wproject'` single-pointing + W, else `'standard'`
   - threshold (Step 7): `3 * thermal_rms_jy` from `ms_radiometer_estimate`; format as mJy

5. First pass: `ms_tclean(ms_path, imagename=<name>_hogbom, field, stokes,
   specmode, deconvolver, nterms, gridder, wprojplanes, cell, imsize,
   weighting='briggs', robust=0.5, niter=50000, threshold,
   savemodel='modelcolumn', workdir, execute=False)` -> run.
   Then step 6 on it.

   Second pass: the same call with `imagename=<name>_<deconvolver>`, the
   second-pass `deconvolver` and `scales` from step 4 -> run. Then step 6 on it.
   MODEL_DATA now holds the second-pass model (both calls record automatically in
   `stage_log.jsonl`).

6. `ms_image_stats(imagename.image.pbcor, psf_path=imagename.psf,
   pb_level=abs(pblimit), png_path=imagename.png)` (for mtmfs the image is the
   `.tt0` one: use the pbcor name on disk) -- quality metrics; open the
   PNG per 11-imaging.md Step 9.

7. Apply 11-imaging.md Step 9 gates to the second-pass image; report the
   first-pass numbers beside them:
   - `residual_rms_jy` vs. `thermal_rms_jy` from `ms_radiometer_estimate` (2x tolerance)
   - `residual_dynamic_range` thresholds per field type
   - `beam_major_arcsec` vs. `lambda / max_baseline_m * (180*3600/pi)` (20% tolerance)
   - `peak_jy` sanity check

8. **IQUV cube** per 11-imaging.md Polarization frequency cubes, one pass:
   `ms_tclean(ms_path, imagename=<name>_iquv, field, stokes='IQUV',
   specmode='cube', deconvolver='hogbom', nchan, start, width, outframe='LSRK',
   gridder, wprojplanes, cell, imsize, weighting='briggs', robust=0.5,
   niter=50000, threshold, savemodel='none', workdir, execute=False)` -> run.
   `savemodel='none'` keeps the Stokes I model in MODEL_DATA for selfcal.
   Gridder and wprojplanes from step 4. `nchan`, `start`, `width` from
   `ms_spectral_window_list(ms_path)` per Channelization (one plane per SpW by
   default); cell and imsize at the highest frequency in the band; threshold
   per Step 7 scaled to the plane width (`thermal_rms_jy * sqrt(eff_bw_hz / width_hz)`).
   Then `ms_image_stats(<name>_iquv.image.pbcor, psf_path=<name>_iquv.psf,
   pb_level=abs(pblimit), png_path=<name>_iquv.png)` and report its `planes`
   against Quality gates (per-plane) in place of step 7.

If `residual_rms_jy > 3 * thermal_rms_jy`, escalate: the problem is calibration
or unflagged target RFI, not imaging parameters.

**Output:** the derived tclean parameters (including `thermal_rms_jy` from
`ms_radiometer_estimate`), image paths, image-quality metrics with pass/fail per
gate, and a recommendation (ship, re-image with different parameters, or go back
to calibration).
