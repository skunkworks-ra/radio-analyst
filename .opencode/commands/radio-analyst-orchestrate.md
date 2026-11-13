---
description: "Orchestrate a continuum reduction of one MS (Stokes I, or IQUV on request) with stage subagents, each stage checked before the next. Same as /radio-analyst:orchestrate in Claude Code."
---
@.claude/skills/orchestrate/SKILL.md

Base directory for this skill: .claude/skills/orchestrate

In opencode, launch each stage with the subagent tool; the agent id is the name
after `radio-analyst:` in the stage table (for example `inspect-stage`). Where
the skill names the Agent tool or `subagent_type`, use the subagent tool and the
agent id. `{ri}` is `.claude/skills/radio-interferometry`. Emit the compact
`<stage_decision>{...}</stage_decision>` JSON block after each stage check;
token and cost accounting comes from the session exports. If a PNG you Read does
not reach you as an image, write `"png_reviewed": "not_viewed"` and do not
describe it.

ARGUMENTS: $ARGUMENTS
