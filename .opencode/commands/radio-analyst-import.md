---
description: Import a raw ASDM/SDM directory into a verified CASA MS (and split continuum SPWs when mixed spectral-line + continuum or setup SPWs exist). Follows skill 10-precal-workflow.md Step 0.
allowed-tools: mcp__plugin_radio-analyst_ms-create__ms_sdm_summary,
               mcp__plugin_radio-analyst_ms-create__ms_import_asdm,
               mcp__plugin_radio-analyst_ms-inspect__ms_verify_import,
               mcp__plugin_radio-analyst_ms-inspect__ms_spectral_window_list,
               mcp__plugin_radio-analyst_ms-modify__ms_casa_task,
               Bash,
               Read
---

Import this raw ASDM/SDM directory into a CASA Measurement Set: $ARGUMENTS

Arguments: `sdm_path=<path to SDM directory>`, `workdir=<dir>`, and optional
`ms_name=<name>.ms`, `spw=<explicit SPW selection>`, or `spw_mode=continuum|all`
(default `continuum` for continuum reductions). If `sdm_path` or `workdir` is
missing, STOP and ask for it.

If your task prompt contains `SKILL EXCERPT FILE:` lines, Read each named file
once before starting: they are the skill text for this stage. Use them, and do
not load the skill or read its files.
Otherwise load the `radio-interferometry` skill (`radio-analyst:radio-interferometry` when
installed as a plugin), then read only its `bundles/import.md` file (resolved
relative to that skill's `SKILL.md` directory) before starting.

Every MCP tool takes one argument, `params`. Every write step records
automatically in `<workdir>/stage_log.jsonl`.
Every "-> run" below: run the script via `run-step.sh` (`--wait 240`), as the
skill's "Running generated scripts" section says, re-running on `status=running`
until `status=done` (`rc=0`). NEVER exit, summarize completion, or proceed
while `run-step.sh` is still `status=running`.

**Workflow:**

1. `ms_sdm_summary(sdm_path)` -- inspect the raw ASDM XML before converting:
   telescope, array configuration, band, per-SPW continuum-vs-line
   classification, correlation products (full-Stokes check), sources/intents,
   and scan balance. Report these measurements.

2. `ms_import_asdm(asdm_path=sdm_path, workdir=workdir, ms_name=<ms_name if given>, execute=False)`
   -> run via `run-step.sh --wait 240`. Re-run on `status=running` until
   `status=done` (`rc=0`) -- a 65 GB SDM import can take 10--30 minutes.

3. `ms_verify_import(ms_path, online_flag_file)` -- confirm `ms_valid`,
   `flag_file_exists`, and `ready_for_preflag` are True (STOP if False).

4. `ms_spectral_window_list(ms_path)` -- inspect the converted MS SPWs.
   - If `spw:` was explicitly given, or if `spw_mode` is `continuum` (default)
     and the MS contains mixed continuum + spectral-line SPWs or dummy/setup
     SPWs (for example 2-corr `[RR,LL]` setup scans alongside 4-corr science
     SPWs, or narrow HI/line zoom windows alongside wide continuum SPWs):
     a. Inspect the first ~20 lines of `online_flag_file` with Read to check
        whether any online flag command contains `spw=`.
     b. Split the selected continuum science SPWs into `<workdir>/continuum.ms`
        via `ms_casa_task(task='split', params={'vis': ms_path, 'outputvis':
        '<workdir>/continuum.ms', 'spw': '<continuum_spw_ids>', 'datacolumn':
        'data', 'keepflags': True}, workdir=workdir, execute=False)` -> run via
        `run-step.sh --wait 240`.
     c. If `online_flag_file` has NO `spw=` tokens (the VLA default: antenna +
        timerange flags only), hand `<workdir>/continuum.ms` as `ms_path` and
        the same `online_flag_file` downstream. If `online_flag_file` DOES
        contain `spw=` tokens, note that explicitly and warn before renumbering.
   - Otherwise (all SPWs are already homogeneous continuum science SPWs, or
     `spw_mode: all`): keep the imported MS directly as `ms_path`.

**Output:** SDM summary (telescope, config, band, full-Stokes status, SPW
counts), imported MS path, online flag file path (`n_commands`), whether a
continuum split was performed (and which SPW IDs were kept/dropped), and the
exact `ms_path` + `online_flags` paths for downstream `inspect` and `precal`.
