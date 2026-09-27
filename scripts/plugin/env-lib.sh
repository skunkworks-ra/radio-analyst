# shellcheck shell=bash disable=SC2034  # variables are used by the sourcing scripts
# Shared helpers for the plugin's Python environment. Sourced by
# scripts/plugin/ensure-env.sh (SessionStart hook + background build) and by
# scripts/plugin/serve*.sh (MCP server launchers). Nothing here writes to stdout: for the
# launchers, stdout is the JSON-RPC stream.
#
# Layout when installed as a plugin (all under ${CLAUDE_PLUGIN_DATA}, which
# survives plugin updates; ${CLAUDE_PLUGIN_ROOT} is a per-version directory):
#
#   app/          copy of pixi.toml, pixi.lock, pyproject.toml, README.md, src/
#                 — the pixi project the environment is built from
#   app/.pixi/    the environment itself (unless pixi detached-environments)
#   env.stamp     source hash the current environment was built from
#   env.prefix    absolute path of the built environment prefix
#   build.lock/   held while a build runs (portable mkdir lock; holds a pid)
#   build.log     output of the current or most recent build
#   build.log.prev  output of the build before that

RA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RA_DATA="${CLAUDE_PLUGIN_DATA:-}"
RA_APP="$RA_DATA/app"
RA_STAMP="$RA_DATA/env.stamp"
RA_PREFIX_FILE="$RA_DATA/env.prefix"
RA_LOCK="$RA_DATA/build.lock"
RA_LOG="$RA_DATA/build.log"

# Files hashed (with src/) to decide whether a rebuild is needed. All of them,
# plus README.md, are copied into app/: pyproject.toml names README.md as the
# package readme, so the build needs it, but its content never changes the
# environment and is left out of the hash.
RA_SOURCE_FILES=(pixi.toml pixi.lock pyproject.toml)
RA_COPY_FILES=("${RA_SOURCE_FILES[@]}" README.md)

# Platforms pixi.toml builds for, as `uname -s`-`uname -m`. Kept in step with
# pixi.toml's `platforms` by tests/unit/test_plugin_env_scripts.py.
RA_SUPPORTED_PLATFORMS=(Linux-x86_64 Darwin-arm64)

ra_platform() {
    printf '%s-%s' "$(uname -s)" "$(uname -m)"
}

ra_platform_supported() {
    local p here
    here="$(ra_platform)"
    for p in "${RA_SUPPORTED_PLATFORMS[@]}"; do
        [[ "$here" == "$p" ]] && return 0
    done
    return 1
}

ra_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum | cut -d' ' -f1
    else
        shasum -a 256 | cut -d' ' -f1
    fi
}

# Content hash of everything the environment is built from. Content, not the
# plugin version: a plugin loaded in place from a local marketplace keeps its
# version string across edits.
ra_source_hash() {
    (
        cd "$RA_ROOT" || exit 1
        {
            for f in "${RA_SOURCE_FILES[@]}"; do
                printf '%s\n' "$f"
                cat "$f"
            done
            find src -type f ! -path '*/__pycache__/*' ! -name '*.pyc' | LC_ALL=C sort |
                while IFS= read -r f; do
                    printf '%s\n' "$f"
                    cat "$f"
                done
        } | ra_sha256
    )
}

ra_prefix() {
    [[ -f "$RA_PREFIX_FILE" ]] && cat "$RA_PREFIX_FILE"
}

# True when the built environment matches the current plugin sources.
ra_ready() {
    local prefix
    [[ -f "$RA_STAMP" ]] || return 1
    prefix="$(ra_prefix)" || return 1
    [[ -x "$prefix/bin/ms-inspect" ]] || return 1
    [[ "$(cat "$RA_STAMP")" == "$(ra_source_hash)" ]]
}

# True while another process holds the build lock. A lock whose pid is gone
# (killed build, reboot) is stale and is removed.
ra_build_running() {
    local pid
    [[ -d "$RA_LOCK" ]] || return 1
    pid="$(cat "$RA_LOCK/pid" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    # No pid yet: the holder is between mkdir and writing it. Only a pid-less
    # lock older than two minutes is treated as stale.
    if [[ -z "$pid" ]] && [[ -z "$(find "$RA_LOCK" -maxdepth 0 -mmin +2 2>/dev/null)" ]]; then
        return 0
    fi
    rm -rf "$RA_LOCK"
    return 1
}

# Start a build detached from the caller, so neither a hook timeout nor the
# MCP client killing a launcher can interrupt it half-way.
ra_spawn_build() {
    mkdir -p "$RA_DATA"
    if command -v setsid >/dev/null 2>&1; then
        setsid bash "$RA_ROOT/scripts/plugin/ensure-env.sh" --build >>"$RA_LOG" 2>&1 </dev/null &
    else
        nohup bash "$RA_ROOT/scripts/plugin/ensure-env.sh" --build >>"$RA_LOG" 2>&1 </dev/null &
    fi
}
