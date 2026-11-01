// opencode adapter for scripts/plugin/reduce_hook.py: the same hook the Claude Code
// plugin runs (hooks/hooks.json). Each opencode event is rewritten into the Claude hook
// JSON and piped to reduce_hook.py, so both harnesses log and reconcile against one
// contract (stages.json). No logic of its own beyond the translation.
//
//   command.execute.before  /radio-analyst-<name> -> UserPromptSubmit as /radio-analyst:<name>
//   chat.message        -> UserPromptSubmit
//   tool.execute.after  -> PostToolUse (opencode MCP names ms-inspect_x become
//                          mcp__plugin_radio-analyst_ms-inspect__x; skill {name} -> Skill {skill})
//   session.idle        -> Stop; a "block" reason goes to .reduce_stop_reason, once per
//                          session (stop_hook_active after); the launcher sends it back
//
// reduce_hook.py from $CLAUDE_PLUGIN_ROOT (the container sets it), else the project dir (a clone);
// the log goes to $CLAUDE_PROJECT_DIR, else the project dir.
import { spawnSync } from "node:child_process"
import { writeFileSync } from "node:fs"

const MCP_RE = /^(ms-inspect|ms-modify|ms-create)_(.+)$/

function claudeTool(tool, args) {
  const m = MCP_RE.exec(tool)
  if (m) return [`mcp__plugin_radio-analyst_${m[1]}__${m[2]}`, args ?? {}]
  if (tool === "skill") return ["Skill", { skill: args?.name }]
  return [tool, args ?? {}]
}

function runHook(root, ev) {
  const hook = `${root}/scripts/plugin/reduce_hook.py`
  const r = spawnSync("python3", [hook], { input: JSON.stringify(ev), encoding: "utf8", timeout: 10000 })
  if (r.stderr) console.error(r.stderr.trim())
  const out = (r.stdout || "").trim()
  return out ? JSON.parse(out) : null
}

export const ReduceHook = async ({ directory }) => {
  const cwd = process.env.CLAUDE_PROJECT_DIR || directory
  const root = process.env.CLAUDE_PLUGIN_ROOT || directory
  const sentBack = new Set()
  return {
    "command.execute.before": async (input) => {
      if (!input.command.startsWith("radio-analyst-")) return
      const prompt = `/radio-analyst:${input.command.slice("radio-analyst-".length)} ${input.arguments}`
      runHook(root, { hook_event_name: "UserPromptSubmit", session_id: input.sessionID, cwd, prompt })
    },
    "chat.message": async (input, output) => {
      const prompt = (output.parts || []).filter((p) => p.type === "text").map((p) => p.text).join("\n")
      runHook(root, { hook_event_name: "UserPromptSubmit", session_id: input.sessionID, cwd, prompt })
    },
    "tool.execute.after": async (input, output) => {
      const [tool_name, tool_input] = claudeTool(input.tool, input.args)
      runHook(root, {
        hook_event_name: "PostToolUse",
        session_id: input.sessionID,
        cwd,
        tool_name,
        tool_input,
        tool_response: output.output,
      })
    },
    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const sid = event.properties?.sessionID
      if (!sid) return
      const out = runHook(root, {
        hook_event_name: "Stop",
        session_id: sid,
        cwd,
        stop_hook_active: sentBack.has(sid),
      })
      if (out?.decision !== "block") return
      sentBack.add(sid)
      // `opencode run` exits at idle, so a prompt from here never reaches the model;
      // the launcher continues the session with this text (run-isolated.sh).
      writeFileSync(`${cwd}/.reduce_stop_reason`, out.reason)
    },
  }
}
