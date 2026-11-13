"""
Unit tests for SAFE_RM_TABLE_SNIPPET -- the archive-aside guard pasted into
every generated script that (re)writes a caltable.

Its failure mode is silent and irreversible: a script that still deletes on a
retry destroys the only copy of the previous attempt's caltable, with nothing
downstream able to tell.
"""

from __future__ import annotations

import os

import pytest

from ms_modify import pathguard


@pytest.fixture
def safe_rm_table():
    """exec the pasted source and hand back the function it defines."""
    ns: dict = {"os": os}
    exec(pathguard.SAFE_RM_TABLE_SNIPPET, ns)
    return ns["_safe_rm_table"]


def test_missing_path_is_a_noop(safe_rm_table, tmp_path):
    target = tmp_path / "gain.g"
    safe_rm_table(str(target))
    assert not target.exists()


def test_existing_table_is_archived_not_deleted(safe_rm_table, tmp_path):
    target = tmp_path / "gain.g"
    target.mkdir()
    (target / "table.dat").write_text("attempt 1")

    safe_rm_table(str(target))

    assert not target.exists()
    archived = tmp_path / "gain.g.attempt1"
    assert archived.is_dir()
    assert (archived / "table.dat").read_text() == "attempt 1"


def test_second_retry_does_not_clobber_the_first_archive(safe_rm_table, tmp_path):
    target = tmp_path / "gain.g"

    target.mkdir()
    (target / "table.dat").write_text("attempt 1")
    safe_rm_table(str(target))

    target.mkdir()
    (target / "table.dat").write_text("attempt 2")
    safe_rm_table(str(target))

    assert (tmp_path / "gain.g.attempt1" / "table.dat").read_text() == "attempt 1"
    assert (tmp_path / "gain.g.attempt2" / "table.dat").read_text() == "attempt 2"


def test_refuses_to_touch_a_measurement_set(safe_rm_table, tmp_path):
    ms = tmp_path / "target.ms"
    ms.mkdir()
    (ms / "table.info").write_text("Type = Measurement Set\n")

    with pytest.raises(RuntimeError, match="Measurement Set"):
        safe_rm_table(str(ms))

    # Refused, so nothing moved.
    assert ms.exists()
    assert not (tmp_path / "target.ms.attempt1").exists()


class TestValidateOutputCaltable:
    """CR-11a: validate_output_caltable rejects workdir itself, outside paths, and MSs."""

    def test_rejects_output_equal_to_workdir(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        workdir = tmp_path / "work"
        workdir.mkdir()
        ms = tmp_path / "src.ms"
        with pytest.raises(ComputationError, match="equals workdir"):
            pathguard.validate_output_caltable(str(workdir), str(workdir), str(ms))

    def test_rejects_output_outside_workdir(self, tmp_path):
        from ms_inspect.exceptions import ComputationError

        workdir = tmp_path / "work"
        workdir.mkdir()
        ms = tmp_path / "src.ms"
        with pytest.raises(ComputationError, match="not inside workdir"):
            pathguard.validate_output_caltable(str(tmp_path / "gain.G"), str(workdir), str(ms))

    def test_accepts_output_strictly_inside_workdir(self, tmp_path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        ms = tmp_path / "src.ms"
        resolved = pathguard.validate_output_caltable(
            str(workdir / "gain.G"), str(workdir), str(ms)
        )
        assert resolved == (workdir / "gain.G").resolve()
