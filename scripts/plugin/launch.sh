#!/usr/bin/env bash
# MCP server launcher shared by bin/serve.sh, bin/serve-modify.sh and
# bin/serve-create.sh.
#
#   launch.sh <server-executable> <pixi-task>
#
# Installed as a plugin (CLAUDE_PLUGIN_DATA set): exec the server from the
# environment scripts/plugin/ensure-env.sh built under CLAUDE_PLUGIN_DATA. If
# that environment is missing or stale, start (or wait on) a detached build
# for up to RADIO_MCP_ENV_WAIT seconds, then exit with a message rather than
# run into the MCP startup timeout mid-install.
#
# Anywhere else (a clone registered by hand): the repo's own pixi environment,
# via the pixi task.
#
# stderr only — stdout is the JSON-RPC stream.
set -euo pipefail

SERVER="$1"
TASK="$2"

# shellcheck source=scripts/plugin/env-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/env-lib.sh"

need_pixi() {
    command -v pixi >/dev/null 2>&1 && return 0
    cat >&2 <<EOF
[$SERVER] pixi is not on PATH, so this server cannot start.

Install pixi (https://prefix.dev), then restart Claude Code:
    curl -fsSL https://pixi.sh/install.sh | bash

Or run the server from a Python >=3.12 environment without pixi:
    pip install "${RA_ROOT}[casa]"
    $SERVER
EOF
    exit 1
}

exec_server() {
    local prefix
    prefix="$(ra_prefix)"
    export PATH="$prefix/bin:$PATH"
    export RADIO_MCP_TRANSPORT=stdio
    exec "$prefix/bin/$SERVER"
}

if [[ -z "$RA_DATA" ]]; then
    need_pixi
    MANIFEST="$RA_ROOT/pixi.toml"
    pixi install --manifest-path "$MANIFEST" --quiet
    if ! pixi run --manifest-path "$MANIFEST" python -c "import casatools" 2>/dev/null; then
        echo "[$SERVER] Installing CASA tools (first run only)..." >&2
        pixi run --manifest-path "$MANIFEST" python -m pip install casatools casatasks --quiet
    fi
    exec pixi run --manifest-path "$MANIFEST" "$TASK"
fi

ra_ready && exec_server
need_pixi

ra_build_running || ra_spawn_build
waited=0
while ((waited < ${RADIO_MCP_ENV_WAIT:-20})); do
    sleep 1
    waited=$((waited + 1))
    ra_ready && exec_server
    # The build exited without producing a usable environment. (Give a
    # just-spawned build a few seconds to take the lock first.)
    ra_build_running || ((waited < 3)) || break
done

if ra_build_running; then
    echo "[$SERVER] The radio-analyst environment is still being built in the background (first run or plugin update)." >&2
    echo "[$SERVER] Follow it in $RA_LOG, then reconnect with /mcp." >&2
else
    echo "[$SERVER] The radio-analyst environment build failed. See $RA_LOG." >&2
    echo "[$SERVER] Retry by reconnecting with /mcp, or run: CLAUDE_PLUGIN_DATA=\"$RA_DATA\" bash \"$RA_ROOT/scripts/plugin/ensure-env.sh\" --build" >&2
fi
exit 1
