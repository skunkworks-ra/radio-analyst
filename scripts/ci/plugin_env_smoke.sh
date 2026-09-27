#!/usr/bin/env bash
# Free (no-LLM) end-to-end test of the installed-plugin environment path, with
# real pixi: the path an installed plugin takes (CLAUDE_PLUGIN_DATA set), which
# mcp_smoke.py on its own does not exercise.
#
#   1. cold SessionStart hook: tells the user, starts a detached build
#   2. a server launched mid-build exits with "still being built"
#   3. the build completes; casatools, casatasks and mcp import from it
#   4. all three servers start from the built env and list the tools
#      tool_manifest.json expects, with no build triggered by the launch
#   5. ms_observation_info answers on a real MS (mcp_smoke.py)
#   6. warm hook: silent to the user, hands Claude the interpreter path
#   7. a source change (a plugin update) is rebuilt while a launcher waits
#
# Usage: scripts/ci/plugin_env_smoke.sh [smoke.ms]
# Env:   CLAUDE_PLUGIN_DATA (default .scratch/plugin-data; wiped first)
#        BUILD_TIMEOUT      (seconds to wait for the first build; default 1800)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SMOKE_MS="${1:-smoke.ms}"
export CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA:-$ROOT/.scratch/plugin-data}"
rm -rf "${CLAUDE_PLUGIN_DATA:?}"
mkdir -p "$HOME/.casa/data"

# shellcheck source=scripts/plugin/env-lib.sh
source scripts/plugin/env-lib.sh

fail() {
    echo "FAIL: $*" >&2
    if [[ -f "$RA_LOG" ]]; then
        echo "---- $RA_LOG (tail) ----" >&2
        tail -n 60 "$RA_LOG" >&2
    fi
    exit 1
}
builds_started() { grep -c '^=== .*environment build from' "$RA_LOG" 2>/dev/null || true; }
builds_completed() { grep -c '^=== .*build complete' "$RA_LOG" 2>/dev/null || true; }

echo "=== 1. cold hook"
out="$(bash scripts/plugin/ensure-env.sh --hook)"
echo "$out"
grep -q '"systemMessage":"radio-analyst: building' <<<"$out" || fail "cold hook did not announce a build"

echo "=== 2. launcher during the build"
set +e
# timeout: a regression that starts a real server here must fail, not hang.
err="$(RADIO_MCP_ENV_WAIT=3 timeout 120 bash scripts/plugin/serve.sh </dev/null 2>&1 >/dev/null)"
rc=$?
set -e
echo "$err"
[[ $rc -ne 0 ]] || fail "launcher exited 0 before the environment existed"
grep -q "still being built" <<<"$err" || fail "launcher did not report the build in progress"

echo "=== 3. wait for the build (timeout ${BUILD_TIMEOUT:-1800}s)"
start=$(date +%s)
until ra_ready; do
    ra_build_running || { sleep 3; ra_ready && break; fail "build exited without a usable environment"; }
    (($(date +%s) - start < ${BUILD_TIMEOUT:-1800})) || fail "build did not finish in time"
    sleep 10
done
echo "first build took $(($(date +%s) - start))s"
PY="$(ra_prefix)/bin/python"
"$PY" -c "import casatools, casatasks, mcp; from importlib.metadata import version; print('casatools', casatools.version_string(), '| mcp', version('mcp'))" ||
    fail "the built environment cannot import casatools/casatasks/mcp"

echo "=== 4. all three servers from the built env"
# With pixi off PATH: a ready environment must launch without it, and the
# in-repo fallback (which needs pixi) cannot quietly stand in for it.
pixi_dir="$(dirname "$(command -v pixi)")"
NO_PIXI_PATH="$(tr ':' '\n' <<<"$PATH" | grep -vxF "$pixi_dir" | paste -sd: -)"
before="$(builds_started)"
PATH="$NO_PIXI_PATH" "$PY" - <<'EOF' || fail "server handshake without pixi on PATH"
import asyncio, json, os, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

expected = json.load(open("scripts/ci/tool_manifest.json"))["tools"]
scripts = {"ms-inspect": "serve.sh", "ms-modify": "serve-modify.sh", "ms-create": "serve-create.sh"}

async def check(server: str) -> None:
    # env= explicitly: the client otherwise passes only a safe subset
    # (HOME, PATH, ...), and the launcher would not see CLAUDE_PLUGIN_DATA.
    params = StdioServerParameters(
        command="bash", args=[f"scripts/plugin/{scripts[server]}"], env=dict(os.environ)
    )
    t0 = time.monotonic()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ready = time.monotonic() - t0
            names = {t.name for t in (await session.list_tools()).tools}
    missing, extra = set(expected[server]) - names, names - set(expected[server])
    print(f"{server}: {len(names)} tools, initialized in {ready:.1f}s")
    assert not missing and not extra, (server, missing, extra)

async def main() -> None:
    for server in scripts:
        await check(server)

asyncio.run(main())
EOF
[[ "$(builds_started)" == "$before" ]] || fail "launching a server with a ready environment started a build"

echo "=== 5. tool call on a real MS"
[[ -d "$SMOKE_MS" ]] || "$PY" scripts/ci/generate_smoke_ms.py "$SMOKE_MS"
PATH="$NO_PIXI_PATH" "$PY" scripts/ci/mcp_smoke.py "$SMOKE_MS" || fail "mcp_smoke.py"

echo "=== 6. warm hook"
out="$(bash scripts/plugin/ensure-env.sh --hook)"
echo "$out"
grep -q '"systemMessage"' <<<"$out" && fail "warm hook shows the user a message"
grep -qF "$PY" <<<"$out" || fail "warm hook does not hand Claude the interpreter path"

echo "=== 7. plugin update: a source change rebuilds while the launcher waits"
touched=src/ms_create/__init__.py
cp "$touched" "$touched.orig"
trap 'mv -f "$ROOT/$touched.orig" "$ROOT/$touched"' EXIT
echo "# plugin_env_smoke: simulated update" >>"$touched"
completed="$(builds_completed)"
start=$(date +%s)
RADIO_MCP_ENV_WAIT=600 "$PY" - <<'EOF' || fail "ms-create did not come up after the rebuild"
import asyncio, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main() -> None:
    params = StdioServerParameters(
        command="bash", args=["scripts/plugin/serve-create.sh"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("ms-create:", len((await session.list_tools()).tools), "tools after rebuild")

asyncio.run(main())
EOF
[[ "$(builds_completed)" -eq $((completed + 1)) ]] || fail "expected exactly one rebuild"
echo "update rebuild + server start took $(($(date +%s) - start))s"

echo "PASS"
