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


def test_plugin_version_matches_package():
    # plugin.json is pinned: `claude plugin update` ignores new commits until the
    # version is bumped. A release bumps plugin.json, pyproject.toml and the three
    # __version__ strings together.
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    want = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert manifest["version"] == want
    for pkg in ("ms_inspect", "ms_modify", "ms_create"):
        init = (REPO_ROOT / "src" / pkg / "__init__.py").read_text()
        assert f'__version__ = "{want}"' in init, pkg


def test_ci_tool_manifest_covers_every_registered_tool():
    # scripts/ci/tool_manifest.json drives the per-tool CI probe matrix; a tool
    # registered on a server but missing here is never probed.
    manifest = json.loads((REPO_ROOT / "scripts" / "ci" / "tool_manifest.json").read_text())
    probed = {server: set(tools) for server, tools in manifest["tools"].items()}
    assert probed == _registered_tools()


@pytest.mark.parametrize("doc", ["CLAUDE.md", "design_docs/DESIGN.md"])
def test_tool_inventories_list_every_registered_tool(doc: str):
    # CLAUDE.md "Adding a new tool", step 8: update the inventory in both files.
    text = (REPO_ROOT / doc).read_text()
    missing = sorted(t for ts in _registered_tools().values() for t in ts if f"`{t}`" not in text)
    assert not missing, f"{doc} does not list {missing}"


def test_documented_tool_counts_match_registrations():
    counts = {server: len(tools) for server, tools in _registered_tools().items()}
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text()
    readme = (REPO_ROOT / "README.md").read_text()
    design = (REPO_ROOT / "design_docs" / "DESIGN.md").read_text()
    for server, n in counts.items():
        assert re.search(rf"\*\*{server}\*\* — .*\({n} tools", claude_md), (server, n)
        assert re.search(rf"\*\*{server}\*\*: .*\({n} tools", readme), (server, n)
    assert f"**Total `ms_inspect`: {counts['ms-inspect']} tools.**" in design


def test_opencode_commands_match_claude_commands():
    # .opencode/commands/radio-analyst-<name>.md are copies, not links (the plugin
    # directory's validator refuses symlinks). Edit .claude/commands/<name>.md and
    # copy it over; this fails until both match.
    src = REPO_ROOT / ".claude" / "commands"
    dst = REPO_ROOT / ".opencode" / "commands"
    for cmd in sorted(src.glob("*.md")):
        copy = dst / f"radio-analyst-{cmd.name}"
        assert copy.is_file() and not copy.is_symlink(), copy
        assert copy.read_text() == cmd.read_text(), f"{copy} differs from {cmd}"


# ---------------------------------------------------------------------------
# Stage agents (agents/*-stage.md) and the orchestrate skill. A stage agent runs
# its command through the Skill tool, so its `tools:` must be exactly that
# command's allowed-tools plus Skill: the command stays the single source of the
# stage's tool grants.
# ---------------------------------------------------------------------------

STAGES = ("inspect", "precal", "calibrate", "image", "selfcal", "postcal")
_ORCH_TOOL_RE = re.compile(r"^mcp__plugin_radio-analyst_(ms-\w+)__(\w+)$")


def _frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n", 2)[1])


def _tools(raw) -> list[str]:
    return [t.strip() for t in (raw if isinstance(raw, list) else raw.split(",")) if t.strip()]


@pytest.mark.parametrize("stage", STAGES)
def test_stage_agent_tools_are_its_command_grants_plus_skill(stage):
    agent = _frontmatter(REPO_ROOT / "agents" / f"{stage}-stage.md")
    command = _frontmatter(REPO_ROOT / ".claude" / "commands" / f"{stage}.md")
    assert agent["name"] == f"{stage}-stage"
    assert agent["model"] == "haiku"
    assert _tools(agent["tools"]) == _tools(command["allowed-tools"]) + ["Skill"]


@pytest.mark.parametrize("stage", STAGES)
def test_stage_agent_runs_its_own_command(stage):
    body = (REPO_ROOT / "agents" / f"{stage}-stage.md").read_text()
    assert f"skill `radio-analyst:{stage}`" in body


def test_orchestrator_grants_registered_read_only_tools_and_calls_each_stage():
    path = REPO_ROOT / ".claude" / "skills" / "orchestrate" / "SKILL.md"
    fm = _frontmatter(path)
    registered = _registered_tools()
    for t in _tools(fm["allowed-tools"]):
        m = _ORCH_TOOL_RE.match(t)
        if not m:
            assert t in ("Agent", "Read", "Write", "Bash"), t
            continue
        server, tool = m.groups()
        assert server == "ms-inspect" or t.endswith(("__ms_report", "__ms_casa_task")), (
            f"orchestrator must not hold write tools: {t}"
        )
        assert tool in registered[server], t
    body = path.read_text()
    for stage in STAGES:
        assert f"`radio-analyst:{stage}-stage`" in body
    assert body.count("Retry cap: 5") == 1


def test_orchestrator_excerpt_headings_exist_in_their_files():
    # The orchestrator cuts skill sections by heading; a renamed heading would
    # silently drop that section from the stage's prompt.
    ri = REPO_ROOT / ".claude" / "skills" / "radio-interferometry"
    body = (REPO_ROOT / ".claude" / "skills" / "orchestrate" / "SKILL.md").read_text()
    table = body.split("| Stage | File | Headings |", 1)[1].split("\n\n", 1)[0]
    n = 0
    for row in table.splitlines()[2:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        fname = cells[1].strip("`")
        heads = re.findall(r"`(## [^`]+)`", cells[2])
        lines = (ri / fname).read_text().splitlines()
        for h in heads:
            assert sum(line.startswith(h) for line in lines) == 1, (fname, h)
            n += 1
    assert n > 0


@pytest.mark.parametrize("stage", STAGES)
def test_opencode_stage_agent_inlines_its_command(stage):
    # opencode has no Skill-loads-a-command step: the runner inlines the
    # "@.claude/commands/<stage>.md" line, so the command stays the single source.
    path = REPO_ROOT / ".opencode" / "agents" / f"{stage}-stage.md"
    fm = _frontmatter(path)
    assert fm["mode"] == "subagent"
    assert path.read_text().count(f"@.claude/commands/{stage}.md") == 1
