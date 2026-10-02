# 15 — Averaging Before Imaging

## Purpose

`average_target` is a standard pipeline stage. It always runs after the final
applycal (and post-cal flagging, skill 13) and before imaging. It splits the
target to a smaller MS with channel and time averaging, so imaging and selfcal
run on fewer visibilities. When no averaging is needed, the stage still runs
and records that. Averaging smears sources away from the phase centre.
`ms_smearing_limits` gives the largest averaging that keeps the smearing loss
within a fixed budget at the 10%-power radius of the primary beam (PB).

Average the target only. Never average `calibrators.ms` or a calibrator field.

---

## When to reduce the averaging

| Situation | Action |
|---|---|
| Spectral-line science | No channel averaging (`width=[1]`); time averaging is still allowed |
| Rotation-measure work on Q/U cubes | No channel averaging unless the user approves the coarser channels |
| `suggested_width_channels` is 1 for every SpW and `suggested_timebin_s` ≤ the dump time | No averaging: run Step 3 with `width=[1]`, `timebin_s=0` |

---

## Step 1 — Get the limits

```
ms_smearing_limits(ms_path={VIS})
```

Keep the defaults: `max_time_loss=0.10`, `max_bandwidth_loss=0.05`,
`max_timebin_s=30`. Change them only if the user asks. The tool refuses a
time cap above 30 s: **never average more than 30 s in time.**

The tool takes the PB radius at the lowest frequency and the beam
(`λ/B_max`) at the highest frequency. The result holds for every frequency in
an image that spans the whole band. `λ/B_max` ignores weighting, so the limits
are conservative.

| Output | Use |
|---|---|
| `suggested_timebin_s` | `timebin_s` for Step 3 (≤ 30 s, whole dumps) |
| `per_spw[].suggested_width_channels` | `width` for Step 3, in SpW order |
| `tau_max_s`, `dnu_max_hz` | Raw limits before the cap and the rounding — report them |
| `time_loss_at_suggested`, `per_spw[].bandwidth_loss_at_suggested` | Predicted peak loss at the 10% PB radius — report them |

Formulae (Bridle & Schwab 1999, *Synthesis Imaging II*, ch. 18), with
`x = r10 / θ_syn`:

- time: loss = 1.23e-9 · x² · τ²  (τ in s; exact at δ=90°, an upper bound elsewhere)
- bandwidth: loss = 1 − 1/√(1 + 0.462 · (Δν/ν · x)²)

---

## Step 2 — Check against selfcal

If selfcal (skill 12) will follow, `timebin_s` must not be longer than the
shortest solution interval you plan to use. The 30 s cap covers `solint='inf'`
and most `solint` values in seconds. After averaging, `solint='int'` means
one averaged bin, not one correlator dump.

---

## Step 3 — Split with averaging

```
ms_split_average(
    ms_path    = {VIS},
    workdir    = {WORKDIR},
    field      = {TARGET_FIELD},
    output_ms  = '{WORKDIR}/<target>_avg.ms',
    width      = [<suggested_width_channels per SpW>],
    timebin_s  = <suggested_timebin_s>,
    execute    = False,
)
```

Run the generated `split_average.py`. The tool reads `CORRECTED_DATA`, never
averages across a scan, and refuses an `output_ms` that exists. If you
select SpWs with `spw`, give one `width` per selected SpW, in the same order.

**No averaging.** Call it with `width=[1]`, `timebin_s=0` and no `output_ms`.
Nothing is split. The script records the stage with `averaged: false`, and
imaging uses the full MS. Say in the report that no averaging was needed, and
give `tau_max_s` and `dnu_max_hz`.

The tool returns `image_ms`: the MS that skills 11 and 12 use as `{VIS}`.

---

## Step 4 — Verify the averaged MS

| Check | Tool | Expected |
|---|---|---|
| Channels | `ms_spectral_window_list(<avg MS>)` | `nchan` = original `nchan` / `width` per SpW |
| Time bin | `stage_log.jsonl` line for `split_average` | `measurement.timebin` equals the `timebin_s` you passed |
| Fields | `ms_field_list(<avg MS>)` | Only the target field(s) |

Then use `image_ms` as `{VIS}` in skills 11 and 12. On that MS,
`ms_workflow_status` returns `averaged_target_ms: true`,
`calibrated_column: "DATA"` and `next_recommended_step: first_image`. Record the split in
the reduction ledger with the limits and predicted losses in `outputs`.

---

## Where the trouble is

1. **The averaged MS has no CORRECTED_DATA.** The calibrated data are in its
   DATA column. `ms_workflow_status` knows this from the stage log only when
   it is given the same workdir as the split. With another workdir it
   recommends `applycal_target` — do not run it; pass the right workdir.
   tclean reads DATA when CORRECTED is absent. Selfcal applycal on the
   averaged MS creates a new CORRECTED_DATA.
2. **`dump_time_s` is wrong on an averaged MS.** `ms_correlator_config`
   reads the step between time stamps. In an averaged MS each row's TIME is
   the centroid of its unflagged data, so baselines in one bin differ by
   about one dump. The tool then reports the original dump, not the bin.
   Use the stage-log line to confirm the time bin.
3. **Width order.** A `width` list is matched to the selected SpWs in order.
   A wrong order averages one SpW too much and smears it.
