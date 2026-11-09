"""
Unit tests for ms_casa_tool: tier policy, plan (validation before anything runs),
the copy manifest, and run() against a fake casatools instance. No CASA needed
except the one partition test, which skips without casatools.
"""

from __future__ import annotations

import json

import pytest

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.casa_tool_policy import COPY, EDIT, NEVER, POLICIES, READ
from ms_modify import casa_tool as ct


def _c(method, **args):
    return {"method": method, "args": args}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_tiers_do_not_overlap():
    p = POLICIES["table"]
    sets = [p.read, p.copy, p.edit, p.never]
    assert sum(len(s) for s in sets) == len(p.all_methods())


def test_every_installed_table_method_has_a_tier():
    casatools = pytest.importorskip("casatools")
    public = {m for m in dir(casatools.table()) if not m.startswith("_")}
    p = POLICIES["table"]
    assert sorted(public - p.all_methods()) == [], "casatools gained a method: give it a tier"
    assert sorted(p.all_methods() - public) == [], "policy lists a method casatools lacks"


def test_known_tiers():
    p = POLICIES["table"]
    assert p.tier("getcol") == READ
    assert p.tier("copy") == COPY
    assert p.tier("putcol") == EDIT
    assert p.tier("taql") == NEVER
    assert p.tier("not_a_method") is None


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


@pytest.fixture
def wd(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d.resolve()


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "src.ms"
    d.mkdir()
    return d.resolve()


def test_read_open_is_forced_nomodify(wd, src):
    pl = ct.plan("table", [_c("open", tablename=str(src)), _c("close")], wd, False, [])
    assert pl.calls[0].args["nomodify"] is True
    assert pl.calls[0].args["tablename"] == str(src)


def test_unknown_tool_refused(wd):
    with pytest.raises(ComputationError, match="serves"):
        ct.plan("ms", [_c("open")], wd, False, [])


@pytest.mark.parametrize("method", ["taql", "query", "clearlocks", "lock", "row"])
def test_never_tier_refused_even_with_allow_write(wd, method):
    with pytest.raises(ComputationError, match="every mode"):
        ct.plan("table", [_c(method)], wd, True, [])


def test_unlisted_method_refused(wd):
    with pytest.raises(ComputationError, match="not in the table policy"):
        ct.plan("table", [_c("brand_new")], wd, True, [])


@pytest.mark.parametrize("method", ["putcol", "copy", "addrows"])
def test_write_tiers_need_allow_write(wd, src, method):
    with pytest.raises(ComputationError, match="allow_write"):
        ct.plan("table", [_c("open", tablename=str(src)), _c(method)], wd, False, [])


def test_nomodify_false_needs_allow_write(wd, src):
    with pytest.raises(ComputationError, match="allow_write"):
        ct.plan("table", [_c("open", tablename=str(src), nomodify=False)], wd, False, [])


def test_source_ms_cannot_be_opened_for_writing(wd, src):
    with pytest.raises(ComputationError, match="not a copy made by ms_casa_tool"):
        ct.plan("table", [_c("open", tablename=str(src), nomodify=False)], wd, True, [])


def test_lockoptions_refused(wd, src):
    with pytest.raises(ComputationError, match="lockoptions"):
        ct.plan("table", [_c("open", tablename=str(src), lockoptions="user")], wd, False, [])


def test_double_open_refused(wd, src):
    calls = [_c("open", tablename=str(src)), _c("open", tablename=str(src))]
    with pytest.raises(ComputationError, match="already open"):
        ct.plan("table", calls, wd, False, [])


def test_copy_then_edit_in_one_list(wd, src):
    dest = wd / "copy.ms"
    calls = [
        _c("open", tablename=str(src)),
        _c("copy", newtablename=str(dest)),
        _c("close"),
        _c("open", tablename=str(dest), nomodify=False),
        _c("putcell", columnname="X", rownr=0, thevalue=1),
        _c("close"),
    ]
    pl = ct.plan("table", calls, wd, True, [])
    assert pl.calls[1].args["deep"] is True
    assert pl.calls[1].makes_copy_of == str(src)
    assert pl.calls[4].written == str(dest)
    assert [c["path"] for c in pl.new_copies] == [str(dest)]


def test_shallow_copy_refused(wd, src):
    calls = [_c("open", tablename=str(src)), _c("copy", newtablename=str(wd / "c"), deep=False)]
    with pytest.raises(ComputationError, match="deep=False"):
        ct.plan("table", calls, wd, True, [])


def test_copy_destination_must_be_inside_workdir(wd, src, tmp_path):
    calls = [_c("open", tablename=str(src)), _c("copy", newtablename=str(tmp_path / "out"))]
    with pytest.raises(ComputationError, match="outside the workdir"):
        ct.plan("table", calls, wd, True, [])


def test_copy_destination_must_not_exist(wd, src):
    (wd / "there").mkdir()
    calls = [_c("open", tablename=str(src)), _c("copy", newtablename=str(wd / "there"))]
    with pytest.raises(ComputationError, match="already exists"):
        ct.plan("table", calls, wd, True, [])


def test_edit_on_read_only_session_refused(wd, src):
    manifest = [{"path": str(src)}]  # even a listed copy needs nomodify=False
    calls = [_c("open", tablename=str(src)), _c("putcol", columnname="X", value=[1])]
    with pytest.raises(ComputationError, match="nomodify=True"):
        ct.plan("table", calls, wd, True, manifest)


def test_subtable_of_a_copy_counts_as_a_copy(wd):
    copy = wd / "c.ms"
    (copy / "ANTENNA").mkdir(parents=True)
    calls = [_c("open", tablename=str(copy / "ANTENNA"), nomodify=False)]
    pl = ct.plan("table", calls, wd, True, [{"path": str(copy)}])
    assert pl.calls[0].args["nomodify"] is False


def test_copyrows_target_must_be_a_copy(wd, src):
    calls = [_c("open", tablename=str(src)), _c("copyrows", outtable=str(wd / "x"))]
    with pytest.raises(ComputationError, match="outtable"):
        ct.plan("table", calls, wd, True, [])


def test_whole_list_checked_before_any_run(wd, src):
    calls = [_c("open", tablename=str(src)), _c("getcol", columnname="A"), _c("taql")]
    with pytest.raises(ComputationError, match=r"call 2 \(taql\)"):
        ct.plan("table", calls, wd, False, [])


def test_create_needs_closed_session_and_new_dest(wd, src):
    with pytest.raises(ComputationError, match="close it first"):
        ct.plan(
            "table",
            [_c("open", tablename=str(src)), _c("create", tablename=str(wd / "n"))],
            wd,
            True,
            [],
        )
    pl = ct.plan("table", [_c("create", tablename=str(wd / "n"))], wd, True, [])
    assert pl.new_copies[0]["source"] == "(created empty)"


# ---------------------------------------------------------------------------
# run, with a fake casatools.table
# ---------------------------------------------------------------------------


class FakeTable:
    instances: list = []

    def __init__(self):
        self.log = []
        self.closed = 0
        FakeTable.instances.append(self)

    def open(self, tablename, nomodify=True):
        self.log.append(("open", tablename, nomodify))

    def nrows(self):
        return 7

    def getcol(self, columnname):
        import numpy as np

        return np.arange(6.0).reshape(2, 3)

    def getcell(self, columnname, rownr):
        return float("nan")

    def copy(self, newtablename, deep=True):
        self.log.append(("copy", newtablename, deep))

    def close(self):
        self.closed += 1

    def done(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeTable.instances = []
    monkeypatch.setattr(ct, "_new_instance", lambda tool: FakeTable())
    monkeypatch.setattr(ct, "record_stage", lambda *a, **k: None)
    return FakeTable


def test_run_reads_and_spills_arrays(fake, wd, src):
    out = ct.run(
        "table",
        [_c("open", tablename=str(src)), _c("nrows"), _c("getcol", columnname="A"), _c("close")],
        str(wd),
    )
    res = out["data"]["results"]["value"]
    assert res[1]["value"] == 7
    spilled = res[2]["value"]
    assert spilled["shape"] == [2, 3] and (wd / "casa_tool_1_call2.npy").exists()
    assert (wd / "casa_tool_1.json").exists()
    assert fake.instances[0].log[0] == ("open", str(src), True)


def test_run_inline_when_small_enough(fake, wd, src):
    out = ct.run(
        "table",
        [_c("open", tablename=str(src)), _c("getcol", columnname="A")],
        str(wd),
        inline_max_elements=6,
    )
    assert out["data"]["results"]["value"][1]["value"] == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]


def test_nan_is_returned_as_string(fake, wd, src):
    out = ct.run(
        "table", [_c("open", tablename=str(src)), _c("getcell", columnname="A", rownr=0)], str(wd)
    )
    assert out["data"]["results"]["value"][1]["value"] == "nan"


def test_failure_closes_and_keeps_earlier_results(fake, wd, src):
    fake.getcol = lambda self, columnname: (_ for _ in ()).throw(RuntimeError("no such column"))
    out = ct.run(
        "table",
        [_c("open", tablename=str(src)), _c("nrows"), _c("getcol", columnname="Z"), _c("nrows")],
        str(wd),
    )
    assert out["data"]["failed_call"]["index"] == 2
    assert out["data"]["n_calls_run"] == 2
    assert out["data"]["results"]["flag"] == "PARTIAL"
    assert fake.instances[-1].closed == 1


def test_copy_is_recorded_in_manifest(fake, wd, src):
    dest = wd / "copy.ms"
    out = ct.run(
        "table",
        [_c("open", tablename=str(src)), _c("copy", newtablename=str(dest)), _c("close")],
        str(wd),
        allow_write=True,
    )
    assert out["data"]["new_copies"][0]["path"] == str(dest)
    saved = json.loads((wd / ct.MANIFEST_NAME).read_text())
    assert saved["copies"][0]["source"] == str(src)
    assert fake.instances[0].log[1] == ("copy", str(dest), True)


def test_refused_list_does_not_touch_casa(fake, wd, src):
    with pytest.raises(ComputationError):
        ct.run("table", [_c("open", tablename=str(src)), _c("putcol")], str(wd))
    assert fake.instances == []
