# 13 — Post-Calibration RFI Flagging & Channel Triage

## Purpose

After the final applycal, remove residual RFI from the phase calibrator and the
science target, and decide which **channels** are RFI-dominated (flag) versus
clean (keep). The decision is made per channel and per half-SpW, never per SpW
from a band-wide median: a SpW whose median looks bad can still hold clean
channels, and a SpW whose median looks fine can hide a few channels that stripe
the image.

---

## Core principles

**The tools measure. This skill decides the cut.** Every cutoff is read off this
dataset's own numbers; the values quoted below are starting points from one
L-band run, not constants.

**Amplitude clipping only against a known model.** A clip on |CORRECTED| of a
field with real sky clips the sky, and a threshold pooled across fields is set by
the brightest one. So:

| Field type | Has a model? | Allowed amplitude flagging |
|---|---|---|
| Primary flux / polarization calibrators (3C147, 3C138, 3C286, 3C48 …) | Yes — setjy / setjy_polcal | Residual clip (CORRECTED − MODEL) at N × thermal floor |
| Phase calibrator | No (MODEL is the 1 Jy default) | None. tfcrop / rflag only, if needed |
| Science target | No | None. Channel decisions from per-channel noise (Step 3); tfcrop / rflag only, if needed |

`ms_postcal_flag` enforces this: any `clip_sigma` / `clipmax` requires
`datacolumn='residual'` and a real MODEL on every selected field, and raises
otherwise.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Final applycal complete on all fields | Residuals and per-channel noise are measured on CORRECTED |
| setjy / setjy_polcal models on the primaries (`usescratch=True`) | The residual clip needs a physical MODEL_DATA column |
| `ms_verify_model` on the primaries | Confirms the models are not the 1 Jy default |

---

## Step 1 — Residual clip on the primary calibrators

Calibrate the primaries robustly before clipping their residuals: per-integration
**phase** plus per-scan **amplitude**, not per-integration amplitude+phase. Heavy
flags starve per-integration amplitude solves, the failed solves leave data badly
calibrated, its residual explodes, and the next clip flags it — a runaway
(observed on 24A-376: flagged fraction climbed every round while the residual
sigma in the dirty SpWs got *worse*).

```
ms_postcal_flag(
    ms_path    = calibrators.ms,
    field      = '<flux cal>,<pol angle cal>',     # primaries only
    datacolumn = 'residual',
    clip_sigma = N,                                 # 24A-376: 7
    floor_spw  = '<clean SpWs>',                    # thermal floor from known-clean windows
    keep_spw   = '<all candidate SpWs>',
)
```

Why `floor_spw`: the SpW's own robust sigma inflates once RFI occupies most of the
SpW (24A-376: 8–15 Jy in the worst SpWs against a 0.2 Jy floor), so a clip at
N × its own sigma removes nothing. The floor from the clean SpWs equals the
thermal noise there — check that it does (3C147: 0.19–0.21 Jy against ~0.19 Jy
predicted).

**Iterate from the base flags, not cumulatively.** Re-solve on the clipped flags,
restore the pre-clip flag version, clip again with the better solutions. Stop when
per-SpW flag fractions change by less than ~1 %. Between rounds, compare the
bandpass and gain flag fractions per SpW: a jump means solves are failing (often
a single refant flagged in those channels) — keep the previous round's flags and
pass a refant list.

**Read the result per channel**, from `flagdata(mode='summary', spwchan=True)` on
the primaries:

| Pattern across a SpW | Meaning |
|---|---|
| Spikes on a low floor | Channel-localized RFI. Those channels go. |
| Flat plateau (every channel ~ the same fraction) | Time / antenna structure (lost scans, failed solves). **Not** channel RFI — do not transfer it. |
| Every channel ≳ 90 % | SpW unusable on the primaries → no bandpass → drop it everywhere. |

---

## Step 2 — Re-solve and apply

Re-run the full solve chain on the cleaned primaries (skill 07 / 09), apply to all
fields. SpWs with no bandpass solutions are flagged by applycal on every field;
that is the only whole-SpW drop this skill makes.

---

## Step 3 — Channel triage on the target (no clip)

Measure per-channel robust noise on the target: sigma = 1.4826 × MAD of
Re(CORRECTED), parallel hands, pooled over target fields, against the median
sigma of the clean SpWs (the floor). The target's visibilities are noise-dominated
(its sources wash out per visibility), so this is a clean RFI gauge — check it:
the clean-SpW median |V| should be ≈ 1.18 × the thermal sigma.

| Cut | Action | 24A-376 starting value |
|---|---|---|
| Single channel above the spike cutoff | Flag that channel | sigma > 3 × floor |
| Half-SpW (channels 0–31 / 32–63) whose median sigma is above the broad cutoff | Flag that half | median > 1.5 × floor |
| Everything else | Keep | — |

Report what stays and what goes **before** applying: channels kept per SpW, and
the kept fraction of the currently unflagged data. On 24A-376 these cuts kept 75 %
of the unflagged target data (31 % of the full continuum band).

Caveat: elevated sigma across a whole SpW at a band edge can be a hotter receiver,
not RFI — MAD cannot tell them apart. Say so when cutting such a SpW.

Primary-calibrator channel flags may be transferred to the target only where they
are channel-structured (spikes in Step 1's table), never plateaus.

Re-run `statwt` after the channel cuts: it computes weights across each SpW, so
RFI channels had been down-weighting the clean data in the same rows.

---

## Step 4 — Image per SpW and look

Dirty (or lightly cleaned) mosaic per SpW in IQUV. Stokes I is limited by dirty-beam
sidelobes, so use **Q, U, V noise** as the RFI gauge (compare to the radiometer
estimate), and look for **straight stripes** — a few bad visibilities, each
imprinting a 2-D sine wave. Localize stripes from their orientation (uv
direction → baselines / times) and flag those visibilities; do not cut more
channels for them.

---

## Known limitations

- `ms_spw_amp_severity` pools all four correlations and has no time axis; on a
  bright calibrator its medians are meaningless. Use residual / per-channel MAD
  measurements as above until it is fixed.
- No tool yet returns per-channel target MAD; it is a short script over
  CORRECTED (parallel hands, sampled rows).
