"""Unit tests for casa_tasks: schemas, catalog, server argument checks, stage-log line."""

from __future__ import annotations

import json
import os
import sys
import types

import numpy as np
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from casa_tasks.catalog import build_catalog, load_schemas, use_mcp
from casa_tasks.config import (
    GUI_PARAMS,
    GUI_TASKS,
    INSPECT_TASKS,
    MCP_TASK_PARAMS,
    STAGES,
    USE_MCP_ENV,
    WRAPPER_PARAMS,
    check_config,
)
from casa_tasks.runner import (
    MAX_LOGGED_PARAMS_CHARS,
    product_path,
    record_stage_line,
    run_task,
    to_jsonable,
)
from casa_tasks.server import INSTRUCTIONS, build_server, call_log_path, lock_paths
from ms_inspect.util.logs import LOGFILE_ENV
from ms_inspect.util.stage_log import SCHEMA_VERSION, completed_stages, read_stage_log

# --------------------------------------------------------------------- schemas


def test_config_matches_schemas():
    check_config(load_schemas())


def test_check_config_names_an_unknown_parameter():
    schemas = json.loads(json.dumps(load_schemas()))
    del schemas["tasks"]["gaincal"]["params"]["refant"]
    with pytest.raises(ValueError, match="gaincal: unknown parameter 'refant'"):
        check_config(schemas)


def test_schemas_match_installed_casatasks():
    pytest.importorskip("casatasks")
    from casa_tasks.gen_schemas import build

    assert build()["tasks"] == load_schemas()["tasks"], (
        "casa_task_schemas.json is stale for the installed casatasks; "
        "run `pixi run gen-casa-schemas` and review the diff"
    )


def test_stage_enum_covers_every_stage_workflow_status_reads():
    import ms_inspect.tools.workflow_status as ws

    read = {
        v
        for k, v in vars(ws).items()
        if k.startswith("_") and isinstance(v, str) and v.islower() and v.isidentifier()
    }
    read |= set(ws._FINAL_SOLVES)
    assert len(read) >= 11, read  # the probe found the module's stage constants
    assert read <= set(STAGES), read - set(STAGES)


def test_vec_type_accepts_scalar_or_list():
    prop = load_schemas()["tasks"]["applycal"]["params"]["gaintable"]
    assert {"type": "string"} in prop["anyOf"]
    assert {"type": "array", "items": {"type": "string"}} in prop["anyOf"]


# --------------------------------------------------------------------- catalog


def _props(catalog: dict, task: str) -> list[str]:
    return list(catalog[task]["inputSchema"]["properties"])


def test_use_mcp_modify_lists_exactly_the_current_tasks_and_params():
    catalog = build_catalog("modify", restricted=True)
    assert set(catalog) == set(MCP_TASK_PARAMS)
    for task, params in MCP_TASK_PARAMS.items():
        assert _props(catalog, task) == [*params, *WRAPPER_PARAMS]


def test_inspect_lists_full_read_only_set_whatever_use_mcp():
    restricted = build_catalog("inspect", restricted=True)
    assert restricted == build_catalog("inspect", restricted=False)
    assert set(restricted) == INSPECT_TASKS
    assert "doPlot" in _props(restricted, "plotweather")


def test_full_catalog_split_and_gui_exclusion():
    inspect_cat = build_catalog("inspect", restricted=False)
    modify_cat = build_catalog("modify", restricted=False)
    assert set(inspect_cat) == INSPECT_TASKS
    assert not set(inspect_cat) & set(modify_cat)
    assert not (set(inspect_cat) | set(modify_cat)) & GUI_TASKS
    for catalog in (inspect_cat, modify_cat):
        for task, spec in catalog.items():
            schema = spec["inputSchema"]
            assert schema["additionalProperties"] is False, task
            assert not set(schema["properties"]) & GUI_PARAMS, task
    assert all("stage" not in _props(inspect_cat, t) for t in inspect_cat)
    assert all("stage" in _props(modify_cat, t) for t in modify_cat)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("true", True), ("1", True), ("false", False), ("0", False), (" No ", False)],
)
def test_use_mcp_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(USE_MCP_ENV, raising=False)
    else:
        monkeypatch.setenv(USE_MCP_ENV, value)
    assert use_mcp() is expected


# ---------------------------------------------------------------------- server


async def _call(kind: str, name: str, arguments: dict):
    server = build_server(kind, restricted=kind == "modify")
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        return await client.call_tool(name, arguments)


async def test_server_rejects_misspelled_parameter():
    result = await _call("modify", "gaincal", {"vis": "/x.ms", "soln": "int"})
    assert result.isError
    assert "'soln' was unexpected" in result.content[0].text


async def test_server_rejects_unknown_stage():
    result = await _call("modify", "gaincal", {"vis": "/x.ms", "stage": "final_gain"})
    assert result.isError
    assert "is not one of" in result.content[0].text


async def test_inspect_server_has_no_stage_argument():
    result = await _call("inspect", "listobs", {"vis": "/x.ms", "stage": "gaincal"})
    assert result.isError
    assert "'stage' was unexpected" in result.content[0].text


async def test_server_lists_schemas_and_read_only_hint():
    server = build_server("inspect", restricted=False)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == INSPECT_TASKS
    # No readOnlyHint: several read-only tasks can overwrite a file they are given.
    assert tools["listobs"].annotations is None
    assert tools["listobs"].inputSchema["additionalProperties"] is False


def test_lock_paths(tmp_path):
    ms = str(tmp_path / "a.ms")
    assert lock_paths({"vis": ms, "caltable": "b.G"}) == [ms, os.path.abspath("b.G")]
    assert lock_paths({"vis": [ms, "other.ms"], "concatvis": "c.ms"}) == [
        ms,
        os.path.abspath("other.ms"),
        os.path.abspath("c.ms"),
    ]
    assert lock_paths({"vis": ms, "outputvis": "cal.ms", "field": "0"}) == [
        ms,
        os.path.abspath("cal.ms"),
    ]
    assert lock_paths({"vis": ms, "caltable": "g.G", "fluxtable": "f.G"}) == [
        ms,
        os.path.abspath("g.G"),
        os.path.abspath("f.G"),
    ]
    assert lock_paths({"imagename": "img"}) == [os.path.abspath("img")]
    assert lock_paths({"field": "0"}) == []
    assert lock_paths({"vis": ""}) == []
    assert lock_paths({"vis": []}) == []
    assert lock_paths({"vis": "~/a.ms"}) == [os.path.expanduser("~/a.ms")]


async def test_server_sends_measures_update_note():
    """The note reaches the server's initialization options (what initialize sends)."""
    server = build_server("modify", restricted=True)
    options = server._mcp_server.create_initialization_options()
    assert options.instructions == INSTRUCTIONS
    assert "measures_update" in INSTRUCTIONS


# ------------------------------------------------------------------ stage line


def test_tclean_product_is_tt0_when_only_taylor_terms_exist(tmp_path):
    prefix = str(tmp_path / "img")
    assert product_path("tclean", {"imagename": prefix}) == prefix + ".image"
    (tmp_path / "img.image.tt0").mkdir()
    assert product_path("tclean", {"imagename": prefix}) == prefix + ".image.tt0"
    (tmp_path / "img.image").mkdir()
    assert product_path("tclean", {"imagename": prefix}) == prefix + ".image"


def _stub_casatasks(monkeypatch, **tasks):
    """Install a fake casatasks module so run_task runs without CASA."""
    module = types.ModuleType("casatasks")
    for name, fn in tasks.items():
        setattr(module, name, fn)
    monkeypatch.setitem(sys.modules, "casatasks", module)
    monkeypatch.delenv(LOGFILE_ENV, raising=False)


def test_run_task_passes_only_casa_params_and_records_stage(monkeypatch, tmp_path):
    seen = {}

    def gaincal(**kwargs):
        seen.update(kwargs)
        os.mkdir(kwargs["caltable"])
        return {"solvestats": np.array([3, 4])}

    _stub_casatasks(monkeypatch, gaincal=gaincal)
    params = {"vis": "a.ms", "caltable": str(tmp_path / "g.G")}
    env = run_task("gaincal", dict(params), stage="gaincal", workdir=str(tmp_path))
    assert seen == params
    assert env["status"] == "ok"
    assert env["warnings"] == []
    assert env["data"]["return"] == {"solvestats": [3, 4]}
    assert completed_stages(read_stage_log(tmp_path)) == {"gaincal"}


def test_run_task_exception_is_error_envelope_and_records_nothing(monkeypatch, tmp_path):
    def gaincal(**kwargs):
        raise AssertionError("the vis parameter must be a path that exists")

    _stub_casatasks(monkeypatch, gaincal=gaincal)
    env = run_task("gaincal", {"vis": "nope.ms"}, stage="gaincal", workdir=str(tmp_path))
    assert env["status"] == "error"
    assert env["error_type"] == "AssertionError"
    assert "must be a path" in env["message"]
    assert read_stage_log(tmp_path) == []


def test_run_task_uses_the_log_path_the_server_chose(monkeypatch, tmp_path):
    pytest.importorskip("casaconfig")
    _stub_casatasks(monkeypatch, listobs=lambda **kw: {})
    chosen = str(tmp_path / "casa-x-listobs.log")
    env = run_task("listobs", {"vis": "a.ms"}, log_path=chosen)
    assert env["data"]["casa_log"] == chosen


def test_call_log_path_is_a_new_casa_log_next_to_the_server_log(monkeypatch, tmp_path):
    monkeypatch.setenv("RADIO_MCP_DIR", str(tmp_path))
    first, second = call_log_path("tclean"), call_log_path("tclean")
    assert first != second
    assert os.path.basename(first).startswith("casa-") and first.endswith("-tclean.log")


def test_run_task_stage_without_workdir_warns(monkeypatch):
    _stub_casatasks(monkeypatch, applycal=lambda **kw: None)
    env = run_task("applycal", {"vis": "a.ms"}, stage="applycal", workdir="")
    assert env["status"] == "ok"
    assert "without workdir" in env["warnings"][0]


def test_product_path(tmp_path):
    assert product_path("tclean", {"imagename": "img/t"}) == os.path.abspath("img/t.image")
    assert product_path("fluxscale", {"caltable": "g.G", "fluxtable": "f.G"}) == os.path.abspath(
        "f.G"
    )
    assert product_path("applycal", {"vis": "a.ms"}) == os.path.abspath("a.ms")
    assert product_path("gaincal", {"vis": "a.ms"}) is None


def test_record_stage_line_present_product(tmp_path):
    caltable = tmp_path / "g.G"
    caltable.mkdir()
    params = {"vis": str(tmp_path / "a.ms"), "caltable": str(caltable), "solint": "int"}
    assert record_stage_line(str(tmp_path), "initial_bandpass", "gaincal", params, "c.log") is None
    (entry,) = read_stage_log(tmp_path)
    assert entry["schema_version"] == SCHEMA_VERSION == 2
    assert entry["stage"] == "initial_bandpass"
    assert entry["task"] == "gaincal"
    assert entry["params"] == params
    assert entry["product"] == str(caltable)
    assert entry["exists"] is True
    assert entry["casa_log"] == "c.log"
    assert completed_stages([entry]) == {"initial_bandpass"}


def test_record_stage_line_missing_product_is_not_complete(tmp_path):
    params = {"vis": "a.ms", "caltable": str(tmp_path / "never.G")}
    warning = record_stage_line(str(tmp_path), "gaincal", "gaincal", params)
    assert warning and "does not exist" in warning
    (entry,) = read_stage_log(tmp_path)
    assert entry["exists"] is False
    assert completed_stages([entry]) == set()


def test_record_stage_line_unwritable_workdir_warns_without_raising(tmp_path):
    warning = record_stage_line(str(tmp_path / "no_such_dir"), "gaincal", "gaincal", {})
    assert warning and "stage log not written" in warning


def test_record_stage_line_truncates_long_params(tmp_path):
    params = {"vis": "a.ms", "inpfile": ["x" * 100] * 50}
    record_stage_line(str(tmp_path), "flag_data", "flagdata", params)
    (entry,) = read_stage_log(tmp_path)
    assert set(entry["params"]) == {"truncated"}
    assert len(entry["params"]["truncated"]) == MAX_LOGGED_PARAMS_CHARS


def test_to_jsonable_converts_numpy():
    value = {"a": np.array([1.0, 2.0]), 3: np.float32(0.5), "b": (np.int64(4), b"x")}
    assert to_jsonable(value) == {"a": [1.0, 2.0], "3": 0.5, "b": [4, "x"]}
    json.dumps(to_jsonable(value))
