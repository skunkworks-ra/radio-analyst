# 09 — Polarisation Calibration Execution

## Purpose

This document guides decisions during polarisation calibration steps that follow
the standard gain/bandpass/fluxscale sequence. These steps are required when the
science target needs polarimetric imaging (Stokes Q, U, V).

Prerequisites:
- `delay.K`, `bandpass.B`, `gain.G` tables must already exist in the workdir
- The polarisation angle calibrator model must be set via `ms_setjy_polcal`
- `ms_pol_cal_conditions` should be run to identify the available calibrators
  and the appropriate D-term strategy

---

## Reading the conditions — before proceeding

`ms_pol_cal_conditions` measures; it returns no verdict and no blocker. It gives
you `pol_angle_calibrator`, `leakage_calibrator` (with
`effective_role_at_band`, `pa_spread_deg`, `n_calibrator_scans`),
`leakage_cal_candidates` (every field ranked by PA spread), and
`recommended_df_poltype` with its `recommended_df_poltype_basis`. You decide
what to run and what to claim from it.

Xf and Df are **independent** capabilities. Decide each separately, and never
infer either from PA coverage.

### Xf (absolute position angle) — do it whenever a pol standard is present

Xf solves the R–L phase against the **known EVPA** of a Category A pol standard
(3C286 / 3C138 / 3C48) whose model was set by `ms_setjy_polcal`. It needs only
that known model. **Parallactic-angle coverage is irrelevant to Xf** — never gate
Xf on PA spread. If `pol_angle_calibrator.available` is true and its `category`
is `A`, run Step 4.

If no angle standard was observed, Xf is not solvable at all: run the D-term
steps and state in the report that absolute EVPA is uncalibrated, so the dataset
cannot support absolute polarisation-angle claims. Fractional polarisation and
EVPA *differences* across the field remain usable.

If the angle calibrator carries a `variability_warning`, proceed and annotate:
quote the note (source and dates) alongside any EVPA result. If the observation
predates the flare period by more than about 6 months the degradation is
usually negligible — say which case applies rather than reporting it as a
qualifier with no date.

### Df (leakage) — poltype follows source knowledge, not coverage

Three strategies (NRAO VLA pol guide). `recommended_df_poltype` is derived from
the leakage source's polarisation knowledge alone; `recommended_df_poltype_basis`
states which case fired, so you can check it:

| Source type | poltype | Notes |
|-------------|---------|-------|
| Zero-pol **primary leakage cal** (Cat C: 3C84, 3C147, OQ208, J0713+4349, J2355+4950) at a band where its frac pol < 1% | `Df` | Q,U known to be ~0; a single scan suffices. Cleanest D-term solve |
| **Known-pol source** (Cat A/B, incl. the angle cal via its known model) | `Df` | Q,U come from the model; ≥2 scans |
| **Unknown-pol source** (e.g. the phase cal) | `Df+QU` | Q,U solved jointly with the D-terms; this is the only path where PA coverage matters |

A source's role is frequency-dependent — 3C147 and 3C84 are low-pol below about
10 GHz and polarized above it. Use `effective_role_at_band`, not a remembered
role.

### PA coverage for a `Df+QU` solve — a continuum, not a threshold

Applies **only** when `recommended_df_poltype` is `Df+QU`. Read `pa_spread_deg`
for the source you intend to use and state the consequence in the report:

| Δ(PA) | What a Df+QU solve gives you | What to say about the result |
|-------|------------------------------|------------------------------|
| ≥ 60° | Well conditioned; D-terms and source Q,U cleanly separated | NRAO's recommended coverage. No coverage caveat needed |
| 30–60° | Usable; the D-term / QU degeneracy is partly broken | Report the coverage. Limit fractional-polarisation claims to roughly the percent level |
| 10–30° | Marginal; D-terms and source QU are substantially covariant | Proceed only if the science tolerates it. Quote the coverage next to every polarisation number, and treat low-level structure as suspect |
| < 10° | Effectively degenerate; the solve will converge on something without constraining it | A `Df+QU` result here is not evidence. Prefer a known-pol or zero-pol source from `leakage_cal_candidates`, or drop the leakage step and report Stokes I only |

Below 30° the honest report is "solved at N degrees of coverage, fractional
polarisation claims limited to X" — not a refusal to compute, and not a
polarisation number quoted without its coverage.

**Choosing a different leakage source.** `leakage_cal_candidates` ranks every
field by PA spread and marks which one the tool identified. If the identified
source has thin coverage and a better-covered field exists, switching to it is
*your* decision and changes the strategy: an uncatalogued field
(`effective_role_at_band: 'unknown'`) means `Df+QU`, not `Df`, whatever the
identified source implied. State the swap and the reason in the report.

---

## Tool API reference

The following table maps each polcal step to the exact MCP tool and key parameters:

| Step | Tool | Key parameters | Note |
|------|------|----------------|------|
| Angle model setup | `ms_setjy_polcal` | `field`, `polindex_deg=3`, `polangle_deg=4` (`reffreq_ghz` defaults to the band centre) | Run once per angle cal; populates MODEL for Df/Xf solves |
| Cross-hand delay | `ms_gaincal` | `gaintype='KCROSS'`, `combine='scan'` (omit `smodel` when `angle_cal` has physical polarized `MODEL_DATA` from `ms_setjy_polcal`) | Must run before D-terms; per-SPW by default, `'scan,spw'` is a deliberate multiband choice; pass `smodel` only on an unmodeled source away from the feed null (Step 2) |
| D-term leakage | `ms_polcal` | `poltype='Df'` or `'Df+QU'`, `solint='inf'`, `combine='scan'` | `Df` for known-pol/zero-pol sources (no PA needed); `Df+QU` only for unknown-pol sources (PA coverage as a continuum, above) |
| Position angle | `ms_polcal` | `poltype='Xf'`, `solint='inf'`, `combine='scan'` | Run whenever a Cat A pol standard is present (`pol_angle_calibrator.category == 'A'`); independent of PA coverage; requires D-terms in gaintable |
| Apply all tables | `ms_applycal` | One call per field type, as 07 Step 7: priorcals → K → B → `gain.fluxscaled` → Kcross → D → X | Table order is required by RIME; `parang=True` mandatory; see Step 5 |

---

## Step 1 — Set the polarisation calibrator model

**This step runs in precal (10 Step 4), before the initial bandpass**, whenever
polarisation is in scope (10 Step 4 says when): the model is set once, right, up front. On
reaching polcal, confirm it with `ms_verify_model(polcal_fields=<angle cal>)`
and do not re-run it. The rest of this step describes what that call does.

`ms_setjy_polcal` populates the MODEL column for the angle calibrator. The generated script is a self-contained
**probe → fit → apply**:

1. **Probe** — runs `setjy(standard='Perley-Butler 2017', usescratch=False)` once
   per SPW (wide SPWs are equipartitioned into chunks ≥ `min_chunk_mhz`, default
   32 MHz) and harvests the returned model Stokes I per frequency.
2. **Fit** — fits `flux@reffreq` + `spix` from those `(freq, I)` points (degree
   adapts to the number of samples), and fits `polindex`/`polangle` from the
   pol-property catalogue (default epoch `2019`).
3. **Apply** — `setjy(standard='manual', fluxdensity=[I,0,0,0], spix, reffreq,
   polindex, polangle, scalebychan=True, usescratch=True)`.

```python
# Generated by ms_setjy_polcal — run this first. The script probes
# Perley-Butler Stokes I at run time; the manual setjy it ends with looks like:
setjy(
    vis='{VIS}',
    field='3C286',
    standard='manual',
    fluxdensity=[flux_at_ref, 0, 0, 0],  # probed from Perley-Butler 2017
    spix=spix,                            # fit from the probe (log-polynomial)
    reffreq='1.5GHz',
    polindex=[0.099, ...],                # ascending [c0, c1, ...], fraction
    polangle=[0.575, ...],                # ascending [c0, c1, ...], radians
    scalebychan=True,
    usescratch=True,
)
```

**Do not hand-write these coefficients.** Always use the script generated by
`ms_setjy_polcal`. Stokes I comes from CASA's own Perley-Butler 2017 standard
(the pol-property catalogue carries fractional polarisation and angle only — no
Stokes I), and the pol terms come from the catalogue with the correct
ascending-order convention and RM-wrapped nodes excluded. This is why the tool
must run against the MS, not a static table: it needs CASA to evaluate
Perley-Butler over the actual SPWs.

**`usescratch=True` is mandatory here and forces a consistency requirement on
the whole MS.** `ms_setjy_polcal` always uses `usescratch=True` because virtual
models (`usescratch=False`) fail on source models with non-zero rotation measure
— a known CASA bug. But `usescratch` cannot be mixed within one MS: the first
`usescratch=True` call creates the physical `MODEL_DATA` column, and every
downstream task then reads `MODEL_DATA` for *all* fields. Any field whose model
was written virtually (`usescratch=False`) is left at the default `MODEL_DATA=1
Jy`, which silently corrupts the flux scale (fluxscale comes out
order-of-magnitude low).

**Therefore, when polcal is in scope, the flux/bandpass cals must be set with
`ms_setjy(usescratch=True)` too** — run `ms_setjy` with `usescratch=True`
**strictly before** `ms_setjy_polcal` so the entire MS uses one consistent
physical `MODEL_DATA`. See skill 07 Step 6 (fluxscale) for the sanity check.

**Ordering is not commutative — never run the two in parallel.** `MODEL_DATA` is
last-writer-wins per (field, spw). The pol-angle calibrator (3C286 / 3C138 /
3C48) is *also* a standard flux/BP calibrator, so `ms_setjy`'s automatic field
selection includes it. If a plain `ms_setjy(usescratch=True)` pass lands on that
field **after** `ms_setjy_polcal`, it overwrites the polarized model with a
Stokes-I-only one — silently. This is the G55 failure: a parallel `ms_setjy`
re-set Stokes-I models on both 3C286 entries after the polarized model, wiping it.

**When the pol-angle cal overlaps a flux/BP cal (the usual case), prefer the full
Stokes model for that field and skip the Stokes-I write on it:** pass the
overlapping field to `ms_setjy(exclude_fields=...)` so the plain pass omits it,
and let `ms_setjy_polcal` (also `usescratch=True`) be the *only* writer of its
model. The excluded field still gets a consistent physical `MODEL_DATA` from
`ms_setjy_polcal`, so the whole-MS `usescratch` consistency (above) is preserved.

**Verify before moving on.** After the setjy steps, run
`ms_verify_model(field='<all cals>', polcal_fields='<pol-angle cal>')`. It flags
any field pinned at the `MODEL=1 Jy` default (unwritten → flux-scale trap) and —
for the `polcal_fields` — a missing polarization signature (zero cross-hands),
which is exactly a Stokes-I clobber of the polarized model.

> **Before editing or debugging a setjy model, read `09b-polcal-reference.md`.**
> Stokes I (`spix`), `polindex` and `polangle` use *three different* polynomial
> forms and variables, and all three are **per-band** local expansions about
> `reffreq` — not global wideband fits. Conflating these is the most common
> setjy-manual error.

---

## Step 2 — Cross-hand delay (Kcross)

Cross-hand delay is a single delay offset between the R and L (or X and Y) feeds.
It must be solved before D-terms because it otherwise aliases into the D-term solution.

```python
gaincal(
    vis='{VIS}',
    caltable='kcross.K',
    field='{ANGLE_CAL_FIELD}',
    gaintype='KCROSS',
    solint='inf',
    combine='scan',           # per-SPW (default); add ',spw' only for multiband
    refant='{REFANT}',
    # Omit smodel when {ANGLE_CAL_FIELD} already has a physical polarized MODEL_DATA from ms_setjy_polcal
    # (lets CASA use true (I, Q, U) with parang=True, avoiding the linear-feed XY -> 0 null at psi = +-45 deg).
    # Pass smodel only when solving KCROSS on an unmodeled source away from the feed null.
    gaintable=['{PRIORCALS}', 'delay.K', 'bandpass.B', 'gain.G'],
    gainfield=[''] * len(PRIORCALS) + ['', '', '{ANGLE_CAL_FIELD}'],  # ALWAYS select solve_field in gain.G (never mix another cal!)
    parang=True,
)
```

**`smodel` rule (avoiding the linear-feed null):** When `{ANGLE_CAL_FIELD}`
already has a physical polarized `MODEL_DATA` written by `ms_setjy_polcal` (Step
1), **omit `smodel`** so CASA solves against the true `(I, Q, U)` sky model with
`parang=True`. Hardcoding `smodel=[1, 0, 1, 0]` (`Q=0, U=1`) creates a
zero-signal trap on linear-feed arrays (`XX/XY/YX/YY`) near parallactic angle
`psi = +-45 deg` where `XY ~ -Q sin(2*psi) + U cos(2*psi) -> 0`. Pass `smodel`
only when solving `KCROSS` on an unmodeled source away from the feed null.

**Explicit `gainfield` on `gain.G` (MANDATORY in Steps 2, 3, and 4):** Always
pass `gainfield=[..., <solve_field>]` in the `gain.G` slot (e.g.
`{ANGLE_CAL_FIELD}` for `kcross.K` and `polangle.X`, `{LEAKAGE_CAL_FIELD}` for
`dterms.D`). Leaving `gainfield=''` on multi-calibrator `gain.G` causes CASA to
linearly interpolate another calibrator's gain (such as the unscaled phase
calibrator) across flagged scans/SPWs!

**Per-SPW vs multiband -- a deliberate choice, not a default.** Two valid options:

- **Per-SPW** (`combine='scan'`): one Kcross solution per SPW. No spwmap needed at
  apply. Simplest; use unless you have a specific reason to combine.
- **Multiband** (`combine='scan,spw'`): one solution across all SPWs for higher SNR,
  treating the cross-hand delay as a single instrumental term. **VLA-specific** (it
  relies on the VLA's discrete-SPW structure; it does not transfer to MeerKAT/uGMRT).
  The combined table holds a single SPW, so **every downstream use must pass
  `spwmap=[[0,0,...0]]`** (length = n_spw) -- in the `ms_polcal` Df/Xf solves that take
  it as a prior, and in the final `ms_applycal`. Omitting spwmap silently leaves
  SPWs 1..N uncorrected. The `spwmap` argument on `ms_gaincal`/`ms_polcal`/
  `ms_applycal` exists for exactly this; it defaults to identity (per-SPW behaviour).

Do not assume multiband; decide per dataset.

**Cross-SPW coherence & post-solve phase-turn jump check (`ms_calsol_stats`):**
- **Cross-SPW coherence gate (array/band-general):** Static receiver and cable
  cross-hand delay offsets calibrate out cleanly on any array and band regardless
  of absolute magnitude (whether `~1 ns` or `~20 ns`). Gate `kcross.K` health on
  **cross-SPW coherence** using signed per-SPW `delay_median_ns` from
  `ms_calsol_stats(caltable_path='{WORKDIR}/kcross.K')`: clean SPWs should have
  `MAD_spw_ns * 1e-9 * spw_bw_hz << 0.1` cycles (equivalently
  `MAD_spw_ns * spw_bw_ghz << 0.1` cycles) across the SPW bandwidth. Large
  array-wide incoherence across SPWs indicates low cross-hand SNR, feed-null /
  model mismatch, or an upstream calibration error.
- **Cross-SPW delay jump check (MANDATORY on both `delay.K` and `kcross.K`):**
  Compute dimensionless phase turns across each SPW from signed per-SPW
  `delay_median_ns` (which catches sign flips such as `-8.5 ns -> +8.5 ns` that
  unsigned `delay_rms_ns` hides). Flag a single-SPW outlier whenever
  `|delay_ns - median_delay_ns| * 1e-9 * spw_bw_hz > 0.25` cycles (`90 deg`
  across the SPW; equivalently `|delay_ns - median_delay_ns| * spw_bw_ghz > 0.25`)
  **AND** `|delay_ns - median_delay_ns| > 5 * MAD_spw_ns` -- this indicates
  narrowband RFI hijacked the FFT delay peak on that SPW (even at low visibility
  flag fraction). Flag the bad SPW's solutions immediately via
  `ms_flag_caltable(caltable_path='{WORKDIR}/kcross.K', mode='manual',
  spw='<bad_spw>', reason='cross-SPW kcross phase-turn outlier (>0.25 cycles and >5*MAD)')`
  (or exclude that SPW from downstream solves and imaging) BEFORE running Step 3.

---

## Step 3 — D-term leakage calibration

D-terms quantify leakage between the two polarisation feeds per antenna per frequency.

### Df vs Df+QU — decision table

Pick the strategy by what is **known** about the source, not by PA coverage. PA
coverage is required **only** for the unknown-pol (`Df+QU`) path. Use the tool's
`recommended_df_poltype` directly.

| Situation | Use | PA coverage |
|---|---|---|
| Zero-pol primary leakage cal (Cat C: 3C84, 3C147, OQ208, J0713+4349, J2355+4950) | `poltype='Df'` | not needed (single scan) |
| Angle cal with known model — 3C286 / 3C138 / 3C48 (model from `fit_from_catalogue`) | `poltype='Df'` | not needed (≥2 scans) |
| Any catalogue source with known Q,U | `poltype='Df'` | not needed |
| Source of **unknown** Q,U (e.g. the phase cal) | `poltype='Df+QU'` | **required**, as a continuum ("PA coverage for a Df+QU solve" above); ≥3 scans |
| Unknown-pol source with thin coverage | prefer a known-pol or zero-pol source from `leakage_cal_candidates` with `Df`; if there is none, solve and limit the claims as the coverage table says | — |

`poltype='Df'` solves for D-terms assuming the source Q,U are known from the
`setjy(standard='manual')` model (or that the source is unpolarised). This is the
default for the primary angle cal and for zero-pol leakage cals — **no parallactic
coverage is required**.

`poltype='Df+QU'` simultaneously solves for D-terms and the source Q,U, for a
source whose polarisation is unknown. This is the **only** path that needs PA
coverage (≥ threshold). The recovered Q and U provide a built-in sanity check:
- If the source is unpolarised: recovered Q/U ≈ noise per SPW — solution is valid
- If the source is polarised: Q/U show coherent frequency structure — the
  recovered values are the true source polarisation, inspectable per SPW

```python
polcal(
    vis='{VIS}',
    caltable='dterms.D',
    field='{LEAKAGE_CAL_FIELD}',
    poltype='Df',              # or 'Df+QU' -- see table above
    solint='inf',
    combine='scan',
    refant='{REFANT}',
    gaintable=['{PRIORCALS}', 'delay.K', 'bandpass.B', 'gain.G', 'kcross.K'],
    gainfield=[''] * len(PRIORCALS) + ['', '', '{LEAKAGE_CAL_FIELD}', ''],  # select solve_field in gain.G
    parang=True,
)
```

### D-term quality thresholds

| D-term amplitude | Assessment |
|---|---|
| < 5% | Good — typical for VLA |
| 5–10% | Marginal — check for antenna-specific outliers |
| 10–20% | Elevated — may indicate feed misalignment on specific antennas |
| > 20% | Flag the affected antenna; do not include in applycal |

A small number of antennas with D-terms slightly above 10% is acceptable if the
rest of the array is clean. An array-wide D-term above 10% is a systematic problem.

**Before applying `dterms.D`, flag its solutions** with `ms_flag_caltable`
(rflag, sigma=5.0) to remove RFI-contaminated outlier leakage solutions — see
"Caltable solution flagging" in 07-calibration-execution.md.

---

## Step 4 — Position angle calibration (Xf)

Xf calibrates the absolute orientation of the polarisation angle on the sky.
It uses a source with a well-known and stable EVPA.

**Always run this step when a Category A pol standard is present**
(`pol_angle_calibrator.available` and `category == 'A'`). Xf solves the R–L phase against that source's known EVPA model — it does
**not** require parallactic-angle coverage. Do not skip Xf for lack of PA spread.

**Preferred sources (VLA):**
- 3C286 — stable PA ~33° at all bands; preferred
- 3C138 — PA ~−14° at L-band; variable on years timescale, use with caution
- 3C48 at S-band — PA modelled from catalogue; use when 3C286/3C138 not observed

```python
polcal(
    vis='{VIS}',
    caltable='polangle.X',
    field='{ANGLE_CAL_FIELD}',
    poltype='Xf',
    solint='inf',
    combine='scan',
    refant='{REFANT}',
    gaintable=['{PRIORCALS}', 'delay.K', 'bandpass.B', 'gain.G', 'kcross.K', 'dterms.D'],
    gainfield=[''] * len(PRIORCALS) + ['', '', '{ANGLE_CAL_FIELD}', '', ''],  # select solve_field in gain.G
    parang=True,
)
```

**Expected residual:** PA residual from Xf should be < 5°. Residual > 10° indicates:
- Wrong polangle model in the setjy step (check polangle[0] in radians)
- Remaining ionospheric Faraday rotation (especially at L-band)
- Source variability (3C138 can vary by ~10° on year timescales)

---

## Step 5 — Apply polarisation calibration tables

`parang=True` is mandatory in applycal for polarimetric data. Without it, the
parallactic angle correction is not applied and the D-term corrections are wrong.

Apply per field type, exactly as 07 Step 7 does, with the three polarisation
tables appended. The gain table is **`gain.fluxscaled`**, not `gain.G`: `gain.G`
carries the phase calibrator's pre-fluxscale amplitudes, so applying it leaves
the target off the flux scale. The solves in Steps 2–4 may use `gain.G` as a
prior; the final apply may not.

```
POLTABLES = [kcross.K, dterms.D, polangle.X]
POLFIELD  = ['', '', '']
POLINTERP = ['nearest', 'nearest', 'nearest']   # one solution each (solint='inf', combine='scan')

# 5a -- EVERY calibrator (flux, phase, distinct pol-angle, distinct leakage):
# one call per calibrator field, ALWAYS using its OWN gainfield=<calibrator field>
# (NEVER transfer a phase cal's gain onto a distinct polarization-angle or leakage calibrator, and never leave gainfield='' on gain.fluxscaled!)
ms_applycal(
    ms_path    = {VIS},
    field      = <calibrator field>,
    gaintable  = {PRIORCALS} + [delay.K, bandpass.B, gain.fluxscaled] + POLTABLES,
    gainfield  = [''] * len(PRIORCALS) + ['', '', <calibrator field>] + POLFIELD,
    interp     = [''] * len(PRIORCALS) + ['nearest,nearestflag', 'nearest', 'nearest'] + POLINTERP,
    parang     = True,     # CRITICAL -- must be True for polarimetric data
    calwt      = False,
    applymode  = 'calflag',
    workdir    = {WORKDIR},
    execute    = False,
)

# 5b — science target: the phase calibrator's gain rows, interpolated in time
ms_applycal(
    ms_path    = {FULL_MS},
    field      = {TARGET_FIELD},
    gaintable  = {PRIORCALS} + [delay.K, bandpass.B, gain.fluxscaled] + POLTABLES,
    gainfield  = [''] * len(PRIORCALS) + ['', '', {PHASE_FIELD}] + POLFIELD,
    interp     = [''] * len(PRIORCALS) + ['nearest,nearestflag', 'nearest', 'linear'] + POLINTERP,
    parang     = True,
    calwt      = False,
    applymode  = 'calflag',
    workdir    = {WORKDIR},
    execute    = False,
)
```

If Kcross was solved multiband (`combine='scan,spw'`, Step 2), pass `spwmap`
with `[0]*n_spw` in the `kcross.K` slot and identity elsewhere.

**Table order matters:** apply in the order listed. Applying Kcross before D-terms
and D-terms before Xf is required by the RIME (Radio Interferometer Measurement Equation).

---

## Calibration table naming convention (polcal tables)

| Table | Name pattern |
|---|---|
| Cross-hand delay | `kcross.K` |
| D-terms (leakage) | `dterms.D` |
| Position angle | `polangle.X` |

These are written alongside `delay.K`, `bandpass.B`, `gain.G` in `{WORKDIR}`.

---

## Placeholder reference

| Placeholder | Source |
|---|---|
| `{VIS}` | `{WORKDIR}/calibrators.ms` — every solve, and the calibrator applies (5a) |
| `{FULL_MS}` | the MS the run was given — the target apply (5b) |
| `{WORKDIR}` | the run's workdir |
| `{ANGLE_CAL_FIELD}` | `ms_pol_cal_conditions` → `pol_angle_calibrator.field_name` |
| `{LEAKAGE_CAL_FIELD}` | `ms_pol_cal_conditions` → `leakage_calibrator.source`, or a field you chose from `leakage_cal_candidates` (often the same as the angle cal) |
| `{REFANT}` | `ms_refant` — same reference antenna used throughout |
| `{PRIORCALS}` | from `ms_verify_priorcals.priorcals_list` |
| `{ALL_FIELDS}` | `ms_field_list` → all field IDs, comma-separated |

---

## Decision summary

| Check | Good | Action if not good |
|---|---|---|
| PA coverage (Df+QU only) | ≥ 60° well conditioned | Thinner: prefer a known/zero-pol source with plain Df; otherwise solve and quote the coverage beside every polarisation number |
| Kcross cross-SPW coherence & jump | Cross-SPW coherence `MAD_spw_ns * 1e-9 * spw_bw_hz << 0.1` cycles (equivalently `MAD_spw_ns * spw_bw_ghz << 0.1`; static cable offsets calibrate out cleanly on any array/band); no SPW with `\|delay_ns - median_delay_ns\| * 1e-9 * spw_bw_hz > 0.25` cycles (`90 deg`; equivalently `* spw_bw_ghz > 0.25`) AND `\|delay_ns - median_delay_ns\| > 5 * MAD_spw_ns` (signed `delay_median_ns`) | Single-SPW outlier: flag bad SPW solutions via `ms_flag_caltable(mode='manual', spw=...)` or exclude SPW; array-wide incoherence: flag in summary and check upstream calibration / polarized model |
| D-term amplitude (median) | < 5% | Flag in summary; if < 10%, proceed with caution |
| D-term outlier antennas | 0–1 | Flag affected antennas; exclude from applycal if > 20% |
| Df+QU recovered Q/U | ≈ noise (unpolarised) or coherent (polarised) | Unexpected pattern → check PA coverage, Kcross solution |
| Xf PA residual | < 5° | Check polangle[0] vs catalogue; check for RM at L-band |
| parang=True in applycal | Always | Never omit — silent polarisation calibration failure |
