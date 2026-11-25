#!/usr/bin/env bash
# Bounded-wait detached runner for generated CASA Python scripts.
#
# Usage:
#   bash scripts/plugin/run-step.sh <python_exe> <script.py> [--wait 240] [--interval 1]
#
# Behaviour:
#   - Default --wait is 240s (< 300s 5-minute subagent prompt-cache TTL).
#   - If <script.py>.pid exists and <script.py> is not newer than <script.py>.pid:
#       * If <script.py>.rc exists, prints status=done rc=<rc>, removes .pid, exits <rc>.
#       * If PID is alive, attaches and polls up to --wait seconds (idempotent).
#       * If PID is dead without .rc (OOM / SIGKILL / crash), prints
#         status=crashed, removes stale .pid, and exits 1 immediately.
#   - Otherwise starts a fresh detached session (setsid) writing <script.py>.log
#     and atomically writing <script.py>.rc on exit, then polls up to --wait.
#   - When .rc appears: prints status=done rc=<rc> + last 25 log lines, exits <rc>.
#   - When --wait elapses and PID is still alive: prints status=running + last 5
#     log lines and exits 0 so the caller can re-invoke the exact same command.

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <python_exe> <script.py> [--wait SECONDS] [--interval SECONDS]" >&2
    exit 2
fi

PYTHON_EXE="$1"
SCRIPT="$2"
shift 2

WAIT_S=240
INTERVAL_S=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --wait)
            WAIT_S="$2"
            shift 2
            ;;
        --interval)
            INTERVAL_S="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

if [ ! -f "$SCRIPT" ]; then
    echo "status=error message=\"script not found: $SCRIPT\"" >&2
    exit 2
fi

LOG_FILE="${SCRIPT}.log"
RC_FILE="${SCRIPT}.rc"
PID_FILE="${SCRIPT}.pid"

_pid_alive() {
    local p="$1"
    [[ "$p" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$p" 2>/dev/null || return 1
    if [ -r "/proc/$p/stat" ]; then
        local state
        state="$(awk '{ sub(/^.*\)[[:space:]]*/, ""); print substr($0, 1, 1) }' "/proc/$p/stat" 2>/dev/null || true)"
        [ "$state" = "Z" ] && return 1
    fi
    return 0
}

_finish_from_rc() {
    local rc
    rc="$(tr -d '[:space:]' < "$RC_FILE")"
    rm -f "$PID_FILE"
    echo "status=done rc=${rc}"
    if [ -f "$LOG_FILE" ]; then
        tail -n 25 "$LOG_FILE"
    fi
    exit "${rc:-1}"
}

pid=""
if [ -f "$PID_FILE" ] && [ ! "$SCRIPT" -nt "$PID_FILE" ]; then
    if [ -f "$RC_FILE" ]; then
        _finish_from_rc
    fi
    pid="$(tr -d '[:space:]' < "$PID_FILE" || true)"
    if ! _pid_alive "$pid"; then
        if [ -f "$RC_FILE" ]; then
            _finish_from_rc
        fi
        echo "status=crashed pid=${pid} pid_alive=false"
        if [ -f "$LOG_FILE" ]; then
            tail -n 30 "$LOG_FILE"
        fi
        rm -f "$PID_FILE"
        exit 1
    fi
else
    script_dir="$(dirname "$SCRIPT")"
    lock_dir="$script_dir/.run-step.launch.lock"
    _release_lock() {
        rm -rf "$lock_dir"
    }
    lock_acquired=0
    lpid=""
    _retry=0
    while true; do
        if mkdir "$lock_dir" 2>/dev/null; then
            lock_acquired=1
            trap _release_lock EXIT
            printf "%s\n" "$$" > "$lock_dir/owner.pid"
            break
        fi
        lpid=""
        if [ -f "$lock_dir/owner.pid" ]; then
            lpid="$(tr -d '[:space:]' < "$lock_dir/owner.pid" 2>/dev/null || true)"
        fi
        if [ -n "$lpid" ] && ! _pid_alive "$lpid"; then
            stale_dir="${lock_dir}.stale.$$"
            if mv "$lock_dir" "$stale_dir" 2>/dev/null; then
                rm -rf "$stale_dir"
            fi
            if [ "$_retry" -lt 5 ]; then
                _retry=$(( _retry + 1 ))
                continue
            fi
        elif [ -z "$lpid" ] && [ -d "$lock_dir" ]; then
            lock_mtime="$(stat -c %Y "$lock_dir" 2>/dev/null || stat -f %m "$lock_dir" 2>/dev/null || echo 0)"
            now_s="$(date +%s)"
            if [ "$lock_mtime" -gt 0 ] && [ $(( now_s - lock_mtime )) -gt 30 ]; then
                stale_dir="${lock_dir}.stale.$$"
                if mv "$lock_dir" "$stale_dir" 2>/dev/null; then
                    rm -rf "$stale_dir"
                fi
                if [ "$_retry" -lt 5 ]; then
                    _retry=$(( _retry + 1 ))
                    continue
                fi
            fi
        fi
        if [ "$_retry" -ge 5 ]; then
            break
        fi
        _retry=$(( _retry + 1 ))
        sleep 0.1
    done
    if [ "$lock_acquired" -ne 1 ]; then
        echo "status=busy active=launch_lock pid=${lpid:-unknown} pid_alive=true"
        exit 1
    fi
    for pfile in "$script_dir"/*.pid; do
        [ -f "$pfile" ] || continue
        [ -f "${pfile%.pid}.rc" ] && continue
        opid="$(tr -d '[:space:]' < "$pfile" || true)"
        if _pid_alive "$opid"; then
            echo "status=busy active=${pfile%.pid} pid=${opid} pid_alive=true"
            exit 1
        fi
    done
    rm -f "$RC_FILE" "$PID_FILE" "${RC_FILE}.tmp"
    : > "$LOG_FILE"
    setsid bash -c '
        "$1" "$2" >>"$3" 2>&1
        rc=$?
        printf "%s\n" "$rc" >"${4}.tmp"
        mv -f "${4}.tmp" "$4"
    ' _ "$PYTHON_EXE" "$SCRIPT" "$LOG_FILE" "$RC_FILE" </dev/null >/dev/null 2>&1 &
    pid="$!"
    printf "%s\n" "$pid" > "${PID_FILE}.tmp"
    mv -f "${PID_FILE}.tmp" "$PID_FILE"
    trap - EXIT
    _release_lock
fi

start_epoch="$(date +%s)"
while true; do
    if [ -f "$RC_FILE" ]; then
        _finish_from_rc
    fi
    if ! _pid_alive "$pid"; then
        if [ -f "$RC_FILE" ]; then
            _finish_from_rc
        fi
        echo "status=crashed pid=${pid} pid_alive=false"
        if [ -f "$LOG_FILE" ]; then
            tail -n 30 "$LOG_FILE"
        fi
        rm -f "$PID_FILE"
        exit 1
    fi
    now_epoch="$(date +%s)"
    elapsed=$(( now_epoch - start_epoch ))
    if [ "$elapsed" -ge "$WAIT_S" ]; then
        echo "status=running pid=${pid} pid_alive=true elapsed_s=${elapsed}"
        if [ -f "$LOG_FILE" ]; then
            tail -n 5 "$LOG_FILE"
        fi
        exit 0
    fi
    sleep "$INTERVAL_S"
done
