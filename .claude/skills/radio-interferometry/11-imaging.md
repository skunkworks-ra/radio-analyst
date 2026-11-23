# 11 — First-Pass Imaging

## Purpose

Guide the first-pass continuum or spectral-cube imaging after
`CORRECTED_DATA` has been written by applycal. This is Phase 3.

Self-calibration is Phase 4 and is out of scope here.

---

## Placeholder reference

All placeholders are populated from Phase 1–2 tool outputs before calling `ms_tclean`.

| Placeholder | Source tool | What to extract |
|---|---|---|
| `{VIS}` | provided | full MS path (not calibrators.ms) |
| `{TARGET_FIELD}` | Step 0 | field **names**, comma-separated, e.g. `'3C391_C1,3C391_C2'` (never numeric IDs; 07 "Field selection") |
| `{IS_MOSAIC}` | Step 0 | True if imaging multiple pointings together |
| `{STOKES}` | Step 0 | `'IQUV'` if polcal ran, else `'I'` |
| `{POINTING_CENTERS}` | `ms_field_list` | RA/Dec of each target pointing (mosaic only) |
| `{MAX_BASELINE_M}` | `ms_baseline_lengths` | `max_baseline_m` |
| `{CENTER_FREQ_HZ}` | `ms_radiometer_estimate` | `center_freq_hz` |
| `{BANDWIDTH_HZ}` | `ms_radiometer_estimate` | `total_bw_hz` (`eff_bw_hz` is unflagged effective bandwidth; for thermal RMS only) |
| `{FRACTIONAL_SPAN}` | `ms_radiometer_estimate` | `fractional_span` (`freq_span_hz / center_freq_hz` across `min_freq_hz..max_freq_hz`; use for wideband `mtmfs` trigger) |
| `{DISH_DIAMETER_M}` | `ms_antenna_list` | `dish_diameter_m` (all antennas same for connected arrays) |
| `{TELESCOPE}` | `ms_radiometer_estimate` | `telescope_name` (also in `ms_observation_info`) |
| `{N_ANT}` | `ms_radiometer_estimate` | `n_ant_unflagged` |
| `{T_ON_SOURCE_S}` | `ms_radiometer_estimate` | `on_source_s` (median per pointing for a mosaic; Step 7) |
| `{THERMAL_RMS_JY}` | `ms_radiometer_estimate` | `thermal_rms_jy` (Step 7) |
| `{WORKDIR}` | provided | directory for image output |

---

## Step 0 — Field selection and Stokes

Decide what to image before deriving any parameter: field selection sets the
gridder, the image size, and whether a mosaic is needed. Take both from what the
run was asked to do. Ask only when someone is there to ask and the request says
nothing; otherwise use the defaults below and state them in the report.

1. **Fields.** The target fields named for the run. If none were named, all
   target fields from `ms_field_list`: one mosaic when they are pointings of one
   source, one image per source when they are separate sources.

2. **Stokes.** `'IQUV'` if polcal ran (skill 09), otherwise `'I'`. With the
   wideband `mtmfs` path (Step 2), IQUV goes through the cube path below
   ("Polarization frequency cubes"); the Stokes I `mtmfs` image stays the
   headline.

Record the values as `{TARGET_FIELD}`, `{IS_MOSAIC}`, and `{STOKES}`.

---

## Step 0.5 — CORRECTED coherence gate (mandatory, before any tclean)

Imaging cannot rescue incoherent CORRECTED data — it yields noise whose brightest
residual spike mimics a source. Gate on `ms_corrected_stats` first, using the same
in-band `chan_start/chan_end` as the gain/delay solves:

```
ms_corrected_stats(field='{PHASE_FIELD},{TARGET_FIELD}', chan_start=..., chan_end=...)
```

| Field | Check | Fail → action |
|---|---|---|
| phase cal | `phase_rms_deg` < 30° | calibration didn't take — do NOT image; re-solve (skill 07) |
| phase cal | `amp_robust_std` < ~20% of `amp_median` | bad gains — fix first |
| target | `amp_median` > 0, `amp_robust_std` not ≫ `amp_median` | decorrelated — imaging will be noise |

A failed gate means the Step 9 verdict will read `marginal`/FAIL: that is
calibration failure, not a faint source. Do not report the peak as a detection.

**Pre-imaging target spectrum cleanliness gate (MANDATORY before ANY target `tclean`, no-op on clean data).**
Calibration flags `calibrators.ms` heavily, whereas science target pointings
only received raw-DATA `preflag`. Before calling `ms_tclean` on target
`CORRECTED_DATA`, you **MUST** run `ms_spw_amp_severity(ms_path,
datacolumn='CORRECTED_DATA', field='{TARGET_FIELD}', workdir={WORKDIR})` and
check its sky-cancelling adjacent-channel complex difference metrics
(`|V(ch) - V(ch-1)| / sqrt(2)` on unflagged parallel hands; cancels smooth
extended continuum sky such as 3C391 while exposing narrow-band/burst RFI):

| Metric (`ms_spw_amp_severity`) | Clean target spectrum | Action if exceeded |
|---|---|---|
| `chan_diff_std_over_mad` | `< 1.5` | **DO NOT image yet** -- run `ms_apply_rflag` below |
| `max_spw_chan_diff_std_over_mad` | `< 1.8` | **DO NOT image yet** -- run `ms_apply_rflag` below |
| `chan_diff_gt10sigma_frac` | `< 0.001` (`< 0.1%`) | **DO NOT image yet** -- run `ms_apply_rflag` below |
| `spw_rms_ratio` (`max_spw_rms / median_spw_rms`) | `< 1.5` | **DO NOT image yet** -- run `ms_apply_rflag` below |

If ANY of these four checks fails (or if `ms_vis_amp_time_stats` shows a
well-populated integration `npts >= 0.25 * median_npts` with `ratio_to_median >= 2.0`),
you MUST flag target RFI BEFORE running `ms_tclean`:
1. Run `ms_apply_rflag(ms_path, workdir={WORKDIR}, field='{TARGET_FIELD}',
   datacolumn='corrected', timedevscale=5.0, freqdevscale=5.0, execute=False)`
   -> run via `run-step.sh` (**never** amplitude-clip targets, which have no `MODEL_DATA`).
2. **Re-run `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA',
   field='{TARGET_FIELD}', workdir={WORKDIR})`** and report the before/after
   spectrum numbers to prove the target spectrum is now clean. If any metric
   remains above threshold after default `5.0/5.0`, run one stricter pass
   (`timedevscale=4.0, freqdevscale=4.0`) or flag the bad channels/half-SpWs per
   `13-postcal-rfi-flagging.md` Step 3 and re-verify before imaging.
3. On clean data where ALL four checks already pass (e.g. clean C-band `chan_diff_std_over_mad ~ 1.02`),
   skip flagging and proceed straight to Step 1.

---

## Step 1 — Choose imaging mode

Determine `specmode` before deriving any other parameter.

| Condition | `specmode` | Notes |
|---|---|---|
| Single SPW or multiple SPWs aggregated, continuum science (including wideband `mtmfs` mosaics) | `'mfs'` | Standard continuum MFS (fast; do NOT use cube-mode `'mvc'` for routine continuum imaging) |
| Spectral line science or per-channel / IQUV polarization cube requested | `'cube'` | Per-plane cube |

Default to `'mfs'` unless the user explicitly asks for a cube.

---

## Step 2 — Choose deconvolver

| Condition | `deconvolver` | Notes |
|---|---|---|
| `specmode='cube'` | `'hogbom'` | Always |
| `{FRACTIONAL_SPAN} > 0.2` (`freq_span_hz / center_freq_hz > 0.2`) | `'mtmfs'`, `nterms=2` | Wideband (uses spanned frequency range across surviving SPWs, not summed `total_bw_hz`); add `scales` for extended emission |
| Otherwise | `'hogbom'` | Default for first-pass |

**Extended emission needs a scale-sensitive deconvolver.** Hogbom models the sky
as point components; on emission much larger than the beam (a supernova remnant
such as 3C391, a radio halo, a nearby galaxy) it leaves the extended flux in the
residual and the RMS reads high. That is a modelling failure, not noise. When the
source is known or seen to be extended, use `deconvolver='multiscale'` with
scales round(k × B) for k = 0, 1, 3, 5, where B = the hogbom pass's restored
`beam_major_arcsec` / `{CELL}` (Step 3); 0 is a point component. Or use
`deconvolver='asp'`. Which one is a judgment (T3); state it in the report.

Order: a `hogbom` first pass, then `multiscale` with `scales` (`ms_tclean`
takes them, in pixels, 0 first). `asp` chooses its own scales but is expensive
(`ms_tclean` warns): use it last, only when multiscale still leaves extended
flux in the residual.

**Masking (physics-driven PyBDSF mask-growing + deep-clean loop).** `ms_tclean`
supports `usemask='pb'` (initial pass) and `usemask='user'` with a native CASA
`.mask` built by `ms_make_mask` (PyBDSF island detection on the flat-noise
`.image`, with `PB < pb_level` blanked). Do **not** use CASA's automatic masking
(`usemask='auto-multithresh'`): it is slow and generates poor masks, and
`ms_tclean` rejects it.

For continuum target imaging (compact or extended, single-pointing or mosaic),
separate masking from deep cleaning into three physics-driven phases instead of
stopping after an arbitrary fixed pass count:

1. **Phase A -- Initial shallow pass (`usemask='pb'`):** Run the first `hogbom`
   (or `mtmfs`, `nterms=2`, `specmode='mfs'` when `fractional_span > 0.2`) pass
   (`<name>_hogbom` or `<name>_mtmfs_init`) with `pblimit=-0.01` on mosaics
   (`-0.1` single-pointing), explicit `pbmask=0.1` (so unmasked PB cleaning
   stays inside `PB >= 0.1` while the outer mosaic PB / first sidelobe remains
   unblanked), and **`nsigma=5.0` on unmasked `mtmfs` mosaics** (`3.5` on
   narrowband `hogbom` mosaics, `3.0` on compact single pointings). Why `5.0`
   on unmasked `mtmfs` mosaics: cleaning 20% of the map unmasked down to `3.5`
   sigma drives `nterms=2` into noise and outer-PB sidelobes (`model.tt1`
   diverges with `stopcode=6`); `nsigma=5.0` stops cleanly on bright structure
   to seed the PyBDSF mask. Verify `converged=True` (`stopcode in (2, 8)`), then
   call `ms_image_stats(..., pb_level=0.1)` on it (for `mtmfs`, use the `.pbcor`
   image on disk: `.image.tt0.pbcor` or `.image.pbcor.tt0`, plus `.psf.tt0`).
2. **Phase B -- Adaptive mask-growing passes (`usemask='user'`, safety cap 4
   rounds, early stop on convergence):**
   - Build or update the mask on the flat-noise `.image` (or `.image.tt0` for
     `mtmfs`; never `.pbcor`) via `ms_make_mask(image_path=<prev>.image[.tt0],
     mask_path=<name>_rN.mask, prior_mask=<prev_mask if N>1 else None>,
     workdir={WORKDIR}, pb_level=0.1,
     png_path=<name>_rN_mask.png, execute=True)`.
     **Keep the `pbmask` (`pb_level=0.1`):** clean only sources found inside
     the cleanable primary beam (`PB >= 0.1`). NEVER stretch `mtmfs`
     (`nterms=2`) clean masks down to `PB = 0.01`: near the first PB null
     (`PB ~ 0.01--0.04`), the frequency-dependent PB varies steeply across the
     band and makes the 2-term Taylor fit singular (`stopcode=6` divergence).
     Uncleaned outer-PB sources outside `PB >= 0.1` happen routinely and are
     NOT an automatic failure; if one throws sidelobes into the science region,
     handle it via the Outer-PB Offending Source Workflow below.
     If `mask_pixels == 0`, fall back to `usemask='pb'` with `pbmask=0.1` and
     `nsigma=3.0` (never pass an empty mask to `tclean`, which triggers `stopcode=7`).
   - Run `ms_tclean` (`<name>_<deconvolver>_rN`) with `deconvolver='multiscale'`
     (or `'mtmfs'`, `nterms=2`, `specmode='mfs'` with `scales` when
     `fractional_span > 0.2`), `usemask='user'`, `mask=<name>_rN.mask`,
     `pblimit=(-0.01 if mosaic else -0.1)`, and `nsigma=2.5` (or `2.0` once
     bright sidelobes drop). Why lower than `3.0`: CASA's `nsigma` multiplies
     the global residual MAD across the whole PB, so unmasked faint emission
     inflates the MAD and stalls `nsigma=3.0` prematurely; `usemask='user'`
     already blocks cleaning outside-mask noise.
   - Verify `converged=True` (`stopcode in (2, 8)`), call
     `ms_image_stats(..., pb_level=0.1)` after each pass, and inspect BOTH the
     residual metrics AND the programmatic **`.model` positivity** metrics
     (`model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`,
     `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac`):
     - **Check `.model` positivity (Stokes I):** A physical Stokes I clean
       model must be mostly positive. If `model_neg_to_pos_flux_ratio` jumps
       above `~0.25--0.30`, `model_neg_to_pos_peak_ratio` rises sharply, or
       `model_neg_pixel_fraction` surges (> 0.50 with growing negative flux)
       between rounds, cleaning is putting negative bowls/noise into `.model` --
       stop deepening, tighten the mask or drop overly large `scales`, or keep
       the cleaner earlier round.
     - **Grow the mask again** (up to round 4) when
       `residual_out_mask_peak_snr >= 5.0` inside `PB >= 0.1`
       **OR** (`mask_growth_fraction >= 0.10` and `residual_out_mask_rms_jy`
       dropped by `>= 15%` from the prior pass).
       If diffuse extended emission still sits outside the mask after 2 standard
       rounds (`residual_out_mask_peak_snr >= 5.0`), enable `atrous_do=True`
       and/or relax to `thresh_pix=4.0, thresh_isl=2.5` on the next
       `ms_make_mask` call to capture low-surface-brightness wings.
     - **Stop growing the mask** as soon as (`mask_growth_fraction < 0.05` and
       `residual_out_mask_peak_snr < 5.0`) -- compact point sources finish in
       1--2 masked passes -- **OR** `mask_fraction_in_pb > 0.50` (guard against
       masking noise), **OR** round 4 is reached.
3. **Phase C -- Deep clean inside the fixed mask (only when needed):**
   - Once mask growth stops, check the **inside-mask** residuals in
     `ms_image_stats`. If `residual_in_mask_peak_snr >= 3.5` **OR**
     `residual_in_to_out_rms_ratio >= 1.5` (the mask covers the source, `tclean`
     stopped too early inside it), run **one final pass** (`<name>_<deconvolver>`)
     with the same fixed mask, `specmode='mfs'`,
     `pblimit=(-0.01 if mosaic else -0.1)`, `nsigma=1.5`,
     `threshold = max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy)`, and
     `savemodel='modelcolumn'`. Verify `converged=True` AND that `.model`
     positivity did not degrade compared to Phase B; if Phase C only added
     negative model components without improving residuals, keep the cleaner
     Phase B round (with `savemodel='modelcolumn'`).
   - If Phase B already converged inside the mask
     (`residual_in_mask_peak_snr < 3.5` and `residual_in_to_out_rms_ratio < 1.5`),
     ensure the final converged pass wrote `savemodel='modelcolumn'` (or run it
     as `<name>_<deconvolver>` with `savemodel='modelcolumn'`). Once `tclean`
     converged (`stopcode in (2, 8)`), inside-mask and outside-mask (`PB >= 0.1`)
     residuals are noise-like, `.model` is predominantly positive, and flat-noise
     `negative_to_peak_ratio <= 0.05`, deconvolution inside the PB is converged;
     any remaining gap to `thermal_rms_jy` is an offending outer-PB source,
     calibration, residual RFI, dynamic-range/selfcal, or confusion -- not masking.

**Primary-beam blanking on mosaics (`pblimit`, `pbmask`, `ms_make_mask`, `ms_image_stats`).**
Positive `pblimit` (`0.1` or `0.2`) blanks all pixels below that gain level,
hiding sources in the outer PB and first sidelobe even when `imsize` covers
`3 * FWHM` (Step 4). Use **`pblimit=-0.01`** on mosaics (`-0.1` on single
pointings) so the outer PB stays visible for diagnostics, while keeping the
clean boundary inside the primary beam:
- In Phase A (`usemask='pb'`): pass explicit `pbmask=0.1` and `nsigma=5.0` on
  `mtmfs` mosaics (`3.5` narrowband) so unmasked cleaning stays inside `PB >= 0.1`
  and does not diverge into `model.tt1`.
- In Phases B/C (`ms_make_mask` on flat-noise `.image`/`.image.tt0`): keep
  **`pb_level=0.1`** so PyBDSF masks only cleanable sources inside `PB >= 0.1`
  (NEVER pass `pb_level=abs(pblimit)=0.01` with `mtmfs`).
- In `ms_image_stats`: keep **`pb_level=0.1`** for science-PB reporting AND
  inspect `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, and
  `residual_outer_pb_peak_j2000` (measured in `0 < PB < pb_level`) to detect
  offending outer-PB sources.

**Outer-PB Offending Source Workflow (phasecal inclusion, outlier fields, and baby peeling).**
Uncleaned sources outside `PB >= 0.1` are common and are NOT a failure by
themselves (some outer-PB sources cannot be deconvolved directly inside a
wideband mosaic). Check `residual_outer_pb_peak_*` in `ms_image_stats` and
follow this decision tree:
1. **Is it hurting the science region?** If `residual_out_mask_rms_jy` inside
   `PB >= 0.1` is near thermal and no sidelobes degrade the science target,
   leave the outer-PB source uncleaned and report its position/SNR in the
   summary.
2. **Is it the phase calibrator (or another observed pointing)?** Cross-match
   `(residual_outer_pb_peak_ra_deg, residual_outer_pb_peak_dec_deg)` against
   `ms_field_list`. If it matches the phasecal (or another calibrated pointing
   in the MS), include that pointing in the mosaic `field` selection so its
   primary beam covers the source cleanly.
3. **Outlier field (`outlierfile`) or two-tier baby peeling (probe mosaic before and after):**
   - **Outlier field (joint imaging without subtracting):** Write a CASA
     outlier-field text file centered on `residual_outer_pb_peak_j2000` and
     pass `outlierfile=<path>` to `ms_tclean`. On `gridder='mosaic'` runs,
     always set `gridder=standard` inside the outlier file (inheriting
     `gridder='mosaic'` on an off-axis cutout that excludes pointing centers
     aborts CASA `MosaicFTNew` with zero weights).
   - **Baby peeling (image only the offending source, subtract with `uvsub`, and
     confirm on the full mosaic dirty image before and after):**
     1. Split calibrated target visibilities to a working MS so the original MS
        stays untouched: `ms_casa_task(task='split', params={'vis': ms_path,
        'outputvis': '<workdir>/target_peeled.ms', 'field': <target>,
        'datacolumn': 'corrected'})`, then `ms_casa_task(task='clearcal',
        params={'vis': '<workdir>/target_peeled.ms', 'addmodel': False})` so
        `CORRECTED_DATA = DATA`.
     2. **Version 1 (Primary -- fast single-call peel across the full target
        selection):** Run ONE `ms_tclean(ms_path='<workdir>/target_peeled.ms',
        field=<target>, gridder='standard',
        phasecenter=<residual_outer_pb_peak_j2000>, specmode='mfs',
        deconvolver='mtmfs', nterms=2, imsize=[128, 128], cell=<CELL>,
        pblimit=-0.01, pbmask=0.0, usemask='user',
        mask=<tight mask around real component(s) only>, niter=500,
        threshold=<above dirty-cutout sidelobe floor>, savemodel='modelcolumn')`.
        Using `gridder='standard'` + `deconvolver='mtmfs'` (`nterms=2`) models
        the apparent (sky * PB) spectral structure directly without PB-division
        singularity, populates `MODEL_DATA` across all target fields in one pass
        (zero unselected-field risk), and is ~3x faster than an `outlierfile`
        mosaic pass.
     3. Verify `.model` positivity on the peel cutout (`model_neg_to_pos_flux_ratio`
        low, e.g. `< 0.30`; never subtract an overcleaned negative-dominated
        model), then run `ms_casa_task(task='uvsub', params={'vis':
        '<workdir>/target_peeled.ms'})` and `ms_casa_task(task='delmod',
        params={'vis': '<workdir>/target_peeled.ms', 'otf': True, 'scr': True})`.
     4. **Probe mosaic after peeling:** Run a dirty image (`niter=0`) on
        `target_peeled.ms` and compare the offending source peak before vs after.
        If it is removed or reduced enough that its sidelobes no longer limit
        the science region, proceed with main imaging on `target_peeled.ms`.
     5. **Version 2 (Fallback -- per-pointing peel when mosaic PB gain varies
        across pointings):** Only if the post-peel mosaic dirty image after
        Version 1 still leaves significant residual flux at the offender
        (because different mosaic pointings see different PB gains/spectra at
        the offender), peel each mosaic pointing individually with
        `gridder='standard'`, `phasecenter=<residual_outer_pb_peak_j2000>`,
        `mtmfs nterms=2`, `savemodel='modelcolumn'` into `MODEL_DATA`, then run
        ONE `uvsub` + `delmod` + dirty check. **Critical CASA `MODEL_DATA`
        safety rule for Version 2:** when `tclean(field=f, savemodel='modelcolumn')`
        creates `MODEL_DATA`, CASA initializes unselected fields to `1+0j`;
        either populate `MODEL_DATA` for every field in `target_peeled.ms`
        before the single `uvsub`, or zero `MODEL_DATA` on unpeeled fields
        before calling `uvsub`.

---

## Step 3 — Derive cell size

```
lambda_m         = c / {CENTER_FREQ_HZ}          # c = 2.998e8 m/s
max_bl_lambda    = {MAX_BASELINE_M} / lambda_m    # baseline in wavelengths
cell_rad         = 1.0 / (max_bl_lambda * 3)      # factor 3: avoid over-sampling
cell_arcsec      = cell_rad * (180 * 3600 / pi)
```

Round `cell_arcsec` to 1 significant figure (e.g. 2.47" → 2.5"). State the
value and record it as `{CELL}`.

---

## Step 4 — Derive image size

Primary beam FWHM (on wideband observations with `{FRACTIONAL_SPAN} > 0.2`, use
`min_freq_hz` for `lambda_max = c / min_freq_hz` so the PB tapers cleanly below
`0.01` inside the image edge with no PB-edge aliasing):
```
pb_fwhm_arcsec = (1.02 * lambda_m / {DISH_DIAMETER_M}) * (180 * 3600 / pi)
```

**Always image out to the first primary-beam sidelobe.** Stopping at the FWHM
leaves bright sources in the first sidelobe (radius ≈ 1.6 × FWHM, where the PB
gain is still a few percent) undeconvolved — their sidelobes alias back across
the field and limit the dynamic range. The first null sits at ≈ 1.2 × FWHM
radius and the first sidelobe peak at ≈ 1.6 × FWHM radius, so the image
**diameter** must be ≈ 3 × FWHM.

**Single pointing:**
```
imsize_pixels = ceil(pb_fwhm_arcsec * 3 / cell_arcsec)   # diameter = 3 × FWHM → covers first sidelobe (~1.6 FWHM radius)
```

**Mosaic:** compute the bounding box of all pointing centres in `{POINTING_CENTERS}`,
convert angular extent to pixels, then pad by `1.5 * pb_fwhm_arcsec` on each side
so every pointing's first sidelobe is imaged:
```
imsize_pixels = ceil((mosaic_extent_arcsec + 3 * pb_fwhm_arcsec) / cell_arcsec)
```

(If compute or memory is the binding constraint, dropping to a `2 × FWHM`
diameter — first null only — is the fallback, but record it explicitly as a
deviation: bright first-sidelobe sources will not be cleaned.)

Round `imsize_pixels` **up** to the nearest composite number of the form
2ᵃ × 3ᵇ × 5ᶜ. Common values: 240, 256, 320, 360, 384, 480, 512, 600, 640,
720, 800, 900, 1024. Do not use a prime number — tclean will run extremely slowly.

Record as `{IMSIZE}`.

---

## Step 5 — Check W-term significance

```
fresnel = {DISH_DIAMETER_M}**2 / ({MAX_BASELINE_M} * lambda_m)
```

| `fresnel` | Action |
|---|---|
| ≥ 0.9 | W-terms negligible |
| < 0.9 | W-projection required; set `wprojplanes` per table below |

`wprojplanes` scaling:

| `fresnel` | `wprojplanes` |
|---|---|
| 0.7–0.9 | 16 |
| 0.4–0.7 | 32 |
| 0.1–0.4 | 64 |
| < 0.1 | 128 |

---

## Step 6 — Choose gridder

| Condition | `gridder` | `wprojplanes` |
|---|---|---|
| Mosaic, first pass, not A-configuration, telescope in `{VLA, ALMA}` | `'mosaic'` | not set |
| Mosaic, A-configuration | **check memory first** (below), then decide | — |
| Mosaic, telescope NOT in `{VLA, ALMA}` | `'mosaic'` only if CASA has a primary-beam model for it; else see note below | — |
| Single pointing AND W-terms required | `'wproject'` | from Step 5 |
| Single pointing AND W-terms not required | `'standard'` | not set |

**First pass on a mosaic is `gridder='mosaic'`.** The A-projection gridders
(`awproject`, `awp2`) cost far more memory and time, and are a later choice
when the science needs wide-field polarisation or beam-squint correction.

**Large mosaics (A-configuration, `imsize >= 2048`, or `>= 10` pointings): check
that the image fits before calling tclean.** Large footprints with `mtmfs` +
`multiscale` or `IQUV` cubes require significant memory. CASA needs roughly

```
memory_bytes ≈ 5.5 × nterms × nscales × (imsize_x × imsize_y × 4 bytes)
```

(plus `nchan * 4` for `IQUV` cubes and mosaic gridding convolution functions),
where 4 bytes is one float pixel, `nterms` is 1 unless `mtmfs`, and `nscales`
is 1 for hogbom. Compare this with the machine's available memory (`free -b` via
Bash). If it does not fit, do not start tclean: report the estimate and the
memory, and image fewer pointings, a smaller region, or on a larger machine.
This is a T3 or user decision, not a default.

Match the telescope against the **canonical** name returned by `ms_inspect`
(`telescope_name` field) -- `VLA`, not the raw `MS::OBSERVATION::TELESCOPE_NAME`
string, which may be `EVLA` or `JVLA`. Name normalization happens in the
telescope profile (`src/ms_inspect/data/telescopes/*.yaml`, `aliases`).

**Telescope without a CASA primary-beam model:** use `'wproject'` if W-terms
are required, else `'standard'`, and warn the user that the pointings will not
be primary-beam corrected as a mosaic.

---

## Step 7 -- Estimate cleaning threshold

Compute the radiometer thermal noise directly with `ms_radiometer_estimate` (do
not hand-derive SEFD, unflagged antennas, effective bandwidth, or per-pointing
time in chat):

```
ms_radiometer_estimate(
    ms_path   = {VIS},
    field     = {TARGET_FIELD},
    spw       = '',
    stokes    = {STOKES},
    weighting = 'briggs',
    robust    = 0.5,
)
```

Read `thermal_rms_jy` (along with `sefd_jy`, `eta_c`, `n_pol`, `n_ant_unflagged`,
`on_source_s`, `eff_bw_hz`, and `weighting_factor` for reporting).

**Do NOT clean an unmasked (`usemask='pb'`) dynamic-range-limited mosaic down to
`3 * thermal_rms_jy`.** On extended or bright sources (for example a supernova
remnant mosaic like 3C391), the actual off-source residual RMS can be 5--10x
higher than the theoretical radiometer floor (`thermal_rms_jy`). Driving an
unmasked PB clean down to `3 * thermal_rms_jy` with `niter=50000` cleans into
noise and PSF sidelobes, producing severe negative clean bowls or timeouts.

Instead, choose the stopping criterion from **measured** off-source RMS:

1. **Theoretical reference (always compute):** `thermal_rms_jy` from
   `ms_radiometer_estimate` is the sensitivity benchmark for Step 9 quality
   assessment (`residual_rms_jy` vs `thermal_rms_jy`), **not** a blind unmasked
   clean floor on extended mosaics.
2. **Measured threshold for unmasked (`usemask='pb'`) cleaning:** Measure the
   actual off-source RMS from a fast dirty or shallow pass (`ms_image_stats`
   `residual_rms_jy` inside `PB >= pb_level` with `pb_level=0.1`), and set:
   ```
   threshold = max(3 * thermal_rms_jy, 3..5 * measured_off_source_rms)
   ```
   and pass `nsigma=3.0` (or `3.5--5.0` on unmasked mosaics) so CASA stops cleanly
   (`stopcode=8`) at `nsigma * MAD` of the residual instead of cleaning into
   noise.
3. **Deep cleaning with an external mask (`usemask='user'`, `mask=<path>`):**
   When cleaning inside a tight source mask (`ms_make_mask`), noise outside the
   source is excluded: use `nsigma=2.0..2.5` during mask-growing passes (Phase
   B) and `nsigma=1.5` with
   `threshold = max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy)` for the
   final deep clean inside the converged mask (Phase C).

If `thermal_rms_jy` is marked `UNAVAILABLE` in `field_flags` (for example an
unmodelled telescope or band), report that explicitly rather than substituting
a guessed SEFD. For an IQUV cube plane of width `W_plane_hz`, call
`ms_radiometer_estimate` with the plane's `spw` or scale
`thermal_rms_jy * sqrt(eff_bw_hz / W_plane_hz)`.

`ms_radiometer_estimate` evaluates VLA OSS "Sensitivity" equation 1:
```
sigma_natural = SEFD / (eta_c * sqrt(n_pol * n_ant_unflagged * (n_ant_unflagged - 1) * on_source_s * eff_bw_hz))
thermal_rms_jy = weighting_factor * sigma_natural
```

| Term | Value returned by `ms_radiometer_estimate` |
|---|---|
| `sefd_jy` | telescope profile's `sefd_jy` for the observed band (`src/ms_inspect/data/telescopes/<telescope>.yaml`) |
| `eta_c` | correlator efficiency (0.93 with 8-bit samplers; 0.78 to 0.83 with 3-bit when known) |
| `n_pol` | 2 for Stokes I, Q, U, V, or IQUV; 1 for a single hand (RR or LL) |
| `on_source_s` | unflagged on-source integration time in seconds; **for a mosaic, median per pointing** rather than summed across all pointings |
| `eff_bw_hz` | unflagged effective bandwidth across selected SPWs (`total_bw_hz * unflagged_fraction`) |
| `weighting_factor` | 1.0 natural; ~1.2 for `briggs` `robust=0.5` |

Two sky contributions are not in the thermal equation and must be considered
by scientific judgment when interpreting `residual_rms_jy`:
- **Confusion** from sources within the beam adds in quadrature: VLA OSS gives
  D-configuration robust-weighted values (P 5330, L 74, S 12, C 2 uJy/beam;
  negligible at X and above), roughly 10x lower in C-configuration.
- **Galactic synchrotron** at P-band raises the effective SEFD by 2x to 3x in
  the Galactic plane and >= 5x near the Galactic centre.

Express `threshold` in mJy, e.g. `'0.5mJy'`. This is a starting estimate --
tclean will stop at this level or at `niter`, whichever comes first.

Set `niter=50000` as the default upper bound. Adjust down for quick diagnostic
runs (`niter=1000`).

---

## Step 8 — Call ms_tclean

```
ms_tclean(
    ms_path      = {VIS},
    imagename    = {WORKDIR}/{imagename},
    field        = {TARGET_FIELD},
    stokes       = {STOKES},
    specmode     = {specmode},
    deconvolver  = {deconvolver},
    nterms       = 2,              # only when deconvolver='mtmfs'
    gridder      = {gridder},
    wprojplanes  = {wprojplanes},  # only when gridder='wproject'
    cell         = {CELL},
    imsize       = [{IMSIZE}, {IMSIZE}],
    weighting    = 'briggs',
    robust       = 0.5,
    niter        = 50000,
    threshold    = {threshold},
    nsigma       = 3.0,            # stops at nsigma*MAD residual; prevents unmasked noise bowls
    savemodel    = 'modelcolumn',
    pblimit      = -0.01,          # negative on mosaics keeps outer PB / first sidelobe unblanked (-0.1 single-pointing)
    pbmask       = 0.1,            # explicit clean boundary when usemask='pb' (never omit with pblimit=-0.01)
    usemask      = 'pb',           # or 'user' with mask=<path> (e.g. PyBDSF mask); never 'auto-multithresh'
    workdir      = {WORKDIR},
    execute      = False,
)
```

`savemodel='modelcolumn'`: writes MODEL_DATA into the MS, required for self-cal (Phase 4).

Generate the script (`execute=False`), then run it via `run-step.sh` (`--wait 240`,
SKILL.md "Running generated scripts"), re-running on `status=running` until
`status=done` (`rc=0`) -- tclean on a real mosaic can run for hours. **Hard
rule:** NEVER write a final reduction report, summarize completion, assume
`tclean` will finish in the background, or exit while `run-step.sh` reports
`status=running` (exiting tears down the container/session and kills `tclean`
mid-run, leaving zero `.image` products). Keep re-invoking
`run-step.sh <python> <script> --wait 240` until `status=done` (`rc=0`) and
verify `<imagename>.image.pbcor` (or `.image.tt0.pbcor` / `.image.pbcor.tt0`
for `mtmfs`) exists on disk before calling `ms_image_stats` or reporting.

**Hard convergence discipline (NEVER accept `converged=False` or hack around divergence):**
- Inspect `stopcode` and `converged` in the `tclean` output / `stage_log.jsonl`.
  **NEVER accept or deliver an image from a run with `converged=False`
  (`stopcode=1` iteration limit, `stopcode=5` or `6` divergence).**
- **On `stopcode=5` or `6` (divergence):** NEVER "fix" divergence by raising
  `threshold` above `~3--5 * off_source_rms` (that only stops cleaning early
  while leaving 5x+ uncleaned in-model residuals). Instead fix the physical
  cause: (1) on unmasked `usemask='pb'` wideband `mtmfs` mosaics, keep Phase A
  shallow (`nsigma=5.0`) and switch immediately to a tight PyBDSF
  `usemask='user'` mask, (2) confirm target `CORRECTED_DATA` passed the Step 0.5
  target spectrum gate (`chan_diff_std_over_mad < 1.5`, `spw_rms_ratio < 1.5`),
  and (3) confirm `imsize` covers `3 * FWHM` at `min_freq_hz` with no PB-edge
  aliasing.
- **On `stopcode=1` (iteration limit):** raise `niter` (or tighten the mask if
  cleaning noise) and re-run until `stopcode in (2, 8)`.

---

## Step 9 — Quality assessment

Call `ms_image_stats` on the pbcor image:

```
ms_image_stats(
    image_path  = {WORKDIR}/{imagename}.image.pbcor,    # for mtmfs: .image.tt0.pbcor or .image.pbcor.tt0 on disk
    psf_path    = {WORKDIR}/{imagename}.psf,            # or .psf.tt0 for mtmfs
    pb_level    = 0.1,                                  # science PB reporting boundary (decoupled from pblimit=-0.01)
    png_path    = {WORKDIR}/{imagename}.png,
)
```

**Which RMS and bowl metric.** Compare `residual_out_mask_rms_jy` (or
`residual_rms_jy` when unmasked / `mask_fraction_in_pb == 1.0`) with the
radiometer estimate, not `rms_jy`. `residual_out_mask_rms_jy` is the robust
`1.4826 * MAD` of `.residual` **outside `.mask`** and inside `.pb >= pb_level`,
so uncleaned flux inside the mask does not bias the off-source noise floor.
`rms_jy` is the whole `.pbcor` plane: towards the PB edge the noise is divided
by a small gain, so it reads high. Similarly, `negative_to_peak_ratio` is
measured on the sibling **flat-noise `.image`** (`flat_noise_min_jy` /
`flat_noise_peak_jy` inside `.pb >= pb_level`) so `1/PB` edge noise
amplification on `.pbcor` is never mistaken for a negative clean bowl. Always
also inspect `residual_full_peak_snr`, `residual_full_peak_pb`, and
`residual_outer_pb_peak_snr` (measured across ALL `PB > 0`) so bright uncleaned
outer-PB sources are never hidden below `pb_level=0.1`. Always write in the
report: "The .pbcor image noise rises toward the PB edge; the RMS quoted is from
the .residual inside PB >= {pb_level}."

**Look at the image (programmatic metrics first; PNG optional).** Do NOT assume
vision is available -- evaluate `.model` positivity (`model_neg_to_pos_flux_ratio`,
`model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`,
`model_outer_pb_flux_frac`), flat-noise `negative_to_peak_ratio`, and residual
peaks (inside `PB >= pb_level` and `residual_outer_pb_peak_*`) programmatically
from `ms_image_stats` on every round. If vision is available, also open `png_path`
with Read to inspect inside the PB contour and outer PB for bowls, stripes,
rings, and edge artefacts.

Quality gates (every delivered target image MUST report and verify all convergence gates):

| Metric | Expected | Action if not met |
|---|---|---|
| `tclean` convergence (`stage_log.jsonl`) | `converged == True` (`stopcode` is `2` or `8`) | **HARD FAIL** on `stopcode=1`, `5`, or `6`: NEVER deliver. Fix root cause (shallow Phase A `nsigma=5.0` + tight PyBDSF `usemask='user'` mask inside `PB >= 0.1`, clean target spectrum, full `imsize`, or higher `niter`) -- NEVER raise `threshold` above `~3--5x` rms to mask divergence |
| `.model` positivity (Stokes I: `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac`) | Predominantly positive (`model_neg_to_pos_flux_ratio < 0.25`, `model_neg_to_pos_peak_ratio < 0.25`, `model_outer_pb_flux_frac` small) | Surging negative model flux/components: stop deepening, tighten mask or drop overly large `scales`, or keep the cleaner earlier round (never subtract or deliver a negative-dominated Stokes I model) |
| `residual_out_mask_peak_snr` | `< 5.0` (masked pass, inside `PB >= 0.1`) | `>= 5.0`: unmasked emission remains inside `PB >= 0.1`; grow mask via `ms_make_mask(..., pb_level=0.1, prior_mask=...)` (enable `atrous_do=True` / `thresh_pix=4.0, thresh_isl=2.5` if diffuse) and re-image |
| `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, `residual_outer_pb_peak_j2000` (`0 < PB < 0.1`) | Diagnostic (uncleaned outer-PB sources are normal and NOT an automatic failure) | If bright enough to throw sidelobes into `PB >= 0.1`: (1) cross-match `(ra_deg, dec_deg)` against `ms_field_list` (if phasecal, include pointing), else (2) `outlierfile` or fast baby peeling (`gridder='standard'`, `phasecenter=<j2000>`, `mtmfs nterms=2`, `savemodel='modelcolumn'`, `uvsub`, confirm via dirty image) |
| `residual_in_mask_peak_snr`, `residual_in_to_out_rms_ratio` | `< 3.5` and `< 1.5` (near `1.0`, masked pass) | Above either: mask covers the source but `tclean` stopped early inside it (or threshold was set too high); run Phase C deep clean inside the fixed mask with `nsigma=1.5` and `threshold = max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy)` |
| `residual_out_mask_rms_jy` (else `residual_rms_jy`) | Within 2x of `thermal_rms_jy` | > 2x after deconvolution converges: separate outer-PB sidelobes, calibration, residual RFI, and self-cal/confusion causes below; do not ship unresolved or dismiss `thermal_rms_jy` as "optimistic" without testing a point-source calibrator |
| `residual_dynamic_range` | > 100 for calibrators; > 20 for typical targets | < 20: imaging artefacts dominant; check PSF sidelobes |
| `flat_noise_min_jy`, `negative_to_peak_ratio` | `negative_to_peak_ratio` <= 0.05 (Stokes I, flat-noise `.image` inside PB >= `pb_level`) | > 0.05 (severe if > 0.10): negative clean bowl from over-cleaning unmasked noise, too-low threshold, or missing short spacings; verify mask and `nsigma`, re-image with tighter masking/threshold before self-cal or shipping |
| `beam_major_arcsec` | Close to `lambda/max_baseline_m * (180*3600/pi)` | Large deviation: uv coverage gaps or flagging holes |
| `peak_jy` | Positive, above threshold | Negative peak > rms: clean diverged; fix divergence cause (never raise threshold arbitrarily) |

When `residual_out_mask_rms_jy` (or `residual_rms_jy` if unmasked) exceeds 2x
the radiometer estimate (including > 3x), do not assume a single cause, do not
dismiss `thermal_rms_jy` as "optimistic", and do not ship the image unresolved.
First verify deconvolution converged (`converged == True`, `stopcode in (2, 8)`,
`residual_out_mask_peak_snr < 5.0`, `residual_in_mask_peak_snr < 3.5`,
`residual_in_to_out_rms_ratio < 1.5`, `.model` predominantly positive,
flat-noise `negative_to_peak_ratio <= 0.05`). Once deconvolution inside the PB
is converged, separate the remaining causes in strict order: (0) check
`residual_outer_pb_peak_*` for an offending outer-PB source (phasecal inclusion,
outlier field, or baby peeling), (A) image the phase calibrator
as a point-source noise check to empirically test calibration and `thermal_rms_jy`,
(B) inspect target `CORRECTED_DATA` amplitudes vs frequency (adjacent-channel
`chan_diff_std_over_mad`, `spw_rms_ratio`) and time for residual RFI and flag if
present, and (C) if calibration and data are clean, evaluate phase
self-calibration when `dynamic_range >= 30` and the model is bowl-free (or
document sky confusion / dynamic-range limits).

### Reading `detection`

`ms_image_stats` returns a **descriptive** `detection` label over
`dynamic_range` (peak-to-noise), plus `detection_thresholds` carrying the two
constants behind it. It does not decide whether you may proceed — you do. Treat
it as a continuum, and say which level you are at when you report a flux:

| `detection` | `dynamic_range` | What it means, and what you may claim |
|---|---|---|
| `undetected` | <= 5 | The peak is consistent with a residual or sidelobe spike. Do not report a flux. At this level the usual cause is calibration decorrelation on `CORRECTED_DATA`, not imaging parameters. |
| `marginal` | > 5, < 10 | A source is probably there. A flux may be quoted with the peak-to-noise stated alongside it; do not quote a spectral index, a polarization fraction, or any second-order quantity. |
| `detection` | ≥ 10 | Report the flux normally. Note that 10 is a floor for *existence*, not for precision — calibrator and self-cal work wants > 100. |
| `unknown` | not computable | `rms_jy` was zero or negative. Something is wrong with the image, not with the source; check the warnings. |

The boundaries are single constants chosen for a typical case. If the science
goal justifies it, recompute the level yourself from `dynamic_range` and
`detection_thresholds` — for a stacking experiment or a known-position
measurement, a peak-to-noise of 4 at the expected position can be a real
measurement, and the label alone would have thrown it away.

---

## Polarization frequency cubes (IQUV)

Use this path when the science needs Stokes Q/U as a function of frequency —
rotation-measure (RM) work, depolarization studies, or any check that the
polarization calibration (skill 09) holds across the band. Spectral-line cubes
(continuum subtraction, velocity frames) are a separate workflow and out of
scope here.

### Why a cube, not wideband MFS

`deconvolver='mtmfs', nterms=2` (Step 2's wideband continuum path) **cannot**
image `stokes='IQUV'` — the Taylor-term expansion is defined for total
intensity only, and CASA will error or silently mis-model Q/U/V. So for
polarization spectral coverage you image a **frequency cube**:
`specmode='cube'`, `stokes='IQUV'`, `deconvolver='hogbom'` (per-plane CLEAN; no
joint spectral deconvolution). This trades the wideband sensitivity/spectral-
index benefit of mtmfs for honest per-channel polarization.

A wideband Stokes-I headline image (mtmfs) and an IQUV cube (hogbom) are
complementary, not alternatives — run both if you need both the deep I image
and the polarization spectrum.

### Channelization

Default to **per-SPW-chunk** planes, not per-native-channel. One plane per SPW
(or per N-MHz chunk) gives enough lambda^2 sampling for RM synthesis without the cost
and per-plane noise of full spectral resolution. This mirrors the chunking
precal's polarization model fit already uses.

- Derive `width` from the chunk size: e.g. a 1 GHz SPW split into 64 MHz
  planes → `width='64MHz'`, `nchan=16`. Match the chunking you used in polcal
  so the model and the cube share a frequency grid.
- Set `start` to the band's low edge and `outframe='LSRK'` (TOPO is acceptable
  for continuum polarization, but be explicit).
- Use **per-native-channel** only for narrow fractional bandwidth, or when RM
  is large enough that Q/U rotates within a chunk (chunk Δ(λ²) must keep the
  intra-chunk RM rotation well below a radian — otherwise bandwidth
  depolarization washes out the signal you are trying to measure).

### Call

Pass the cube args through `ms_tclean` (no separate tool):

```
ms_tclean(
    ms_path     = {VIS},
    imagename   = {WORKDIR}/{imagename}_iquv,
    field       = {TARGET_FIELD},
    stokes      = 'IQUV',
    specmode    = 'cube',
    deconvolver = 'hogbom',
    nchan       = {N_CHUNKS},
    start       = {BAND_LOW_EDGE},   # e.g. '1.0GHz'
    width       = {CHUNK_WIDTH},     # e.g. '64MHz'
    outframe    = 'LSRK',
    gridder     = {gridder},         # Steps 5–6 as usual
    cell        = {CELL},
    imsize      = [{IMSIZE}, {IMSIZE}],
    weighting   = 'briggs',
    robust      = 0.5,
    niter       = 50000,
    threshold   = {threshold},
    nsigma      = 3.0,               # prevent unmasked cube cleaning into noise
    pblimit     = -0.01,             # keeps outer mosaic PB unblanked (-0.1 single-pointing)
    pbmask      = 0.1,               # explicit clean boundary if usemask='pb' (or usemask='user' with Stokes I mask)
    usemask     = 'pb',              # or 'user' reusing converged Stokes I PyBDSF mask
    savemodel   = 'none',            # preserve Stokes I model in MODEL_DATA
    workdir     = {WORKDIR},
    execute     = False,
)
```

Cell size and imsize are derived as in Steps 3–4 using the **highest** frequency
in the band (smallest beam → finest cell), so every plane is adequately sampled.

### Quality gates (per-plane)

`ms_image_stats` returns a `planes` array (per Stokes, per channel) for a cube.
Reason over it — the tool does not interpret:

| Check | Expectation | If violated |
|---|---|---|
| Stokes I `rms_jy` per plane | rises smoothly toward band edges / RFI-flagged chunks | a single spiking plane = residual RFI or a flagged-out chunk; flag and re-image or drop the plane |
| Q, U `peak_jy` per plane | present and varying smoothly with frequency | Q/U at noise across all planes when the source is known-polarized = polcal (skill 09) didn't apply, or parang was off in applycal |
| V `peak_jy` per plane | near noise (most sources have negligible circular pol) | significant V everywhere = leakage (D-term) error; revisit skill 09 |
| fractional pol = sqrt(Q²+U²)/I | physically plausible (≲ a few–10% for most sources) | > ~20% smoothly across the band = I likely wrong (model/fluxscale); spiky = per-plane artefact |

Compute fractional polarization and RM-related quantities yourself from the
per-plane numbers — these are skill-level interpretations, deliberately not in
the tool.
