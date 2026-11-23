# 00 — Playbook (stage → next action)

## Mandatory 5-Stage E2E Contract (read each stage's file before its write tools)

1. **Inspect** -> Read `01-workflow.md` + `01b-workflow-phase2.md`
2. **Precal** -> Read `10-precal-workflow.md` (`missing_precal_steps == []`)
3. **Calibrate** (+ Polcal if IQUV) -> Read `07-calibration-execution.md` (+ `09-polcal-execution.md`)
4. **Postcal target spectrum gate (`next_recommended_step == 'postcal_target_rfi'`)** -> Read `13-postcal-rfi-flagging.md` and run `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field=<targets>, workdir=workdir)`; flag with `rflag` only (never clip targets) and re-measure until clean (`chan_diff_std_over_mad < 1.5`, `max_spw_chan_diff_std_over_mad < 1.8`, `chan_diff_gt10sigma_frac < 0.001`, `spw_rms_ratio < 1.5`)
5. **Image (`next_recommended_step == 'first_image'`)** -> **MUST Read `11-imaging.md` before calling `ms_tclean`** (never ship an unmasked quick-look or a non-converged/rejected image)

Find your current state in the left column. Run the right-column tool
(or read the named skill file for decision tables).

## Stage transitions

| Current state | Next action |
|---------------|-------------|
| Starting from ASDM | Run `/import` (or `ms_sdm_summary` -> `ms_import_asdm(..., execute=False)` -> run -> `ms_verify_import`; split continuum SPWs if mixed line+continuum or setup SPWs exist) |
| MS imported, no intents | `ms_set_intents(ms_path)` → proceed |
| MS imported, intents present | Run `/inspect` or read `01-workflow.md` |
| Phase 1 + 2 inspection done, go decision | Run `/precal` or read `10-precal-workflow.md` |
| Pre-cal complete (`ms_workflow_status.next_recommended_step == 'delay_bandpass_gain'`, `missing_precal_steps == []`) | Run `/calibrate` or read `07-calibration-execution.md` |
| Calibration solve done (`next_recommended_step == 'postcal_target_rfi'`, or `'polcal'` for IQUV) | For pol: `/polcal` or read `09-polcal-execution.md`. Then **MUST run `ms_spw_amp_severity(ms_path, datacolumn='CORRECTED_DATA', field=<targets>, workdir=workdir)`** (read `13-postcal-rfi-flagging.md` if elevated: run `ms_apply_rflag` / `/postcal` and re-measure until clean) until `next_recommended_step == 'first_image'` |
| Target spectrum verified clean (`next_recommended_step == 'first_image'`) | **MUST Read `11-imaging.md` before calling `ms_tclean`**, then run `/image` (`stokes='I'`, followed by `stokes='IQUV'` if polcal ran) |
| First-pass image done | Read `12-selfcal.md` — one-pass phase selfcal with before/after assessment |
| Final applycal done, RFI on target/phase cal | Read `13-postcal-rfi-flagging.md` — residual clip on the primaries, per-channel triage on the target |

## Unknown state? Use ms_workflow_status(ms_path, workdir) — it returns a next_recommended_step label.

## Record every step that worked

See `ledger.md`.

## Load skill files on demand
- 01-workflow.md / 01b-workflow-phase2.md — orientation + instrument sanity
- 02-orientation.md — band tables, intents, mosaics
- 03-instrument-sanity.md — array configs, elevation/PA/flag thresholds
- 04-diagnostic-reasoning.md — report template, go/no-go
- 05-calibrator-science.md — flux standards, resolved sources
- 06-failure-modes.md — recovery paths
- 07-calibration-execution.md — solve sequence (read only when you reach calibration)
- 07b-gaincal-recovery.md — gaincal recovery trees + escalation (read only when a Step 4b post-flight check fails)
- 08-pband-specifics.md — VLA P-band
- 09-polcal-execution.md — polarization
- 10-precal-workflow.md — pre-calibration pipeline
- 11-imaging.md — first-pass imaging
- 12-selfcal.md — single-pass phase selfcal with before/after DR comparison
- 13-postcal-rfi-flagging.md — residual clip on the primaries only + per-channel triage on the target (no clip on phase cal or target)

Read each file with the Read tool when you reach that stage — do not load everything up front.
