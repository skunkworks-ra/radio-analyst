---
description: Post-calibration rflag on the target's CORRECTED data (rflag only, no clip), with the flagged fraction before and after.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_flag_summary,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_rflag,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               Bash,
               Read
---

Arguments: the MS path, `workdir=<dir>`, and `field: <target fields>`. $ARGUMENTS
If `field:` is missing, STOP and ask for it: rflag must be scoped to the target
fields, whose CORRECTED is valid after the final applycal.

If your task prompt contains `SKILL EXCERPTS` blocks, they are the skill text
for this stage: use them, and do not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry`
when installed as a plugin), then read only its `ledger.md`.

Every MCP tool takes one argument, `params`. Every "→ run" below: run the
script detached and poll it, as the skill's "Running generated scripts" says.

1. `ms_flag_summary(ms_path, field=<field>)`: flagged fraction before.
2. `ms_apply_rflag(ms_path, workdir, field=<field>, datacolumn='corrected',
   execute=False)` with the tool's default thresholds → run. It saves flag
   version `before_rflag` first (a second run would reuse that name: save a
   backup by hand before re-running). CASA's default `extendflags=True` applies,
   so rflag also grows its flags in time and frequency; report that. Record the
   call with `ms_reduction_log`.
3. `ms_flag_summary(ms_path, field=<field>)`: flagged fraction after.

**Output:** the flagged fraction per field before and after, the thresholds
used, and the flag version name.
