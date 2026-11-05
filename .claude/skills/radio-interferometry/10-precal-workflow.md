# 10 — Pre-Calibration Workflow

Use `ms_workflow_status(ms_path, workdir)` to probe where you are before starting any step.

## Purpose

This document guides decisions across the full pre-calibration sequence:
online flag assessment → preflag → priorcals → flux model → refant selection
→ initial bandpass → initial RFI flagging on residuals.

The goal is a clean calibrator-only MS with CORRECTED populated and a first
pass of RFI removed, ready for the full calibration solve.

---

## Sequence overview

```
ms_sdm_summary(sdm_path)                 → what this dataset IS, before importing it
ms_import_asdm(execute=False, ...)       → generate import_asdm.py
  → run import_asdm.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report
ms_verify_import(ms_path, flag_file)     → confirm MS valid + .flagonline.txt present

ms_apply_preflag(execute=False, ...)     → generate preflag.py + preflag_cmds.txt
  → run preflag.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report

ms_generate_priorcals(execute=False)     → generate priorcals.py
  → run priorcals.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report
ms_verify_priorcals(workdir)             → confirm all required tables exist

ms_setjy(usescratch=True, execute=False, ...) → generate setjy.py
  → run setjy.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report

ms_refant(calibrators.ms, field=bp_field)    → refant ranked on BP cal (calibrate re-scores on all calibrators)
ms_initial_bandpass(execute=False, ...)   → generate initial_bandpass.py
  → run initial_bandpass.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report

ms_verify_model(field=bp_field)          → confirm a real model, not the 1 Jy default
ms_apply_initial_rflag(execute=False)    → generate initial_rflag.py
  → run initial_rflag.py in the foreground (no run_in_background, timeout=600000); on timeout STOP and report
```

---

## Step 0 — ASDM triage and ingestion

### 0a — Read the ASDM before converting it

Run `ms_sdm_summary(sdm_path)` first when starting from raw ASDM data. It reads
the ASDM XML directly — no casatools, no conversion — and tells you what the
dataset is before you spend the import on it: telescope and array configuration,
band, per-SPW continuum-vs-line classification, HI-21cm coverage, correlation
products (whether cross-hands are present at all, which decides whether polcal
is even on the table), sources with their intents, scan balance between
calibrators and target, and maximum target elevation.

Use it to answer, before importing:
- Is this the dataset you think it is (right target, right band, right config)?
- Are the cross-hand products there? Without RL/LR there is no polarisation path.
- Is there a flux/bandpass calibrator in the scan list at all?
- Does the target ever rise high enough to be worth calibrating?

A wrong answer here costs one command; the same wrong answer after import costs
the import plus everything built on it.

### 0b — Convert

Run `ms_import_asdm` next if starting from raw ASDM data.

**Always generate the script first (`execute=False`).** The script is short —
review it to confirm the output paths are correct before running.

Fixed parameters (not configurable):
- `ocorr_mode='co'` — cross-correlations only; auto-correlations are dropped
- `savecmds=True` — online flags written to `<ms_name>.flagonline.txt`
- `applyflags=False` — flags are NOT applied during import; `ms_apply_preflag` owns flagging

After running `import_asdm.py`, call `ms_verify_import` to confirm:

| Check | Pass | Fail |
|-------|------|------|
| `ms_valid` | True | MS directory exists but no `table.info` — import failed mid-run |
| `flag_file_exists` | True | `.flagonline.txt` absent — re-run with `savecmds=True` |
| `flag_file_n_commands` | > 0 | Empty file — no online flags recorded (unusual for VLA; note it) |
| `ready_for_preflag` | True | All three above must pass before proceeding |

Pass `online_flag_file` from the `ms_import_asdm` response directly to
`ms_apply_preflag` as its `online_flag_file` parameter.

An MS that did not come from an ASDM (a tutorial or archive MS) has no
`.flagonline.txt`. Continue without online flags only when the user states
`online_flags=none`: pass `online_flag_file=""` to `ms_apply_preflag`. A
missing flag file without that statement is a failed import: STOP.

---

## Step 1 — Online flags

`ms_apply_preflag` applies the online flags as-is — do not edit them. They are
deterministic hardware records.

---

## Step 2 — Pre-calibration flagging and calibrator split

`ms_apply_preflag` applies its flagging steps in a single pass and splits
calibrators to `calibrators.ms`. It quacks the first 5 s of every scan
(`quack_interval_s`): the first integrations read 4 to 17 % low.

**Always generate the script first (`execute=False`).** Review `preflag_cmds.txt`
before running — it is the complete audit record of what will be flagged.

---

## Step 3 — Prior calibration tables

`ms_generate_priorcals` generates four deterministic tables. After running,
verify with `ms_verify_priorcals`:

| Table | Required | If missing |
|-------|----------|-----------|
| `gain_curves.gc` | Yes — hard stop | Data cannot be calibrated without elevation gain curves |
| `opacities.opac` | K-band and above (`bp_field_centre_ghz` >= 18) | Empty table: hard stop at K-band and above; note and continue below K-band |
| `requantizer.rq` | VLA WIDAR data; it matters for 3-bit samplers | Pass it whenever gencal writes it. On 8-bit data the solutions are the same value over and over, which is harmless. It is skipped when the MS has no SYSPOWER rows (e.g. a split copy). Do not infer the data's era from the skip, and do not skip by observation date. Nothing to do when the tool reports it skipped; record the reason as reported |
| `antpos.ap` | No | Skip silently if gencal returns empty; note if returned with rows |

A missing `gain_curves.gc` (any band), or a missing `opacities.opac` at K-band
and above, means `gencal` could not access the telescope correction database.
Do not proceed — escalate. Below K-band a missing `opacities.opac` is expected.

---

## Step 4 — Flux density model (setjy)

`ms_setjy` sets Stokes I flux models for the flux calibrators it finds,
resolving the standard PER FIELD from that field's observing frequency. Do not
pass `standard` — see "Flux standards" in `07-calibration-execution.md` for why
it is an override that skips the frequency check.

Pass `usescratch=True`. `ms_verify_model` reads the physical MODEL_DATA column
before the residual rflag, and a virtual model writes no column.

**Check the warnings field in the response:**

| Warning | Action |
|---------|--------|
| `CALIBRATOR_RESOLVED_WARNING` | Use the component model listed in the warning, not a point source model |
| Bandpass calibrator has a UV limit | See "UV limits on the bandpass calibrator" at the end of Step 5 |
| 3C138 present at K/Ka/Q | Source was in flare in early 2025 — note in summary; flux scale may be affected |
| 3C48 present below 4 GHz | PA is unstable at these frequencies — viable for Stokes I only |

The returned `flux_fields` list confirms which fields received a model. A flux
calibrator missing from it is one of two different problems, and the response
separates them:

- In `skipped_fields` — the name did not match a catalogued flux calibrator.
  Check the spelling against `ms_field_list`.
- In `skipped_no_standard` — the source WAS found, but no standard applies at
  its observing frequency. **This is not a naming problem and re-running will
  not fix it.** The reason names the model's validity range and the observed
  span. You need a different flux calibrator for this band. On ALMA that is
  normally a solar-system body; a 3C source at Band 6 is far outside
  Perley-Butler 2017's 50 GHz ceiling.

Also read `n_range_checked`. A solar-system body modelled at a constant
brightness temperature is scaled without any frequency check, because CASA
codes no range for it. That is expected, not a defect — but it means the model
is unverified at your band, so treat a surprising flux scale as plausible
rather than impossible.

**If polarization calibration is in the run scope, set every model here, once,
before the initial bandpass:**

1. `ms_pol_cal_conditions` → the angle calibrator (`pol_angle_calibrator`).
2. `ms_setjy(usescratch=True, exclude_fields=<angle cal>)`. `usescratch` cannot
   be mixed within one MS without corrupting the flux scale, and
   `ms_setjy_polcal` always uses `True`.
3. `ms_setjy_polcal` on the angle cal (skill 09 Step 1 has the detail).
4. `ms_verify_model(field=<all cals>, polcal_fields=<angle cal>)`.

The angle cal is usually also the flux and bandpass cal. Done this way it carries
its full Stokes model through the initial bandpass, the residual rflag, the gain
solve and fluxscale. Excluding it from `ms_setjy` and deferring `ms_setjy_polcal`
to the polcal stage would leave it at the 1 Jy default for all of those. Skill
09 Step 1 is then already done; do not re-run it.

A zero-polarisation leakage calibrator (3C84, 3C147 at low frequency) needs no
model of its own: a `Df` solve assumes unit Stokes I and zero Q, U and solves
for the leakage.

---

## Step 5 — Reference antenna selection

**Score the refant on every calibrator it must serve, not just the bandpass
calibrator.** `ms_refant`'s flag heuristic is computed only over the `field` you
pass it. An antenna can rank top on the bandpass cal yet be heavily flagged on
the phase cal — different scans, elevation, and RFI — and scoring on the BP field
alone is blind to that. The same refant is used for all solves (G0, K, B, and the
gain solve over flux+phase cals), so it must be well populated on all of them. The
phase cal especially: the science target inherits its gain solutions, so a refant
weak on the phase cal corrupts the target even when the bandpass looks perfect.

In precal the initial bandpass solves on the bandpass calibrator alone, so run
`ms_refant(calibrators.ms, field=bp_field)` once. The calibrate stage runs
`ms_refant` once per calibrator field and chooses the antenna that ranks well on
**all** of them, before the full solve.

A `flag_score` near 0 means the antenna is fully flagged on that field — never
pick it, however high it ranks on another. Prefer the highest-ranked antenna with
a healthy `flag_score` in every list over the top pick of any single list.

| Condition | Action |
|-----------|--------|
| Candidate `flag_score` near 0 on *any* calibrator field | Disqualify — dead on that field; drop to the next antenna healthy on all fields |
| Top-ranked antenna has `flag_score` ≫ `geo_score` (periphery of array) | Note this — peripheral refants can cause phase-wrapping on long baselines at high freq |
| Only one heuristic used (completeness flag `INFERRED`) | Accept result but note lower confidence |
| Fewer than 3 antennas scored (`n_antennas` < 3) | Escalate — array is too sparse for reliable refant selection |

Record the top 3 cross-field candidates. If a solve fails or a gain solve flags
heavily, first check whether the refant is weak on that solve's field, then try
the next cross-field candidate before changing other parameters.

**UV limits on the bandpass calibrator.** Read the bandpass field's
`resolved_source` and warnings in `ms_field_list`. For a field outside the
bundled catalogue, the tool takes them from the VLA calibrator list at the
band of the field's centre frequency. The limits are band-specific: 3C84 has
`uvmin 12 klambda` at L-band and no limit at C-band. The tool projects the
baselines with data toward the field at the start, middle and end of each of
its scans, and counts, per antenna, the baselines inside the `uvrange`. The
field is usable only if at least 70% of the antennas keep 4 baselines at every
one of those times. The note gives the time with the fewest. Without scan
times the tool counts physical lengths, an upper limit, and the note says so.

| `ms_field_list` for the bandpass field | Action |
|---|---|
| warning says `pass uvrange='...'` | Pass that `uvrange` to `ms_initial_bandpass` and the later bandpass and gain solves on this field, whatever refant you chose |
| warning also names antennas with fewer than 4 baselines | Those antennas get no solution on this field at one or more scan times. Pass the `uvrange` anyway. Name them in the summary; do not pick one as refant |
| warning says `do not use this field as a calibrator` | The list grades it X in every configuration, or X in this MS's configuration (`ms_observation_info` `array_config`), or the `uvrange` leaves fewer than 70% of the antennas with 4 baselines at one or more scan times. Pick another bandpass calibrator or stop and report |
| warning says `configuration of this MS is unknown` | The list grades it X in the named configurations. Check the configuration from the observation's proposal or the SDM `configName`. If it is one of them, treat it as the row above |
| `true`, COMPLETE | Bundled-catalogue source. Follow `CALIBRATOR_RESOLVED_WARNING` |
| `false`, no warning | No `uvrange` |
| UNAVAILABLE | Unknown structure; the note says why. Say so in the summary. Do not invent a `uvrange`: in interactive mode ask the user; hands-off, pick another bandpass calibrator or stop and report |

---

## Step 6 — Initial bandpass

`ms_initial_bandpass` runs three CASA tasks in sequence (gaincal → bandpass → applycal)
and populates the CORRECTED column.

**This tool runs casatasks — it can take several minutes on large MSs.**

**Set `applycal_field` to the bandpass calibrator field at this stage.** It is a
required argument with no default. Gains are solved on the bandpass calibrator
only (`bp_field`), so it is the only field with a valid solution. The Step 3
applycal must be restricted to that field — applying to other fields under the
default `applymode='calflagstrict'` flags them for lack of a matching solution
and silently corrupts the FLAG state of every non-BP calibrator (observed on
AB1345). There is no flagversions rollback in this build, so the only recovery
is to re-split `calibrators.ms`. Pass `applycal_field=bp_field` here; reserve
`applycal_field=''` (all fields) for stages where all fields genuinely have
solutions.

**Never re-run `ms_initial_bandpass` before the final gain/pol solves.** It is a
one-shot bootstrap to populate CORRECTED for residual rflag on the BP cal — not
something to iterate. If you need a clean FLAG state for the final solves,
re-split `calibrators.ms` rather than re-running this tool.

If the script reports either caltable missing, do not proceed to rflag. Diagnose:
1. Was `bp_field` correct? Cross-check against `ms_field_list` intents.
2. Was the refant heavily flagged on the bandpass calibrator scans? Try rank-2.
3. Were prior caltables passed in `priorcals`? If `opacities.opac` was missing earlier, this will fail silently.

---

## Step 8 — Initial RFI flagging on residuals

**`ms_apply_initial_rflag` requires a `field` argument — there is no all-field
default, by design.** Residual rflag is only meaningful on a field whose
CORRECTED column is genuinely calibrated at the point you call it.

**At this stage that field is the bandpass calibrator only (`field={BP_FIELD}`),
and only if it is a primary with a real model.** Run `ms_verify_model` on it
first. A residual against the 1 Jy default model is the sky, not RFI. If the
bandpass calibrator has no setjy model, skip this step.
`ms_initial_bandpass` solves gains on the bandpass calibrator alone, so it is the
only field with a valid CORRECTED column right now. On every other field,
CORRECTED−MODEL is dominated by uncorrected gain/phase error — not RFI — so a
residual pass there flags almost the entire field (observed: 9.2% → ~90% overall,
phase cals ~97%), recoverable only by re-splitting the calibrators.

Residual flagging never runs on the phase calibrator or the target: neither has
a true model. Later residual flagging on the primaries (flux and polarization
calibrators) is 13-postcal-rfi-flagging.md Step 1, with the threshold set at
N × the thermal floor from clean SpWs.

`ms_apply_initial_rflag` runs rflag + tfcrop on the residual column in a single
flagdata list-mode pass. `flagbackup=True` saves a versioned backup automatically.

If the bandpass calibrator minimum elevation during its scans (from `ms_elevation_vs_time`
Phase 2 output) is < 30°, use `timedevscale=7, freqdevscale=7` instead of the
defaults (5, 5). Elevated system temperature at low elevations inflates scatter
and causes false positives at tighter thresholds.

---

## Decision gate — proceed to full calibration solve?

After Step 8, make a go/no-go decision:

| Condition | Decision |
|-----------|----------|
| `gain_curves.gc` missing | Hard stop — do not proceed |
| `opacities.opac` missing at K-band and above | Hard stop — do not proceed |
| Initial bandpass caltables missing | Hard stop — diagnose before proceeding |
| Bandpass calibrator model is the 1 Jy default | Hard stop — re-run setjy before proceeding |
| None of the above | Proceed to calibration solve |

Pass the following forward to the calibration solve:
- `refant`: top-ranked surviving antenna from `ms_refant`
- `priorcals`: list from `ms_verify_priorcals`
- `bp_field`: the bandpass calibrator field selection
- `workdir`: directory containing `init_gain.g` and `BP0.b`
