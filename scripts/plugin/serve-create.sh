#!/usr/bin/env bash
# MCP plugin entry point for ms-create. See scripts/plugin/launch.sh.
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/launch.sh" ms-create serve-create
