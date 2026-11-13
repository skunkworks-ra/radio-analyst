---
description: Pre-calibration workflow for a CASA Measurement Set (preflag → priorcals → setjy → refant → initial bandpass → residual rflag). Follows skill 10-precal-workflow.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_field_list,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_import,
               mcp__plugin_radio-analyst_ms-modify__ms_set_intents,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_preflag,
               mcp__plugin_radio-analyst_ms-modify__ms_generate_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy,
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-inspect__ms_correlator_config,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy_polcal,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_model,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-modify__ms_initial_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_initial_rflag,
               mcp__plugin_radio-analyst_ms-inspect__ms_observation_info,
               mcp__plugin_radio-analyst_ms-create__ms_reduction_log,
               Bash,
               Read
---

Run the pre-calibration workflow on this MS: $ARGUMENTS

Arguments: the MS path, `workdir=<dir>`, and `online_flags=<path to .flagonline.txt>`
or `online_flags=none`. `none` means the MS has no online flag file (no ASDM) and
that is expected. If `workdir` or `online_flags` is missing, STOP and ask for it.

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read only its `10-precal-workflow.md` and
`ledger.md` supporting files (siblings of that skill's `SKILL.md`) before starting,
skipping the files the skill lists under "Start here".

Execute the stages below in order; STOP and report if any stage fails its
decision gate. Run each generated script as written; do not Read it first.
Record each validated write step with `ms_reduction_log`, as `ledger.md` says.
Every MCP tool takes one argument, `params`: `{"ms_path": ..., ...}`.

Every "→ run" below: run the script detached and poll it, as the skill's
"Running generated scripts" says. No time limit.

**Workflow:**

1. `ms_workflow_status(ms_path, workdir)` — where are we starting from?
   If `next_recommended_step` is past pre-calibration, STOP and tell the user.
   If `ms_valid` is False, STOP.

2. With `online_flags=<path>`: `ms_verify_import(ms_path, online_flag_file)` —
   if `ready_for_preflag` is False, STOP. With `online_flags=none`: skip this step.

3. If intents are missing from Phase-1 orientation: `ms_set_intents(ms_path, workdir,
   execute=True)`, one call, no preview.
   If you ran it, `cal_fields` for step 4 is every field its `field_intent_map`
   gives a `CALIBRATE_*` intent; that replaces the handoff's `cal_fields`.

4. `ms_apply_preflag(ms_path, workdir, cal_fields, online_flag_file, execute=False)`,
   `cal_fields` one comma-separated string
   → run.
   With `online_flags=none`, pass `online_flag_file=""`; the other flags still run.

5. `ms_generate_priorcals(calibrators.ms, workdir, execute=False)` → run.
   Then `ms_verify_priorcals(calibrators.ms, workdir)` — its `priorcals_list` goes to step 8.

6. If the arguments say `pol_scope: off`, polarisation is out of scope: skip to
   the `ms_setjy` call at the end of this step. Otherwise
   `ms_pol_cal_conditions(calibrators.ms)` and `ms_correlator_config(calibrators.ms)`
   first. Polarisation is in scope when `pol_angle_calibrator.available` and
   `leakage_calibrator.available` are true, `pol_angle_calibrator.pol_angle_deg`
   is not UNAVAILABLE, and `full_stokes` is true: follow 10-precal-workflow.md Step 4's
   polarisation path (the angle cal excluded from `ms_setjy`, then
   `ms_setjy_polcal` on it and `ms_verify_model(polcal_fields=...)`), all
   before step 8. Otherwise `ms_setjy(calibrators.ms, workdir, usescratch=True,
   execute=False)` → run. Check its warnings field.
   Record the result for the output: `pol_scope: on` with the angle cal's field
   name, or `pol_scope: off` with the reason (asked off, or the condition that
   failed, with its tool value).

7. `ms_refant(calibrators.ms, field=bp_field)`, one call. The initial bandpass
   solves on bp_field alone; /calibrate re-scores the refant on every calibrator.

8. `ms_field_list(calibrators.ms)`: read bp_field's `resolved_source` and warnings,
   and pick `uvrange` by 10-precal-workflow.md Step 5, "UV limits on the bandpass
   calibrator". Then `ms_initial_bandpass(calibrators.ms, bp_field,
   applycal_field=bp_field, ref_ant=ref_ant, workdir=workdir,
   priorcals=<priorcals_list from step 5>, uvrange=<from that table>, execute=False)` -> run.

9. `ms_verify_model(calibrators.ms, field=bp_field)` — if the model is the
   1 Jy default, skip the rflag below. Otherwise
   `ms_apply_initial_rflag(calibrators.ms, workdir, field=bp_field, execute=False)` → run.

10. Final decision gate (§Decision gate): go/no-go for full calibration solve.

**Output:** a structured report of each stage's outcome, flagged warnings,
and `workdir` for `/calibrate` (calibrate re-derives refant, priorcals and
bp_field itself). End with these two lines, from step 6:

```
pol_scope: <on | off (reason)>
angle_cal: <field name | none>
```
