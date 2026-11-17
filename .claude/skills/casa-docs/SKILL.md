---
description: >
  Look up CASA task documentation. Auto-invoked when a user asks a CASA
  task/parameter question directly, or when a skill names a CASA Docs page.
allowed-tools: Read,
               mcp__plugin_radio-analyst_ms-inspect__ms_casa_task_spec,
               mcp__plugin_radio-analyst_ms-inspect__ms_casa_task_lookup,
               WebFetch
---

# CASA Documentation Lookup

Two sources, each for one thing:

- **Parameters** (name, type, default, sub-parameter): `ms_casa_task_spec(task)`.
  It reads the installed CASA. Its defaults win over any default in prose.
- **Prose and examples**: the task's CASA Docs page, `docs_path` in the same
  result. The copy is in `tasks/` next to this file; NOTICE names the CASA Docs tag.

Never answer a CASA task question from memory and present it as documentation.

## Procedure

1. Call `ms_casa_task_spec(task)`.
2. Read `docs_path`. A large page is an index: one line per piece, with its
   size and the headings it covers. Read only the piece you need. Examples
   holds call patterns; Description holds parameter and mode prose.
3. Quote the text you rely on, and name the task and piece.

## Not copied

GUI tasks (plotms, plotcal, imview, msview) and testconcat have no page:
`docs_path` is null. Then call `ms_casa_task_lookup(task)` and WebFetch its
`docs_url`. If that fails too, say the documentation is not available; do
not guess a URL.
