#!/usr/bin/env bash
# MCP plugin entry point for ms-inspect. See scripts/plugin/launch.sh.
# Claude Code sets CLAUDE_PLUGIN_ROOT; in a clone it is the repo root. The launcher
# path is spelled from it so the plugin directory's validator can read it.
set -euo pipefail
CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
exec bash "${CLAUDE_PLUGIN_ROOT}/scripts/plugin/launch.sh" ms-inspect serve
