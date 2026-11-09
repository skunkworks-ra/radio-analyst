"""
catalog.py — the tool list of one server, built from the schemas and config.

Pure data; imports neither mcp nor casatasks.
"""

from __future__ import annotations

import functools
import json
import os

from casa_tasks.config import (
    EXCLUDED_TASKS,
    GUI_PARAMS,
    INSPECT_TASKS,
    MCP_TASK_PARAMS,
    USE_MCP_ENV,
    WRAPPER_PARAMS,
    check_config,
)
from casa_tasks.gen_schemas import SCHEMA_FILE

KINDS = ("inspect", "modify")


@functools.cache
def load_schemas() -> dict:
    """The checked-in translation of every task (see gen_schemas.py)."""
    return json.loads(SCHEMA_FILE.read_text())


def use_mcp() -> bool:
    """True unless the environment sets RADIO_MCP_USE_MCP to a false value."""
    return os.environ.get(USE_MCP_ENV, "true").strip().lower() not in ("0", "false", "no", "off")


def build_catalog(kind: str, restricted: bool) -> dict[str, dict]:
    """Map task name to its description and input schema for one server.

    ``restricted`` is the use_mcp switch: True keeps only MCP_TASK_PARAMS.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    schemas = load_schemas()
    check_config(schemas)
    catalog: dict[str, dict] = {}
    for task, spec in schemas["tasks"].items():
        if task in EXCLUDED_TASKS or (task in INSPECT_TASKS) != (kind == "inspect"):
            continue
        if restricted:
            if task not in MCP_TASK_PARAMS:
                continue
            params = {p: spec["params"][p] for p in MCP_TASK_PARAMS[task]}
        else:
            params = {p: s for p, s in spec["params"].items() if p not in GUI_PARAMS}
        if kind == "modify":
            params = {**params, **WRAPPER_PARAMS}
        catalog[task] = {
            "description": spec["description"],
            "inputSchema": {
                "type": "object",
                "properties": params,
                "additionalProperties": False,
            },
        }
    return catalog
