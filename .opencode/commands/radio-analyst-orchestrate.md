---
description: "Orchestrate a continuum reduction of one MS (Stokes I, or IQUV on request) with stage subagents, each stage checked before the next. Same as /radio-analyst:orchestrate in Claude Code."
agent: orchestrate
---
@.claude/skills/orchestrate/SKILL.md

Base directory for this skill: .claude/skills/orchestrate

In opencode, launch each stage with the `task` subagent tool; the agent id is
the name after `radio-analyst:` in the stage table (for example `inspect-stage`).
Where the skill names the Agent tool or `subagent_type`, use `task` and the
agent id. `{ri}` is `.claude/skills/radio-interferometry`. Emit the compact
`<stage_decision>{...}</stage_decision>` JSON block in the same assistant turn
as the next `task(...)` or diagnostic/`ms-create_ms_report` tool call whenever
`decision` is `"next"` or `"retry"` (never end a turn with text-only
`<stage_decision>` unless `decision` is `"stop_ask_user"` or the final report is
complete); token and cost accounting comes from the session exports. If a PNG
you Read does not reach you as an image, write `"png_reviewed": "not_viewed"`
and do not describe it.

ARGUMENTS: $ARGUMENTS
