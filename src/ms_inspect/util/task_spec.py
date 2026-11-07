"""
task_spec.py — CASA task parameter specs, read from the installed casatasks XML.

Every casatasks release ships one XML file per task under
``casatasks/__xml__/<task>.xml``. Each ``<param>`` there carries the
parameter's name, type, default value and short description. This module
parses those files so the generated ``casa_<task>`` tools take their parameter
list from the CASA version that is installed, not from a hand-written copy.

The XML is located with ``importlib.util.find_spec`` and read as text:
casatasks is never imported here. No CASA dependency.
"""

from __future__ import annotations

import ast
import importlib.util
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_NS = "{http://casa.nrao.edu/schema/psetTypes.html}"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str  # XML type attribute: string, int, double, bool, stringVec, any, ...
    default: object  # parsed Python value, or None when the XML gives none
    description: str  # the XML <shortdescription>
    subparam: bool
    mustexist: bool  # the XML marks this path as an input that must already exist


@dataclass(frozen=True)
class TaskSpec:
    name: str
    description: str
    params: dict[str, ParamSpec]  # in XML order


def xml_dir() -> Path:
    """Directory holding the installed casatasks XML specs."""
    spec = importlib.util.find_spec("casatasks")
    if spec is None or not spec.submodule_search_locations:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError("casatasks is not installed; no task XML to read.")
    return Path(next(iter(spec.submodule_search_locations))) / "__xml__"


def _text(el: ET.Element | None) -> str:
    return " ".join((el.text or "").split()) if el is not None else ""


def _parse_default(ptype: str, value_el: ET.Element | None) -> object:
    """Parse a <value> element into a Python value. Unparseable text stays a string."""
    if value_el is None:
        return None
    items = value_el.findall(f"{_NS}value")
    if ptype.endswith("Vec") or items:
        return [_scalar(ptype.removesuffix("Vec"), _text(v)) for v in items]
    return _scalar(ptype, (value_el.text or "").strip())


def _scalar(ptype: str, text: str) -> object:
    if ptype == "bool":
        return text.lower() == "true"
    if ptype in ("int", "double"):
        try:
            return ast.literal_eval(text) if text else None
        except (ValueError, SyntaxError):
            return text
    return text


def parse_task_xml(path: Path) -> TaskSpec:
    """Parse one casatasks XML file."""
    root = ET.parse(path).getroot()
    task = root.find(f"{_NS}task")
    if task is None:
        raise ValueError(f"{path}: no <task> element")
    params: dict[str, ParamSpec] = {}
    inp = task.find(f"{_NS}input")
    for p in inp.findall(f"{_NS}param") if inp is not None else []:
        ptype = p.get("type", "")
        params[p.get("name", "")] = ParamSpec(
            name=p.get("name", ""),
            type=ptype,
            default=_parse_default(ptype, p.find(f"{_NS}value")),
            description=_text(p.find(f"{_NS}shortdescription")),
            subparam=p.get("subparam") == "true",
            mustexist=p.get("mustexist") == "true",
        )
    return TaskSpec(
        name=task.get("name", path.stem),
        description=_text(task.find(f"{_NS}shortdescription")),
        params=params,
    )


@cache
def task_spec(task: str) -> TaskSpec:
    """Spec for an installed casatasks task, e.g. task_spec('gaincal')."""
    path = xml_dir() / f"{task}.xml"
    if not path.exists():
        raise ValueError(f"casatasks has no XML spec for task {task!r} ({path})")
    return parse_task_xml(path)
