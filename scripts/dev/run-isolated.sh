#!/usr/bin/env bash
# One isolated agent run: a fresh podman container, the plugin installed from a
# commit into an empty HOME, the environment built cold, then one headless
# session at a given model and effort. Nothing on the host is reused except the
# image, so every run starts from the same state.
#
# DEBUG=1 adds set -x. Progress: <run_dir>/progress.log; all output: container.log.
# Usage:
#   scripts/dev/run-isolated.sh --sha <commit> --model <model> --effort <level> \
#       --prompt <file> --ms <path.ms> [--allowed-tools "<tools>"] [--harness claude|opencode]
#       [--no-plugin]
# --no-plugin: the A/B baseline. The CASA environment is built from $SHA, the
# plugin is not installed (no skills, commands, MCP servers or hooks), and the
# interpreter path goes into ./CLAUDE.md (claude) or ./AGENTS.md (opencode).
#
# Credentials: export CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or
# ANTHROPIC_API_KEY. Passed into the container by name; never written to disk.
# --harness opencode: --model is provider/model (e.g. opencode/glm-5.3),
# --effort default leaves the model's reasoning level alone, anything else is
# passed as --variant. Credentials: $OPENCODE_AUTH (default
# ~/.local/share/opencode/auth.json), mounted read-only, never copied to /out.
# Custom providers (e.g. nrp/...): $OPENCODE_CONFIG (default
# ~/.config/opencode/opencode.jsonc), mounted read-only; only its provider block
# is copied into the container's global config, never to /out.
# CASA_DATA=<dir> (opencode only): seed ~/.casa/data from a host copy instead of
# downloading it, for when the NRAO data server is down.
#
# Output: $RUNS_ROOT/<run_id>/ with meta.env, prompt.txt, trace.jsonl,
# claude.stderr, build.log, timings.env and workdir/ (everything the run wrote
# except the MS itself).
#
# Steps follow .github/workflows/plugin-ci.yml (smoke-llm job).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNS_ROOT="${RUNS_ROOT:-/var/mnt/fast/radio_analyst_runs}"
IMAGE="${IMAGE:-radio-analyst-ci:local}"

SHA="" MODEL="" EFFORT="" PROMPT="" MS="" ALLOWED_TOOLS="" HARNESS="claude" NO_PLUGIN=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sha) SHA="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --effort) EFFORT="$2"; shift 2 ;;
        --prompt) PROMPT="$2"; shift 2 ;;
        --ms) MS="$2"; shift 2 ;;
        --allowed-tools) ALLOWED_TOOLS="$2"; shift 2 ;;
        --harness) HARNESS="$2"; shift 2 ;;
        --no-plugin) NO_PLUGIN=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

die() { echo "run-isolated: $*" >&2; exit 1; }
[[ -n "$SHA" && -n "$MODEL" && -n "$EFFORT" && -n "$PROMPT" && -n "$MS" ]] \
    || die "--sha, --model, --effort, --prompt and --ms are required"
[[ "$HARNESS" == "claude" || "$HARNESS" == "opencode" ]] \
    || die "harness '$HARNESS' is not wired; use claude or opencode"
[[ -f "$PROMPT" ]] || die "prompt file not found: $PROMPT"
[[ -f "$MS/table.info" ]] || die "not a Measurement Set: $MS"
OPENCODE_AUTH="${OPENCODE_AUTH:-$HOME/.local/share/opencode/auth.json}"
OPENCODE_CONFIG="${OPENCODE_CONFIG:-$HOME/.config/opencode/opencode.jsonc}"
if [[ "$HARNESS" == "claude" ]]; then
    [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}${ANTHROPIC_API_KEY:-}" ]] \
        || die "set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY"
else
    [[ -f "$OPENCODE_AUTH" ]] || die "opencode credentials not found: $OPENCODE_AUTH"
fi
FULL_SHA="$(git -C "$ROOT" rev-parse --verify "$SHA^{commit}")" \
    || die "commit not found: $SHA"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_${HARNESS}${NO_PLUGIN:+-noplugin}_${MODEL//\//-}_${EFFORT}_${FULL_SHA:0:7}"
OUT="$RUNS_ROOT/$RUN_ID"
mkdir -p "$OUT"
cp "$PROMPT" "$OUT/prompt.txt"
cat >"$OUT/meta.env" <<EOF
run_id=$RUN_ID
sha=$FULL_SHA
harness=$HARNESS
model=$MODEL
effort=$EFFORT
ms=$(cd "$MS" && pwd)
allowed_tools=$ALLOWED_TOOLS
no_plugin=${NO_PLUGIN:-0}
casa_data=${CASA_DATA:-}
launcher_sha256=$(sha256sum "$ROOT/scripts/dev/run-isolated.sh" | cut -d" " -f1)
image=$IMAGE
image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || echo none)
EOF

podman image exists "$IMAGE" \
    || podman build -t "$IMAGE" -f "$ROOT/docker/ci.Dockerfile" "$ROOT/docker"

echo "run-isolated: $OUT"

# label=disable: read the repo and the MS without relabelling host files.
# keep-id: the container's uid 1000 (analyst) is the host user, so /out is writable.
POD=(podman run --rm -i
    --userns=keep-id --user analyst
    --security-opt label=disable
    -v "$ROOT:/src:ro"
    -v "$(cd "$MS" && pwd):/data/input.ms:ro"
    -v "$OUT:/out"
    -e SHA="$FULL_SHA" -e MODEL="$MODEL" -e EFFORT="$EFFORT"
    -e ALLOWED_TOOLS="$ALLOWED_TOOLS" -e NO_PLUGIN="$NO_PLUGIN" -e DEBUG="${DEBUG:-}")

if [[ "$HARNESS" == "opencode" ]]; then
SEED=()
[[ -n "${CASA_DATA:-}" ]] && SEED=(-v "$CASA_DATA:/casadata:ro")
[[ -f "$OPENCODE_CONFIG" ]] && SEED+=(-v "$OPENCODE_CONFIG:/secrets/opencode-config.jsonc:ro")
"${POD[@]}" -v "$OPENCODE_AUTH:/secrets/opencode-auth.json:ro" "${SEED[@]}" \
    "$IMAGE" bash -s <<'INNER' 2>&1 | tee "$OUT/container.log"
set -euo pipefail
[[ -n "$DEBUG" ]] && set -x
step() { echo "[$(date -u +%T)] $*" | tee -a /out/progress.log; }
trap 'rc=$?; [[ $rc -ne 0 ]] && step "FAILED rc=$rc at line $LINENO: $BASH_COMMAND"' EXIT
step "start harness=opencode sha=$SHA model=$MODEL effort=$EFFORT"
t0=$(date +%s)
git config --global --add safe.directory '*'
step "clone + checkout"
git clone -q /src /work/plugin
git -C /work/plugin checkout -q "$SHA"
mkdir -p "$HOME/.casa/data" /work/run /work/pd "$HOME/.local/share/opencode"
cp /secrets/opencode-auth.json "$HOME/.local/share/opencode/auth.json"
if [[ -f /secrets/opencode-config.jsonc ]]; then
    step "providers from host opencode config"
    mkdir -p "$HOME/.config/opencode"
    python3 - <<'PYEOF'
import json, os, re
txt = open("/secrets/opencode-config.jsonc").read()
txt = re.sub(r"(?m)^\s*//.*$", "", txt)
txt = re.sub(r",(\s*[}\]])", r"\1", txt)
prov = json.loads(txt).get("provider", {})
json.dump({"$schema": "https://opencode.ai/config.json", "provider": prov},
          open(os.path.expanduser("~/.config/opencode/opencode.json"), "w"), indent=2)
print("providers:", ", ".join(sorted(prov)))
PYEOF
fi
if [[ -d /casadata ]]; then
    step "seed casa data from host copy"
    rm -rf "$HOME/.casa/data" && cp -r /casadata "$HOME/.casa/data" && rm -f "$HOME/.casa/data/data_update.lock"
fi
step "copy MS"
cp -r /data/input.ms /work/run/
cd /work/run

# What the Claude plugin install provides, laid out for opencode: the
# environment under a plugin data dir, the repo's .claude/skills + .claude/commands
# and its .opencode/ (commands /radio-analyst-<name>, the reduce-hook plugin), all
# from $SHA, the three MCP servers from plugin.json, and the SessionStart hook's
# interpreter line.
step "env build (cold, about 5 min)"
t1=$(date +%s)
export CLAUDE_PLUGIN_ROOT=/work/plugin CLAUDE_PLUGIN_DATA=/work/pd
bash /work/plugin/scripts/plugin/ensure-env.sh --build >/out/build.log 2>&1
PY="$(source /work/plugin/scripts/plugin/env-lib.sh && ra_prefix)/bin/python"
[[ -x "$PY" ]] || { echo "FAIL: plugin environment not built" >&2; exit 1; }
t2=$(date +%s)
if [[ -n "$NO_PLUGIN" ]]; then
echo "Python with casatools and casatasks installed: $PY" >AGENTS.md
step "env built in $((t2 - t1)) s; no plugin"
else
mkdir -p .claude
cp -a /work/plugin/.claude/skills /work/plugin/.claude/commands .claude/
cp -a /work/plugin/.opencode .opencode
# `opencode run --command` does not expand @file, so inline each skill a command
# names (body without frontmatter), as Claude Code injects it on /radio-analyst:<skill>.
python3 - <<'PYEOF'
import pathlib, re
for cmd in pathlib.Path(".opencode/commands").glob("*.md"):
    t = cmd.read_text()
    m = re.search(r"^@(\S+/SKILL\.md)$", t, re.M)
    if m:
        body = pathlib.Path(m.group(1)).read_text().split("---", 2)[2].lstrip()
        cmd.unlink()
        cmd.write_text(t.replace(m.group(0), body))
PYEOF
export CLAUDE_PROJECT_DIR=/work/run
python3 - <<'PYEOF'
import json
srv = {"ms-inspect": "serve.sh", "ms-modify": "serve-modify.sh", "ms-create": "serve-create.sh"}
mcp = {n: {"type": "local", "command": ["bash", f"/work/plugin/scripts/plugin/{f}"],
           "environment": {"CLAUDE_PLUGIN_ROOT": "/work/plugin", "CLAUDE_PLUGIN_DATA": "/work/pd"},
           "timeout": 60000}
       for n, f in srv.items()}
json.dump({"$schema": "https://opencode.ai/config.json", "mcp": mcp}, open("opencode.json", "w"), indent=2)
PYEOF
echo "radio-analyst plugin: run Python/CASA scripts generated by the ms-modify / ms-create tools (and ms-simulator scripts) with this interpreter, which has casatools and casatasks installed: $PY" >AGENTS.md
step "env built in $((t2 - t1)) s; mcp: $(opencode mcp list 2>&1 | grep -o -E 'ms-(inspect|modify|create).*(connected|failed|disabled)' | tr -s ' ' | tr '\n' ';')"
fi

# A persistent server holds the session (and the hook plugin's state): a bare
# `opencode run` exits at idle and its session is gone afterwards, so neither the
# Stop send-back nor the export works without it.
opencode serve --port 4096 >/out/opencode-serve.log 2>&1 &
srv=$!
for i in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:4096/ && break; sleep 1; done
args=(--attach http://127.0.0.1:4096 --dir /work/run --model "$MODEL" --format json --thinking --auto)
[[ "$EFFORT" != "default" ]] && args+=(--variant "$EFFORT")
set +e
# "/radio-analyst-reduce <args>" in the prompt file runs that command, as
# "/radio-analyst:reduce <args>" does in Claude Code; anything else is sent as text.
prompt="$(cat /out/prompt.txt)"
if [[ "$prompt" =~ ^/([A-Za-z0-9-]+)[[:space:]]*(.*)$ ]]; then
    opencode run "${args[@]}" --command "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" </dev/null >/out/trace.jsonl 2>/out/opencode.stderr
else
    opencode run "${args[@]}" "$prompt" </dev/null >/out/trace.jsonl 2>/out/opencode.stderr
fi
rc=$?
sid="$(grep -m1 -o '"sessionID":"[^"]*"' /out/trace.jsonl | head -1 | cut -d'"' -f4)"
# Stop hook (plugin) left open items: send the model back once, as Claude Code does.
if [[ -n "$sid" && -s .reduce_stop_reason ]]; then
    step "stop hook: sending the model back once ($(grep -c '^- ' .reduce_stop_reason) items)"
    mv .reduce_stop_reason .reduce_stop_reason.sent
    opencode run "${args[@]}" --session "$sid" "$(cat .reduce_stop_reason.sent)" </dev/null >>/out/trace.jsonl 2>>/out/opencode.stderr
    rc=$?
fi
set -e
t3=$(date +%s)
[[ -n "$sid" ]] && opencode export "$sid" >/out/session.json 2>>/out/opencode.stderr || true
[[ -s /out/session.json ]] || step "session export failed for '$sid'"
kill $srv 2>/dev/null || true

step "session done rc=$rc in $((t3 - t2)) s; copying workdir"
mkdir -p /out/workdir
find /work/run -mindepth 1 -maxdepth 1 ! -name input.ms -exec cp -r {} /out/workdir/ \;
cat >/out/timings.env <<EOF
install_s=$((t1 - t0))
env_build_s=$((t2 - t1))
session_s=$((t3 - t2))
opencode_exit=$rc
opencode_version=$(opencode --version)
session_id=$sid
EOF
exit "$rc"
INNER
exit "${PIPESTATUS[0]}"
fi

"${POD[@]}" -e CLAUDE_CODE_OAUTH_TOKEN -e ANTHROPIC_API_KEY \
    "$IMAGE" bash -s <<'INNER' 2>&1 | tee "$OUT/container.log"
set -euo pipefail
[[ -n "$DEBUG" ]] && set -x
step() { echo "[$(date -u +%T)] $*" | tee -a /out/progress.log; }
trap 'rc=$?; [[ $rc -ne 0 ]] && step "FAILED rc=$rc at line $LINENO: $BASH_COMMAND"' EXIT
step "start sha=$SHA model=$MODEL effort=$EFFORT"
t0=$(date +%s)
git config --global --add safe.directory '*'
step "clone + checkout"
git clone -q /src /work/plugin
git -C /work/plugin checkout -q "$SHA"

mkdir -p "$HOME/.casa/data" /work/run
if [[ -z "$NO_PLUGIN" ]]; then
step "plugin install"
claude plugin marketplace add /work/plugin </dev/null
claude plugin install radio-analyst@radio-analyst </dev/null
fi
step "copy MS"
cp -r /data/input.ms /work/run/
cd /work/run

# A non-interactive HOME never sees the trust dialog.
python3 -c "import json, os; p = os.path.join(os.environ['HOME'], '.claude.json'); d = json.load(open(p)) if os.path.exists(p) else {}; d.setdefault('projects', {}).setdefault(os.getcwd(), {})['hasTrustDialogAccepted'] = True; json.dump(d, open(p, 'w'))"

if [[ -n "$NO_PLUGIN" ]]; then
# Same environment as the plugin's, built from $SHA, but nothing installed in Claude.
step "env build, no plugin (cold, about 5 min)"
t1=$(date +%s)
mkdir -p /work/pd
CLAUDE_PLUGIN_ROOT=/work/plugin CLAUDE_PLUGIN_DATA=/work/pd \
    bash /work/plugin/scripts/plugin/ensure-env.sh --build >/out/build.log 2>&1
PY="$(export CLAUDE_PLUGIN_ROOT=/work/plugin CLAUDE_PLUGIN_DATA=/work/pd; source /work/plugin/scripts/plugin/env-lib.sh && ra_prefix)/bin/python"
[[ -x "$PY" ]] || { echo "FAIL: environment not built" >&2; exit 1; }
echo "Python with casatools and casatasks installed: $PY" >CLAUDE.md
t2=$(date +%s)
step "env built in $((t2 - t1)) s; session start"
else
# Build the plugin environment as a user's first session does.
step "env build (cold, about 5 min)"
t1=$(date +%s)
DATA="$HOME/.claude/plugins/data"
mkdir -p "$DATA"  # find on a missing dir exits 1 and set -e ends the run silently
claude mcp list </dev/null >/dev/null 2>&1 || true
stamp=""
for i in $(seq 1 180); do
    stamp="$(find "$DATA" -name env.stamp 2>/dev/null | head -n1)"
    [[ -n "$stamp" ]] && break
    if [[ "$i" -eq 3 ]] && ! find "$DATA" -name build.log 2>/dev/null | grep -q .; then
        claude -p "Reply with OK." --model haiku </dev/null >/dev/null 2>&1 || true
    fi
    sleep 10
done
find "$DATA" -name build.log -exec cp {} /out/build.log \;
[[ -n "$stamp" ]] || { echo "FAIL: plugin environment not built" >&2; exit 1; }
t2=$(date +%s)
# Servers that failed during the build are listed here, and a -p session
# skips them (reported "failed", never started).
rm -f "$HOME/.claude/mcp-needs-auth-cache.json"
step "env built in $((t2 - t1)) s; session start"
fi

args=(-p "$(cat /out/prompt.txt)" --model "$MODEL" --effort "$EFFORT"
      --output-format stream-json --verbose --include-hook-events --permission-prompts none)
[[ -n "$ALLOWED_TOOLS" ]] && args+=(--allowed-tools "$ALLOWED_TOOLS")
set +e
# </dev/null: claude reads stdin, which here is the rest of this script.
claude "${args[@]}" </dev/null >/out/trace.jsonl 2>/out/claude.stderr &
pid=$!
for i in $(seq 1 60); do grep -q '"subtype":"init"' /out/trace.jsonl 2>/dev/null && break; sleep 1; done
step "mcp: $(grep -m1 '"subtype":"init"' /out/trace.jsonl | grep -o '"name":"plugin:radio-analyst:[a-z-]*","status":"[a-z-]*"' | sed 's/"name":"plugin:radio-analyst://; s/","status":"/=/; s/"$//' | tr '\n' ' ')"
wait "$pid"
rc=$?
set -e
t3=$(date +%s)

step "session done rc=$rc in $((t3 - t2)) s; copying workdir"
mkdir -p /out/workdir
find /work/run -mindepth 1 -maxdepth 1 ! -name input.ms -exec cp -r {} /out/workdir/ \;
cat >/out/timings.env <<EOF
install_s=$((t1 - t0))
env_build_s=$((t2 - t1))
session_s=$((t3 - t2))
claude_exit=$rc
claude_version=$(claude --version)
EOF
exit "$rc"
INNER
