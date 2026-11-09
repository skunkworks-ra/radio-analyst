"""
task_spec.py — CASA task parameter specs, read from the checked-in task schemas.

The schemas are a one-time translation of the casatasks XML, made with
``pixi run gen-casa-schemas`` (casa_tasks/gen_schemas.py) for the pinned CASA
version. A unit test fails when they no longer match the installed casatasks.
Nothing here reads the XML or imports casatasks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache

from casa_tasks.gen_schemas import SCHEMA_FILE


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str  # XML type attribute: string, int, double, bool, stringVec, any, ...
    default: object  # the Python signature default; None when there is none
    description: str  # JSON-schema description: short description, default, documented values
    subparam: bool
    mustexist: bool  # the XML marks this path as an input that must already exist


@dataclass(frozen=True)
class TaskSpec:
    name: str
    description: str
    params: dict[str, ParamSpec]  # in XML order


@cache
def load_schemas() -> dict:
    """The checked-in translation of every task: casatasks_version and tasks."""
    return json.loads(SCHEMA_FILE.read_text())


def schema_version() -> str:
    """The casatasks version the schemas were made from."""
    return load_schemas()["casatasks_version"]


def task_names() -> list[str]:
    """Every task in the schemas, sorted."""
    return sorted(load_schemas()["tasks"])


def spec_from_entry(name: str, entry: dict) -> TaskSpec:
    """TaskSpec from one task entry of the schemas."""
    params = {
        pname: ParamSpec(
            name=pname,
            type=m["xml_type"],
            default=m["default"],
            description=entry["params"][pname].get("description", ""),
            subparam=m["subparam"],
            mustexist=m["mustexist"],
        )
        for pname, m in entry["meta"].items()
    }
    return TaskSpec(name=name, description=entry["description"], params=params)


def task_spec(task: str) -> TaskSpec:
    """Spec for a CASA task, e.g. task_spec('gaincal'). ValueError if unknown."""
    entry = load_schemas()["tasks"].get(task)
    if entry is None:
        raise ValueError(
            f"no CASA task {task!r} in the task schemas (casatasks {schema_version()})"
        )
    return spec_from_entry(task, entry)
