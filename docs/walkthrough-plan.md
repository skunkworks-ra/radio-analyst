# Plan — 3C391 walkthrough for the first release

Status: planned, not started (2026-10-28). Runs are deferred.

## Goal

A user installs the plugin, downloads the public 3C391 dataset, and has a
session with Claude that shows every measurement and every decision, ending
at the same calibrated data and image we did, within stated tolerances. The
README becomes that session. Showing the workings is how the tool earns trust.

## Two levels of "same answer"

| Level | The user | Promise |
|---|---|---|
| Replay | runs the recorded `replay.py` from the reference ledger | identical calls and parameters; caltables and image match to numerical precision |
| Fresh session | talks to Claude on the same data | decisions and key numbers fall inside measured tolerance bands; this is where model stochasticity lives |

Replay proves the workings are real. The fresh session proves the reasoning
reproduces. Machinery already on main: the ledger and replay
(`ms_reduction_log`), `report.html` (`ms_report`), the `stages.json` contract,
`scripts/dev/score_run.py`. `param_log` is on the unmerged `paper-param-log`
branch.

## Steps

1. **Pin the dataset.** `3c391_ctm_mosaic_10s_spw0.ms.tgz` is the CASA-guide
   dataset. Record the public NRAO URL and a sha256.
2. **Measure the spread, per model.** Run `/reduce` on 3C391 with all three
   model tiers (Haiku, Sonnet, Opus), N runs each (N ≈ 5), through
   `scripts/dev/run-isolated.sh` for a clean environment. Per run, record:
   - token counts (input, output, cache read, cache write) and the cost
     estimate derived from them
   - wall-clock time and number of turns
   - the `score_run.py` result against `stages.json`
   - key numbers: refant ranking, flag fractions after preflag, the J1822
     flux bootstrapped by fluxscale, per-antenna calsol SNR, image RMS /
     peak / DR / beam

   Report, per model, the median and range of cost and of each key number.
   N = 5 gives a rough spread, not a tight one; state that next to the
   numbers.
3. **Choose one reference run** and publish its trace, ledger,
   `report.html` and replay script under `examples/3c391/`.
4. **Expected-answers file.** `examples/3c391/expected.json`: each key number
   with its tolerance band and where the band came from (the step 2 spread).
   Cross-check against the CASA guide's quoted values where it gives them.
5. **User-side comparison.** A `score_run.py` mode that compares a user's run
   to `expected.json` and reports per number whether it is inside or outside
   the band. It reports; it does not pass or fail (the tools-measure rule).
6. **README walkthrough.** Per stage: the prompt typed, the tools called, the
   numbers returned, the decision and its reason, what you should see (with
   tolerance), and a link into the reference report. Close with the per-model
   cost and spread table from step 2.

## Open questions

- **Claude Desktop vs Claude Code.** Record the reference in Claude Code:
  the hooks, isolated runner, trace capture and scorer depend on it. Whether
  Desktop runs this plugin's skills and hooks is unverified. MCP servers are
  expected to work, skills probably, hooks uncertain. Verify before promising
  a Desktop experience.
- **Token budget** for 3 models × N runs. Estimate it from one run per model
  before committing to N.

## Before tagging 0.1.0

- `src/ms_inspect/server.py:68`: server instructions still say
  "Phase 1 — Layer 1 & 2".
- `design_docs/DESIGN.md` header: "Design — not yet implemented", scope
  Phase 1 only.
- Run `pixi run test-int`; then check for `casa-*.log` written outside
  `logs/` (`find . -path ./.pixi -prune -o -name 'casa-*.log' -newermt <date> -print`).
- State at writing: `pixi run check` passes; unit tests 1137 passed.
