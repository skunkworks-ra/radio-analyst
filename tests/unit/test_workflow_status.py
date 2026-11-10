"""
Unit tests for tools/workflow_status.py.

What these cover: the branch between "this stage has not happened yet" and
"the probe for this stage failed", and the split between the stage log (what
COMPLETED, as history) and the MS probes (what is TRUE NOW). Fake MS directory
trees and a patched open_table. No CASA is involved.

The old version of this docstring said the tests did not cover "whether the
filesystem heuristics for priorcals, caltables and images match what the
ms_modify tools really write". They did not match — the tool held a hardcoded
list of caltable NAMES while those paths are arguments the caller chooses —
and that was the defect. The heuristics are gone; state comes from
stage_log.jsonl, which the tools write themselves.

What these still do NOT cover: whether open_table raises on a real locked or
corrupt CASA table. That needs a real MS.
"""

from __future__ import annotations

import pytest

from ms_inspect.tools import workflow_status


@pytest.fixture
def fake_ms(tmp_path):
    """A directory that passes validate_ms_path, with no STATE subtable."""
    ms = tmp_path / "fake.ms"
    ms.mkdir()
    (ms / "table.info").write_text("Type = Measurement Set\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    return ms, workdir


def _run(ms, workdir, stokes="I"):
    return workflow_status.run(str(ms), str(workdir), stokes)


class _Raiser:
    """Stand-in for open_table that fails the way a locked table would."""

    def __init__(self, exc):
        self._exc = exc

    def __call__(self, *_args, **_kwargs):
        raise self._exc


def test_absent_state_subtable_is_not_populated_not_unavailable(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    # MAIN opens fine and has no CORRECTED_DATA.
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))

    result = _run(ms, workdir)
    intents = result["data"]["intents_populated"]

    assert intents["value"] is False
    assert intents["flag"] == "COMPLETE"
    assert result["data"]["next_recommended_step"] == "set_intents"


def test_unreadable_state_subtable_yields_unavailable_not_incomplete(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()  # exists, so absence is not the explanation
    monkeypatch.setattr(
        workflow_status, "open_table", _Raiser(RuntimeError("table is locked by another process"))
    )

    result = _run(ms, workdir)
    intents = result["data"]["intents_populated"]

    assert intents["flag"] == "UNAVAILABLE"
    assert intents["value"] is None
    assert "locked" in intents["note"]
    # The critical assertion: a failed probe must not be reported as
    # "intents not set", which would recommend re-running set_intents.
    assert result["data"]["next_recommended_step"] == "probe_failed_intents"
    assert any("STATE subtable exists but could not be read" in w for w in result["warnings"])


def test_unreadable_main_table_yields_unavailable_corrected(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    # Advance past every earlier stage via the stage log, so the derivation
    # actually reaches the CORRECTED_DATA branch instead of stopping before it.
    _log(workdir, "set_intents", "preflag", "priorcals", "initial_bandpass")
    cal_ms = workdir / "calibrators.ms"
    cal_ms.mkdir()
    (cal_ms / "table.info").write_text("Type = Measurement Set\n")

    def _open(path, *_args, **_kwargs):
        if path.endswith("/STATE"):
            return _table(nrows=3, colnames=[])
        raise RuntimeError("permission denied")

    monkeypatch.setattr(workflow_status, "open_table", _open)

    result = _run(ms, workdir)
    corrected = result["data"]["corrected_populated_calibrators"]

    assert corrected["flag"] == "UNAVAILABLE"
    assert corrected["value"] is None
    assert "permission denied" in corrected["note"]
    assert result["data"]["next_recommended_step"] == "probe_failed_corrected_calibrators"
    assert result["completeness_summary"] == "UNAVAILABLE"


def test_present_corrected_column_reads_true(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    monkeypatch.setattr(
        workflow_status,
        "open_table",
        _fake_main_table(colnames=["DATA", "CORRECTED_DATA"]),
    )

    result = _run(ms, workdir)
    corrected = result["data"]["corrected_populated_target"]

    assert corrected["value"] is True
    assert corrected["flag"] == "COMPLETE"


def _log(workdir, *stages, product="/w/thing", measurement=None):
    """Append a completed line per stage, the way a generated script does."""
    import json

    from ms_inspect.util.stage_log import STAGE_LOG_NAME

    with open(workdir / STAGE_LOG_NAME, "a") as fh:
        for stage in stages:
            entry = {
                "stage": stage,
                "product": product,
                "at": "2026-09-02T00:00:00Z",
                "exists": True,
            }
            if measurement is not None:
                entry["measurement"] = measurement
            fh.write(json.dumps(entry) + "\n")


# --- helpers -----------------------------------------------------------------


class _FakeTable:
    def __init__(self, nrows, colnames):
        self._nrows = nrows
        self._colnames = colnames

    def nrows(self):
        return self._nrows

    def colnames(self):
        return self._colnames

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _table(nrows=0, colnames=()):
    return _FakeTable(nrows, list(colnames))


def _fake_main_table(colnames):
    def _open(_path, *_args, **_kwargs):
        return _table(nrows=0, colnames=colnames)

    return _open


# ---------------------------------------------------------------------------
# Stage completion from the log, not from a fixed set of caltable names
# ---------------------------------------------------------------------------


def test_caller_chosen_caltable_names_are_recognised(fake_ms, monkeypatch):
    """Caltable paths are arguments with no default, so no fixed name list
    can be right — completion must come from the stage log, by stage name."""
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(
        workflow_status, "open_table", _fake_main_table(colnames=["DATA", "CORRECTED_DATA"])
    )
    _log(workdir, "set_intents", "preflag", "priorcals", "initial_bandpass", "initial_rflag")
    for stage, product in (
        ("gaincal", "/w/delay.K"),
        ("gaincal", "/w/gain.g"),
        ("bandpass", "/w/bandpass.b"),
        ("fluxscale", "/w/flux.fluxscale"),
    ):
        _log(workdir, stage, product=product)

    result = _run(ms, workdir)
    assert result["data"]["final_solves_completed"] == ["gaincal", "bandpass", "fluxscale"]
    assert result["data"]["next_recommended_step"] != "delay_bandpass_gain"


def test_corrected_is_reported_for_both_measurement_sets(fake_ms, monkeypatch):
    """Calibration runs on calibrators.ms; the target applycal writes CORRECTED
    to the MS this tool is given. Both must be reported, never merged."""
    ms, workdir = fake_ms
    cal_ms = workdir / "calibrators.ms"
    cal_ms.mkdir()
    (cal_ms / "table.info").write_text("Type = Measurement Set\n")

    def _open(path, *_args, **_kwargs):
        if path.endswith("/STATE"):
            return _table(nrows=3, colnames=[])
        if "calibrators.ms" in path:
            return _table(colnames=["DATA", "CORRECTED_DATA"])
        return _table(colnames=["DATA"])

    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _open)
    _log(workdir, "set_intents", "preflag", "priorcals", "initial_bandpass", "initial_rflag")

    result = _run(ms, workdir)
    assert result["data"]["corrected_populated_calibrators"]["value"] is True
    assert result["data"]["corrected_populated_target"]["value"] is False


def test_final_solves_advance_once_corrected_and_flagged(fake_ms, monkeypatch):
    """With CORRECTED on the calibrators and the initial rflag recorded, the
    tool must recommend the final solves, not repeat the prior stage."""
    ms, workdir = fake_ms
    cal_ms = workdir / "calibrators.ms"
    cal_ms.mkdir()
    (cal_ms / "table.info").write_text("Type = Measurement Set\n")
    (ms / "STATE").mkdir()

    def _open(path, *_args, **_kwargs):
        if path.endswith("/STATE"):
            return _table(nrows=3, colnames=[])
        if "calibrators.ms" in path:
            return _table(colnames=["DATA", "CORRECTED_DATA"])
        return _table(colnames=["DATA"])

    monkeypatch.setattr(workflow_status, "open_table", _open)
    _log(workdir, "set_intents", "preflag", "priorcals", "initial_bandpass", "initial_rflag")

    assert _run(ms, workdir)["data"]["next_recommended_step"] == "delay_bandpass_gain"


# ---------------------------------------------------------------------------
# Log vs. live state
# ---------------------------------------------------------------------------


def test_no_stage_log_reads_as_nothing_done_and_says_so(fake_ms, monkeypatch):
    """Deliberate, and not backward compatible: a workdir written before the
    stage log existed cannot be resumed. The warning is what makes that
    visible rather than silently wrong."""
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))

    result = _run(ms, workdir)
    assert result["data"]["stage_log_present"]["value"] is False
    assert result["data"]["stages_completed"] == []
    assert any("stage_log.jsonl" in w for w in result["warnings"])


def test_a_stage_recorded_only_as_failed_does_not_count(fake_ms, monkeypatch):
    """The failure line is the record OF the failure, not of the stage."""
    import json

    from ms_inspect.util.stage_log import STAGE_LOG_NAME

    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))
    _log(workdir, "set_intents")
    (workdir / STAGE_LOG_NAME).open("a").write(
        json.dumps(
            {
                "stage": "preflag",
                "product": "/w/calibrators.ms",
                "exists": False,
                "error": "product not found",
            }
        )
        + "\n"
    )

    result = _run(ms, workdir)
    assert "preflag" not in result["data"]["stages_completed"]
    assert result["data"]["next_recommended_step"] == "apply_preflag"


def test_disagreement_between_log_and_ms_is_reported_not_resolved(fake_ms, monkeypatch):
    """A stage recorded complete whose product is gone from the MS is a real
    event. The tool says so instead of picking a winner."""
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))
    _log(
        workdir,
        "set_intents",
        "preflag",
        "priorcals",
        "initial_bandpass",
        "initial_rflag",
        "gaincal",
        "bandpass",
        "fluxscale",
        "applycal",
    )

    result = _run(ms, workdir)
    assert any(
        "recorded complete in the stage log, but CORRECTED_DATA is not" in w
        for w in result["warnings"]
    )


def test_products_recorded_reports_the_paths_the_run_actually_used(fake_ms, monkeypatch):
    """The names are data now, so the tool can report them instead of assuming."""
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))
    _log(workdir, "gaincal", product="/w/delay.K")
    _log(workdir, "gaincal", product="/w/gain.g")

    assert _run(ms, workdir)["data"]["products_recorded"]["gaincal"] == [
        "/w/delay.K",
        "/w/gain.g",
    ]


# ---------------------------------------------------------------------------
# stokes='IQUV': the same presence rule, two more steps
# ---------------------------------------------------------------------------


def _stokes_i_done(ms, workdir, monkeypatch):
    """A workdir where the Stokes I chain has reached first_image."""
    (ms / "STATE").mkdir()
    cal_ms = workdir / "calibrators.ms"
    cal_ms.mkdir()
    (cal_ms / "table.info").write_text("Type = Measurement Set\n")
    monkeypatch.setattr(
        workflow_status, "open_table", _fake_main_table(colnames=["DATA", "CORRECTED_DATA"])
    )
    _log(workdir, "set_intents", "preflag", "priorcals", "initial_bandpass", "initial_rflag")
    _log(workdir, "gaincal", product="/w/delay.K", measurement={"gaintype": "K"})
    _log(workdir, "bandpass", "fluxscale")
    # calibrate's Stokes I apply on the target: parang is True by default, and
    # no pol table is in the gaintable.
    _log(
        workdir,
        "applycal",
        product=str(ms),
        measurement={"field": "T", "corrected_data": True, "parang": True, "pol_types": []},
    )


def _kcross(workdir):
    _log(workdir, "gaincal", product="/w/kcross.K", measurement={"gaintype": "KCROSS"})


def _dterms(workdir, poltype="Df"):
    _log(workdir, "polcal", product="/w/dterms.D", measurement={"poltype": poltype})


def _pol_apply(workdir, ms, pol_types=("Kcross", "Df")):
    _log(
        workdir,
        "applycal",
        product=str(ms),
        measurement={
            "field": "T",
            "corrected_data": True,
            "parang": True,
            "pol_types": list(pol_types),
        },
    )


def test_stokes_i_chain_is_unchanged_and_says_which_stokes(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    data = _run(ms, workdir)["data"]
    assert data["next_recommended_step"] == "first_image"
    assert data["stokes"] == "I"
    assert "polcal_solves_completed" not in data
    assert "pol_applied_target" not in data


def test_iquv_with_no_pol_solve_asks_for_polcal(fake_ms, monkeypatch):
    """The Stokes I apply (parang True, no pol tables) must not satisfy it."""
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    data = _run(ms, workdir, "IQUV")["data"]
    assert data["next_recommended_step"] == "polcal"
    assert data["polcal_solves_completed"] == []
    assert data["pol_applied_target"]["value"] is False


def test_iquv_needs_both_kcross_and_dterms(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    assert _run(ms, workdir, "IQUV")["data"]["next_recommended_step"] == "polcal"


def test_iquv_with_solves_asks_for_the_pol_apply(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir, "Df+QU")
    data = _run(ms, workdir, "IQUV")["data"]
    assert data["polcal_solves_completed"] == ["Kcross", "Df"]
    assert data["next_recommended_step"] == "applycal_pol_target"


def test_iquv_pol_apply_on_the_target_reaches_first_image(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir)
    _pol_apply(workdir, ms)
    data = _run(ms, workdir, "IQUV")["data"]
    assert data["pol_applied_target"]["value"] is True
    assert data["next_recommended_step"] == "first_image"


def test_iquv_pol_apply_on_calibrators_ms_does_not_count(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir)
    _pol_apply(workdir, workdir / "calibrators.ms")
    assert _run(ms, workdir, "IQUV")["data"]["next_recommended_step"] == "applycal_pol_target"


def test_iquv_pol_apply_matches_the_target_through_a_symlink(fake_ms, monkeypatch, tmp_path):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir)
    link = tmp_path / "link.ms"
    link.symlink_to(ms)
    _pol_apply(workdir, link)
    assert _run(ms, workdir, "IQUV")["data"]["next_recommended_step"] == "first_image"


def test_iquv_apply_without_dterms_table_does_not_count(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir)
    _pol_apply(workdir, ms, pol_types=("Kcross",))
    assert _run(ms, workdir, "IQUV")["data"]["next_recommended_step"] == "applycal_pol_target"


def test_iquv_xf_is_reported_but_not_required(fake_ms, monkeypatch):
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir)
    _log(workdir, "polcal", product="/w/polangle.X", measurement={"poltype": "Xf"})
    _pol_apply(workdir, ms, pol_types=("Kcross", "Df", "Xf"))
    data = _run(ms, workdir, "IQUV")["data"]
    assert data["polcal_solves_completed"] == ["Kcross", "Df", "Xf"]
    assert data["next_recommended_step"] == "first_image"


def test_iquv_lines_without_the_solve_kind_do_not_count_and_warn(fake_ms, monkeypatch):
    """Lines written by an older tool carry no gaintype/poltype/pol_types."""
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _log(workdir, "gaincal", product="/w/kcross.K")
    _log(workdir, "polcal", product="/w/dterms.D")
    result = _run(ms, workdir, "IQUV")
    assert result["data"]["polcal_solves_completed"] == []
    assert result["data"]["next_recommended_step"] == "polcal"
    assert any("do not record the solve kind" in w for w in result["warnings"])


def test_iquv_does_not_skip_an_earlier_missing_step(fake_ms, monkeypatch):
    """Pol steps sit after the target applycal; they never jump the chain."""
    ms, workdir = fake_ms
    (ms / "STATE").mkdir()
    monkeypatch.setattr(workflow_status, "open_table", _fake_main_table(colnames=["DATA"]))
    _log(workdir, "set_intents")
    _kcross(workdir)
    _dterms(workdir)
    assert _run(ms, workdir, "IQUV")["data"]["next_recommended_step"] == "apply_preflag"


def test_unknown_stokes_is_refused(fake_ms):
    from ms_inspect.exceptions import ComputationError

    ms, workdir = fake_ms
    with pytest.raises(ComputationError):
        _run(ms, workdir, "QU")


def test_iquv_plain_d_solve_is_not_a_dterm_solve(fake_ms, monkeypatch):
    """The apply side counts only Df VisCal types, so the solve side must too:
    otherwise a 'D' solve counts as done and its apply never does."""
    ms, workdir = fake_ms
    _stokes_i_done(ms, workdir, monkeypatch)
    _kcross(workdir)
    _dterms(workdir, "D")
    data = _run(ms, workdir, "IQUV")["data"]
    assert data["polcal_solves_completed"] == ["Kcross"]
    assert data["next_recommended_step"] == "polcal"
