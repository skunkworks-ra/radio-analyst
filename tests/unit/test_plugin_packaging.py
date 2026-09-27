"""
Drift guard: the plugin's tool pre-approvals must name tools that exist.

Installed as a plugin, an MCP tool is named
`mcp__plugin_<plugin>_<server>__<tool>`. The `allowed-tools` frontmatter of the
commands and skills used to list bare names (`ms_observation_info`), which match
nothing, so no MCP tool was pre-approved and every call prompted. These tests
pin the full form against what each server actually registers, so a renamed or
moved tool, a renamed server, or a renamed plugin fails here instead of
silently turning pre-approval off again.

Also checked: every path the plugin wiring (plugin.json, hooks/hooks.json)
hands to Claude Code exists, the clone's project .mcp.json agrees with the
plugin's servers without depending on ${CLAUDE_PLUGIN_ROOT}, and nothing is
shipped under a top-level bin/ (which a plugin puts on the Bash tool's PATH).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]

SERVER_MODULES = {
    "ms-inspect": REPO_ROOT / "src" / "ms_inspect" / "server.py",
    "ms-modify": REPO_ROOT / "src" / "ms_modify" / "server.py",
    "ms-create": REPO_ROOT / "src" / "ms_create" / "server.py",
}

FRONTMATTER_FILES = sorted((REPO_ROOT / ".claude" / "commands").glob("*.md")) + sorted(
    (REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md")
)

_TOOL_RE = re.compile(r'@mcp\.tool\(\s*name="(ms_\w+)"')
_PLUGIN_TOOL_RE = re.compile(r"^mcp__plugin_(?P<plugin>[\w-]+?)_(?P<server>ms-\w+)__(?P<tool>\w+)$")


def _registered_tools() -> dict[str, set[str]]:
    return {s: set(_TOOL_RE.findall(p.read_text())) for s, p in SERVER_MODULES.items()}


def _allowed_tools(path: Path) -> list[str]:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    frontmatter = yaml.safe_load(text.split("---\n", 2)[1])
    raw = frontmatter.get("allowed-tools", "")
    if isinstance(raw, list):
        return [t.strip() for t in raw]
    return [t.strip() for t in raw.split(",") if t.strip()]


def test_servers_register_tools():
    # Guards the regex itself: an empty set would make every check below vacuous.
    for server, tools in _registered_tools().items():
        assert tools, f"no @mcp.tool registrations found for {server}"


@pytest.mark.parametrize("path", FRONTMATTER_FILES, ids=lambda p: p.parent.name + "/" + p.name)
def test_allowed_tools_use_plugin_names_of_registered_tools(path: Path):
    registered = _registered_tools()
    problems = []
    for entry in _allowed_tools(path):
        if entry.startswith("ms_"):
            problems.append(f"{entry}: bare tool name matches nothing once installed as a plugin")
            continue
        if not entry.startswith("mcp__"):
            continue  # built-in tool (Bash, Read, WebFetch, ...)
        m = _PLUGIN_TOOL_RE.match(entry)
        if m is None:
            problems.append(f"{entry}: not of the form mcp__plugin_<plugin>_<server>__<tool>")
        elif m["plugin"] != PLUGIN_NAME:
            problems.append(f"{entry}: plugin is {PLUGIN_NAME!r}")
        elif m["server"] not in registered:
            problems.append(f"{entry}: unknown server {m['server']!r}")
        elif m["tool"] not in registered[m["server"]]:
            problems.append(f"{entry}: {m['server']} registers no tool {m['tool']!r}")
    assert not problems, "\n".join(problems)


def _plugin_root_paths(obj) -> list[str]:
    """Every string under obj that starts with ${CLAUDE_PLUGIN_ROOT}/."""
    if isinstance(obj, dict):
        return [p for v in obj.values() for p in _plugin_root_paths(v)]
    if isinstance(obj, list):
        return [p for v in obj for p in _plugin_root_paths(v)]
    if isinstance(obj, str) and obj.startswith("${CLAUDE_PLUGIN_ROOT}/"):
        return [obj]
    return []


@pytest.mark.parametrize("config", [".claude-plugin/plugin.json", "hooks/hooks.json"])
def test_plugin_wiring_paths_exist(config: str):
    paths = _plugin_root_paths(json.loads((REPO_ROOT / config).read_text()))
    assert paths, f"{config} references no ${{CLAUDE_PLUGIN_ROOT}} paths"
    for p in paths:
        assert (REPO_ROOT / p.removeprefix("${CLAUDE_PLUGIN_ROOT}/")).is_file(), p


def _server_scripts(servers: dict, prefix: str) -> dict[str, str]:
    return {name: cfg["args"][0].removeprefix(prefix) for name, cfg in servers.items()}


def test_plugin_and_project_mcp_configs_agree():
    # The plugin declares its servers in plugin.json with ${CLAUDE_PLUGIN_ROOT};
    # those replace the same-named servers Claude Code also reads from the
    # plugin's .mcp.json. The root .mcp.json is what a clone loads as project
    # config, where ${CLAUDE_PLUGIN_ROOT} is undefined (every server failed
    # with CONNECTION_CLOSED), so it must use repo-relative paths. Claude Code
    # does not honour ${CLAUDE_PLUGIN_ROOT:-.} for plugin servers, so one file
    # cannot serve both.
    plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())["mcpServers"]
    project = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]
    assert set(plugin) == set(project) == set(SERVER_MODULES)
    assert "CLAUDE_PLUGIN_ROOT" not in (REPO_ROOT / ".mcp.json").read_text()
    for script in _server_scripts(project, "").values():
        assert (REPO_ROOT / script).is_file(), script
    assert _server_scripts(plugin, "${CLAUDE_PLUGIN_ROOT}/") == _server_scripts(project, "")


def test_no_top_level_bin_dir():
    assert not (REPO_ROOT / "bin").exists(), (
        "a plugin's top-level bin/ is put on the Bash tool's PATH, and claude.ai "
        "and Cowork refuse to install a plugin that has one"
    )


def test_plugin_version_not_pinned():
    # A "version" in plugin.json (or the marketplace entry) pins installed users
    # to that string: `claude plugin update` ignores new commits until someone
    # edits it. Unpinned, Claude Code versions the plugin by commit SHA. Remove
    # this test only together with a release process that bumps the version.
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert "version" not in manifest
    assert all("version" not in entry for entry in marketplace["plugins"])


def test_ci_tool_manifest_covers_every_registered_tool():
    # scripts/ci/tool_manifest.json drives the per-tool CI probe matrix; a tool
    # registered on a server but missing here is never probed.
    manifest = json.loads((REPO_ROOT / "scripts" / "ci" / "tool_manifest.json").read_text())
    probed = {server: set(tools) for server, tools in manifest["tools"].items()}
    assert probed == _registered_tools()
