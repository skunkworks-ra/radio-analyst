# 12 — Single-Pass Phase Self-Calibration

## Purpose

Run one round of phase-only self-calibration after the first-pass image
(Skill 11). Compare dynamic range and RMS before and after. Do not iterate
automatically.

**Who decides.** Whether to selfcal (Step 0) and whether to go further (Step 5)
is a judgment call: in an interactive session, the user's; hands-off, the
strongest model in the run. It is never a default the run takes because no one
decided. Either way, report the decision and the numbers it rests on.

Self-calibration amplitude+phase, multi-round loops, and convergence
management are Phase 5 and are not in scope here.

---

## Prerequisites

Before starting, confirm all of the following:

| Requirement | How to verify |
|---|---|
| `CORRECTED_DATA` populated | `ms_workflow_status` returns `selfcal_or_done` |
| `MODEL_DATA` populated | `ms_tclean` was run with `savemodel='modelcolumn'` |
| First-pass image exists on disk | `{WORKDIR}/{imagename}.image.pbcor` present |
| First-pass `ms_image_stats` result available | Has `rms_jy`, `dynamic_range`, `peak_jy` values |

If `MODEL_DATA` is not populated, re-run `ms_tclean` with `savemodel='modelcolumn'`
before proceeding. Self-calibration solves phases against MODEL_DATA — an empty
or missing column produces garbage solutions.

---

## Step 0 — Assess whether selfcal is warranted

Self-calibration is most effective when the residuals are dominated by
antenna-based phase errors rather than noise or calibration artefacts.

From the first-pass `ms_image_stats` result:

| Dynamic range (peak / rms) | Assessment | Action |
|---|---|---|
| < 30 | Calibration quality is the limit — selfcal unlikely to help | Note and skip; flag for re-calibration review |
| 30–100 | Phase errors likely significant — selfcal appropriate | Proceed |
| 100–500 | Moderate phase errors — selfcal will likely improve image | Proceed |
| > 500 | Good first-pass — selfcal may still yield marginal improvement | Proceed; modest gains expected |

Also call `ms_residual_stats` on the target to confirm the residuals are not
dominated by RFI or bad baselines. It takes one integer FIELD_ID: for a mosaic,
run it once per pointing (IDs from `ms_field_list` on this MS) and judge by the
worst:

```python
ms_residual_stats(
    ms_path = {VIS},
    field_id = {TARGET_FIELD_ID},
)
```

If `p95_amp / median_amp > 10` in any SPW, the residuals are RFI-dominated —
selfcal will not help and may make things worse. Flag for additional rflag
before selfcal.

---

## Step 1 — Phase-only gain solve against MODEL_DATA

```python
ms_gaincal(
    ms_path   = {VIS},
    caltable  = f"{WORKDIR}/pcal1.g",
    field     = {TARGET_FIELD},
    spw       = {ALL_SPW},
    solint    = 'inf',
    refant    = {REFANT},
    gaintype  = 'G',
    calmode   = 'p',
    minsnr    = 3.0,
    gaintable = {PRIORCALS} + [delay.K, bandpass.B, gain.fluxscaled],
    gainfield = [''] * len(PRIORCALS) + ['', '', {PHASE_FIELD}],
    interp    = [''] * len(PRIORCALS) + ['nearest,nearestflag', 'nearest', 'linear'],
    workdir   = {WORKDIR},
    execute   = False,
)
```

**The gaintable is the full target stack from 07 Step 7c, not the priorcals
alone.** gaincal solves against DATA with `gaintable` applied on the fly, never
against CORRECTED. With only the priorcals, `pcal1.g` absorbs the delay,
bandpass and gain corrections as well as the residual phase errors: the
solutions show tens to hundreds of degrees, and the flux scale is lost. If the
polarisation tables were applied (09 Step 5), append `kcross.K`, `dterms.D` and
`polangle.X` with `gainfield=''` and `interp='nearest'`.

`gainfield` takes `gain.fluxscaled` from `{PHASE_FIELD}` only, exactly as the
apply in Step 2 does. Without it the solve draws rows from every field,
interpolated in time, and a target scan next to a flux-calibrator scan picks up
that field's solutions.

Parameter choices:

| Parameter | Value | Reason |
|---|---|---|
| `calmode='p'` | Phase only | Do not solve amplitude in first pass — risk of absorbing source structure |
| `solint='inf'` | Time-averaged per scan | Conservative; use `'int'` only if source is bright (> 1 Jy) and ionosphere is active |
| `minsnr=3.0` | Minimum SNR gate | Prevents flagging all solutions on faint targets; lower to 2.0 if many solutions are flagged |
| `gaintype='G'` | Per-polarisation | Standard; use `'T'` only if polarisation independent solutions are acceptable (low SNR) |

Generate the script (`execute=False`), then run it via `run-step.sh` (SKILL.md "Running generated scripts").

After the script completes, call `ms_calsol_stats` to inspect solution quality:

```python
ms_calsol_stats(
    caltable_path = f"{WORKDIR}/pcal1.g",
    verbosity     = 'full',     # phase_mean_deg is not in compact output
)
```

Check:

| Output | What to look for | Action if bad |
|---|---|---|
| `flagged_frac` / `overall_flagged_frac` | > 0.30 flagged -> solution failed for that antenna | Lower `minsnr` to 2.0 and re-solve |
| `phase_mean_deg` / `phase_rms_deg` per antenna | Large mean offset or > 30° scatter over time → large phase errors being corrected (this is fine) | Just note — this is what selfcal is for |
| `abs(phase_mean_deg)` < 1° **and** `phase_rms_deg` < 1° on every antenna | Solutions are near-zero — no phase error to correct | Selfcal will not help; stop here |

Also plot with `ms_plot_caltable_library`:

```python
ms_plot_caltable_library(
    caltable_paths = [f"{WORKDIR}/pcal1.g"],
    output_dir     = {WORKDIR},
)
```

Look for smooth phase vs time per antenna. Jumps or discontinuities between
scans indicate the solution is fitting noise — consider longer `solint`.

---

## Step 2 — Apply phase corrections

```python
ms_applycal(
    ms_path    = {VIS},
    field      = {TARGET_FIELD},
    # When 09 Step 5 applied the polarisation tables, insert kcross.K,
    # dterms.D (and polangle.X) before pcal1.g, gainfield '' and interp 'nearest'.
    gaintable  = {PRIORCALS} + [delay.K, bandpass.B, gain.fluxscaled, f"{WORKDIR}/pcal1.g"],
    gainfield  = [''] * len(PRIORCALS) + ['', '', {PHASE_FIELD}, ''],
    interp     = [''] * len(PRIORCALS) + ['nearest,nearestflag', 'nearest', 'linear', 'nearest'],
    calwt      = False,
    applymode  = 'calflag',
    workdir    = {WORKDIR},
    execute    = False,
)
```

Generate (`execute=False`) and run via `run-step.sh`. This overwrites CORRECTED_DATA.

**applycal writes CORRECTED from DATA, so the stack must be complete.** Pass the
same tables as the first-pass apply (07 Step 7c, plus the polarisation tables if
09 Step 5 applied them), then `pcal1.g` last. A stack of the priorcals and
`pcal1.g` alone discards the delay, bandpass and flux-scaled gains.

`pcal1.g` takes `gainfield=''` and `interp='nearest'`: with `solint='inf'` each
target scan has its own solution, and `nearest` picks it. `linear` would
interpolate between scans of different pointings in a mosaic.

---

## Step 3 — Re-image with corrected data

Run `ms_tclean` with identical parameters to the first-pass image (same cell,
imsize, threshold, niter, gridder, weighting). Use a different `imagename`
to preserve the first-pass image for comparison:

```python
ms_tclean(
    ms_path   = {VIS},
    imagename = f"{WORKDIR}/{imagename}_sc1",
    ...            # all other parameters identical to first-pass
    savemodel = 'modelcolumn',
    execute   = False,
)
```

Generate (`execute=False`) and run via `run-step.sh` (SKILL.md "Running generated scripts").

---

## Step 4 — Compare before and after

Call `ms_image_stats` on both the first-pass and selfcal images:

```python
# First-pass (already have this result — no need to re-run if values are recorded)

# Selfcal image
ms_image_stats(
    image_path = f"{WORKDIR}/{imagename}_sc1.image.pbcor",
    psf_path   = f"{WORKDIR}/{imagename}_sc1.psf",
)
```

Report the comparison:

| Metric | First-pass | After selfcal | Change |
|---|---|---|---|
| `rms_jy` | ... | ... | ... |
| `dynamic_range` | ... | ... | ... |
| `peak_jy` | ... | ... | ... |

Interpret the improvement:

| Dynamic range improvement | Assessment |
|---|---|
| < 10% | Negligible — selfcal did not help; no further selfcal recommended |
| 10–50% | Moderate — single-pass selfcal was effective; recommend one more round to user |
| > 50% | Significant — phase errors were dominant; strongly recommend full selfcal loop to user |
| Dynamic range decreased | Selfcal diverged — applycal worsened the image; investigate `pcal1.g` solutions |

---

## Step 5 — Report and recommendation

Summarise the selfcal assessment to the user:

1. First-pass image quality (DR, RMS, peak)
2. Phase solution quality (`phase_rms_deg`, flagged fraction, plot observations)
3. Post-selfcal image quality
4. Whether improvement was significant

**If improvement ≥ 10%:** state clearly that additional selfcal rounds are
likely to yield further improvement, and recommend running a full selfcal loop
with convergence management (not implemented yet — flag as a manual next step).

**If improvement < 10%:** state that the first-pass calibration quality is
the limiting factor, not antenna-based phase errors. Identify the most likely
alternative (remaining RFI, calibration transfer error, source structure).

**Stop here.** Do not iterate automatically. In an interactive session the user
decides whether to proceed; hands-off, record the recommendation in the report
and end the run.
