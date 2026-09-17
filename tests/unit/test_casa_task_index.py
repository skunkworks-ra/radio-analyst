"""
Unit tests for util/casa_task_index.py — CASA task -> docs/source URL lookup.

No network access required: static table lookups only.
"""

from __future__ import annotations

from ms_inspect.util.casa_task_index import TASK_SECTIONS, lookup


class TestLookupKnownTasks:
    def test_flagdata_resolves_flagging_section(self):
        loc = lookup("flagdata")
        assert loc is not None
        assert loc.section == "flagging"
        assert loc.docs_url == (
            "https://casadocs.readthedocs.io/en/stable/api/tt/casatasks.flagging.flagdata.html"
        )
        assert loc.source_url == (
            "https://open-bitbucket.nrao.edu/projects/CASA/repos/casa6/raw/"
            "casatasks/src/private/task_flagdata.py?at=refs/heads/master"
        )

    def test_display_heading_does_not_match_section_slug(self):
        # "Single Dish" on the docs site maps to the "single" slug, not
        # "singledish" or "single_dish" — this is the whole reason the
        # index exists rather than deriving the slug from the heading text.
        loc = lookup("sdbaseline")
        assert loc is not None
        assert loc.section == "single"

        loc = lookup("importasdm")
        assert loc is not None
        assert loc.section == "data"  # heading is "Input / Output"

    def test_case_insensitive(self):
        assert lookup("TCLEAN").section == "imaging"
        assert lookup("  Tclean  ").section == "imaging"


class TestLookupUnknownTask:
    def test_unknown_task_returns_none(self):
        assert lookup("not_a_real_task") is None

    def test_empty_string_returns_none(self):
        assert lookup("") is None


class TestIndexIntegrity:
    def test_every_section_has_at_least_one_task(self):
        sections = set(TASK_SECTIONS.values())
        expected = {
            "data",
            "information",
            "flagging",
            "calibration",
            "imaging",
            "single",
            "manipulation",
            "analysis",
            "visualization",
            "simulation",
        }
        assert sections == expected

    def test_all_task_names_are_lowercase(self):
        assert all(name == name.lower() for name in TASK_SECTIONS)
