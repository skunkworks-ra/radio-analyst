#!/usr/bin/env bash
# Stop / SessionEnd hook: parse <stage_decision> blocks from the session
# transcript and write {workdir}/orchestrator/{n:02d}_{stage}_try{k}.json.
# Never fails the session.
source "$(dirname "$0")/env-lib.sh"
prefix="$(ra_prefix)" || exit 0
[[ -x "$prefix/bin/python" ]] || exit 0
exec "$prefix/bin/python" -I -m ms_create.audit_hook
