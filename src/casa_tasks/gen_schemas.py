"""
gen_schemas.py — translate the installed casatasks XML into MCP input schemas.

Run after every casatasks upgrade:

    pixi run gen-casa-schemas

It writes ``casa_task_schemas.json`` next to this file. The servers read only
that JSON; nothing reads the casatasks XML at runtime. A unit test rebuilds the
translation in memory and fails if the checked-in file no longer matches the
installed casatasks.

The JSON is a plain translation of every task and carries no policy. Which tasks
each server lists, and which parameters, is decided in ``config.py``.

Translation rules:

- One JSON-schema property per XML ``<param>``, in XML order.
- Scalar types map directly. A ``*Vec`` type accepts one value or a list,
  because CASA's own validator accepts both. ``any`` and ``variant`` carry no
  type constraint: CASA's validator checks them.
- No ``enum``: the XML allowed-value lists disagree with CASA's validator for
  many parameters, so they appear in the description as documentation only.
- No ``required``: every CASA task parameter has a default.
- The default in the description is the one in the task's Python signature,
  which is what CASA uses when the parameter is omitted.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA_FILE = Path(__file__).with_name("casa_task_schemas.json")

_NS = "{http://casa.nrao.edu/schema/psetTypes.html}"

_SCALAR = {
    "string": "string",
    "path": "string",
    "bool": "boolean",
    "int": "integer",
    "double": "number",
    "float": "number",
}
_VEC = {
    "stringVec": "string",
    "pathVec": "string",
    "intVec": "integer",
    "doubleVec": "number",
    "boolVec": "boolean",
}


def _type_schema(xml_type: str, task: str, param: str) -> dict:
    """JSON-schema type fragment for one XML parameter type."""
    if xml_type in _SCALAR:
        return {"type": _SCALAR[xml_type]}
    if xml_type in _VEC:
        item = _VEC[xml_type]
        return {"anyOf": [{"type": item}, {"type": "array", "items": {"type": item}}]}
    if xml_type == "record":
        return {"type": "object"}
    if xml_type in ("any", "variant"):
        return {}
    raise ValueError(f"{task}.{param}: XML type {xml_type!r} has no JSON-schema mapping")


def _text(element) -> str:
    """Element text with all whitespace runs collapsed to one space."""
    return " ".join((element.text or "").split()) if element is not None else ""


def _documented_values(param_el) -> list[str]:
    """The XML enum values of one parameter, de-duplicated, in XML order."""
    values: list[str] = []
    for allowed in param_el.findall(f"{_NS}allowed"):
        if allowed.get("kind") != "enum":
            continue
        for value in allowed.findall(f"{_NS}value"):
            text = (value.text or "").strip()
            if text not in values:
                values.append(text)
    return values


def _task_schema(xml_path: Path, signature: inspect.Signature) -> dict:
    """Description and per-parameter schema for one task."""
    name = xml_path.stem
    task_el = ET.parse(xml_path).getroot().find(f"{_NS}task")
    params: dict[str, dict] = {}
    for param_el in task_el.find(f"{_NS}input").findall(f"{_NS}param"):
        pname = param_el.get("name")
        prop = _type_schema(param_el.get("type"), name, pname)
        desc = _text(param_el.find(f"{_NS}shortdescription"))
        if desc and desc[-1] not in ".?!":
            desc += "."
        sig_param = signature.parameters.get(pname)
        if sig_param is not None and sig_param.default is not inspect.Parameter.empty:
            desc = f"{desc} Default: {sig_param.default!r}."
        values = _documented_values(param_el)
        if values:
            desc = f"{desc} Documented values: {', '.join(repr(v) for v in values)}."
        prop["description"] = desc.strip()
        params[pname] = prop
    return {"description": _text(task_el.find(f"{_NS}shortdescription")), "params": params}


def build() -> dict:
    """Translate every task XML of the installed casatasks. Imports casatasks."""
    from ms_inspect.util.logs import configure_casa_log

    configure_casa_log()
    import casatasks

    xml_dir = Path(casatasks.__file__).parent / "__xml__"
    tasks = {}
    for xml_path in sorted(xml_dir.glob("*.xml")):
        wrapper = getattr(casatasks, xml_path.stem)
        tasks[xml_path.stem] = _task_schema(xml_path, inspect.signature(wrapper.__call__))
    return {"casatasks_version": importlib.metadata.version("casatasks"), "tasks": tasks}


def main() -> int:
    data = build()
    SCHEMA_FILE.write_text(json.dumps(data, indent=1) + "\n")
    print(
        f"wrote {len(data['tasks'])} tasks (casatasks {data['casatasks_version']}) to {SCHEMA_FILE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
