"""
refresh_casadocs.py — copy the CASA Docs task pages into the casa-docs skill.

Run by hand after a CASA version bump:

    pixi run refresh-casadocs

It writes ``.claude/skills/casa-docs/tasks/`` and ``.claude/skills/casa-docs/NOTICE``
and deletes the previous output first. Nothing reads casangi/casadocs at runtime.

Source: https://github.com/casangi/casadocs, ``docs/tasks/task_<name>.rst``, at the
highest tag ``v<major>.<minor>.<patch>-<N>`` for the installed casatasks version.
The tag counter N is not the casatasks build number.

Per task page:

- GUI tasks (``EXCLUDE``) are left out.
- A link whose target is not ``http(s)`` is reduced to its text: its target is a
  casadocs page that is not copied.
- A page of at most ``MAX_PIECE_TOKENS`` is written whole to ``tasks/<name>.rst``.
- A larger page is cut at its section headings (Returns, Description, Examples,
  Development) and at each top-level ``.. rubric::``. Adjacent cuts in the same
  merge group are merged up to ``MERGE_TARGET`` tokens: Returns goes with
  Description, Development with Examples, because both are short. The pieces go to
  ``tasks/<name>/NN-<slug>.rst`` and ``tasks/<name>.rst`` becomes an index of them.
- A piece above ``MAX_PIECE_TOKENS`` after the cut stops the run with ValueError,
  so a new page shape is seen and decided.

Tokens are estimated as characters / 4.
"""

from __future__ import annotations

import importlib.metadata
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/casangi/casadocs"
SKILL_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "casa-docs"
TASKS_DIR = SKILL_DIR / "tasks"
NOTICE = SKILL_DIR / "NOTICE"

MAX_PIECE_TOKENS = 4000
MERGE_TARGET = 2000
EXCLUDE = frozenset({"imview", "msview", "plotms", "plotcal"})

_GROUP = {"Returns": 0, "Description": 0, "Examples": 1, "Development": 1}
_SECTION = re.compile(r"^(Returns|Description|Examples|Development)$")
_RUBRIC = re.compile(r"^   \.\. rubric:: (.+)$")
_ANCHOR = re.compile(r"^\.\. _\w+:$")
_LINK = re.compile(r"`([^`<]+?)\s*<([^>`]+)>`__?", re.S)


def tokens(text: str) -> int:
    return -(-len(text) // 4)


def resolve_tag(casatasks_version: str) -> str:
    """Highest v<M.m.p>-N tag of casangi/casadocs for the given casatasks version."""
    mmp = ".".join(casatasks_version.split(".")[:3])
    out = subprocess.run(
        ["git", "ls-remote", "--tags", REPO], check=True, capture_output=True, text=True
    ).stdout
    pattern = re.compile(rf"refs/tags/v{re.escape(mmp)}-(\d+)$")
    counters = [int(m.group(1)) for line in out.splitlines() if (m := pattern.search(line))]
    if not counters:
        raise ValueError(f"casadocs has no v{mmp}-N tag for casatasks {casatasks_version}")
    return f"v{mmp}-{max(counters)}"


def strip_links(text: str) -> str:
    """Reduce every link with a non-http target to its text."""

    def _sub(m: re.Match) -> str:
        return m.group(0) if m.group(2).startswith(("http://", "https://")) else m.group(1)

    return _LINK.sub(_sub, text)


def _cuts(lines: list[str]) -> list[tuple[str, str, int]]:
    """(section, label, start line) of each cut. Anchor and blank lines above a
    heading belong to the cut that the heading starts."""
    cuts: list[tuple[str, str, int]] = []
    section = ""
    for i, line in enumerate(lines):
        m_sec, m_rub = _SECTION.match(line), _RUBRIC.match(line)
        if not (m_sec or m_rub):
            continue
        if m_sec:
            section = label = m_sec.group(1)
        else:
            label = m_rub.group(1).replace("*", "").replace("\\", "").strip()
        start = i
        while start > 0 and (not lines[start - 1].strip() or _ANCHOR.match(lines[start - 1])):
            start -= 1
        cuts.append((section, label, start))
    return cuts


def split_page(name: str, text: str) -> list[dict]:
    """Pieces of one page: [{section, labels, text}], merged to MERGE_TARGET."""
    lines = text.splitlines(keepends=True)
    cuts = _cuts([ln.rstrip("\n") for ln in lines])
    if not cuts:
        raise ValueError(f"{name}: {tokens(text)} tokens and no section heading to cut at")
    raw = []
    for k, (section, label, start) in enumerate(cuts):
        end = cuts[k + 1][2] if k + 1 < len(cuts) else len(lines)
        raw.append({"section": section, "labels": [label], "text": "".join(lines[start:end])})
    # Text above the first heading goes with the first piece.
    raw[0]["text"] = "".join(lines[: cuts[0][2]]) + raw[0]["text"]
    merged: list[dict] = []
    for piece in raw:
        last = merged[-1] if merged else None
        if (
            last is not None
            and _GROUP[last["section"]] == _GROUP[piece["section"]]
            and tokens(last["text"] + piece["text"]) <= MERGE_TARGET
        ):
            last["labels"] += [lb for lb in piece["labels"] if lb not in last["labels"]]
            last["text"] += piece["text"]
        else:
            merged.append(dict(piece))
    for piece in merged:
        n = tokens(piece["text"])
        if n > MAX_PIECE_TOKENS:
            raise ValueError(
                f"{name}: piece {piece['section']} / {piece['labels'][0]!r} is {n} tokens "
                f"(> {MAX_PIECE_TOKENS})"
            )
    return merged


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-") or "piece"


def index_text(name: str, tag: str, pieces: list[tuple[str, dict]]) -> str:
    """The index that replaces a split page. One line per piece."""
    out = [
        f"{name}: CASA Docs task page ({tag}), split into {len(pieces)} pieces.\n",
        "Read only the piece you need. Paths are relative to this file's directory.\n",
        "Examples holds call patterns; Description holds parameter and mode prose.\n\n",
    ]
    for rel, piece in pieces:
        labels = "; ".join(piece["labels"])
        out.append(f"{rel}  ~{tokens(piece['text'])} tokens  {labels}\n")
    return "".join(out)


def write_tasks(src: Path, tag: str) -> int:
    """Write every task page under src (docs/tasks) to TASKS_DIR. Returns the count."""
    if TASKS_DIR.exists():
        shutil.rmtree(TASKS_DIR)
    TASKS_DIR.mkdir(parents=True)
    count = 0
    for path in sorted(src.glob("task_*.rst")):
        name = path.stem.removeprefix("task_")
        if name in EXCLUDE:
            continue
        text = strip_links(path.read_text())
        count += 1
        if tokens(text) <= MAX_PIECE_TOKENS:
            (TASKS_DIR / f"{name}.rst").write_text(text)
            continue
        (TASKS_DIR / name).mkdir()
        written = []
        for k, piece in enumerate(split_page(name, text), start=1):
            first = next((lb for lb in piece["labels"] if lb != "Returns"), "Returns")
            rel = f"{name}/{k:02d}-{_slug(first)}.rst"
            (TASKS_DIR / rel).write_text(piece["text"])
            written.append((rel, piece))
        (TASKS_DIR / f"{name}.rst").write_text(index_text(name, tag, written))
    return count


def notice_text(tag: str, casatasks_version: str, licence: str) -> str:
    return (
        "The files under tasks/ are derived from CASA Docs,\n"
        f"{REPO}, tag {tag}, docs/tasks/task_<name>.rst,\n"
        f"for casatasks {casatasks_version}.\n"
        "Changes: GUI tasks left out; links to casadocs pages reduced to their text;\n"
        "large pages split into pieces with an index. Generated by\n"
        "src/casa_tasks/refresh_casadocs.py.\n\n"
        "CASA Docs is licensed under the Apache License, Version 2.0, reproduced below.\n\n"
        + licence
    )


def main() -> int:
    version = importlib.metadata.version("casatasks")
    tag = resolve_tag(version)
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "casadocs"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                tag,
                REPO,
                str(clone),
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(clone), "sparse-checkout", "set", "docs/tasks"], check=True
        )
        count = write_tasks(clone / "docs" / "tasks", tag)
        NOTICE.write_text(notice_text(tag, version, (clone / "LICENSE").read_text()))
    print(f"wrote {count} task pages from casadocs {tag} (casatasks {version}) to {TASKS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
