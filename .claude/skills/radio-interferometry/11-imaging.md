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
| `{CENTER_FREQ_HZ}` | `ms_observation_info` | centre frequency in Hz |
| `{BANDWIDTH_HZ}` | `ms_spectral_window_list` | total bandwidth in Hz |
| `{DISH_DIAMETER_M}` | `ms_antenna_list` | dish diameter (all antennas same for connected arrays) |
| `{TELESCOPE}` | `ms_observation_info` | `telescope_name` |
| `{N_ANT}` | `ms_antenna_list` | number of unflagged antennas |
| `{T_ON_SOURCE_S}` | `ms_scan_list` | on-source time in seconds; for a mosaic, per pointing (Step 7) |
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

---

## Step 1 — Choose imaging mode

Determine `specmode` before deriving any other parameter.

| Condition | `specmode` |
|---|---|
| Single SPW, continuum science | `'mfs'` |
| Multiple SPWs aggregated, continuum science | `'mfs'` |
| Spectral line science or per-channel imaging requested | `'cube'` |

Default to `'mfs'` unless the user explicitly asks for a cube.

---

## Step 2 — Choose deconvolver

| Condition | `deconvolver` | Notes |
|---|---|---|
| `specmode='cube'` | `'hogbom'` | Always |
| `{BANDWIDTH_HZ} / {CENTER_FREQ_HZ} > 0.2` | `'mtmfs'`, `nterms=2` | Wideband; also produces a spectral index map |
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

**Masking.** `ms_tclean` cleans inside the primary-beam mask (`usemask='pb'`).
Do not switch to CASA's automatic masking (`usemask='auto-multithresh'`): it
generates poor masks. A hand-made mask, or a mask derived from a previous image
outside CASA's auto-masking, is the alternative.

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

Primary beam FWHM:
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

**A-configuration: check that the image fits before calling tclean.** The
resolution sets a small cell, so a mosaic footprint becomes a very large image.
CASA needs roughly

```
memory_bytes ≈ 5.5 × nterms × nscales × (imsize_x × imsize_y × 4 bytes)
```

where 4 bytes is one float pixel, `nterms` is 1 unless `mtmfs`, and `nscales`
is 1 for hogbom. Compare this with the machine's free memory (`free -b` via
Bash). If it does not fit, do not start tclean: report the estimate and the
memory, and image fewer pointings, a smaller region, or on a larger machine.
This is a T3 or user decision, not a default.

Match the telescope against the **canonical** name returned by `ms_inspect`
(`telescope` field) — `VLA`, not the raw `MS::OBSERVATION::TELESCOPE_NAME`
string, which may be `EVLA` or `JVLA`. Name normalization happens in the
telescope profile (`src/ms_inspect/data/telescopes/*.yaml`, `aliases`).

**Telescope without a CASA primary-beam model:** use `'wproject'` if W-terms
are required, else `'standard'`, and warn the user that the pointings will not
be primary-beam corrected as a mosaic.

---

## Step 7 — Estimate cleaning threshold

Thermal image noise, VLA OSS "Sensitivity", equation 1 (natural weighting):
```
sigma_natural = SEFD / (eta_c * sqrt(n_pol * {N_ANT} * ({N_ANT} - 1) * t_int * {BANDWIDTH_HZ}))
sigma_jy      = w * sigma_natural
threshold     = 3 * sigma_jy
```

| Term | Value |
|---|---|
| `SEFD` | the telescope profile's `sefd_jy` for the band (table below) |
| `eta_c` | correlator efficiency: 0.93 with 8-bit samplers; 0.78–0.83 with 3-bit (a further 10–15% loss). If the sampler is not known, use 0.93 and say so |
| `n_pol` | 2 for Stokes I, Q, U or V; 1 for a single hand (RR or LL) |
| `t_int` | on-source time in seconds. **For a mosaic, the time on one pointing**, not the total over all pointings: each pointing's noise follows its own time (overlaps are lower) |
| `w` | weighting: 1.0 natural; ≈ 1.2 for robust weighting (OSS), which the template below uses |

Two contributions are not in the equation. **Confusion** from sources within the
beam adds in quadrature: the OSS gives D-configuration robust-weighted values
(P 5330, L 74, S 12, C 2 µJy/beam; negligible at X and above), roughly 10×
lower in C-configuration. **Galactic synchrotron** at P-band raises the SEFD by
2–3× in the plane and ≥ 5× near the Galactic centre.

SEFD reference values (Jy). VLA values from the OSS "Sensitivity" Table 3.2.1.
Band codes are **per telescope** — uGMRT numbers its own bands and they do not
map onto VLA band letters:

| Telescope | Band | SEFD (Jy) |
|---|---|---|
| VLA | P | 2790 |
| VLA | L | 420 |
| VLA | S | 370 |
| VLA | C | 310 |
| VLA | X | 250 |
| VLA | Ku | 320 |
| VLA | K | 500 |
| VLA | Ka | 600 |
| VLA | Q | 1300 |
| MeerKAT | L | 400 |
| MeerKAT | S | 380 |
| uGMRT | 2 (125–250 MHz) | 1500 |
| uGMRT | 3 (250–500 MHz) | 350 |
| uGMRT | 4 (550–850 MHz) | 285 |
| uGMRT | 5 (1000–1460 MHz) | 300 |

> **Authoritative source:** `src/ms_inspect/data/telescopes/<telescope>.yaml`,
> key `sefd_jy`. This table is a cross-telescope comparison view only. Read the
> profile for the value you actually put into the calculation above, and use its
> band code — bands absent from `sefd_jy` yield SEFD UNAVAILABLE by design, which
> you must report rather than substitute a guess.

Express `threshold` in mJy, e.g. `'0.5mJy'`. This is a starting estimate —
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
    savemodel    = 'modelcolumn',
    pblimit      = -0.1,           # Step 9 reads pb_level = abs(pblimit)
    workdir      = {WORKDIR},
    execute      = False,
)
```

`savemodel='modelcolumn'`: writes MODEL_DATA into the MS, required for self-cal (Phase 4).

Generate the script first (`execute=False`), review it, then run it as a
background job. Wait for completion however long it takes — tclean on a
real mosaic can run for hours.

---

## Step 9 — Quality assessment

Call `ms_image_stats` on the pbcor image:

```
ms_image_stats(
    image_path  = {WORKDIR}/{imagename}.image.pbcor,
    psf_path    = {WORKDIR}/{imagename}.psf,
    pb_level    = 0.1,                                  # abs(pblimit) of the tclean call
    png_path    = {WORKDIR}/{imagename}.png,
)
```

**Which RMS.** Compare `residual_rms_jy` with the radiometer estimate, not
`rms_jy`. `residual_rms_jy` is measured on the `.residual` where the `.pb` is at
or above `pb_level`; `rms_region` gives the paths and pixel count, and you
quote them with the number. `rms_jy` is the whole `.pbcor` plane: towards the
PB edge the noise is divided by a small gain, so it reads high, and on an
extended source it also includes source pixels. Always write this in the
report: "The .pbcor image noise rises toward the PB edge; the RMS quoted is
from the .residual inside PB >= {pb_level}."

**Look at the image.** Open `png_path` with Read when the clean did not
converge (stopcode not 2 or 8), when `residual_rms_jy` is more than 2 times the
radiometer estimate, or before you quote a flux. The white line is
PB = `pb_level`; judge only what is inside it.

Quality gates:

| Metric | Expected | Action if not met |
|---|---|---|
| `residual_rms_jy` | Within 2× of radiometer estimate | > 2×: residual RFI, calibration artefacts or a dynamic-range limit; look at the PNG, then check CORRECTED |
| `residual_dynamic_range` | > 100 for calibrators; > 20 for typical targets | < 20: imaging artefacts dominant; check PSF sidelobes |
| `beam_major_arcsec` | Close to `lambda/max_baseline_m * (180*3600/pi)` | Large deviation: uv coverage gaps or flagging holes |
| `peak_jy` | Positive, above threshold | Negative peak > rms: clean diverged; reduce gain or niter |

If `residual_rms_jy` is > 3× the radiometer estimate, escalate rather than
re-imaging: the problem is likely in the calibration or unflagged target RFI,
not in the imaging parameters.

### Reading `detection`

`ms_image_stats` returns a **descriptive** `detection` label over
`dynamic_range` (peak-to-noise), plus `detection_thresholds` carrying the two
constants behind it. It does not decide whether you may proceed — you do. Treat
it as a continuum, and say which level you are at when you report a flux:

| `detection` | `dynamic_range` | What it means, and what you may claim |
|---|---|---|
| `undetected` | ≤ 5 | The peak is consistent with a residual or sidelobe spike. Do not report a flux. Cross-check Step 0.5: at this level the usual cause is calibration decorrelation, not imaging parameters. |
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
(or per N-MHz chunk) gives enough λ² sampling for RM synthesis without the cost
and per-plane noise of full spectral resolution. This mirrors the chunking
`ms_setjy_polcal` already uses to fit the polarization model.

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
