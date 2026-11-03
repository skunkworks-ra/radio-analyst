# A/B test: GLM-5 reducing 3C391, with and without radio-analyst

Status: draft, 2026-11-03. A1 and B1 done; A2, B2, A3, B3 pending.

## Question

Does the plugin (skills, MCP tools, hooks) change what an LLM does when asked to
reduce a VLA dataset to a first image? Same model, same data, same container;
the only difference is whether the plugin is installed.

## Setup

| | A: with plugin | B: without |
|---|---|---|
| Harness | opencode 1.19.0, `scripts/dev/run-isolated.sh --harness opencode` | same, plus `--no-plugin` |
| Model | `nrp/glm-5` (NRP), default effort | same |
| Commit | 7d70bc5 | same (only its CASA environment is used) |
| Data | 3C391 CASA-guide MS, `fixture_3c391_fresh` (no MODEL/CORRECTED) | same |
| Plugin | skills, `/radio-analyst-reduce` command, 3 MCP servers, reduce hook | none |
| Prompt | `/radio-analyst-reduce ./input.ms There is no online flag file for this MS; proceed without one.` | `Reduce ./input.ms (VLA, 3C391) to a first calibrated image. There is no online flag file for this MS; proceed without one.` |
| Python/CASA | plugin environment | same environment, path given in `AGENTS.md` |
| Cap | 5 h per run, runs one at a time | same |

Runs: A1 B1 A2 B2 A3 B3, under `/var/mnt/fast/radio_analyst_runs/ab_20261102_glm5/`
(`COMMAND.txt`, `COMMAND_resume.txt`, `ab.log`).

## What is measured per run

- Outcome: exit code, reached an image or not, report built or not.
- Effort: wall time, model steps, tool calls (MCP vs other), tool errors.
- Tokens: input, output, reasoning, cache read/write, from opencode's
  `step_finish` events in `trace.jsonl`.
- Cost: opencode reports `cost` 0.0 for the NRP provider, so cost is
  **not measured**. Tokens are the cost proxy.
- Image: `ms_image_stats` on the final image (peak, residual rms where pb >= 0.1,
  residual dynamic range, beam). For arm B, the same tool run afterwards on
  whatever image it made.
- Failure modes: tool errors by tool, where a run stopped, and anything the
  model did off the tools.

## Results

### A1 `20261102T210643Z_opencode_nrp-glm-5_default_7d70bc5`

| Quantity | Value |
|---|---|
| Exit | 0 |
| Environment build | 222 s |
| Session | 6770 s (1 h 53 min) |
| Model steps | 134 |
| Tool calls | 198: 121 MCP (77 ms-inspect, 21 ms-modify, 23 ms-create), 44 bash, 17 read, 6 write, other 10 |
| Tool errors | 2, both `ms_calsol_stats` |
| Skills loaded | `reduce`, `report` |
| Stop hook | sent the model back once, 20 open items |
| Ledger | 20 entries, 24 scripts, `reduction_replay.py` and `report.html` written |
| Tokens | input 23,485,460; output 33,917; reasoning 60,601; cache read 0; cache write 0 |
| Cost | not measured (reported 0.0) |

Images, `ms_image_stats` as the model called it (pb_level 0.1):

| Image | Peak (Jy/beam) | Residual rms (mJy/beam) | Residual DR | Beam (arcsec) |
|---|---|---|---|---|
| `3c391_mosaic_i` first clean | 0.1407 | 2.784 | 50.5 | 16.79 x 14.13 |
| `3c391_mosaic_i` re-clean | 0.1380 | 0.0588 | 2346.8 | 16.79 x 14.13 |
| `3c391_mosaic_i_sc1` after phase selfcal | 0.1266 | 0.0739 | 1712.7 | 16.86 x 14.15 |

The model compared the selfcal image with the re-clean (residual rms +26 %,
peak -8 %), rejected selfcal, re-applied the pre-selfcal calibration to the
target (trace call 175) and delivered the re-clean `3c391_mosaic_i`. The
`_sc1` image is still on disk.

Observed, not yet explained:

- 5 `casa-*.log` files in the run's working directory, from scripts run with
  bash. The servers keep theirs under `logs/`.
- Peak 0.13 to 0.14 Jy/beam here; the Claude Haiku run A5 (Claude Code, commit
  34c1e81) reported 1.30 Jy/beam on the same data. Not checked.

### B1 `20261102T230345Z_opencode-noplugin_nrp-glm-5_default_7d70bc5`

| Quantity | Value |
|---|---|
| Exit | 0 |
| Environment build | 81 s |
| Session | 3137 s (52 min) |
| Model steps | 94 |
| Tool calls | 104: 72 bash, 15 write, 8 edit, 4 todowrite, 2 read, 2 webfetch, 1 grep |
| Tool errors | 2 webfetch (404 on two casaguides 3C391 tutorial URLs); 6 bash calls exited non-zero |
| Scripts | 15 written; 3 raised: `cal1.py` (`setjy` given `listfile`, not a parameter), `inspect3.py`, `inspect4.py` (own numpy bugs) |
| Calibration | setjy (`Perley-Butler 2010`, model's choice), gaincal G0, bandpass, gaincal G1 (ap), fluxscale, applycal x3, split; no delay (K) solve, no prior caltables |
| Imaging | tclean x4, mosaic gridder, 3 arcsec cell, 768 px, briggs 0.5, auto-multithresh mask, threshold 0.5 mJy |
| Record | no ledger, no replay script, no report |
| Tokens | input 6,614,442; output 22,007; reasoning 50,827; cache read 0; cache write 0 |
| Cost | not measured (reported 0.0) |
| Stray logs | 59 `casa-*.log` in the working directory |

Final image `3c391_first.image.pbcor`, `ms_image_stats` run after the session
with A1's settings (pb_level 0.1; code identical to 7d70bc5), output in
`<run>/image_stats_check/`:

| Image | Peak (Jy/beam) | Residual rms (mJy/beam) | Residual DR | Beam (arcsec) |
|---|---|---|---|---|
| `3c391_first` | 0.1545 | 0.888 | 173.9 | 16.88 x 14.19 |

For comparison, A1 also had 3 bash calls exit non-zero.

### A2, B2, A3, B3

Pending.

## A1 vs B1, stage by stage

What each run actually did, from the A1 trace (write-tool calls and the
scripts it ran) and the B1 trace and scripts. A1's steps come from the
`/radio-analyst-reduce` contract; B1's are the model's own.

| Stage | A1: with plugin | B1: without |
|---|---|---|
| Look at the data | 77 ms-inspect calls: orientation, antennas, elevation, flags, refant ranking per calibrator | `listobs`, `flagdata` summary, 4 own inspection scripts (2 raised, fixed and rerun) |
| Intents | `ms_set_intents` script | none (used field names) |
| Pre-flag | list mode: quack 5 s, shadow, clip zeros, tfcrop (3/3), extend pols; calibrators split to `calibrators.ms` | manual: ea13, scan 1, channels 0~4 and 59~63; quack 10 s; shadow |
| Prior caltables | gain curves, opacities, antenna positions | none |
| Flux model | `Perley-Butler 2017` on J1331+3030 | `Perley-Butler 2010` on J1331+3030; first attempt raised (`listfile`) |
| Refant | `ea21` from `ms_refant` | `ea21` |
| Initial phase | G0, solint int, phase, minsnr 5, channels 27~35 | G0, solint int, phase, minsnr 2 |
| Delay | K, solint inf, combine scan | **not solved** |
| Bandpass | B, solint inf, combine scan, minsnr 3; caltable autoflag (tfcrop, +0.03 % flagged) | B0, solint inf, combine scan, minsnr 3 |
| Residual RFI flag | rflag + tfcrop on the flux calibrator (timedev/freqdev 7) | none |
| Gain | G, solint inf, amp+phase, both calibrators | G1, solint inf, amp+phase, both calibrators |
| Fluxscale: J1822-0938 | **2.3035 ± 0.0059 Jy** | **2.3413 ± 0.0065 Jy** |
| Apply | per field, priorcals + K + B + fluxscaled gain, gainfield set | per field: B0 + G1 on the flux calibrator, B0 + G1_flux on J1822 and the target, gainfield set; target split to `3c391_calibrated.ms` |
| Image | tclean x2 on one name: asp then multiscale; mosaic, 4 arcsec, 512 px, briggs 0.5, threshold 0.05 mJy, pblimit -0.1 (PB mask) | tclean x4 (dirty, then 3 cleans): mosaic, 3 arcsec, 768 px, briggs 0.5, auto-multithresh, threshold 0.5 mJy, pblimit 0.1 |
| Selfcal | one phase round; image worse; rejected and reverted | none |
| Record | ledger 20 entries, replay script, `report.html`; hook sent it back once for 20 open checks | 15 scripts and their stdout/stderr files |

Delivered images, `ms_image_stats` at pb_level 0.1 on both (same code):

| | A1 `3c391_mosaic_i` | B1 `3c391_first` |
|---|---|---|
| Peak (Jy/beam) | 0.1380 | 0.1545 |
| Residual rms (mJy/beam) | 0.0588 | 0.888 |
| Residual dynamic range | 2346.8 | 173.9 |
| Beam (arcsec) | 16.79 x 14.13 | 16.88 x 14.19 |
| Session | 113 min | 52 min |
| Input / output+reasoning tokens | 23.5 M / 94.5 k | 6.6 M / 72.8 k |

Not yet checked:

- The two images' residual rms differ by a factor of 15. A1 cleaned to
  0.05 mJy, B1 to 0.5 mJy, with different masks; part or all of the gap may be
  depth of clean rather than calibration. Needs a same-tclean comparison on both
  calibrated datasets.
- J1822-0938 differs by 1.6 % between runs; the two runs used different flux
  standards (PB2017 vs PB2010).
- Whether the missing delay solve and prior caltables in B1 show up in the
  calibrator phases or amplitudes.
- B1's peak is 12 % higher than A1's; flux scale, clean depth or masking.

## Comparison

Pending all six runs. Per arm: median and range of each quantity above.
Three runs per arm gives a rough spread, not a tight one.
