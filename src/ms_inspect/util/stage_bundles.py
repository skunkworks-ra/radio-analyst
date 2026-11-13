"""
util/stage_bundles.py -- Build-time stage skill bundle generator.

Generates static, single-file stage excerpts under
`.claude/skills/radio-interferometry/bundles/{precal,calibrate,polcal,image,image_iquv,postcal,selfcal}.md`
so neither the orchestrator nor standalone stage commands slice skill markdown
at runtime with `awk` or load ungranted tool cues into stage prompts.

Run via:
    pixi run gen-stage-bundles
    python -m ms_inspect.util.stage_bundles [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

BUNDLE_NAMES: tuple[str, ...] = (
    "precal",
    "calibrate",
    "polcal",
    "image",
    "image_iquv",
    "postcal",
    "selfcal",
)

BUNDLE_COMMAND_MAP: dict[str, str] = {
    "precal": "precal",
    "calibrate": "calibrate",
    "polcal": "polcal",
    "image": "image",
    "image_iquv": "image",
    "postcal": "postcal",
    "selfcal": "selfcal",
}

_COMMON_SKILL_HEADINGS: tuple[str, ...] = (
    "## Core operating principle",
    "## Running generated scripts",
)

_SECTION_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "precal": (
        "10-precal-workflow.md",
        (
            "## Step 1 ",
            "## Step 2 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 5 ",
            "## Step 6 ",
            "## Step 8 ",
            "## Decision gate",
        ),
    ),
    "calibrate": (
        "07-calibration-execution.md",
        (
            "## Execution protocol",
            "## Placeholder reference",
            "## Field selection",
            "## solint guidance",
            "## Calibration table naming",
            "## Caltable solution flagging",
            "## Drilling into",
            "## Step 1 ",
            "## Step 2 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 4b ",
            "## Step 5 ",
            "## Step 6 ",
            "## Decision gate",
            "## Antenna-set consistency",
            "## Step 7 ",
            "## Post-applycal assessment",
            "## parang parameter",
        ),
    ),
    "polcal": (
        "09-polcal-execution.md",
        (
            "## Purpose",
            "## Reading the conditions",
            "## Tool API reference",
            "## Step 2 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 5 ",
            "## Calibration table naming convention",
            "## Placeholder reference",
            "## Decision summary",
        ),
    ),
    "image": (
        "11-imaging.md",
        (
            "## Placeholder reference",
            "## Step 0 ",
            "## Step 1 ",
            "## Step 2 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 5 ",
            "## Step 6 ",
            "## Step 7 ",
            "## Step 8 ",
            "## Step 9 ",
        ),
    ),
    "image_iquv": (
        "11-imaging.md",
        (
            "## Placeholder reference",
            "## Step 0 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 5 ",
            "## Step 6 ",
            "## Step 7 ",
            "## Polarization frequency cubes",
        ),
    ),
    "selfcal": (
        "12-selfcal.md",
        (
            "## Prerequisites",
            "## Step 0 ",
            "## Step 1 ",
            "## Step 2 ",
            "## Step 3 ",
            "## Step 4 ",
            "## Step 5 ",
        ),
    ),
}

_POLCAL_MODEL_NOTE = """\
## Step 1 -- Verify the polarisation calibrator model

Precal sets the polarisation angle calibrator model (`ms_setjy_polcal`,
`usescratch=True`) up front before the initial bandpass. Confirm it here with
`ms_verify_model(ms_path=calibrators.ms, field=<all cals>, polcal_fields=<angle cal>)`
before solving cross-hand delay; run `ms_setjy_polcal` in polcal only when
precal ran without polarisation in scope (and then redo calibration)."""

_POSTCAL_BODY = """\
## Post-calibration target rflag (`CORRECTED_DATA` only, no amplitude clip)

- Scope strictly to the science target field names (`field=<target fields>`,
  verified against `ms_field_list`). Never run an amplitude clip on target
  fields: the target has no a-priori sky model in `MODEL_DATA`, so clipping
  `|CORRECTED|` clips real sky emission.
- Measure `ms_flag_summary(ms_path, field=<target fields>)` before and after
  flagging and report `per_field` `flag_fraction` for every target field.
- Generate the rflag script with `ms_apply_rflag(ms_path, workdir,
  field=<target fields>, datacolumn='corrected', execute=False)` using default
  thresholds unless a retry explicitly overrides them, then run it via
  `run-step.sh`. The script saves flag backup `before_rflag` first (re-running
  would overwrite that backup name) and uses CASA's default `extendflags=True`."""

_TOOL_REG_RE = re.compile(r'@mcp\.tool\(\s*name="(ms_\w+)"')
_PLUGIN_GRANT_RE = re.compile(r"^mcp__plugin_[\w-]+?_ms-\w+__(ms_\w+)$")
_MS_TOKEN_RE = re.compile(r"\b(ms_[a-z0-9_]+)\b")


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_typography(text: str) -> str:
    return text.replace("\u2014", "--").replace("\u2013", "-")


def _split_h2_sections(markdown_text: str) -> list[tuple[str, str]]:
    """Return `(heading_line, section_text)` pairs for every top-level `## ` block."""
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    buf: list[str] = []
    in_fence = False

    for line in markdown_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            if current_heading is not None:
                sections.append((current_heading, _trim_section(buf)))
            current_heading = line
            buf = [line]
        elif current_heading is not None:
            buf.append(line)

    if current_heading is not None:
        sections.append((current_heading, _trim_section(buf)))
    return sections


def _trim_section(lines: list[str]) -> str:
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    if out and out[-1].strip() == "---":
        out.pop()
        while out and not out[-1].strip():
            out.pop()
    return "\n".join(out)


def _heading_key(heading: str) -> str:
    norm = _normalize_typography(heading)
    norm = re.sub(r"\s+--\s+", " ", norm)
    norm = re.sub(r"\s+", " ", norm)
    return norm


def slice_sections(markdown_text: str, prefixes: tuple[str, ...]) -> str:
    """Extract `## ` sections matching `prefixes` in source order; raise if any prefix is missing."""
    sections = _split_h2_sections(markdown_text)
    norm_prefixes = [_heading_key(p) for p in prefixes]
    matched_prefixes: set[int] = set()
    kept: list[str] = []

    for heading, body in sections:
        hkey = _heading_key(heading)
        for idx, pkey in enumerate(norm_prefixes):
            if hkey.startswith(pkey) or _normalize_typography(heading).startswith(
                _normalize_typography(prefixes[idx])
            ):
                matched_prefixes.add(idx)
                kept.append(body)
                break

    missing = [prefixes[i] for i in range(len(prefixes)) if i not in matched_prefixes]
    if missing:
        raise ValueError(f"Missing expected section headings: {missing}")
    return "\n\n---\n\n".join(kept)


def build_stage_bundles(repo_root: Path | None = None) -> dict[str, str]:
    """Build all static stage skill bundles as `{bundle_name: markdown_content}`."""
    root = repo_root or default_repo_root()
    ri_dir = root / ".claude" / "skills" / "radio-interferometry"
    skill_md = (ri_dir / "SKILL.md").read_text(encoding="utf-8")
    common_block = slice_sections(skill_md, _COMMON_SKILL_HEADINGS)

    bundles: dict[str, str] = {}
    for name in BUNDLE_NAMES:
        header = (
            f"<!-- Generated by python -m ms_inspect.util.stage_bundles ({name}) "
            "-- do not edit by hand -->\n\n"
            f"# Stage Skill Bundle: {name}"
        )
        if name == "postcal":
            body = _POSTCAL_BODY
        else:
            src_file, prefixes = _SECTION_SPECS[name]
            src_text = (ri_dir / src_file).read_text(encoding="utf-8")
            body = slice_sections(src_text, prefixes)
            if name == "polcal":
                marker = "## Step 2 "
                norm_body = _normalize_typography(body)
                idx = norm_body.find(marker)
                if idx == -1:
                    raise ValueError("polcal bundle missing '## Step 2 ' insertion point")
                body = (
                    norm_body[:idx].rstrip()
                    + "\n\n---\n\n"
                    + _POLCAL_MODEL_NOTE
                    + "\n\n---\n\n"
                    + norm_body[idx:]
                )
        full = f"{header}\n\n{common_block}\n\n---\n\n{body}\n"
        bundles[name] = _normalize_typography(full)
    return bundles


def registered_mcp_tools(repo_root: Path | None = None) -> set[str]:
    root = repo_root or default_repo_root()
    servers = (
        root / "src" / "ms_inspect" / "server.py",
        root / "src" / "ms_modify" / "server.py",
        root / "src" / "ms_create" / "server.py",
    )
    out: set[str] = set()
    for srv in servers:
        out.update(_TOOL_REG_RE.findall(srv.read_text(encoding="utf-8")))
    return out


def command_granted_mcp_tools(command_path: Path) -> set[str]:
    text = command_path.read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    raw = fm.get("allowed-tools", "")
    entries = [t.strip() for t in (raw if isinstance(raw, list) else raw.split(",")) if t.strip()]
    granted: set[str] = set()
    for entry in entries:
        m = _PLUGIN_GRANT_RE.match(entry)
        if m:
            granted.add(m.group(1))
    return granted


def verify_bundle_tool_grants(bundles: dict[str, str], repo_root: Path | None = None) -> list[str]:
    """Return any violations where a bundle names a registered MCP tool not granted to its stage."""
    root = repo_root or default_repo_root()
    all_tools = registered_mcp_tools(root)
    problems: list[str] = []
    for name, content in bundles.items():
        cmd_name = BUNDLE_COMMAND_MAP[name]
        cmd_path = root / ".claude" / "commands" / f"{cmd_name}.md"
        granted = command_granted_mcp_tools(cmd_path)
        mentioned = {tok for tok in _MS_TOKEN_RE.findall(content) if tok in all_tools}
        ungranted = sorted(mentioned - granted)
        if ungranted:
            problems.append(
                f"bundles/{name}.md mentions ungranted MCP tools for {cmd_name}: {ungranted}"
            )
    return problems


def write_stage_bundles(repo_root: Path | None = None) -> list[Path]:
    root = repo_root or default_repo_root()
    out_dir = root / ".claude" / "skills" / "radio-interferometry" / "bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    bundles = build_stage_bundles(root)
    written: list[Path] = []
    for name, content in bundles.items():
        p = out_dir / f"{name}.md"
        p.write_text(content, encoding="utf-8")
        written.append(p)
    return written


def check_stage_bundles(repo_root: Path | None = None) -> list[str]:
    root = repo_root or default_repo_root()
    out_dir = root / ".claude" / "skills" / "radio-interferometry" / "bundles"
    bundles = build_stage_bundles(root)
    problems: list[str] = []
    for name, expected in bundles.items():
        p = out_dir / f"{name}.md"
        if not p.is_file():
            problems.append(f"Missing bundle file: {p}")
            continue
        actual = p.read_text(encoding="utf-8")
        if actual != expected:
            problems.append(f"Out-of-sync bundle file: {p} (re-run `pixi run gen-stage-bundles`)")
        if "\u2014" in actual or "\u2013" in actual:
            problems.append(f"Bundle contains em/en dash: {p}")
    problems.extend(verify_bundle_tool_grants(bundles, root))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify static stage skill bundles.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify on-disk bundles match source files and stage grants without writing.",
    )
    args = parser.parse_args(argv)

    root = default_repo_root()
    if args.check:
        problems = check_stage_bundles(root)
        if problems:
            for item in problems:
                print(item, file=sys.stderr)
            return 1
        print(f"OK: {len(BUNDLE_NAMES)} stage bundles verified.")
        return 0

    written = write_stage_bundles(root)
    for p in written:
        print(f"wrote {p.relative_to(root)} ({p.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
