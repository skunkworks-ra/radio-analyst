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
| `{POINTING_CENTERS}` | `ms_field_list` | RA/Dec of each target pointing and `mosaic_groups[]` (`extent_ra_arcmin`, `extent_dec_arcmin`, `max_extent_arcmin`) |
| `{PHASECENTER}` | `ms_field_list` | `mosaic_groups[].bbox_center_j2000` (MANDATORY on every multi-pointing mosaic; check `central_field_id` / `central_field_name` / `central_field_offset_arcmin` for hollow mosaics) |
| `{SURVIVING_SPWS}` | `postcal` / `ms_spw_amp_severity` | comma-separated clean continuum SPWs (or `''` if all SPWs are clean) |
| `{MAX_BASELINE_M}` | `ms_baseline_lengths` | `max_baseline_m` |
| `{CENTER_FREQ_HZ}` | `ms_radiometer_estimate` | `center_freq_hz` (also read `min_freq_hz` for PB `imsize` and `max_freq_hz` for wideband/cube `cell`) |
| `{BANDWIDTH_HZ}` | `ms_radiometer_estimate` | `total_bw_hz` (`eff_bw_hz` is unflagged effective bandwidth; for thermal RMS only) |
| `{FRACTIONAL_SPAN}` | `ms_radiometer_estimate` | `fractional_span` (`freq_span_hz / center_freq_hz` across `min_freq_hz..max_freq_hz`; use for wideband `mtmfs` trigger) |
| `{DISH_DIAMETER_M}` | `ms_antenna_list` | smallest active dish diameter `D_min` (`min(diameter_m)` across unflagged antennas on heterogeneous arrays; equals `dish_diameter_m` on homogeneous arrays) |
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

**Pre-imaging continuum target spectrum cleanliness gate (MANDATORY before ANY continuum target `tclean`, no-op on clean data).**
Calibration flags `calibrators.ms` heavily, whereas science target pointings
only received raw-DATA `preflag`. Scope automatic `freqdev` `rflag` and
`surviving_spws` dropping strictly to **continuum SPWs (`specmode='mfs'`)** --
explicitly **exempt spectral-line / maser SPWs and rest-frequency line windows**,
where genuine narrow astronomical lines produce steep adjacent-channel sky
derivatives that trigger `chan_diff_*`. Before calling `ms_tclean` on continuum
target `CORRECTED_DATA`, you **MUST** run `ms_spw_amp_severity(ms_path,
datacolumn='CORRECTED_DATA', field='{TARGET_FIELD}', spw='{SURVIVING_SPWS}',
workdir={WORKDIR})` and check its sky-cancelling adjacent-channel complex
difference metrics (`|V(ch) - V(ch-1)| / sqrt(2)` on unflagged parallel hands;
cancels smooth extended continuum sky emission while exposing narrow-band/burst
RFI). Gate continuum target cleanliness strictly on the SEFD-invariant
within-SPW Gaussianity metrics below; treat bandwidth-normalized
`spw_noise_density_ratio` (from `chan_diff_noise_density = chan_diff_rms *
sqrt(chan_width_hz)`) / `spw_rms_ratio` strictly as a secondary smoothness
diagnostic (distinguishing a discontinuous single-SPW RFI jump from a smooth
`T_sys(nu)` / atmospheric / sky-temperature gradient across the band):

| Metric (`ms_spw_amp_severity`) | Clean continuum target spectrum | Action if exceeded |
|---|---|---|
| `chan_diff_std_over_mad` | `< 1.5` | **DO NOT image yet** -- run bounded continuum target `rflag` / SPW triage below |
| `max_spw_chan_diff_std_over_mad` | `< 1.8` | **DO NOT image yet** -- run bounded continuum target `rflag` / SPW triage below |
| `chan_diff_gt10sigma_frac` | `< 0.001` (`< 0.1%`) | **DO NOT image yet** -- run bounded continuum target `rflag` / SPW triage below |
| `spw_noise_density_ratio` / `spw_rms_ratio` | Secondary smoothness diagnostic (not a hard gate) | Inspect `per_spw` `chan_diff_noise_density` (`Jy * Hz^{1/2}`): a smooth `T_sys(nu)` / atmospheric / sky-temperature gradient across frequency is physical thermal noise; investigate only a discontinuous single-SPW jump |

If ANY of the three primary Gaussianity metrics fails on continuum SPWs (or if
`ms_vis_amp_time_stats` shows a well-populated integration `npts >= 0.25 *
median_npts` with `ratio_to_median >= 2.0`), you MUST triage and flag continuum
target RFI BEFORE running `ms_tclean`:
1. Run at most **`<= 2` `rflag` rounds** on continuum SPWs of target
   `CORRECTED_DATA`: round 1 at default `ms_apply_rflag(ms_path,
   workdir={WORKDIR}, field='{TARGET_FIELD}', spw='<continuum_spws>',
   datacolumn='corrected', timedevscale=5.0, freqdevscale=5.0, execute=False)`
   (pass `spw=''` when all SPWs are continuum, or the explicit continuum SPW
   list when spectral-line / maser SPWs are present) -> run via `run-step.sh`
   (**never** amplitude-clip targets, which have no `MODEL_DATA`, **never** run
   automatic `freqdev` `rflag` on spectral-line / maser SPWs or rest-frequency
   line windows, and **never** run destructive whole-SPW flagging in `postcal`).
   Only if cleanable RFI outliers remain on candidate continuum SPWs, run one
   stricter second pass (`spw='<continuum_spws>'`, `timedevscale=4.0,
   freqdevscale=4.0`). Never spin 3+ rounds on persistently RFI-saturated or
   atmospheric-absorption-dominated SPWs.
2. Inspect `per_spw` from `ms_spw_amp_severity` to identify any persistently
   RFI-saturated, atmospheric-absorption-dominated, or >95%-flagged continuum
   SPWs and form `spw='{SURVIVING_SPWS}'` from the clean surviving continuum
   SPWs (never auto-drop spectral-line / maser SPWs). **Re-run
   `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA',
   field='{TARGET_FIELD}', spw='{SURVIVING_SPWS}', workdir={WORKDIR})`** and
   report the before/after spectrum numbers to prove the surviving continuum
   SPWs pass the gate, then forward `spw='{SURVIVING_SPWS}'` to all downstream
   `ms_tclean` and `ms_radiometer_estimate` calls.
3. On clean continuum data where all three primary Gaussianity checks already
   pass (e.g. `chan_diff_std_over_mad ~ 1.0`), skip flagging and proceed
   straight to Step 1.

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

1. **Phase A -- Initial shallow pass (`usemask='pb'`, `savemodel='none'`):** Run
   the first `hogbom` (or `mtmfs`, `nterms=2`, `specmode='mfs'` when
   `fractional_span > 0.2`) pass (`<name>_hogbom` or `<name>_mtmfs_init`) with
   `phasecenter={PHASECENTER}` on multi-pointing mosaics, `spw={SURVIVING_SPWS}`,
   `savemodel='none'` (never pay the `MODEL_DATA` write cost on an initial
   shallow pass), `pblimit=-0.01` on mosaics (`-0.1` single-pointing), explicit
   `pbmask=0.1` (so unmasked PB cleaning stays inside `PB >= 0.1` while the
   outer mosaic PB / first sidelobe remains unblanked), and **`nsigma=5.0` on
   unmasked `mtmfs` mosaics** (`3.5` on narrowband `hogbom` mosaics, `3.0` on
   compact single pointings). Why `5.0` on unmasked `mtmfs` mosaics: cleaning
   20% of the map unmasked down to `3.5` sigma drives `nterms=2` into noise and
   outer-PB sidelobes (`model.tt1` diverges with `stopcode=6`); `nsigma=5.0`
   stops cleanly on bright structure to seed the PyBDSF mask. Verify
   `converged=True` (`stopcode in (2, 8)`), then call `ms_image_stats(...,
   pb_level=0.1)` on it (for `mtmfs`, use the `.pbcor` image on disk:
   `.image.tt0.pbcor` or `.image.pbcor.tt0`, plus `.psf.tt0`).
2. **Phase B -- Adaptive mask-growing passes (`usemask='user'`, `savemodel='none'`
   on intermediate passes, safety cap 4 rounds, early stop on convergence):**
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
     `fractional_span > 0.2`), `phasecenter={PHASECENTER}` (mosaics),
     `spw={SURVIVING_SPWS}`, `usemask='user'`, `mask=<name>_rN.mask`,
     `pblimit=(-0.01 if mosaic else -0.1)`, `nsigma=2.5` (or `2.0` once
     bright sidelobes drop), and **`savemodel='none'`** on intermediate passes.
     Why lower than `3.0`: CASA's `nsigma` multiplies the global residual MAD
     across the whole PB, so unmasked faint emission inflates the MAD and stalls
     `nsigma=3.0` prematurely; `usemask='user'` already blocks cleaning
     outside-mask noise.
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
     with the same fixed mask, `specmode='mfs'`, `phasecenter={PHASECENTER}`
     (mosaics), `spw={SURVIVING_SPWS}`, `pblimit=(-0.01 if mosaic else -0.1)`,
     `nsigma=1.5`,
     `threshold = max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy)`, and
     `savemodel='modelcolumn'` **ONLY when `selfcal` (`dynamic_range >= 30`) or
     `uvsub` will consume `MODEL_DATA`** (otherwise keep `savemodel='none'` to
     avoid expensive `MODEL_DATA` write/I/O overhead on large MSs). Verify
     `converged=True` AND that `.model` positivity did not degrade compared to
     Phase B; if Phase C only added negative model components without improving
     residuals, keep the cleaner Phase B round.
   - If Phase B already converged inside the mask
     (`residual_in_mask_peak_snr < 3.5` and `residual_in_to_out_rms_ratio < 1.5`),
     write `savemodel='modelcolumn'` ONLY if `selfcal` (`dynamic_range >= 30`)
     or `uvsub` will consume `MODEL_DATA` (otherwise keep `savemodel='none'`).
     Once `tclean` converged (`stopcode in (2, 8)`), inside-mask and
     outside-mask (`PB >= 0.1`) residuals are noise-like, `.model` is
     predominantly positive, and flat-noise `negative_to_peak_ratio <= 0.05`,
     deconvolution inside the PB is converged; any remaining gap to
     `thermal_rms_jy` is an offending outer-PB source, calibration, residual
     RFI, dynamic-range/selfcal, or confusion -- not masking.

**Primary-beam blanking on mosaics (`pblimit`, `pbmask`, `ms_make_mask`, `ms_image_stats`).**
Positive `pblimit` (`0.1` or `0.2`) blanks all pixels below that gain level,
hiding sources in the outer PB and first sidelobe even when `imsize` covers
`extent + 4.0 * pb_fwhm` (Step 4). Use **`pblimit=-0.01`** on mosaics (`-0.1`
on single pointings) so the outer PB stays visible for diagnostics, while
keeping the clean boundary inside the primary beam:
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

**Quick-look (`usemask='pb'`) pass vs. Delivered Noise-Limited Science Image.**
An initial shallow `usemask='pb'` pass (Phase A) is a **quick-look image only**
-- NOT a finished science deliverable whenever uncleaned source flux or elevated
noise remains. Before declaring target imaging complete, ALL THREE criteria
below must be met:
- **(a) Hard convergence:** `converged == True` (`stopcode in (2, 8)`) on the
  final delivered image.
- **(b) Masked deep clean required when quick-look is not noise-limited:** Run
  Phase B (`ms_make_mask` + `usemask='user'` deconvolver pass, plus Phase C if
  needed) whenever the initial pass has `residual_in_model_rms_ratio > 1.5` (or
  `residual_in_to_out_rms_ratio > 1.5`) **OR** `residual_rms_jy > 1.3 * thermal_rms_jy`.
  Do NOT stop after Phase A just because `usemask='pb'` converged (`stopcode=8`).
- **(c) Quantitative outer-PB baby-peel probe trigger:** Whenever
  `residual_outer_pb_peak_snr >= 20` **AND** science-PB RMS (`residual_out_mask_rms_jy`,
  else `residual_rms_jy`) `> 1.3 * thermal_rms_jy`, run the Version-1 baby-peel
  probe below (compare science-PB dirty mosaic RMS before vs. after peeling):
  keep the peeled MS and re-image if science-PB RMS improves, otherwise keep the
  unpeeled image and report the measured before/after probe delta.

**Outer-PB Offending Source Workflow (phasecal inclusion, outlier fields, and baby peeling).**
Uncleaned sources outside `PB >= 0.1` are common and are NOT a failure by
themselves (some outer-PB sources cannot be deconvolved directly inside a
wideband mosaic). Check `residual_outer_pb_peak_*` in `ms_image_stats` and
follow this decision tree:
1. **Quantitative trigger:** If `residual_outer_pb_peak_snr < 20` **OR**
   science-PB RMS (`residual_out_mask_rms_jy`, else `residual_rms_jy`)
   `<= 1.3 * thermal_rms_jy`, leave the outer-PB source uncleaned and report its
   position/SNR in the summary. Otherwise (`residual_outer_pb_peak_snr >= 20`
   AND science-PB RMS `> 1.3 * thermal_rms_jy`), test Steps 2--3 below.
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
     4. **Probe mosaic before vs. after peeling:** Run a dirty image (`niter=0`)
        on `target_peeled.ms` and compare both the offending source peak AND
        science-PB (`PB >= 0.1`) dirty RMS before vs. after. Keep the peeled MS
        and re-image if science-PB RMS improves; otherwise keep the unpeeled
        image and report the measured before/after probe delta.
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

## Step 3 -- Derive cell size

```
# For specmode='cube' imaging a narrow sub-band of a wideband SPW, use the
# cube's imaged frequency bounds [nu_cube_min, nu_cube_max] (nu_cube_max here)
# rather than the entire wideband SPW's max_freq_hz.
freq_ref_hz      = nu_cube_max if specmode == 'cube' else (max_freq_hz if {FRACTIONAL_SPAN} > 0.2 else {CENTER_FREQ_HZ})
lambda_ref_m     = c / freq_ref_hz                # c = 2.998e8 m/s
max_bl_lambda    = {MAX_BASELINE_M} / lambda_ref_m
cell_rad         = 1.0 / (max_bl_lambda * 4)      # factor 4: >= 3.0 pixels per beam minor axis (Nyquist safe)
cell_arcsec      = cell_rad * (180 * 3600 / pi)
```

Round `cell_arcsec` down (or to 1--2 significant figures, e.g. 2.87" -> 2.8") so
the actual restored beam stays well sampled: target **`pixels_per_beam_minor >= 3.0`**
(hard floor **`2.5`**, never coarser/sub-Nyquist). At `3` pixels per beam at
`center_freq_hz`, wideband upper-band channels drop below `2.5 px/beam` and
discrete CLEAN pixels incur large peak errors; dividing by `4` at `max_freq_hz`
(or upper-band frequency) keeps every channel safely above Nyquist. State the
value and record it as `{CELL}`.

---

## Step 4 -- Derive image size and mosaic phasecenter

**Mandatory mosaic `phasecenter`:** On every multi-pointing mosaic
(`{IS_MOSAIC} == True`), ALWAYS pass
`phasecenter = mosaic_groups[].bbox_center_j2000` (from `ms_field_list`) to
every `ms_tclean` call. Omitting `phasecenter` (`""`) defaults in CASA to the
first selected pointing -- often an outer-edge pointing -- which shifts the grid
off-center, slices through the opposite edge's primary beam, and triggers
toroidal FFT wrap-around (`stopcode=5`). Also check
`mosaic_groups[].central_field_id`, `central_field_name`, and
`central_field_offset_arcmin`: if `central_field_offset_arcmin > 0.5 * pb_fwhm`
(a hollow or ring mosaic whose bounding-box midpoint sits in an unobserved gap
where `PB ~ 0`), pass `psfphasecenter = central_field_id` (integer field ID) or
a `J2000` direction string to `ms_tclean` so CASA `makePSF()` evaluates on an
observed pointing. For both `phasecenter` and `psfphasecenter`, CASA `tclean`
accepts an integer field ID (`central_field_id`) or a `J2000` direction string
using `d/m/s` or `.` for Declination (e.g. `'J2000 03h26m24.16s +30d35m59.4s'`
or `'J2000 03:26:24.16 +30.35.59.4'` -- NEVER `:` in Declination, which CASA
interprets as hours, and NEVER `'FK5'`); `ms_tclean` also accepts
`central_field_name` (or a numeric string) and converts it to the integer field
ID for CASA. Record `bbox_center_j2000` as `{PHASECENTER}`.

Primary beam FWHM: use the tapered-aperture approximation
`PB_FWHM ~ 1.15 * lambda / D_min` (where `D_min` is the smallest active dish
diameter on heterogeneous arrays, e.g. `min(diameter_m)` from `ms_antenna_list`,
matching real tapered/Cassegrain CASA primary-beam models rather than an
untapered uniform-disk `1.02` factor). Evaluate `lambda_max = c / nu_low`: on
wideband continuum observations (`{FRACTIONAL_SPAN} > 0.2`), set `nu_low =
min_freq_hz` of the imaged SPWs; for `specmode='cube'` imaging a narrow sub-band
of a wideband SPW, set `nu_low = nu_cube_min` of the cube's imaged frequency
range `[nu_cube_min, nu_cube_max]`:
```
pb_fwhm_arcsec = (1.15 * lambda_max / D_min) * (180 * 3600 / pi)
```

**Always pad out PAST the first positive primary-beam sidelobe on EACH side.**
For tapered/Cassegrain CASA primary-beam models, the first null sits near
`~1.2 * FWHM` radius and the **first positive sidelobe peak** sits near
`~1.6 * FWHM` radius (`PB ~ 0.02-0.04`). Padding only `1.5 * FWHM` per side
(`3 * FWHM` total) slices right through the first positive sidelobe peak, and
stopping at the first null reads `PB = 0` on the border while STILL wrapping the
first positive sidelobe toroidally across the periodic FFT boundary (aliasing).
Therefore pad **`2.0 * pb_fwhm_arcsec` on EACH side** (`4.0 * pb_fwhm_arcsec`
total):

**Single pointing:**
```
imsize_pixels = ceil((4.0 * pb_fwhm_arcsec) / cell_arcsec)   # 2.0 * FWHM per side -> clears 1st positive sidelobe
```

**Mosaic:** read `extent_ra_arcmin` and `extent_dec_arcmin` (and
`max_extent_arcmin`) from `ms_field_list` `mosaic_groups[]` (convert to arcsec
by multiplying by 60), then pad by `2.0 * pb_fwhm_arcsec` on EACH side
(`+ 4.0 * pb_fwhm_arcsec` total):
```
imsize_x = ceil((extent_ra_arcsec  + 4.0 * pb_fwhm_arcsec) / cell_arcsec)
imsize_y = ceil((extent_dec_arcsec + 4.0 * pb_fwhm_arcsec) / cell_arcsec)
```

**Rectangular `[nx, ny]` is valid and preferred** when `extent_ra_arcmin` and
`extent_dec_arcmin` differ by `> 20%` (saves memory and gridding time without
clipping either axis). When the aspect ratio is within 20%, square
`[IMSIZE, IMSIZE]` using `max_extent_arcmin * 60` is fine. Do NOT drop to a
first-null fallback (`2 * FWHM` or `3 * FWHM`) -- never shrink `imsize` below
`extent + 4.0 * pb_fwhm_arcsec`.

Round `imsize_x` and `imsize_y` **up** to the smallest **even composite number
of the form `2^a * 3^b * 5^c`** (with `a >= 1`, generated programmatically, e.g.
in Python, with **no arbitrary pixel ceiling** -- `imsize` is bounded solely by
available machine RAM via the Step 6 `free -b` memory check). Do not use a prime
number -- `tclean` will run extremely slowly.

**Retry growth on `edge_pb_max >= 0.02`:** If Step 9 measures
`edge_pb_max >= 0.02` even with centered `phasecenter` and the formula above
(e.g. strong tapered/Cassegrain sidelobes), **grow `imsize` beyond the formula**
(add at least `+1.0 * pb_fwhm_arcsec` per side, i.e. `+2.0 * pb_fwhm_arcsec`
total, rounded up to the next even `2^a * 3^b * 5^c` within available RAM)
rather than re-evaluating the identical `4.0 * pb_fwhm_arcsec` formula.

Record as `{IMSIZE}` (or `[{IMSIZE_X}, {IMSIZE_Y}]`).

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

## Step 6 -- Choose gridder

Evaluate the dimensionless wide-field W-phase parameter across the imaged half-width
`theta_fov` (in radians; half the mosaic extent + primary beam radius for mosaics,
or the primary beam radius for a single pointing):
```
w_phase_turns = ({MAX_BASELINE_M} / lambda_m) * theta_fov**2
```

| Condition | `gridder` | `wprojplanes` |
|---|---|---|
| Mosaic, telescope has a CASA PB model, and wide-field W-phase `(B_max / lambda) * theta_fov^2` is modest (`< 1` or first-pass imaging) | `'mosaic'` | ignored by CASA (do not set) |
| Mosaic, telescope has a CASA PB model, and wide-field W-phase `(B_max / lambda) * theta_fov^2 >= 1` | **check memory & A-projection CF feasibility first** (below), then `'awp2'` (if supported and within RAM; else `'mosaic'`) | from Step 5 |
| Mosaic, telescope has NO CASA primary-beam model | see note below (`'wproject'` if W-terms required, else `'standard'`) | from Step 5 (if `'wproject'`) |
| Single pointing AND W-terms required | `'wproject'` | from Step 5 |
| Single pointing AND W-terms not required | `'standard'` | not set |

**CASA `gridder='mosaic'` ignores `wprojplanes`.** `wprojplanes` applies only
to `wproject`, `awproject`, and `awp2`. Because `MosaicFTNew` phase-rotates each
pointing onto the common `phasecenter`, W-phase error scales with the
dimensionless wide-field parameter `(B_max / lambda) * theta_fov^2` rather than
a telescope-specific array configuration letter. `gridder='mosaic'` is accurate
and fast for any telescope with a CASA primary-beam model when `phasecenter` is
centered (`bbox_center_j2000`) and wide-field W-phase is small. When wide-field
W-phase is large (`(B_max / lambda) * theta_fov^2 >= 1`), `gridder='mosaic'`
cannot correct non-coplanar W-terms, so `'awp2'` + `wprojplanes` is needed --
but ONLY after verifying both (1) available RAM (`free -b`, below) and (2) that
CASA's A-projection convolution functions support the array/Stokes mode
(A-projection gridders cost far more memory and time, and are otherwise a later
choice when the science needs wide-field polarization or beam-squint correction).

**Large mosaics (long-baseline arrays, `imsize >= 2048`, or `>= 10` pointings): check
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

## Step 8 -- Call ms_tclean

```
ms_tclean(
    ms_path      = {VIS},
    imagename    = {WORKDIR}/{imagename},
    field        = {TARGET_FIELD},
    spw          = {SURVIVING_SPWS},     # surviving clean continuum SPWs from postcal (or '')
    phasecenter  = {PHASECENTER},        # MANDATORY on multi-pointing mosaics: mosaic_groups[].bbox_center_j2000 (J2000 d/m/s or '.' for Dec, never ':' or FK5; or int field ID)
    psfphasecenter = '',                 # optional: int central_field_id (or central_field_name, converted to int for CASA) or J2000 direction on hollow mosaics (central_field_offset_arcmin > 0.5 * pb_fwhm)
    stokes       = {STOKES},
    specmode     = {specmode},
    deconvolver  = {deconvolver},
    nterms       = 2,                    # only when deconvolver='mtmfs'
    gridder      = {gridder},
    wprojplanes  = {wprojplanes},        # only when gridder in ('wproject', 'awproject', 'awp2'); ignored by 'mosaic'
    cell         = {CELL},
    imsize       = [{IMSIZE_X}, {IMSIZE_Y}],
    weighting    = 'briggs',
    robust       = 0.5,
    niter        = 50000,
    threshold    = {threshold},
    nsigma       = 5.0,                  # Phase A mtmfs mosaic (3.5 narrowband mosaic, 3.0 single-pointing; 2.5 Phase B; 1.5 Phase C)
    savemodel    = 'none',               # 'none' on Phase A & intermediate Phase B; 'modelcolumn' ONLY on final converged Stokes I pass when selfcal/uvsub will consume MODEL_DATA
    pblimit      = -0.01,                # negative on mosaics keeps outer PB / first sidelobe unblanked (-0.1 single-pointing)
    pbmask       = 0.1,                  # explicit clean boundary when usemask='pb' (never omit with pblimit=-0.01)
    usemask      = 'pb',                 # or 'user' with mask=<path> (e.g. PyBDSF mask); never 'auto-multithresh'
    workdir      = {WORKDIR},
    execute      = False,
)
```

`savemodel`: use **`savemodel='none'`** on Phase A and intermediate Phase B
passes; set `savemodel='modelcolumn'` **ONLY** on the final converged Stokes I
pass when `selfcal` (`dynamic_range >= 30`) or `uvsub` will actually consume
`MODEL_DATA` (avoids expensive `MODEL_DATA` write/I/O overhead on large MSs).

**Hard pre-flight guards (`tclean.py`):** Before writing or executing a script,
`ms_tclean` raises `ComputationError` on (a) a live `tclean_*.py.pid` in
`workdir`, (b) missing `phasecenter=''` on a multi-pointing mosaic, (c) an
unparseable or invalid `phasecenter` / `psfphasecenter` (including `:` in
Declination, `'FK5'`, or an out-of-range field ID), (d) an undersized centered
mosaic FOV (`fov < extent + 3.6 * pb_fwhm` or margin `< 1.8 * pb_fwhm`), and
(e) a strict unprojected Nyquist violation (`px_per_beam < 2.0` without
`uvtaper`). Items (a)--(c) are always hard errors; only geometry checks (d)--(e)
can be downgraded to warnings by passing `allow_geometry_override=True`
(reserved for intentional non-standard diagnostics, never for routine science
imaging or panic retries).

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

**Hard convergence & anti-panic rules (NEVER accept `converged=False` or panic-degrade parameters):**
- Inspect `stopcode` and `converged` in the `tclean` output / `stage_log.jsonl`.
  **NEVER accept or deliver an image from a run with `converged=False`
  (`stopcode=1` iteration limit, `stopcode=5` or `6` divergence).**
- **Auto-quarantine (`tclean.py`):** On numerically diverged runs
  (`niter > 0` and `stopcode in (5, 6)`), `tclean.py` automatically moves
  `<imagename>.*` products into `{WORKDIR}/rejected/` (preserving them for
  `ms_image_stats` inspection while keeping `{WORKDIR}/` clean and recording
  `exists=False` in `stage_log.jsonl`), and re-running on an existing
  `imagename` archives prior products into `{WORKDIR}/rejected/`. For any other
  rejected pass (e.g. negative-dominated `.model` or an abandoned `stopcode=1`),
  move `<rejected_imagename>.*` into `{WORKDIR}/rejected/` before delivering,
  and verify your handoff/summary lists ONLY the exact converged final prefix.
- **Anti-panic prohibitions on `stopcode=5` or `6` (divergence):**
  1. **NEVER** coarsen `cell` below Nyquist (`pixels_per_beam_minor < 2.5`) or
     shrink `imsize` below `extent + 4.0 * pb_fwhm(min_freq)` (`4.0 * pb_fwhm`
     single-pointing) to "speed up" or retry a failed run.
  2. **NEVER** "fix" divergence by raising `threshold` above `~3--5 *
     off_source_rms` (that only stops cleaning early while leaving 5x+ uncleaned
     in-model residuals).
  3. **NEVER** retry unmasked `usemask='pb'` more than **once** after
     `stopcode=5/6`. After a `stopcode=5/6` failure, diagnose in strict order:
     (a) inspect the quarantined `.pb` / `.image` in `{WORKDIR}/rejected/` for
     `edge_pb_max >= 0.02`, missing/off-center `phasecenter`, or undersized
     `imsize < extent + 4.0 * pb_fwhm(min_freq)` and `pixels_per_beam_minor < 2.5`;
     (b) confirm target `CORRECTED_DATA` on `spw={SURVIVING_SPWS}` passed the
     Step 0.5 SEFD-invariant spectrum gate (`chan_diff_std_over_mad < 1.5`,
     `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001`);
     (c) switch to a tight PyBDSF mask (`ms_make_mask` inside `PB >= 0.1` +
     `usemask='user'`, keeping Phase A shallow at `nsigma=5.0` on wideband
     `mtmfs` mosaics).
  4. **Failed-convergence recovery retry cap:** Cap *failed-convergence recovery
     retries* (`stopcode not in (2, 8)`) at **`<= 2`** per `image-stage`
     invocation (separate from normal Phase A -> Phase B up to 4 mask-grow
     rounds -> Phase C progression), and **`<= 3`** orchestrator `image` stage
     retries. If still failing after 2 recovery attempts, STOP and report the
     diagnostic numbers from `{WORKDIR}/rejected/` rather than spinning.
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
| `tclean` convergence (`stage_log.jsonl`) | `converged == True` (`stopcode` is `2` or `8`) | **HARD FAIL** on `stopcode=1`, `5`, or `6`: NEVER deliver (`tclean.py` auto-quarantines `stopcode in (5, 6)` to `{WORKDIR}/rejected/`). Fix root cause (`phasecenter = bbox_center_j2000`, `fov >= extent + 4.0 * pb_fwhm(min_freq)`, `pixels_per_beam_minor >= 2.5`, clean `spw={SURVIVING_SPWS}` spectrum, shallow Phase A `nsigma=5.0` + tight PyBDSF `usemask='user'` mask inside `PB >= 0.1`, or higher `niter`) -- NEVER coarsen `cell`, shrink `imsize`, or raise `threshold` above `~3--5x` rms to mask divergence |
| `edge_pb_max` + geometric FOV padding (`ms_image_stats` + Step 4) | `edge_pb_max < 0.02` **AND** `fov >= extent + 4.0 * pb_fwhm(nu_low, D_min)` (single-pointing: `>= 4.0 * pb_fwhm(nu_low, D_min)`, tapered `1.15 * lambda / D_min`) | Both checks are required together: a border sitting in the 1st PB null reads `edge_pb_max == 0.0` while STILL wrapping the 1st positive sidelobe toroidally across the FFT boundary! First ensure `phasecenter = mosaic_groups[].bbox_center_j2000` and `imsize` covers `extent + 4.0 * pb_fwhm`; if `edge_pb_max >= 0.02` persists on retry, **grow `imsize` beyond the formula** (e.g. `+1.0 * pb_fwhm` per side, rounded up to the next even `2^a * 3^b * 5^c` within available RAM) rather than re-evaluating the identical formula |
| `pixels_per_beam_minor` (`ms_image_stats`) | `>= 2.5` (prefer `>= 3.0`, derived with divisor `4` in Step 3) | `< 2.5` is sub-Nyquist (causes clean oscillation / peak bias): re-image with finer `cell` (`<= beam_minor_arcsec / 3.0`, never coarsen `cell` on retry) |
| `.model` positivity (Stokes I: `model_neg_to_pos_flux_ratio`, `model_neg_pixel_fraction`, `model_neg_to_pos_peak_ratio`, `model_outer_pb_flux_frac`) | Predominantly positive (`model_neg_to_pos_flux_ratio < 0.25`, `model_neg_to_pos_peak_ratio < 0.25`, `model_outer_pb_flux_frac` small) | Surging negative model flux/components: stop deepening, tighten mask or drop overly large `scales`, or keep the cleaner earlier round (never subtract or deliver a negative-dominated Stokes I model) |
| `residual_out_mask_peak_snr` | `< 5.0` (masked pass, inside `PB >= 0.1`) | `>= 5.0`: unmasked emission remains inside `PB >= 0.1`; grow mask via `ms_make_mask(..., pb_level=0.1, prior_mask=...)` (enable `atrous_do=True` / `thresh_pix=4.0, thresh_isl=2.5` if diffuse) and re-image |
| `residual_outer_pb_peak_snr`, `residual_outer_pb_peak_pb`, `residual_outer_pb_peak_j2000` (`0 < PB < 0.1`) | Diagnostic (uncleaned outer-PB sources are normal; probe required when `>= 20` AND science-PB RMS `> 1.3 * thermal_rms_jy`) | If `residual_outer_pb_peak_snr >= 20` AND `residual_out_mask_rms_jy` (else `residual_rms_jy`) `> 1.3 * thermal_rms_jy`: (1) cross-match `(ra_deg, dec_deg)` against `ms_field_list` (if phasecal, include pointing), else (2) run the Version-1 baby-peel probe (before/after dirty mosaic RMS) -- keep the peeled MS and re-image if science-PB RMS improves, otherwise keep unpeeled and report the probe delta |
| `residual_in_mask_peak_snr`, `residual_in_to_out_rms_ratio`, `residual_in_model_rms_ratio` | `< 3.5` and `< 1.5` (near `1.0`, checked even on `usemask='pb'` passes via `residual_in_model_rms_ratio`) | Above `1.5` on Phase A (`usemask='pb'`): quick-look only -- MUST run Phase B masked deep clean (`ms_make_mask` + `usemask='user'`). Above either on a masked pass: run Phase C deep clean inside the fixed mask (`nsigma=1.5`, `threshold = max(2 * thermal_rms_jy, 1.5 * residual_out_mask_rms_jy)`) |
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
(B) inspect continuum target `CORRECTED_DATA` amplitudes vs frequency
(within-SPW `chan_diff_std_over_mad`, plus secondary smoothness diagnostic
`spw_noise_density_ratio` / `spw_rms_ratio`) and time for residual RFI and flag
if present, and (C) if calibration and data are clean, evaluate phase
self-calibration when `dynamic_range >= 30` and the model is bowl-free (or
document sky confusion / dynamic-range limits).

**Mandatory delivered-image handoff/report block.** Every imaging handoff and
final summary MUST report these exact fields for the converged final deliverable
prefix ONLY (never a rejected/quarantined prefix):
- Exact delivered image prefix on disk (e.g. `{WORKDIR}/mosaic_mtmfs_r2.image.tt0.pbcor`)
- `stopcode` and `converged` (`True`, `stopcode in (2, 8)`)
- `edge_pb_max` (`< 0.02`, paired with `fov >= extent + 4.0 * pb_fwhm(min_freq)` and `phasecenter`) and `pixels_per_beam_minor` (`>= 2.5`, prefer `>= 3.0`)
- `residual_out_mask_rms_jy` (else `residual_rms_jy`) and ratio to `thermal_rms_jy`
- `residual_in_to_out_rms_ratio` and `residual_in_model_rms_ratio`
- `residual_out_mask_peak_snr` and `.model` positivity (`model_neg_to_pos_flux_ratio`, `model_neg_to_pos_peak_ratio`)
- `residual_outer_pb_peak_snr` (and Version-1 peel probe before/after RMS delta if triggered)

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
  planes -> `width='64MHz'`, `nchan=16`. Match the chunking you used in polcal
  so the model and the cube share a frequency grid.
- **Non-contiguous surviving SPWs (`spw={SURVIVING_SPWS}`):** When RFI triage
  excluded one or more interior SPWs so surviving SPWs are non-contiguous, a
  uniform `start/width/nchan` grid spanning the full band will create empty
  (`sumwt=0`) planes across the dropped SPW gaps. Use gap-aware / per-SPW
  channelization (either image per surviving SPW / contiguous SPW block, or set
  `width` to one SPW width and note the expected empty gap planes explicitly
  rather than treating them as imaging failures).
- Set `start` to the band's low edge and `outframe='LSRK'` (TOPO is acceptable
  for continuum polarization, but be explicit).
- Use **per-native-channel** only for narrow fractional bandwidth, or when RM
  is large enough that Q/U rotates within a chunk (chunk delta(lambda^2) must keep the
  intra-chunk RM rotation well below a radian -- otherwise bandwidth
  depolarization washes out the signal you are trying to measure).

### Call

Pass the cube args through `ms_tclean` (no separate tool):

```
ms_tclean(
    ms_path     = {VIS},
    imagename   = {WORKDIR}/{imagename}_iquv,
    field       = {TARGET_FIELD},
    spw         = {SURVIVING_SPWS},  # surviving clean continuum SPWs from postcal (or '')
    phasecenter = {PHASECENTER},     # MANDATORY on multi-pointing mosaics: mosaic_groups[].bbox_center_j2000
    stokes      = 'IQUV',
    specmode    = 'cube',
    deconvolver = 'hogbom',
    nchan       = {N_CHUNKS},
    start       = {BAND_LOW_EDGE},   # e.g. '1.0GHz'
    width       = {CHUNK_WIDTH},     # e.g. '64MHz'
    outframe    = 'LSRK',
    gridder     = {gridder},         # Steps 5-6 as usual
    cell        = {CELL},            # derived at nu_cube_max (divisor 4) so highest-freq plane stays >= 3.0 px/beam
    imsize      = [{IMSIZE_X}, {IMSIZE_Y}],  # padded by 2.0 * pb_fwhm(nu_cube_min, D_min) per side (tapered 1.15*lambda/D_min) so lowest-freq plane clears 1st positive sidelobe
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

Derive `cell` from the **highest** imaged frequency of the cube (`nu_cube_max`,
which is `max_freq_hz` for a full-band cube or the upper edge of the sub-band
when imaging a narrow sub-band of a wideband SPW, divisor `4`) so even the
narrowest-beam top-of-band plane satisfies `pixels_per_beam_minor >= 2.5`
(prefer `>= 3.0`), and derive `imsize` from tapered `pb_fwhm = 1.15 * lambda /
D_min` at the **lowest** imaged frequency of the cube (`nu_cube_min`,
`extent + 4.0 * pb_fwhm`, rounded up to an even `2^a * 3^b * 5^c` bounded only
by available RAM) so even the widest-beam bottom-of-band plane clears its first
positive sidelobe (`edge_pb_max < 0.02`; grow `imsize` by `+1.0 * pb_fwhm` per
side on retry if `edge_pb_max >= 0.02` persists).

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
