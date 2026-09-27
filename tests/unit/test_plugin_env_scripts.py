"""
Behaviour of the plugin's environment scripts (scripts/plugin/*.sh) that can be
checked without pixi or CASA: the platform guard and build-log handling.

The full build path (real pixi, real casatools) is exercised in CI by
scripts/ci/plugin_env_smoke.sh.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import time
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
    assert not (data / "build.log").exists() and not (data / "build.flock").exists()


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
    assert not Path(unsupported_machine["CLAUDE_PLUGIN_DATA"], "build.flock").exists()


def _ra_source_hash(env: dict[str, str]) -> str:
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPTS / "env-lib.sh"}" && ra_source_hash'],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_build_starts_a_fresh_log_and_keeps_the_previous_one(tmp_path: Path):
    # A ready environment (stamp == source hash, server executable present)
    # makes --build stop at "already up to date", after the log rotation and
    # before any pixi call, so this runs without pixi.
    data = tmp_path / "plugin-data"
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "ms-inspect").write_text("#!/bin/sh\n")
    (prefix / "bin" / "ms-inspect").chmod(0o755)
    data.mkdir()
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(data))
    (data / "env.prefix").write_text(f"{prefix}\n")
    (data / "env.stamp").write_text(_ra_source_hash(env) + "\n")
    (data / "build.log").write_text("=== old build\nold output\n")

    with (data / "build.log").open("a") as log_out:  # as ra_spawn_build does
        subprocess.run(
            ["bash", str(SCRIPTS / "ensure-env.sh"), "--build"],
            env=env,
            stdout=log_out,
            stderr=subprocess.STDOUT,
            check=True,
        )

    assert (data / "build.log.prev").read_text() == "=== old build\nold output\n"
    log = (data / "build.log").read_text()
    assert "old output" not in log
    assert log.startswith("=== [") and "environment already up to date" in log


# --- build lock, readiness stamp, launcher --------------------------------


def _lib(snippet: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet with env-lib.sh sourced."""
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPTS / "env-lib.sh"}"\n{snippet}'],
        env=env,
        capture_output=True,
        text=True,
    )


def _fake_bin(tmp_path: Path, **scripts: str) -> Path:
    """A directory of executable shell scripts, to put first on PATH."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in scripts.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return bin_dir


@pytest.fixture
def plugin_env(tmp_path: Path) -> dict[str, str]:
    data = tmp_path / "plugin-data"
    data.mkdir()
    return dict(os.environ, CLAUDE_PLUGIN_DATA=str(data))


def _data(env: dict[str, str]) -> Path:
    return Path(env["CLAUDE_PLUGIN_DATA"])


@contextlib.contextmanager
def _held_lock(env: dict[str, str]):
    """Hold the build lock from this process, as a running build would."""
    with (_data(env) / "build.flock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def test_build_running_follows_the_lock(plugin_env):
    with _held_lock(plugin_env):
        assert _lib("ra_build_running", plugin_env).returncode == 0
    assert _lib("ra_build_running", plugin_env).returncode == 1


def test_second_build_waits_for_the_lock(tmp_path, plugin_env):
    installs = tmp_path / "installs"
    fake = _fake_bin(tmp_path, pixi=f'echo run >>"{installs}"; exit 1')
    env = dict(plugin_env, PATH=f"{fake}{os.pathsep}{plugin_env['PATH']}")
    with _held_lock(env):
        build = subprocess.Popen(
            ["bash", str(SCRIPTS / "ensure-env.sh"), "--build"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        assert build.poll() is None
        assert not installs.exists()
    build.wait(timeout=60)
    assert installs.read_text().split() == ["run"]


def test_lock_of_a_killed_holder_is_free(plugin_env):
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            f'source "{SCRIPTS / "env-lib.sh"}"; exec 9>>"$RA_LOCK"; ra_lock 9; '
            "echo locked; exec sleep 60",
        ],
        env=plugin_env,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "locked"
    assert _lib("ra_build_running", plugin_env).returncode == 0
    holder.kill()
    holder.wait(timeout=10)
    assert _lib("ra_build_running", plugin_env).returncode == 1


def _fake_build_tools(tmp_path: Path, casatools_ok: bool) -> Path:
    """Fake pixi whose environment prefix has a python that can or cannot import casatools."""
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "ms-inspect").write_text("#!/bin/sh\n")
    (prefix / "bin" / "ms-inspect").chmod(0o755)
    (prefix / "bin" / "python").write_text(f"#!/bin/sh\nexit {0 if casatools_ok else 1}\n")
    (prefix / "bin" / "python").chmod(0o755)
    return _fake_bin(tmp_path, pixi=f'case "$1" in install) exit 0 ;; run) echo "{prefix}" ;; esac')


def _build(tmp_path: Path, env: dict[str, str], casatools_ok: bool):
    fake = _fake_build_tools(tmp_path, casatools_ok)
    env = dict(env, PATH=f"{fake}{os.pathsep}{env['PATH']}", HOME=str(tmp_path / "home"))
    return subprocess.run(
        ["bash", str(SCRIPTS / "ensure-env.sh"), "--build"], env=env, capture_output=True, text=True
    )


def test_build_writes_prefix_and_stamp(tmp_path, plugin_env):
    proc = _build(tmp_path, plugin_env, casatools_ok=True)
    assert proc.returncode == 0, proc.stderr
    data = _data(plugin_env)
    assert (data / "env.stamp").read_text().strip() == _ra_source_hash(plugin_env)
    assert (data / "env.prefix").read_text().strip() == str(tmp_path / "env")
    assert not list(data.glob("*.tmp"))
    assert _lib("ra_ready", plugin_env).returncode == 0


def test_build_without_casatools_fails_and_writes_no_stamp(tmp_path, plugin_env):
    proc = _build(tmp_path, plugin_env, casatools_ok=False)
    assert proc.returncode != 0
    assert "casatools still not importable" in proc.stderr
    assert not (_data(plugin_env) / "env.stamp").exists()


def test_failed_rebuild_leaves_no_stale_stamp(tmp_path, plugin_env):
    # An environment built from other sources, then a rebuild whose pixi
    # install fails after app/ has been changed.
    data = _data(plugin_env)
    prefix = tmp_path / "old-env"
    (prefix / "bin").mkdir(parents=True)
    (data / "env.prefix").write_text(f"{prefix}\n")
    (data / "env.stamp").write_text("hash-of-older-sources\n")
    fake = _fake_bin(tmp_path, pixi="exit 1")
    env = dict(plugin_env, PATH=f"{fake}{os.pathsep}{plugin_env['PATH']}")
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "ensure-env.sh"), "--build"], env=env, capture_output=True
    )
    assert proc.returncode != 0
    assert not (data / "env.stamp").exists()


def test_launcher_serves_a_build_that_finishes_during_the_wait(tmp_path, plugin_env):
    # The build finishes between the wait loop's readiness check and its lock
    # check. Fake flock: its first call reports the lock held; its second call
    # writes a ready environment and reports the lock free.
    data = _data(plugin_env)
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "ms-inspect").write_text("#!/bin/sh\necho served >&2\n")
    (prefix / "bin" / "ms-inspect").chmod(0o755)
    stamp_src = tmp_path / "stamp"
    stamp_src.write_text(_ra_source_hash(plugin_env) + "\n")
    calls = tmp_path / "flock-calls"
    fake = _fake_bin(
        tmp_path,
        pixi="exit 0",
        flock=(
            f'echo x >>"{calls}"\n'
            f'if [ "$(wc -l <"{calls}")" -eq 1 ]; then exit 1; fi\n'
            f'echo "{prefix}" >"{data}/env.prefix"; cp "{stamp_src}" "{data}/env.stamp"'
        ),
    )
    env = dict(plugin_env, PATH=f"{fake}{os.pathsep}{plugin_env['PATH']}", RADIO_MCP_ENV_WAIT="1")
    proc = subprocess.run(
        ["bash", str(SCRIPTS / "serve.sh")],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "served" in proc.stderr, proc.stderr
    assert "build failed" not in proc.stderr
