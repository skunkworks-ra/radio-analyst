---
name: report
description: >
  Build the reduction report for the user: a short text summary in chat and an
  HTML report (report.html) in the workdir with the steps, decisions, caveats,
  replay script, plots and image. Invoke at the end of a reduction, or when the
  user asks for a report or wants to choose which steps to keep.
allowed-tools: mcp__plugin_radio-analyst_ms-create__ms_report,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               mcp__plugin_radio-analyst_ms-inspect__ms_image_stats,
               Read
---

# Report: what was done, what it shows, what to keep

`ms_report` lays out what the workdir already holds. You write the three parts
only you can: the summary, the decisions, the caveats. Every number in them
comes from a tool output or a ledger entry, with the step it came from. Do not
measure anything new for the report.

## Steps

1. `ms_reduction_log(action='render', workdir=<workdir>)`, so the report carries
   the current replay script.
2. Write the three sections as plain text, a blank line between paragraphs:
   - `summary`: the data, what was done stage by stage, the final image numbers
     (rms, peak, dynamic range, beam) from `ms_image_stats`.
   - `decisions`: each choice that changed the result (refant, flagging,
     solints, selfcal yes or no) and the numbers it rests on.
   - `caveats`: what the result does not support, every check skipped and why,
     every step done off the tools.
3. `ms_report(workdir, summary, decisions, caveats, image_path=<final image>.image.pbcor)`.
4. Give the user the report path and the same three sections, shortened, in chat.

## Keeping or dropping steps

Each step in the report has a keep box. Unticking boxes builds a line like
`ms_reduction_log(action='render', keep_steps=[1, 2, 4])`. When the user gives
you that line, run it, then rebuild the report with `ms_report`. Warn them which
later steps use the products of a dropped step: those will fail on replay.

## Rebuilding

`ms_report` overwrites `report.html`. Call it again whenever the ledger changes.
