"""
Unit tests for util/array_config.py: the VLA array configuration of an MS,
from ASDM_EXECBLOCK.configName or from the longest baseline with data.

No CASA dependency: msmd is faked and open_table is patched.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from test_field_roles import FakeMsmd
from test_resolved_from_callist import _y_array

from ms_inspect.util import array_config as ac


@pytest.mark.parametrize(
    "name, letters",
    [
        ("D", ["D"]),
        ("BnA", ["B", "A"]),
        (" C ", ["C"]),
        ("", None),
        (None, None),
        ("E", None),
        ("B->C", None),
    ],
)
def test_config_letters(name, letters):
    assert ac.config_letters(name) == letters


def _array(arm_m):
    return ac.array_baselines(FakeMsmd([], antenna_ecef=_y_array(arm_m)))


# Y arms of r give a longest baseline of r * sqrt(3).
@pytest.mark.parametrize(
    "arm_m, letter",
    [(600.0, "D"), (1960.0, "C"), (6400.0, "B"), (21000.0, "A")],
)
def test_longest_baseline_matches_a_configuration(arm_m, letter):
    cfg = ac.config_from_array(_array(arm_m))
    assert cfg["value"] == letter and cfg["flag"] == "INFERRED"


@pytest.mark.parametrize("arm_m", [1000.0, 3500.0])  # 1.7 km and 6.1 km: between configurations
def test_longest_baseline_between_configurations_is_unavailable(arm_m):
    cfg = ac.config_from_array(_array(arm_m))
    assert cfg["value"] is None and cfg["flag"] == "UNAVAILABLE"
    assert "hybrid or move-time" in cfg["note"]


def test_no_array_is_unavailable():
    assert ac.config_from_array(None)["flag"] == "UNAVAILABLE"


class _FakeTable:
    def __init__(self, names):
        self._names = names

    def getcol(self, col):
        assert col == "configName"
        return list(self._names)


def _execblock(monkeypatch, tmp_path, names):
    (tmp_path / "ASDM_EXECBLOCK").mkdir()

    @contextmanager
    def fake_open(_path):
        yield _FakeTable(names)

    monkeypatch.setattr(ac, "open_table", fake_open)
    return ac.config_from_execblock(tmp_path)


def test_execblock_absent_gives_none(tmp_path):
    assert ac.config_from_execblock(tmp_path) is None


def test_execblock_config_is_complete(monkeypatch, tmp_path):
    cfg = _execblock(monkeypatch, tmp_path, ["BnA"])
    assert cfg["value"] == "BnA" and cfg["flag"] == "COMPLETE"


@pytest.mark.parametrize("names", [["B", "C"], ["B->C"]])
def test_execblock_unusable_names_are_unavailable(monkeypatch, tmp_path, names):
    cfg = _execblock(monkeypatch, tmp_path, names)
    assert cfg["value"] is None and cfg["flag"] == "UNAVAILABLE"


def test_resolve_prefers_execblock_over_length(monkeypatch, tmp_path):
    def boom(_p):
        raise AssertionError("msmd opened although ASDM_EXECBLOCK exists")

    monkeypatch.setattr(ac, "open_msmd", boom)
    _execblock(monkeypatch, tmp_path, ["A"])
    assert ac.resolve_array_config(tmp_path)["value"] == "A"
