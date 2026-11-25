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

3. Gather placeholders from tool outputs (no hand math) and confirm clean continuum target spectrum:
   - `ms_field_list(ms_path)` -> target field names and, for multi-pointing mosaics, `mosaic_groups[].bbox_center_j2000` (mandatory `phasecenter`), `extent_ra_arcmin`, `extent_dec_arcmin`, `max_extent_arcmin`, `central_field_id`, `central_field_name`, `central_field_offset_arcmin`
   - `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field, spw=<spw or ''>, workdir=workdir)` -> on **continuum SPWs (`specmode='mfs'`)** (explicitly exempt spectral-line / maser SPWs and rest-frequency line windows, where genuine astronomical line derivatives trigger `chan_diff_*`), verify the SEFD-invariant within-SPW Gaussianity gate: `chan_diff_std_over_mad < 1.5`, `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001` (treat bandwidth-normalized `spw_noise_density_ratio` / `spw_rms_ratio` strictly as a secondary smoothness diagnostic for discontinuous single-SPW jumps vs smooth `T_sys(nu)` / atmospheric / sky-temperature gradients). If primary metrics are elevated on continuum SPWs, STOP and run bounded `/postcal` continuum target rflag + SPW triage first -- never image unflagged RFI
   - `ms_radiometer_estimate(ms_path, field, spw=<spw or ''>, stokes, weighting='briggs', robust=0.5)` -> `telescope_name`, `center_freq_hz`, `min_freq_hz`, `max_freq_hz`, `freq_span_hz`, `fractional_span`, `total_bw_hz`, `eff_bw_hz`, `n_ant_unflagged`, `on_source_s`, `thermal_rms_jy`
   - `ms_antenna_list(ms_path)` -> smallest active dish diameter `D_min` (`min(diameter_m)` across unflagged antennas on heterogeneous arrays; `dish_diameter_m` on homogeneous arrays), `n_antennas`
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
   - `phasecenter` / `psfphasecenter` (Step 4, `phasecenter` MANDATORY on multi-pointing mosaics): pass
     `phasecenter = mosaic_groups[].bbox_center_j2000` on EVERY mosaic `ms_tclean` call
     (never leave `phasecenter=''`, which centers on the first edge pointing and causes toroidal
     wrap-around!). CASA `tclean` accepts an integer field ID (`central_field_id`) or a `J2000`
     direction string (using `d/m/s` or `.` for Declination, never `:` or `FK5`; `ms_tclean` also
     accepts `central_field_name` and converts it to the integer field ID for CASA). If
     `central_field_offset_arcmin > 0.5 * pb_fwhm` (hollow mosaic), also pass
     `psfphasecenter=central_field_id` (or `central_field_name`, converted to `int` by `ms_tclean`).
   - cell (Step 3): `1 / (max_baseline_lambda * 4)` using `nu_cube_max` (the cube's imaged upper
     frequency bound) for `specmode='cube'`, `max_freq_hz` for wideband continuum (`fractional_span > 0.2`),
     or `center_freq_hz` for narrowband continuum, rounded down to target `pixels_per_beam_minor >= 3.0`
     (hard floor `2.5`, unless user gave `cell:`).
   - imsize (Step 4): use tapered-aperture `pb_fwhm_arcsec = (1.15 * lambda_max / D_min) * (180*3600/pi)`
     with smallest active dish diameter `D_min` (evaluating `lambda_max` at `nu_cube_min` for
     `specmode='cube'` sub-bands, `min_freq_hz` for wideband continuum `fractional_span > 0.2`, or
     `center_freq_hz` for narrowband continuum). Pad **out past the first positive sidelobe on EACH side**
     (`2.0 * pb_fwhm_arcsec` per side -> `ceil((extent + 4.0 * pb_fwhm_arcsec) / cell)` for mosaics,
     `ceil(4.0 * pb_fwhm_arcsec / cell)` for single pointings), rounded up to the smallest even composite
     `2^a * 3^b * 5^c` generated programmatically and bounded solely by available RAM (`free -b`; unless
     user gave `imsize:`). Rectangular `[nx, ny]` is valid and preferred when `extent_ra` and
     `extent_dec` differ by `> 20%`. Never shrink `imsize` below `extent + 4.0 * pb_fwhm_arcsec` (no
     `2 * FWHM` or `3 * FWHM` fallback!). If `edge_pb_max >= 0.02` persists on retry, grow `imsize`
     beyond the formula (e.g. `+1.0 * pb_fwhm_arcsec` per side) rather than re-evaluating the identical
     formula.
   - Fresnel check (Step 5) -> `wprojplanes`
   - gridder (Step 6): for mosaics on any telescope with a CASA primary-beam model, use `'mosaic'`
     when the dimensionless wide-field W-phase `(B_max / lambda) * theta_fov^2` is modest (`< 1` or
     first-pass imaging; note CASA `gridder='mosaic'` ignores `wprojplanes`); when `(B_max / lambda) *
     theta_fov^2 >= 1`, run an explicit memory (`free -b`) and A-projection convolution-function
     feasibility check first before switching to `'awp2'` + `wprojplanes`. Without a CASA PB model,
     or for single pointings, use `'wproject'` if W-terms are required, else `'standard'`.
   - `pblimit`, `pbmask`, `ms_make_mask` `pb_level`, and `ms_image_stats` `pb_level` (Step 7):
     on mosaics use `pblimit=-0.01` (keeps outer PB and first sidelobe unblanked; single-pointing:
     `pblimit=-0.1`), pass explicit `pbmask=0.1` in Phase A (`usemask='pb'`), keep
     **`pb_level=(user pbmask or 0.1)` in `ms_make_mask`** (clean only sources inside the
     cleanable PB -- NEVER pass `pb_level=0.01` with `mtmfs`, which diverges near the first PB
     null), and keep **`pb_level=0.1` in `ms_image_stats`** (which also reports `edge_pb_max`,
     `pixels_per_beam_minor`, programmatic `.model` positivity stats, and outer-PB peak sky
     coordinates `residual_outer_pb_peak_j2000`).
   - threshold (Step 7): do NOT clean an unmasked (`usemask='pb'`) dynamic-range-limited mosaic down to `3 * thermal_rms_jy` alone. Use `nsigma=5.0` on unmasked `mtmfs` mosaics (`3.5` on narrowband `hogbom` mosaics, `3.0` single-pointing) with `threshold = max(3 * thermal_rms_jy, 3..5 * measured_off_source_rms)`. NEVER raise `threshold` above `~3--5 * off_source_rms` to mask divergence. Use `usemask='user'` + `mask=<path>` when a tight external/PyBDSF mask is available; never use `auto-multithresh`.

5. **Phase A -- Initial shallow pass (`usemask='pb'`, `savemodel='none'`, quick-look only):** `ms_tclean(ms_path,
   imagename=<name>_hogbom, field, spw=<spw or ''>,
   phasecenter=(bbox_center_j2000 if mosaic else ''), stokes, specmode,
   deconvolver, nterms, gridder, wprojplanes, cell, imsize,
   weighting='briggs', robust=0.5, niter=50000, threshold,
   nsigma=(user nsigma or (5.0 if (mosaic and mtmfs) else (3.5 if mosaic else 3.0))),
   pblimit=(user pblimit or (-0.01 if mosaic else -0.1)),
   pbmask=(user pbmask or 0.1), usemask='pb',
   savemodel='none', workdir, execute=False)` -> run.
   Verify `converged=True` (`stopcode in (2, 8)`), then step 6 on it (use its
   `residual_rms_jy` and `residual_in_model_rms_ratio` to decide Phase B:
   **Phase B masked deep clean is MANDATORY whenever `residual_in_model_rms_ratio > 1.5`
   OR `residual_rms_jy > 1.3 * thermal_rms_jy`** -- never stop at a quick-look
   `usemask='pb'` pass).

   **Phase B -- Adaptive PyBDSF mask-growing passes (`savemodel='none'` on
   intermediate passes, safety cap 4 rounds, stop early on convergence per
   11-imaging.md Step 2):**
   - For `N = 1..4`: call `ms_make_mask(image_path=<prev>.image` (or `.image.tt0` for `mtmfs`),
     `mask_path=<name>_rN.mask, prior_mask=(<name>_r{N-1}.mask if N>1 else None),
     workdir=workdir, pb_level=(user pbmask or 0.1), png_path=<name>_rN_mask.png,
     execute=True)` (flat-noise `.image`/`.image.tt0`, never `.pbcor`; keep
     `pb_level=0.1` inside the cleanable PB -- never stretch `mtmfs` masks to
     `0.01`; if `mask_pixels == 0`, fall back to `usemask='pb'` with `pbmask=0.1`
     and `nsigma=3.0`).
     Run `ms_tclean(..., imagename=<name>_<deconvolver>_rN,
     spw=<spw or ''>, phasecenter=(bbox_center_j2000 if mosaic else ''),
     deconvolver=<second-pass>, nterms=(2 if mtmfs else 1), scales=<scales>,
     usemask='user', mask=<name>_rN.mask,
     pblimit=(user pblimit or (-0.01 if mosaic else -0.1)), nsigma=2.5,
     savemodel='none', execute=False)` -> run, verify `converged=True`,
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
     spw=<spw or ''>, phasecenter=(bbox_center_j2000 if mosaic else ''),
     deconvolver=<second-pass>, nterms=(2 if mtmfs else 1), scales=<scales>,
     usemask='user', mask=<final_mask>,
     pblimit=(user pblimit or (-0.01 if mosaic else -0.1)), nsigma=1.5,
     threshold=max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy),
     savemodel=('modelcolumn' if selfcal_or_uvsub_needed else 'none'),
     execute=False)` -> run, verify `converged=True` (`stopcode in (2, 8)`),
     then step 6 on it (verify `.model` positivity did not degrade compared to
     Phase B).
   - **`savemodel` rule:** Use `savemodel='none'` on Phase A and intermediate
     Phase B passes; set `savemodel='modelcolumn'` ONLY on the final converged
     Stokes I pass when `selfcal` (`dynamic_range >= 30`) or `uvsub` will
     consume `MODEL_DATA` (avoids expensive `MODEL_DATA` write/I/O overhead on large MSs).
   **Outer-PB offending source handling (11-imaging.md Step 2):** Uncleaned
   outer-PB sources (`0 < PB < 0.1`) are normal and NOT an automatic failure,
   EXCEPT when **`residual_outer_pb_peak_snr >= 20` AND science-PB RMS
   (`residual_out_mask_rms_jy`, else `residual_rms_jy`) `> 1.3 * thermal_rms_jy`**:
   (1) cross-match `(ra_deg, dec_deg)` against `ms_field_list` (if it is the
   phasecal, include that pointing in the mosaic), else (2) run the Version-1
   baby-peel probe on a split working MS (`split` + `clearcal(addmodel=False)`
   -> single-call `gridder='standard'` across all target fields at
   `phasecenter=<residual_outer_pb_peak_j2000>` + `mtmfs nterms=2` + tight mask
   + `savemodel='modelcolumn'` -> verify `.model` positivity -> `uvsub` ->
   `delmod` -> mosaic dirty check before/after): keep the peeled MS and re-image
   if science-PB RMS improves (escalate to Version-2 per-pointing peel only if
   needed), otherwise keep the unpeeled image and report the measured probe delta.
   **Hard convergence, anti-panic & quarantine rules:** NEVER deliver an image
   with `converged=False` (`stopcode=1`, `5`, or `6`), NEVER coarsen `cell`
   below Nyquist (`pixels_per_beam_minor < 2.5`) or shrink `imsize` below
   `extent + 4.0 * pb_fwhm(min_freq)` on `stopcode=5/6`, NEVER raise `threshold`
   above `~3--5 * off_source_rms` to hide divergence, and NEVER retry unmasked
   `usemask='pb'` more than once after `stopcode=5/6` (must check
   `edge_pb_max`/`phasecenter`/`imsize` -> clean SPW spectrum -> switch to
   `ms_make_mask` + `usemask='user'`). Cap *failed-convergence recovery retries*
   at **`<= 2`** per `image-stage` invocation (separate from normal Phase A/B/C
   progression). Note `tclean.py` automatically quarantines diverged
   `stopcode in (5, 6)` products into `<workdir>/rejected/`; for any other
   rejected pass, move `<rejected>.*` into `<workdir>/rejected/` before
   delivering and verify your handoff lists ONLY the converged final prefix.

6. `ms_image_stats(imagename.image.pbcor, psf_path=imagename.psf,
   pb_level=(user pbmask or 0.1), png_path=imagename.png)` (for `mtmfs` use
   the `.pbcor` file on disk -- `imagename.image.tt0.pbcor` or
   `imagename.image.pbcor.tt0` -- and `psf_path=imagename.psf.tt0`; keep
   `pb_level=0.1`) -- programmatic quality metrics (including `edge_pb_max`,
   `pixels_per_beam_minor`, `residual_out_mask_rms_jy`,
   `residual_out_mask_peak_snr`, `residual_in_mask_peak_snr`,
   `residual_in_to_out_rms_ratio`, `residual_in_model_rms_ratio`,
   `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`,
   `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac`,
   `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`,
   `residual_outer_pb_peak_j2000`, `residual_rms_jy`, `flat_noise_min_jy`,
   `negative_to_peak_ratio`, `dynamic_range`); do not assume vision -- rely on
   the numeric metrics above (open `png_path` with Read only if vision is
   available).

7. Apply 11-imaging.md Step 9 gates to the final converged image and report
   ALL mandatory handoff fields for the exact delivered prefix ONLY (never a
   rejected/quarantined basename):
   - exact delivered image prefix on disk (e.g. `<workdir>/<name>_mtmfs_r2.image.tt0.pbcor`)
   - `tclean` convergence: `converged == True` (`stopcode in (2, 8)` in `stage_log.jsonl`) -- HARD GATE
   - `edge_pb_max < 0.02` paired with `fov >= extent + 4.0 * pb_fwhm(nu_low, D_min)` (tapered `1.15 * lambda / D_min`) and `phasecenter = bbox_center_j2000` (a 1st-null border reads `0.0` while still wrapping the 1st positive sidelobe! If `edge_pb_max >= 0.02` persists on retry, grow `imsize` beyond the formula by e.g. `+1.0 * pb_fwhm` per side)
   - `pixels_per_beam_minor >= 2.5` (prefer `>= 3.0`)
   - `.model` positivity (Stokes I): `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac` (mostly positive)
   - `residual_out_mask_rms_jy` (or `residual_rms_jy` if unmasked) and ratio to `thermal_rms_jy` from `ms_radiometer_estimate` (2x tolerance)
   - deconvolution convergence inside `PB >= 0.1`: `residual_out_mask_peak_snr` (< 5.0), `residual_in_mask_peak_snr` (< 3.5), `residual_in_to_out_rms_ratio` (< 1.5), `residual_in_model_rms_ratio` (< 1.5), `mask_growth_fraction`
   - outer-PB diagnostic (`0 < PB < 0.1`): report `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, `residual_outer_pb_peak_j2000` (and Version-1 peel probe before/after RMS delta if triggered)
   - `residual_dynamic_range` thresholds per field type
   - `flat_noise_min_jy` and `negative_to_peak_ratio` (Stokes I clean-bowl check on flat-noise `.image` inside PB >= `pb_level`)
   - `beam_major_arcsec` vs. `lambda / max_baseline_m * (180*3600/pi)` (20% tolerance)
   - `peak_jy` sanity check

8. **IQUV cube** per 11-imaging.md Polarization frequency cubes, one pass:
   `ms_tclean(ms_path, imagename=<name>_iquv, field, spw=<spw or ''>,
   phasecenter=(bbox_center_j2000 if mosaic else ''), stokes='IQUV',
   specmode='cube', deconvolver='hogbom', nchan, start, width, outframe='LSRK',
   gridder, wprojplanes, cell, imsize, weighting='briggs', robust=0.5,
   niter=50000, threshold, nsigma=(user nsigma or 3.0),
   pblimit=(user pblimit or (-0.01 if mosaic else -0.1)),
   pbmask=(user pbmask or 0.1), usemask='pb',
   savemodel='none', workdir, execute=False)` -> run.
   `savemodel='none'` keeps the Stokes I model in MODEL_DATA for selfcal.
   Gridder and wprojplanes from step 4. `nchan`, `start`, `width` from
   `ms_spectral_window_list(ms_path)` per Channelization (one plane per SpW by
   default, or `cube_width:` if given; when `spw` holds non-contiguous surviving
   SPWs, use gap-aware / per-SPW channelization or explicitly note empty gap
   planes); derive `cell` at the cube's imaged upper frequency bound
   `nu_cube_max` (divisor `4`, using the sub-band bound when imaging a narrow
   sub-band of a wideband SPW) and `imsize` from tapered `pb_fwhm = 1.15 *
   lambda / D_min` at the cube's imaged lower frequency bound `nu_cube_min`
   (`extent + 4.0 * pb_fwhm`, rounded up to an even `2^a * 3^b * 5^c` bounded
   only by available RAM; grow `imsize` by `+1.0 * pb_fwhm` per side if
   `edge_pb_max >= 0.02` persists on retry); threshold per Step 7 scaled to the
   plane width (`thermal_rms_jy * sqrt(eff_bw_hz / width_hz)`).
   Then `ms_image_stats(<name>_iquv.image.pbcor, psf_path=<name>_iquv.psf,
   pb_level=(user pbmask or 0.1), png_path=<name>_iquv.png)` and report its
   `edge_pb_max`, `pixels_per_beam_minor`, and `planes` against Quality gates
   (per-plane) in place of step 7.

**Output:** the derived tclean parameters (including `phasecenter`, `spw`, and
`thermal_rms_jy` from `ms_radiometer_estimate`), image and mask paths (plus
per-round `mask_pixels` and `mask_growth_fraction`), `png_path` visual findings,
and all measured image-quality metrics (`edge_pb_max`, `pixels_per_beam_minor`,
`residual_out_mask_rms_jy`, `residual_out_mask_peak_snr`,
`residual_in_mask_rms_jy`, `residual_in_mask_peak_snr`,
`residual_in_to_out_rms_ratio`, `residual_rms_jy`, `rms_jy`, `peak_jy`,
`flat_noise_min_jy`, `negative_to_peak_ratio`, `residual_dynamic_range`,
`dynamic_range`, `detection`, restoring beam) compared against Step 9
thresholds. Report numbers only -- do not recommend skipping re-imaging,
calibration review, or downstream stages.
