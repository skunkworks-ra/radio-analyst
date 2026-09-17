---
description: >
  Look up CASA task documentation and source code. Auto-invoked when a user
  asks a CASA task/parameter question directly, or when the radio-interferometry
  skill hits a question its own reference files do not answer.
allowed-tools: ms_casa_task_lookup, WebFetch
---

# CASA Documentation Lookup

You use `ms_casa_task_lookup` and `WebFetch` as your instruments — the tool
resolves a task name to its URLs, you fetch and read the actual content.
Never answer a CASA task/parameter question from training memory and present
it as documentation or source-verified — always fetch first.

## Procedure

1. Call `ms_casa_task_lookup(task_name)`. It returns `docs_url` and
   `source_url` for the task, or `status=NOT_FOUND` if the task is not in
   the bundled index (check spelling; it may be a task added to CASA since
   the index was built).
2. Decide docs vs. source (see below).
3. `WebFetch` the chosen URL. Quote the fetched text for any parameter
   default, mode description, or behavior claim. Do not paraphrase from
   memory.
4. State which source you used (docs page or source file) and, if the docs
   page shows one, the CASA version it describes — defaults can change
   between releases.

## Docs vs. source — which one to read

**Default to docs** (`docs_url`) for anything about *intended behavior*:
what a parameter does, what a mode means, expected inputs/outputs, the
documented default value.

**Go to source** (`source_url`) only when docs do not resolve the question:

- the docstring is silent or ambiguous on the point you need,
- you need the *actual current* default (docs can lag a code change),
- the question is about an edge case, internal algorithm choice, or
  parameter interaction docs do not cover.

**If docs and source disagree**, source wins for describing current
behavior — but say so explicitly in the answer and flag the docs page as
stale. Do not silently pick one and hide the conflict.

## Failure modes

- `status=NOT_FOUND` from the lookup tool: do not guess a URL. Say the task
  is not in the bundled index and ask the user to confirm the task name.
- `WebFetch` 404s on a URL the tool returned: the docs site or the casa6
  repo layout has likely moved since the index was built. Say so; do not
  retry with a guessed alternate URL.
