"""Unit tests for casa_tasks: schemas, catalog, server argument checks, stage-log line."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from casa_tasks.catalog import build_catalog, load_schemas, use_mcp
from casa_tasks.config import (
    GUI_PARAMS,
    GUI_TASKS,
    INSPECT_TASKS,
    MCP_TASK_PARAMS,
    USE_MCP_ENV,
    WRAPPER_PARAMS,
    check_config,
)
from casa_tasks.runner import (
    MAX_LOGGED_PARAMS_CHARS,
    product_path,
    record_stage_line,
    to_jsonable,
)
from casa_tasks.server import build_server, lock_path
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


def test_use_mcp_inspect_lists_nothing():
    # Every task the ms_* tools call can change an MS.
    assert build_catalog("inspect", restricted=True) == {}


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
    assert tools["listobs"].annotations.readOnlyHint is True
    assert tools["listobs"].inputSchema["additionalProperties"] is False


def test_lock_path(tmp_path):
    ms = str(tmp_path / "a.ms")
    assert lock_path({"vis": ms, "caltable": "b.G"}) == ms
    assert lock_path({"vis": [ms, "other.ms"]}) == ms
    assert lock_path({"imagename": "img"}) == os.path.abspath("img")
    assert lock_path({"field": "0"}) is None
    assert lock_path({"vis": ""}) is None


# ------------------------------------------------------------------ stage line


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
