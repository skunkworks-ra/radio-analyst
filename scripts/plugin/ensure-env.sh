#!/usr/bin/env bash
# Build the plugin's Python/CASA environment under ${CLAUDE_PLUGIN_DATA}.
#
#   ensure-env.sh --hook    SessionStart hook. Returns in well under a second:
#                           if the environment is stale or missing it starts a
#                           detached --build and tells the user and Claude so.
#   ensure-env.sh --build   Do the build (normally spawned detached; output
#                           goes to ${CLAUDE_PLUGIN_DATA}/build.log).
#
# The first build is a conda solve plus ~500 MB of casatools wheels, far past
# the MCP startup timeout, which is why it does not run inside the server
# launchers. Later builds (plugin update, same pixi.lock) only re-sync the
# sources and reuse the installed packages.
set -euo pipefail

# shellcheck source=scripts/plugin/env-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/env-lib.sh"

json_escape() {
    sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '
}

# SessionStart output: systemMessage is shown to the user, additionalContext
# goes to Claude.
emit() {
    printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
        "$(printf '%s' "$1" | json_escape)" "$(printf '%s' "$2" | json_escape)"
}

run_hook() {
    # Not running as an installed plugin (e.g. a clone with this hook wired
    # by hand): the launchers use the repo's own pixi environment instead.
    [[ -n "$RA_DATA" ]] || exit 0

    if ! command -v pixi >/dev/null 2>&1; then
        emit "radio-analyst: pixi is not on PATH, so the ms-inspect / ms-modify / ms-create MCP servers cannot start. Install it (curl -fsSL https://pixi.sh/install.sh | bash), restart Claude Code, and the environment will build automatically." \
            "The radio-analyst MCP servers (ms-inspect, ms-modify, ms-create) are unavailable because pixi is not installed. If the user asks for a Measurement Set tool, tell them to install pixi from https://pixi.sh and restart Claude Code."
        exit 0
    fi

    ra_ready && exit 0

    ra_build_running || ra_spawn_build
    emit "radio-analyst: building the Python/CASA environment in the background (first run or plugin update; the first build downloads ~1 GB and can take several minutes). Log: $RA_LOG. When it finishes, reconnect the servers with /mcp." \
        "The radio-analyst MCP servers (ms-inspect, ms-modify, ms-create) are unavailable until their environment finishes building in the background (log: $RA_LOG). If the user asks for a Measurement Set tool before then, tell them the build is still running and that they can reconnect the servers with /mcp once it completes."
}

run_build() {
    [[ -n "$RA_DATA" ]] || { echo "CLAUDE_PLUGIN_DATA is not set" >&2; exit 1; }
    mkdir -p "$RA_DATA"

    if ! mkdir "$RA_LOCK" 2>/dev/null; then
        if ra_build_running; then
            echo "[$(date)] another build is already running; exiting"
            exit 0
        fi
        mkdir "$RA_LOCK" 2>/dev/null || exit 0
    fi
    echo $$ >"$RA_LOCK/pid"
    trap 'rm -rf "$RA_LOCK"' EXIT

    echo "=== [$(date)] radio-analyst environment build from $RA_ROOT"
    if ra_ready; then
        echo "environment already up to date"
        exit 0
    fi
    command -v pixi >/dev/null 2>&1 || { echo "pixi is not on PATH" >&2; exit 1; }

    local hash prefix
    hash="$(ra_source_hash)"

    # Sync the sources. app/.pixi is left in place so unchanged packages are
    # reused; src/ is replaced wholesale so deleted modules do not linger.
    mkdir -p "$RA_APP"
    for f in "${RA_COPY_FILES[@]}"; do
        cp "$RA_ROOT/$f" "$RA_APP/$f"
    done
    rm -rf "$RA_APP/src"
    cp -R "$RA_ROOT/src" "$RA_APP/src"
    find "$RA_APP/src" -name __pycache__ -prune -exec rm -rf {} +

    # --frozen: install exactly what pixi.lock pins, never re-solve.
    pixi install --manifest-path "$RA_APP/pixi.toml" --frozen
    prefix="$(pixi run --manifest-path "$RA_APP/pixi.toml" --frozen \
        python -c 'import sys; print(sys.prefix)')"

    # casatools is locked for linux-64 only; elsewhere install it with pip.
    # The servers import it lazily and report CASA_NOT_AVAILABLE themselves,
    # so a failure here is logged but does not block them from starting.
    mkdir -p "$HOME/.casa/data"
    if ! "$prefix/bin/python" -c 'import casatools' 2>/dev/null; then
        echo "casatools not importable; trying pip install casatools casatasks"
        "$prefix/bin/python" -m pip install casatools casatasks --quiet ||
            echo "WARNING: pip install of casatools/casatasks failed"
        "$prefix/bin/python" -c 'import casatools' ||
            echo "WARNING: casatools still not importable; CASA-backed tools will return CASA_NOT_AVAILABLE"
    fi

    printf '%s\n' "$prefix" >"$RA_PREFIX_FILE"
    printf '%s\n' "$hash" >"$RA_STAMP"
    echo "=== [$(date)] build complete: $prefix"
}

case "${1:-}" in
    --hook) run_hook ;;
    --build) run_build ;;
    *)
        echo "usage: $0 --hook | --build" >&2
        exit 2
        ;;
esac
