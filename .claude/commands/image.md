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
               mcp__plugin_radio-analyst_ms-inspect__ms_spw_amp_severity,
               mcp__plugin_radio-analyst_ms-modify__ms_make_mask,
               mcp__plugin_radio-analyst_ms-modify__ms_tclean,
               mcp__plugin_radio-analyst_ms-modify__ms_casa_task,
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
until `status=done` (`rc=0`). NEVER exit, summarize completion, or move to
`ms_image_stats` while `run-step.sh` is still `status=running`; verify the
expected `.image.pbcor` exists on disk first.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` -- confirm `corrected_populated_target` is True and `next_recommended_step` is not `applycal_target` or earlier (STOP if not).

2. **Step 0 -- field, Stokes, and user constraints** per 11-imaging.md Step 0.
   If the arguments give `stokes:`, `field:`, `spw:`, `cell:`, `imsize:`,
   `deconvolver:`, `pblimit:`, `pbmask:`, `nsigma:`, `cube_width:`,
   `imagename:`, `passes: 1`, or `constraints:`, honor EVERY explicit value
   (do not silently drop or shrink a user-specified `spw`, `cell`, `imsize`,
   `pblimit`, `pbmask`, `nsigma`, or `cube_width`).
   `<name>` below is the `imagename:` given, else the target name. `passes: 1`:
   the first pass only, with `savemodel='none'` so the field's MODEL_DATA is not
   overwritten; `on_source_s` and `thermal_rms_jy` from `ms_radiometer_estimate`
   are for the field imaged. Otherwise: the run's named targets (else all target
   fields, a mosaic for pointings of one source).
   Stokes: `stokes: I` from the arguments runs steps 3-7 for Stokes I.
   `stokes: IQUV` from the arguments runs steps 3, 4 and 8. With no `stokes:`, run
   steps 3-7 for Stokes I, then step 8 if polcal ran. State both in the report.

3. Gather placeholders from tool outputs (no hand math) and confirm clean target spectrum:
   - `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field, workdir=workdir)` -> verify `chan_diff_std_over_mad < 1.5`, `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001`, `spw_rms_ratio < 1.5` (if elevated, STOP and run `/postcal` target rflag first -- never image unflagged RFI)
   - `ms_radiometer_estimate(ms_path, field, spw=<spw or ''>, stokes, weighting='briggs', robust=0.5)` -> `telescope_name`, `center_freq_hz`, `min_freq_hz`, `max_freq_hz`, `freq_span_hz`, `fractional_span`, `total_bw_hz`, `eff_bw_hz`, `n_ant_unflagged`, `on_source_s`, `thermal_rms_jy`
   - `ms_antenna_list(ms_path)` -> `dish_diameter_m`, `n_antennas`
   - `ms_baseline_lengths(ms_path)` -> `max_baseline_m`, `resolution_arcsec_range`
   - `ms_spectral_window_list(ms_path)` -> per-SPW edges and widths (when running step 8)

4. Derive tclean parameters per 11-imaging.md Steps 1-7 (evaluate the Step 3-5 formulas via `python -c` rather than mental arithmetic):
   - specmode (Step 1): `'mfs'` unless user asks for a cube (keep `'mfs'` for wideband `mtmfs` mosaics -- do NOT switch to slow cube-mode `'mvc'`)
   - deconvolver (Step 2), two passes. First pass: `'hogbom'`, OR `'mtmfs'` with `nterms=2`
     if `fractional_span > 0.2` (use `fractional_span = freq_span_hz / center_freq_hz`, NOT
     `total_bw_hz / center_freq_hz`, because non-contiguous surviving SPWs can span > 20%
     bandwidth even when summed SPW width is < 20%). Second pass: `'multiscale'` with `scales`
     per Step 2 (for `'mtmfs'`, keep `'mtmfs'` with `nterms=2` and add `scales`). If the
     arguments give `deconvolver:`, the second pass uses it (`'asp'` is the last resort:
     `ms_tclean` warns it is expensive). Report the scales with the beam (arcsec) and cell they
     came from, so they can be recomputed.
   - cell (Step 3): `1 / (max_baseline_lambda * 3)`, rounded to 1 sf (unless user gave `cell:`)
   - imsize (Step 4): primary-beam diameter (`3 * pb_fwhm_arcsec` using `min_freq_hz` when
     `fractional_span > 0.2`, or mosaic extent + `3 * pb_fwhm_arcsec`) / cell, rounded up to
     composite number (unless user gave `imsize:`). Never shrink `imsize` below
     `3 * pb_fwhm_arcsec` unless `free -b` proves available RAM cannot hold the image grids
     (11-imaging.md Step 4).
   - Fresnel check (Step 5) -> `wprojplanes`
   - gridder (Step 6): `'mosaic'` for a first-pass mosaic (A-configuration / large image: memory
     check first), `'wproject'` single-pointing + W, else `'standard'`
   - `pblimit`, `pbmask`, `ms_make_mask` `pb_level`, and `ms_image_stats` `pb_level` (Step 7):
     on mosaics use `pblimit=-0.01` (keeps outer PB and first sidelobe unblanked; single-pointing:
     `pblimit=-0.1`), pass explicit `pbmask=0.1` in Phase A (`usemask='pb'`), keep
     **`pb_level=(user pbmask or 0.1)` in `ms_make_mask`** (clean only sources inside the
     cleanable PB -- NEVER pass `pb_level=0.01` with `mtmfs`, which diverges near the first PB
     null), and keep **`pb_level=0.1` in `ms_image_stats`** (which also reports programmatic
     `.model` positivity stats and outer-PB peak sky coordinates `residual_outer_pb_peak_j2000`).
   - threshold (Step 7): do NOT clean an unmasked (`usemask='pb'`) dynamic-range-limited mosaic down to `3 * thermal_rms_jy` alone. Use `nsigma=5.0` on unmasked `mtmfs` mosaics (`3.5` on narrowband `hogbom` mosaics, `3.0` single-pointing) with `threshold = max(3 * thermal_rms_jy, 3..5 * measured_off_source_rms)`. NEVER raise `threshold` above `~3--5 * off_source_rms` to mask divergence. Use `usemask='user'` + `mask=<path>` when a tight external/PyBDSF mask is available; never use `auto-multithresh`.

5. **Phase A -- Initial shallow pass (`usemask='pb'`):** `ms_tclean(ms_path,
   imagename=<name>_hogbom, field, spw=<spw or ''>, stokes, specmode,
   deconvolver, nterms, gridder, wprojplanes, cell, imsize,
   weighting='briggs', robust=0.5, niter=50000, threshold,
   nsigma=(user nsigma or (5.0 if (mosaic and mtmfs) else (3.5 if mosaic else 3.0))),
   pblimit=(user pblimit or (-0.01 if mosaic else -0.1)),
   pbmask=(user pbmask or 0.1), usemask='pb',
   savemodel='modelcolumn', workdir, execute=False)` -> run.
   Verify `converged=True` (`stopcode in (2, 8)`), then step 6 on it (use its
   `residual_rms_jy` to check/raise the threshold).

   **Phase B -- Adaptive PyBDSF mask-growing passes (safety cap 4 rounds, stop
   early on convergence per 11-imaging.md Step 2):**
   - For `N = 1..4`: call `ms_make_mask(image_path=<prev>.image` (or `.image.tt0` for `mtmfs`),
     `mask_path=<name>_rN.mask, prior_mask=(<name>_r{N-1}.mask if N>1 else None),
     workdir=workdir, pb_level=(user pbmask or 0.1), png_path=<name>_rN_mask.png,
     execute=True)` (flat-noise `.image`/`.image.tt0`, never `.pbcor`; keep
     `pb_level=0.1` inside the cleanable PB -- never stretch `mtmfs` masks to
     `0.01`; if `mask_pixels == 0`, fall back to `usemask='pb'` with `pbmask=0.1`
     and `nsigma=3.0`).
     Run `ms_tclean(..., imagename=<name>_<deconvolver>_rN,
     deconvolver=<second-pass>, nterms=(2 if mtmfs else 1), scales=<scales>,
     usemask='user', mask=<name>_rN.mask,
     pblimit=(user pblimit or (-0.01 if mosaic else -0.1)), nsigma=2.5,
     savemodel='modelcolumn', execute=False)` -> run, verify `converged=True`,
     then step 6 on it.
   - Check `.model` positivity (`model_neg_to_pos_flux_ratio`,
     `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`,
     `model_outer_pb_flux_frac`) after every pass: Stokes I `.model` must stay
     mostly positive. If negative model flux/components surge, stop deepening
     and tighten mask/scales or keep the cleaner earlier round.
   - Continue to round `N+1` (up to 4) if `residual_out_mask_peak_snr >= 5.0`
     inside `PB >= 0.1`
     OR (`mask_growth_fraction >= 0.10` and `residual_out_mask_rms_jy` dropped
     by `>= 15%` from the previous round). If diffuse extended emission still
     sits outside the mask after round 2 (`residual_out_mask_peak_snr >= 5.0`),
     set `atrous_do=True` and/or `thresh_pix=4.0, thresh_isl=2.5` on the next
     `ms_make_mask` call.
   - Stop growing as soon as (`mask_growth_fraction < 0.05` and
     `residual_out_mask_peak_snr < 5.0`), OR `mask_fraction_in_pb > 0.50`,
     OR `N == 4`.

   **Phase C -- Deep clean inside the fixed mask (only if inside-mask residuals
   remain high):**
   - If `residual_in_mask_peak_snr >= 3.5` OR `residual_in_to_out_rms_ratio >= 1.5`,
     run one final pass `ms_tclean(..., imagename=<name>_<deconvolver>,
     deconvolver=<second-pass>, nterms=(2 if mtmfs else 1), scales=<scales>,
     usemask='user', mask=<final_mask>,
     pblimit=(user pblimit or (-0.01 if mosaic else -0.1)), nsigma=1.5,
     threshold=max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy),
     savemodel='modelcolumn', execute=False)` -> run, verify `converged=True`
     (`stopcode in (2, 8)`), then step 6 on it (verify `.model` positivity did
     not degrade compared to Phase B).
   **Outer-PB offending source handling (11-imaging.md Step 2):** Uncleaned
   outer-PB sources (`0 < PB < 0.1`) are normal and NOT an automatic failure.
   If `residual_outer_pb_peak_snr` is bright enough to throw sidelobes into the
   science region: (1) cross-match `(ra_deg, dec_deg)` against `ms_field_list`
   (if it is the phasecal, include that pointing in the mosaic), else (2) use
   `outlierfile` (set `gridder=standard` inside the outlier file on mosaic runs)
   or two-tier baby peeling on a split working MS (`split` +
   `clearcal(addmodel=False)` -> **Version 1 primary:** single-call
   `gridder='standard'` across all target fields at
   `phasecenter=<residual_outer_pb_peak_j2000>` + `mtmfs nterms=2` + tight mask
   + `savemodel='modelcolumn'` -> verify `.model` positivity -> `uvsub` ->
   `delmod` -> mosaic dirty check before/after; **Version 2 fallback** only if
   pointing-to-pointing PB gain leaves strong residual: per-pointing
   `gridder='standard'` populating/zeroing all fields in `MODEL_DATA` -> single
   `uvsub` -> `delmod` -> dirty check -> re-image).
   **Hard convergence rule:** NEVER deliver an image with `converged=False`
   (`stopcode=1`, `5`, or `6`) and NEVER raise `threshold` above
   `~3--5 * off_source_rms` to hide divergence.
   MODEL_DATA now holds the final masked model (all calls record automatically in
   `stage_log.jsonl`).

6. `ms_image_stats(imagename.image.pbcor, psf_path=imagename.psf,
   pb_level=(user pbmask or 0.1), png_path=imagename.png)` (for `mtmfs` use
   the `.pbcor` file on disk -- `imagename.image.tt0.pbcor` or
   `imagename.image.pbcor.tt0` -- and `psf_path=imagename.psf.tt0`; keep
   `pb_level=0.1`) -- programmatic quality metrics (including
   `residual_out_mask_rms_jy`, `residual_out_mask_peak_snr`,
   `residual_in_mask_peak_snr`, `residual_in_to_out_rms_ratio`,
   `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`,
   `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac`,
   `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`,
   `residual_outer_pb_peak_j2000`, `residual_rms_jy`, `flat_noise_min_jy`,
   `negative_to_peak_ratio`, `dynamic_range`); do not assume vision -- rely on
   the numeric metrics above (open `png_path` with Read only if vision is
   available).

7. Apply 11-imaging.md Step 9 gates to the final masked image; report the
   first-pass and mask-growth numbers beside them:
   - `tclean` convergence: `converged == True` (`stopcode in (2, 8)` in `stage_log.jsonl`) -- HARD GATE
   - `.model` positivity (Stokes I): `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac` (mostly positive)
   - `residual_out_mask_rms_jy` (or `residual_rms_jy` if unmasked) vs. `thermal_rms_jy` from `ms_radiometer_estimate` (2x tolerance)
   - deconvolution convergence inside `PB >= 0.1`: `residual_out_mask_peak_snr` (< 5.0), `residual_in_mask_peak_snr` (< 3.5), `residual_in_to_out_rms_ratio` (< 1.5), `mask_growth_fraction`
   - outer-PB diagnostic (`0 < PB < 0.1`): report `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, `residual_outer_pb_peak_j2000` (and whether phasecal-included, peeled, or left uncleaned)
   - `residual_dynamic_range` thresholds per field type
   - `flat_noise_min_jy` and `negative_to_peak_ratio` (Stokes I clean-bowl check on flat-noise `.image` inside PB >= `pb_level`)
   - `beam_major_arcsec` vs. `lambda / max_baseline_m * (180*3600/pi)` (20% tolerance)
   - `peak_jy` sanity check

8. **IQUV cube** per 11-imaging.md Polarization frequency cubes, one pass:
   `ms_tclean(ms_path, imagename=<name>_iquv, field, spw=<spw or ''>, stokes='IQUV',
   specmode='cube', deconvolver='hogbom', nchan, start, width, outframe='LSRK',
   gridder, wprojplanes, cell, imsize, weighting='briggs', robust=0.5,
   niter=50000, threshold, nsigma=(user nsigma or 3.0),
   pblimit=(user pblimit or (-0.01 if mosaic else -0.1)),
   pbmask=(user pbmask or 0.1), usemask='pb',
   savemodel='none', workdir, execute=False)` -> run.
   `savemodel='none'` keeps the Stokes I model in MODEL_DATA for selfcal.
   Gridder and wprojplanes from step 4. `nchan`, `start`, `width` from
   `ms_spectral_window_list(ms_path)` per Channelization (one plane per SpW by
   default, or `cube_width:` if given); cell and imsize at the highest frequency in
   the band; threshold per Step 7 scaled to the plane width
   (`thermal_rms_jy * sqrt(eff_bw_hz / width_hz)`).
   Then `ms_image_stats(<name>_iquv.image.pbcor, psf_path=<name>_iquv.psf,
   pb_level=(user pbmask or 0.1), png_path=<name>_iquv.png)` and report its `planes`
   against Quality gates (per-plane) in place of step 7.

**Output:** the derived tclean parameters (including `thermal_rms_jy` from
`ms_radiometer_estimate`), image and mask paths (plus per-round `mask_pixels`
and `mask_growth_fraction`), `png_path` visual findings, and all measured
image-quality metrics (`residual_out_mask_rms_jy`, `residual_out_mask_peak_snr`,
`residual_in_mask_rms_jy`, `residual_in_mask_peak_snr`,
`residual_in_to_out_rms_ratio`, `residual_rms_jy`, `rms_jy`, `peak_jy`,
`flat_noise_min_jy`, `negative_to_peak_ratio`, `residual_dynamic_range`,
`dynamic_range`, `detection`, restoring beam) compared against Step 9
thresholds. Report numbers only -- do not recommend skipping re-imaging,
calibration review, or downstream stages.
