// OpenCode hook adapter matching hooks/hooks.json (Claude Code plugin):
//   - Plugin init (SessionStart): scripts/plugin/ensure-env.sh --hook (detached)
//   - session.idle on root session (Stop / SessionEnd):
//       1. Export root session + child subagent sessions via client.session SDK
//       2. Pipe {"transcript_path": ..., "cwd": ...} to scripts/plugin/audit_hook.sh
//          (writes {workdir}/orchestrator/{seq:02d}_{stage}_try{try}.json)
//       3. Pipe {"transcript_path": ..., "cwd": ...} to scripts/plugin/session_end.sh
//          (writes {workdir}/accounting.json and rebuilds report.html once ms_report ran)
// Never throws: a hook failure must never break the user session.

import { spawn, spawnSync } from "node:child_process"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

function runShellHook(scriptPath, payload, env, timeoutMs) {
  try {
    const r = spawnSync("bash", [scriptPath], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      env,
      timeout: timeoutMs,
    })
    if (r.stderr && r.stderr.trim()) {
      console.error(r.stderr.trim())
    }
  } catch (err) {
    console.error(`radio-analyst opencode hook (${scriptPath}):`, err?.message || err)
  }
}

export const RadioAnalystHooks = async ({ client, directory }) => {
  const cwd = process.env.CLAUDE_PROJECT_DIR || directory
  const root = process.env.CLAUDE_PLUGIN_ROOT || directory
  const hookEnv = { ...process.env, CLAUDE_PROJECT_DIR: cwd, CLAUDE_PLUGIN_ROOT: root }

  // SessionStart parity: ensure the Python/CASA pixi environment is built in the background.
  try {
    const child = spawn("bash", [`${root}/scripts/plugin/ensure-env.sh`, "--hook"], {
      detached: true,
      stdio: "ignore",
      env: hookEnv,
    })
    child.unref()
  } catch (err) {
    console.error("radio-analyst ensure-env hook:", err?.message || err)
  }

  return {
    event: async ({ event }) => {
      if (event?.type !== "session.idle") return
      const sid = event.properties?.sessionID
      if (!sid || !client?.session) return

      let exportDir = null
      try {
        const s = await client.session.get({ path: { id: sid } })
        const info = s?.data
        // Only run root-session Stop / SessionEnd hooks (ignore child stage subagent idle events).
        if (!info || info.parentID) return

        const msgs = await client.session.messages({ path: { id: sid } })
        exportDir = mkdtempSync(join(tmpdir(), "ra-opencode-hook-"))
        const mainPath = join(exportDir, "session.json")
        writeFileSync(
          mainPath,
          JSON.stringify({ info, messages: msgs?.data ?? [] }),
          "utf8",
        )

        const kids = await client.session.children({ path: { id: sid } })
        for (const childInfo of kids?.data ?? []) {
          if (!childInfo?.id) continue
          const cMsgs = await client.session.messages({ path: { id: childInfo.id } })
          writeFileSync(
            join(exportDir, `session_${childInfo.id}.json`),
            JSON.stringify({ info: childInfo, messages: cMsgs?.data ?? [] }),
            "utf8",
          )
        }

        const hookPayload = { transcript_path: mainPath, cwd }
        runShellHook(`${root}/scripts/plugin/audit_hook.sh`, hookPayload, hookEnv, 30000)
        runShellHook(`${root}/scripts/plugin/session_end.sh`, hookPayload, hookEnv, 60000)
      } catch (err) {
        console.error("radio-analyst session.idle hook:", err?.message || err)
      } finally {
        if (exportDir) {
          try {
            rmSync(exportDir, { recursive: true, force: true })
          } catch {
            // ignore temp cleanup errors
          }
        }
      }
    },
  }
}
