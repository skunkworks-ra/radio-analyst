---
description: First-pass continuum or cube imaging of a calibrated CASA MS with derived tclean parameters and image-quality assessment. Follows skill 11-imaging.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_observation_info,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_baseline_lengths,
               mcp__plugin_radio-analyst_ms-inspect__ms_scan_list,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               Bash,
               Read,
               Write
---

Run first-pass imaging on this calibrated MS: $ARGUMENTS

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read its `11-imaging.md` supporting
file (a sibling of that skill's `SKILL.md`) before starting.
Prerequisite: CORRECTED_DATA populated on the target field(s) — run
`/calibrate` (and `/polcal` for IQUV) first if not.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` — confirm CORRECTED is populated.

2. **Step 0 — field and Stokes** per 11-imaging.md §0. If the arguments give
   `stokes:`, `field:`, `deconvolver:`, `imagename:` or `passes: 1`, use them.
   `<name>` below is the `imagename:` given, else the target name. `passes: 1`:
   the first pass only, with `savemodel='none'` so the field's MODEL_DATA is not
   overwritten; t_on_source and the radiometer estimate are for the field imaged. Otherwise: the run's named
   targets (else all target fields, a mosaic for pointings of one source).
   Stokes: `stokes: I` from the arguments runs steps 3-7 for Stokes I.
   `stokes: IQUV` from the arguments runs steps 3, 4 and 8. With no `stokes:`, run
   steps 3-7 for Stokes I, then step 8 if polcal ran. State both in the report.

3. Gather placeholders from tool outputs (no hand math):
   - `ms_observation_info(ms_path)` → telescope, center_freq_hz
   - `ms_spectral_window_list(ms_path)` → bandwidth_hz
   - `ms_antenna_list(ms_path)` → dish_diameter_m, n_ant
   - `ms_baseline_lengths(ms_path)` → max_baseline_m, expected_beam_major_arcsec
   - `ms_scan_list(ms_path)` → t_on_source_s for the imaged field

4. Derive tclean parameters per 11-imaging.md §Steps 1–7:
   - specmode (§1): 'mfs' unless user asks for a cube
   - deconvolver (§2), two passes. First pass: 'hogbom' ('mtmfs' with nterms=2
     if bw/freq > 0.2). Second pass: 'multiscale' with `scales` per §2 (for mtmfs,
     keep 'mtmfs' and add `scales`). If the arguments give `deconvolver:`, the
     second pass uses it ('asp' is the last resort: ms_tclean warns it is
     expensive). Report the scales with the beam (arcsec) and cell they came
     from, so they can be recomputed.
   - cell (§3): 1 / (max_baseline_lambda × 3), rounded to 1 sf
   - imsize (§4): primary-beam-FWHM / cell, rounded up to composite number
   - Fresnel check (§5) → wprojplanes
   - gridder (§6): 'mosaic' for a first-pass mosaic (A-configuration: memory
     check first), 'wproject' single-pointing + W, else 'standard'
   - threshold (§7): 3 × the OSS equation-1 noise (eta_c, n_pol, per-pointing t_int
     for a mosaic, robust factor 1.2); format as mJy

5. First pass: `ms_tclean(ms_path, imagename=<name>_hogbom, field, stokes,
   specmode, deconvolver, nterms, gridder, wprojplanes, cell, imsize,
   weighting='briggs', robust=0.5, niter=50000, threshold,
   savemodel='modelcolumn', workdir, execute=False)` → run the generated script.
   Then step 6 on it.

   Second pass: the same call with `imagename=<name>_<deconvolver>`, the
   second-pass `deconvolver` and `scales` from step 4 → run. Then step 6 on it.
   MODEL_DATA now holds the second-pass model. Record both calls in the ledger;
   the first one's step label says "first pass (hogbom)".

6. `ms_image_stats(imagename.image.pbcor, psf_path=imagename.psf,
   pb_level=abs(pblimit), png_path=imagename.png)` (for mtmfs the image is the
   `.tt0` one: use the pbcor name on disk) — quality metrics; open the
   PNG per 11-imaging.md §Step 9.

7. Apply 11-imaging.md §Step 9 gates to the second-pass image; report the
   first-pass numbers beside them:
   - residual_rms_jy vs. radiometer prediction (2× tolerance)
   - residual_dynamic_range thresholds per field type
   - beam_major_arcsec vs. expected_beam_major_arcsec (20% tolerance)
   - peak_jy sanity check

8. **IQUV cube** per 11-imaging.md §Polarization frequency cubes, one pass:
   `ms_tclean(ms_path, imagename=<name>_iquv, field, stokes='IQUV',
   specmode='cube', deconvolver='hogbom', nchan, start, width, outframe='LSRK',
   gridder, wprojplanes, cell, imsize, weighting='briggs', robust=0.5,
   niter=50000, threshold, savemodel='none', workdir, execute=False)` → run.
   `savemodel='none'` keeps the Stokes I model in MODEL_DATA for selfcal.
   Gridder and wprojplanes from step 4. `nchan`, `start`, `width` from
   `ms_spectral_window_list(ms_path)` per §Channelization (one plane per SpW by
   default); cell and imsize at the highest frequency in the band; threshold
   per §7 with the plane width as the bandwidth.
   Then `ms_image_stats(<name>_iquv.image.pbcor, psf_path=<name>_iquv.psf,
   pb_level=abs(pblimit), png_path=<name>_iquv.png)` and report its `planes`
   against §Quality gates (per-plane) in place of step 7.

If `residual_rms_jy > 3 x` radiometer estimate, escalate: the problem is calibration
or unflagged target RFI, not imaging parameters.

**Output:** the derived tclean parameters, image paths, image-quality metrics
with pass/fail per gate, and a recommendation (ship, re-image with different
parameters, or go back to calibration).
