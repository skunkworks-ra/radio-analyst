#!/usr/bin/env bash
# One isolated agent run: a fresh podman container, the plugin installed from a
# commit into an empty HOME, the environment built cold, then one headless
# session at a given model and effort. Nothing on the host is reused except the
# image, so every run starts from the same state.
#
# Usage:
#   scripts/dev/run-isolated.sh --sha <commit> --model <model> --effort <level> \
#       --prompt <file> --ms <path.ms> [--allowed-tools "<tools>"] [--harness claude]
#
# Credentials: export CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or
# ANTHROPIC_API_KEY. Passed into the container by name; never written to disk.
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

SHA="" MODEL="" EFFORT="" PROMPT="" MS="" ALLOWED_TOOLS="" HARNESS="claude"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sha) SHA="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --effort) EFFORT="$2"; shift 2 ;;
        --prompt) PROMPT="$2"; shift 2 ;;
        --ms) MS="$2"; shift 2 ;;
        --allowed-tools) ALLOWED_TOOLS="$2"; shift 2 ;;
        --harness) HARNESS="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

die() { echo "run-isolated: $*" >&2; exit 1; }
[[ -n "$SHA" && -n "$MODEL" && -n "$EFFORT" && -n "$PROMPT" && -n "$MS" ]] \
    || die "--sha, --model, --effort, --prompt and --ms are required"
[[ "$HARNESS" == "claude" ]] \
    || die "harness '$HARNESS' is not wired yet; only 'claude' is"
[[ -f "$PROMPT" ]] || die "prompt file not found: $PROMPT"
[[ -f "$MS/table.info" ]] || die "not a Measurement Set: $MS"
[[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}${ANTHROPIC_API_KEY:-}" ]] \
    || die "set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY"
FULL_SHA="$(git -C "$ROOT" rev-parse --verify "$SHA^{commit}")" \
    || die "commit not found: $SHA"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_${HARNESS}_${MODEL}_${EFFORT}_${FULL_SHA:0:7}"
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
image=$IMAGE
image_id=$(podman image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || echo none)
EOF

podman image exists "$IMAGE" \
    || podman build -t "$IMAGE" -f "$ROOT/docker/ci.Dockerfile" "$ROOT/docker"

echo "run-isolated: $OUT"

# label=disable: read the repo and the MS without relabelling host files.
# keep-id: the container's uid 1000 (analyst) is the host user, so /out is writable.
podman run --rm \
    --userns=keep-id --user analyst \
    --security-opt label=disable \
    -v "$ROOT:/src:ro" \
    -v "$(cd "$MS" && pwd):/data/input.ms:ro" \
    -v "$OUT:/out" \
    -e CLAUDE_CODE_OAUTH_TOKEN -e ANTHROPIC_API_KEY \
    -e SHA="$FULL_SHA" -e MODEL="$MODEL" -e EFFORT="$EFFORT" \
    -e ALLOWED_TOOLS="$ALLOWED_TOOLS" \
    "$IMAGE" bash -s <<'INNER'
set -euo pipefail
t0=$(date +%s)
git config --global --add safe.directory '*'
git clone -q /src /work/plugin
git -C /work/plugin checkout -q "$SHA"

mkdir -p "$HOME/.casa/data" /work/run
claude plugin marketplace add /work/plugin
claude plugin install radio-analyst@radio-analyst
cp -r /data/input.ms /work/run/
cd /work/run

# A non-interactive HOME never sees the trust dialog.
python3 -c "import json, os; p = os.path.join(os.environ['HOME'], '.claude.json'); d = json.load(open(p)) if os.path.exists(p) else {}; d.setdefault('projects', {}).setdefault(os.getcwd(), {})['hasTrustDialogAccepted'] = True; json.dump(d, open(p, 'w'))"

# Build the plugin environment as a user's first session does.
t1=$(date +%s)
DATA="$HOME/.claude/plugins/data"
mkdir -p "$DATA"  # find on a missing dir exits 1 and set -e ends the run silently
claude mcp list >/dev/null 2>&1 || true
stamp=""
for i in $(seq 1 180); do
    stamp="$(find "$DATA" -name env.stamp 2>/dev/null | head -n1)"
    [[ -n "$stamp" ]] && break
    if [[ "$i" -eq 3 ]] && ! find "$DATA" -name build.log 2>/dev/null | grep -q .; then
        claude -p "Reply with OK." --model haiku >/dev/null 2>&1 || true
    fi
    sleep 10
done
find "$DATA" -name build.log -exec cp {} /out/build.log \;
[[ -n "$stamp" ]] || { echo "FAIL: plugin environment not built" >&2; exit 1; }
t2=$(date +%s)

args=(-p "$(cat /out/prompt.txt)" --model "$MODEL" --effort "$EFFORT"
      --output-format stream-json --verbose --permission-prompts none)
[[ -n "$ALLOWED_TOOLS" ]] && args+=(--allowed-tools "$ALLOWED_TOOLS")
set +e
claude "${args[@]}" >/out/trace.jsonl 2>/out/claude.stderr
rc=$?
set -e
t3=$(date +%s)

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
