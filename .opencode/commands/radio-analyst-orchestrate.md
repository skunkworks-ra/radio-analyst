---
description: "Orchestrate a continuum reduction of one MS (Stokes I, or IQUV on request) with stage subagents, each stage checked before the next. Same as /radio-analyst:orchestrate in Claude Code."
agent: orchestrate
---
@.claude/skills/orchestrate/SKILL.md

Base directory for this skill: .claude/skills/orchestrate

In opencode, launch each stage with the `task` subagent tool; the agent id is
the name after `radio-analyst:` in the stage table (for example `inspect-stage`).
Where the skill names the Agent tool or `subagent_type`, use `task` and the
agent id. `{ri}` is `.claude/skills/radio-interferometry`. Record every stage
decision by calling the `ms-create_ms_record_stage_decision` tool (never prose
`<stage_decision>` XML), and immediately launch the next `task(...)`,
diagnostic, or `ms-create_ms_report` call whenever `decision` is `"next"` or
`"retry"` (never end a turn with text-only output unless `decision` is
`"stop_ask_user"` or the final report is complete); token and cost accounting
comes from the session exports. If a PNG you Read does not reach you as an
image, pass `png_reviewed="not_viewed"` and do not describe it.

ARGUMENTS: $ARGUMENTS
