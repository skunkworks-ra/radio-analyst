"""
Behaviour of the plugin's environment scripts (scripts/plugin/*.sh) that can be
checked without pixi or CASA: the platform guard and build-log handling.

The full build path (real pixi, real casatools) is exercised in CI by
scripts/ci/plugin_env_smoke.sh.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "plugin"

# pixi platform name -> `uname -s`-`uname -m`
_PIXI_TO_UNAME = {
    "linux-64": "Linux-x86_64",
    "linux-aarch64": "Linux-aarch64",
    "osx-64": "Darwin-x86_64",
    "osx-arm64": "Darwin-arm64",
}


def _supported_platforms() -> list[str]:
    text = (SCRIPTS / "env-lib.sh").read_text()
    m = re.search(r"^RA_SUPPORTED_PLATFORMS=\(([^)]*)\)", text, re.M)
    assert m, "RA_SUPPORTED_PLATFORMS not found in env-lib.sh"
    return m.group(1).split()


def test_supported_platforms_match_pixi_toml():
    pixi = tomllib.loads((REPO_ROOT / "pixi.toml").read_text())
    expected = sorted(_PIXI_TO_UNAME[p] for p in pixi["workspace"]["platforms"])
    assert sorted(_supported_platforms()) == expected


@pytest.fixture
def unsupported_machine(tmp_path: Path) -> dict[str, str]:
    """Env for running the scripts as if on Linux/aarch64, with a fresh data dir."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uname = fake_bin / "uname"
    uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo aarch64 ;; esac\n')
    uname.chmod(0o755)
    data = tmp_path / "plugin-data"
    return dict(
        os.environ,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        CLAUDE_PLUGIN_DATA=str(data),
    )


def test_hook_on_unsupported_platform_explains_and_builds_nothing(unsupported_machine):
    out = subprocess.run(
        ["bash", str(SCRIPTS / "ensure-env.sh"), "--hook"],
        env=unsupported_machine,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    msg = json.loads(out)
    assert "Linux-aarch64" in msg["systemMessage"]
    assert "cannot run" in msg["hookSpecificOutput"]["additionalContext"]
    data = Path(unsupported_machine["CLAUDE_PLUGIN_DATA"])
    assert not (data / "build.log").exists() and not (data / "build.lock").exists()


def test_launcher_on_unsupported_platform_fails_fast(unsupported_machine):
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "serve.sh")],
        env=unsupported_machine,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1
    assert proc.stdout == ""  # stdout is the JSON-RPC stream
    assert "this machine is Linux-aarch64" in proc.stderr
    assert not Path(unsupported_machine["CLAUDE_PLUGIN_DATA"], "build.lock").exists()
