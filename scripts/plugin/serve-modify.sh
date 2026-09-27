#!/usr/bin/env bash
# MCP plugin entry point for ms-modify. See scripts/plugin/launch.sh.
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/launch.sh" ms-modify serve-modify
