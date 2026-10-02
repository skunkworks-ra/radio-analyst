---
description: First-pass continuum or cube imaging of a calibrated CASA MS with derived tclean parameters and image-quality assessment. Follows skill 11-imaging.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_observation_info,
               mcp__plugin_radio-analyst_ms-inspect__ms_antenna_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_baseline_lengths,
               mcp__plugin_radio-analyst_ms-inspect__ms_scan_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_smearing_limits,
               mcp__plugin_radio-analyst_ms-modify__ms_split_average,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               Bash,
               Read,
               Write
---

Run first-pass imaging on this calibrated MS: $ARGUMENTS

Load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read its `11-imaging.md` supporting
file (a sibling of that skill's `SKILL.md`) before starting.
Prerequisite: CORRECTED_DATA populated on the target field(s) — run
`/calibrate` (and `/polcal` for IQUV) first if not.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` — confirm CORRECTED is populated.

2. **Step 0 — confirm field and Stokes with the user** per 11-imaging.md §0.
   Never assume mosaic vs. single pointing. Default Stokes='I' unless
   polcal is complete and the user wants IQUV.

3. If no averaged target MS exists, read `15-averaging.md`:
   `ms_smearing_limits` → `ms_split_average` → run the script → verify.
   Use the averaged MS as `ms_path` from here on.

3a. Gather placeholders from tool outputs (no hand math):
   - `ms_observation_info(ms_path)` → telescope, center_freq_hz
   - `ms_spectral_window_list(ms_path)` → bandwidth_hz
   - `ms_antenna_list(ms_path)` → dish_diameter_m, n_ant
   - `ms_baseline_lengths(ms_path)` → max_baseline_m, expected_beam_major_arcsec
   - `ms_scan_list(ms_path)` → t_on_source_s for the target field

4. Derive tclean parameters per 11-imaging.md §Steps 1–7:
   - specmode (§1): 'mfs' unless user asks for a cube
   - deconvolver (§2): 'mtmfs' with nterms=2 if bw/freq > 0.2, else 'hogbom'
   - cell (§3): 1 / (max_baseline_lambda × 3), rounded to 1 sf
   - imsize (§4): primary-beam-FWHM / cell, rounded up to composite number
   - Fresnel check (§5) → wprojplanes
   - gridder (§6): 'awp2' mosaic + EVLA/ALMA, 'wproject' single-pointing + W,
     else 'standard'
   - threshold (§7): 3 × radiometer RMS from SEFD table; format as mJy

5. `ms_tclean(ms_path, imagename, field, stokes, specmode, deconvolver,
   nterms, gridder, wprojplanes, cell, imsize, weighting='briggs',
   robust=0.5, niter=50000, threshold, savemodel='modelcolumn',
   workdir, execute=False)` → run the generated script. Wait for completion.

6. `ms_image_stats(imagename.image.pbcor, psf_path=imagename.psf)`
   — quality metrics.

7. Apply 11-imaging.md §Step 9 gates:
   - rms_jy vs. radiometer prediction (2× tolerance)
   - dynamic_range thresholds per field type
   - beam_major_arcsec vs. expected_beam_major_arcsec (20% tolerance)
   - peak_jy sanity check

If `rms_jy > 3 ×` radiometer estimate, escalate — the problem is calibration,
not imaging. `ms_residual_stats` on the target's CORRECTED column before
re-imaging.

**Output:** the derived tclean parameters, image paths, image-quality metrics
with pass/fail per gate, and a recommendation (ship, re-image with different
parameters, or go back to calibration).
