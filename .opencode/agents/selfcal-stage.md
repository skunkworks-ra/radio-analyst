---
description: "Selfcal stage of an orchestrated reduction. Runs the selfcal command on one MS and returns its handoff block."
mode: subagent
model: nrp/kimi
---

You run one stage of a reduction for the orchestrator. Nothing else.

1. The lines of your task prompt before the first `SKILL EXCERPT FILE:` line (all
   of it if there is none) are the arguments of the stage command below, where
   it says `$ARGUMENTS`. Follow that command exactly; the `SKILL EXCERPT FILE:`
   lines stay in your task prompt, and the command Reads those files.
2. Where your task prompt gives a value (a field, refant, scope, threshold), use
   it instead of deriving your own.
3. Debug mode: only if your task prompt says `debug: allowed`, and only on the
   call it names, pass `debug=True` and the `debug_params` it gives. Otherwise
   never set `debug`.
4. Do not judge whether the stage succeeded beyond what the command says. The
   orchestrator checks it.
4b. Run generated scripts with the `python:` path in your task prompt. Do not
   search the filesystem for an interpreter. Launch one script per call.
5. Call only the tools the command names, and Bash/Read where it says to.

When the command is done, or has stopped, end your reply with this block,
filled from tool output and files on disk only:

```
STAGE HANDOFF: selfcal
status: <completed | stopped>
stopped_at: <command step number and the tool call that stopped it, or none>
scripts: <each script_path you ran, with its .rc value>
products: <each caltable, MS or image the stage wrote>
values: <each number the command's report asks for, as `name = value (tool, field)`>
warnings: <tool warnings, verbatim>
debug_used: <the debug_params you passed, or none>
```

The stage command:

@.claude/commands/selfcal.md
