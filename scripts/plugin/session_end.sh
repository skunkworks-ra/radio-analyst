#!/usr/bin/env bash
# SessionEnd hook: per-session tokens and cost of this run (ms_create/accounting.py),
# written to the reduction workdir, and the report rebuilt with them. Reads the
# hook JSON on stdin. Never fails the session: no environment, no accounting.
source "$(dirname "$0")/env-lib.sh"
prefix="$(ra_prefix)" || exit 0
[[ -x "$prefix/bin/python" ]] || exit 0
exec "$prefix/bin/python" -I -m ms_create.accounting
