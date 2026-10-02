# 15 — Averaging Before Imaging

## Purpose

After the final applycal (and post-cal flagging, skill 13), split the target
to a smaller MS with channel and time averaging, so imaging and selfcal run on
fewer visibilities. Averaging smears sources away from the phase centre.
`ms_smearing_limits` gives the largest averaging that keeps the smearing loss
within a fixed budget at the 10%-power radius of the primary beam (PB).

Average the target only. Never average `calibrators.ms` or a calibrator field.

---

## When to skip

| Situation | Action |
|---|---|
| Spectral-line science | No channel averaging (`width=[1]`); time averaging is still allowed |
| Rotation-measure work on Q/U cubes | No channel averaging unless the user approves the coarser channels |
| `suggested_width_channels` is 1 for every SpW and `suggested_timebin_s` ≤ the dump time | Nothing to gain; image the full MS |

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

---

## Step 4 — Verify the averaged MS

| Check | Tool | Expected |
|---|---|---|
| Channels | `ms_spectral_window_list(<avg MS>)` | `nchan` = original `nchan` / `width` per SpW |
| Time bin | `ms_correlator_config(<avg MS>)` | `dump_time_s` ≈ `timebin_s` (shorter at scan ends) |
| Fields | `ms_field_list(<avg MS>)` | Only the target field(s) |

Then use the averaged MS as `{VIS}` in skills 11 and 12. Record the split in
the reduction ledger with the limits and predicted losses in `outputs`.

---

## Where the trouble is

1. **The averaged MS has no CORRECTED_DATA.** The calibrated data are in its
   DATA column. `ms_workflow_status` on it does not report CORRECTED as
   populated; that is expected. tclean reads DATA when CORRECTED is absent.
   Selfcal applycal on the averaged MS creates a new CORRECTED_DATA.
2. **Width order.** A `width` list is matched to the selected SpWs in order.
   A wrong order averages one SpW too much and smears it.
