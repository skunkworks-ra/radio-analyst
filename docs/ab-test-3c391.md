# A/B test: GLM-5 reducing 3C391, with and without radio-analyst

Status: draft, 2026-11-02. Arm A run 1 of 3 done; arm B and runs 2 and 3 pending.

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

Observed, not yet explained:

- 5 `casa-*.log` files in the run's working directory, from scripts run with
  bash. The servers keep theirs under `logs/`.
- Peak 0.13 to 0.14 Jy/beam here; the Claude Haiku run A5 (Claude Code, commit
  34c1e81) reported 1.30 Jy/beam on the same data. Not checked.

### B1, A2, B2, A3, B3

Pending.

## Comparison

Pending all six runs. Per arm: median and range of each quantity above.
Three runs per arm gives a rough spread, not a tight one.
