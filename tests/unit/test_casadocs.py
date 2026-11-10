"""
Unit tests for the CASA Docs copy in the casa-docs skill
(casa_tasks/refresh_casadocs.py and the checked-in .claude/skills/casa-docs/).

Offline: the checked-in files and synthetic pages only. `pixi run
refresh-casadocs` makes the files; these tests check what it wrote.
"""

from __future__ import annotations

import re

import pytest

from casa_tasks.refresh_casadocs import (
    EXCLUDE,
    MAX_PIECE_TOKENS,
    NOTICE,
    TASKS_DIR,
    split_page,
    strip_links,
    tokens,
)
from ms_inspect.tools.casa_task_spec import docs_path
from ms_inspect.util.task_spec import load_schemas, task_names

# Schema tasks with no CASA Docs page.
NO_PAGE = {"testconcat"}

_INDEX_HEAD = re.compile(r"^(\w+): CASA Docs task page \(v[\d.]+-\d+\), split into (\d+) pieces\.$")
_INDEX_LINE = re.compile(r"^(\S+\.rst)  ~(\d+) tokens  ")


def _indexes() -> dict[str, list[str]]:
    """name -> index lines, for every split page."""
    out = {}
    for page in TASKS_DIR.glob("*.rst"):
        lines = page.read_text().splitlines()
        if lines and _INDEX_HEAD.match(lines[0]):
            out[page.stem] = lines
    return out


# ------------------------------------------------------------ checked-in copy


def test_every_schema_task_has_a_docs_page():
    missing = [
        name
        for name in task_names()
        if name not in NO_PAGE | EXCLUDE and not (TASKS_DIR / f"{name}.rst").is_file()
    ]
    assert not missing, f"no CASA Docs page for {missing}; run `pixi run refresh-casadocs`"


def test_docs_path_resolves_for_every_copied_task():
    for name in task_names():
        if name in NO_PAGE | EXCLUDE:
            assert docs_path(name) is None
        else:
            assert docs_path(name) == str(TASKS_DIR / f"{name}.rst")


def test_no_docs_file_exceeds_max_piece_tokens():
    big = {
        str(p.relative_to(TASKS_DIR)): tokens(p.read_text())
        for p in TASKS_DIR.rglob("*.rst")
        if tokens(p.read_text()) > MAX_PIECE_TOKENS
    }
    assert not big


def test_index_lines_match_their_pieces():
    indexes = _indexes()
    assert indexes, "no split page found"
    for name, lines in indexes.items():
        stated = int(_INDEX_HEAD.match(lines[0]).group(2))
        entries = [m for line in lines if (m := _INDEX_LINE.match(line))]
        files = sorted(p.name for p in (TASKS_DIR / name).glob("*.rst"))
        assert stated == len(entries) == len(files), name
        for m in entries:
            piece = TASKS_DIR / m.group(1)
            assert piece.is_file(), m.group(1)
            assert int(m.group(2)) == tokens(piece.read_text()), m.group(1)


def test_no_empty_piece():
    # Body text is indented; headings and anchors are not; a rubric is a heading.
    for piece in TASKS_DIR.glob("*/*.rst"):
        body = [
            ln
            for ln in piece.read_text().splitlines()
            if ln.startswith(" ") and ln.strip() and ".. rubric::" not in ln
        ]
        assert body, piece.name


def test_no_relative_links_left():
    for path in TASKS_DIR.rglob("*.rst"):
        assert "<../" not in path.read_text(), path.name


def test_notice_matches_pinned_casatasks():
    tag = re.search(r"tag v(\d+)\.(\d+)\.\d+-\d+", NOTICE.read_text())
    assert tag, "NOTICE has no casadocs tag"
    pinned = load_schemas()["casatasks_version"].split(".")[:2]
    assert list(tag.groups()) == pinned


# -------------------------------------------------------------- pure functions

_PAGE = """

.. _Returns:

Returns
   None

.. _Description:

Description
   Intro text.

   .. rubric:: First block

   First block text.

   -  .. rubric:: Nested

      Nested text stays in First block.

   .. rubric:: Second block

   Second block text.

.. _Examples:

Examples
   Example text.

.. _Development:

Development
   No additional development details
"""


def test_split_page_cuts_at_headings_and_top_level_rubrics_only(monkeypatch):
    import casa_tasks.refresh_casadocs as rc

    monkeypatch.setattr(rc, "MERGE_TARGET", 0)
    pieces = split_page("demo", _PAGE)
    labels = [p["labels"] for p in pieces]
    assert labels == [
        ["Returns"],
        ["Description"],
        ["First block"],
        ["Second block"],
        ["Examples"],
        ["Development"],
    ]
    assert "Nested text stays in First block." in pieces[2]["text"]
    # an anchor line goes with the heading below it
    assert pieces[1]["text"].lstrip().startswith(".. _Description:")
    assert "".join(p["text"] for p in pieces) == _PAGE


def test_split_page_merges_within_group_only():
    pieces = split_page("demo", _PAGE)
    assert [p["labels"] for p in pieces] == [
        ["Returns", "Description", "First block", "Second block"],
        ["Examples", "Development"],
    ]


def test_split_page_rejects_an_oversized_piece(monkeypatch):
    import casa_tasks.refresh_casadocs as rc

    monkeypatch.setattr(rc, "MAX_PIECE_TOKENS", 10)
    with pytest.raises(ValueError, match="tokens"):
        split_page("demo", _PAGE)


def test_strip_links_keeps_http_and_reduces_relative():
    text = (
        "see `level\n   of logging\n   <../../notebooks/usingcasa.ipynb#x>`__ and "
        "`tclean <https://casadocs.readthedocs.io/x.html>`_ and "
        "`gaincal <./casatasks.calibration.gaincal.html>`_"
    )
    out = strip_links(text)
    assert "level\n   of logging" in out
    assert "<../" not in out and "<./" not in out
    assert "`tclean <https://casadocs.readthedocs.io/x.html>`_" in out
    assert "gaincal" in out
