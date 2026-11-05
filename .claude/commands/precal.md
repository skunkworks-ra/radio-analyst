---
description: Pre-calibration workflow for a CASA Measurement Set (preflag → priorcals → setjy → refant → initial bandpass → residual rflag). Follows skill 10-precal-workflow.md.
allowed-tools: mcp__plugin_radio-analyst_ms-inspect__ms_workflow_status,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_import,
               mcp__plugin_radio-analyst_ms-modify__ms_set_intents,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_preflag,
               mcp__plugin_radio-analyst_ms-modify__ms_generate_priorcals,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy,
               mcp__plugin_radio-analyst_ms-inspect__ms_pol_cal_conditions,
               mcp__plugin_radio-analyst_ms-modify__ms_setjy_polcal,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_model,
               mcp__plugin_radio-analyst_ms-inspect__ms_refant,
               mcp__plugin_radio-analyst_ms-modify__ms_initial_bandpass,
               mcp__plugin_radio-analyst_ms-modify__ms_apply_initial_rflag,
               Bash,
               Read
---

Run the pre-calibration workflow on this MS: $ARGUMENTS

Arguments: the MS path, `workdir=<dir>`, and `online_flags=<path to .flagonline.txt>`
or `online_flags=none`. `none` means the MS has no online flag file (no ASDM) and
that is expected. If `workdir` or `online_flags` is missing, STOP and ask for it.

Load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read its `10-precal-workflow.md`
supporting file (a sibling of that skill's `SKILL.md`) before starting.
Execute the stages below in order; STOP and report if any stage fails its
decision gate.

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

4. `ms_apply_preflag(ms_path, workdir, cal_fields, online_flag_file, execute=False)`
   → run the generated script in the foreground (Bash without run_in_background,
     timeout=600000) and wait for it. If the call times out, STOP and report.
   With `online_flags=none`, pass `online_flag_file=""`; the other flags still run.

5. `ms_generate_priorcals(calibrators.ms, workdir, execute=False)` → run.
   Then `ms_verify_priorcals(workdir)` — its `priorcals_list` goes to step 8.

6. `ms_setjy(calibrators.ms, workdir, usescratch=True, execute=False)` → run.
   Check warnings field for resolved calibrators (3C84 uvrange gate).
   If polarisation is in the run scope, follow 10-precal-workflow.md Step 4
   instead: the angle cal excluded, then `ms_setjy_polcal`
   on it and `ms_verify_model(polcal_fields=...)`, all before step 8.

7. `ms_refant(calibrators.ms, field=<each calibrator>)`, once per calibrator
   field. Choose the highest-ranked antenna healthy on all of them
   (10-precal-workflow.md Step 5).

8. `ms_initial_bandpass(calibrators.ms, bp_field, refant, workdir,
   priorcals=<priorcals_list from step 5>, uvrange=<if 3C84>, execute=False)` → run.

9. `ms_verify_model(calibrators.ms, field=bp_field)` — if the model is the
   1 Jy default, skip the rflag below. Otherwise
   `ms_apply_initial_rflag(calibrators.ms, workdir, field=bp_field, execute=False)` → run.

10. Final decision gate (§Decision gate): go/no-go for full calibration solve.

**Output:** a structured report of each stage's outcome, flagged warnings,
and the forward hand-off values (`refant`, `priorcals`, `bp_field`, `workdir`)
ready for `/calibrate`.
