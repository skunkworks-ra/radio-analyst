"""
casa_task_spec.py — casa_task_spec: the parameters of an installed CASA task.

Read from the casatasks XML that ships with the installed CASA (util/task_spec.py),
so the list matches the version that will run. Read-only; no MS is opened.
"""

from __future__ import annotations

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.task_spec import task_spec, xml_dir

TOOL_NAME = "ms_casa_task_spec"


def run(task: str) -> dict:
    """
    Parameters of casatasks.<task>: name, type, default, description, and whether
    the XML marks it a sub-parameter or an input path that must exist.

    An empty task name returns the list of installed task names instead.
    """
    if not task.strip():
        names = sorted(p.stem for p in xml_dir().glob("*.xml"))
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path="",
            data={"n_tasks": len(names), "tasks": names},
            casa_calls=[f"glob {xml_dir()}/*.xml"],
        )
    try:
        spec = task_spec(task.strip())
    except ValueError as e:
        raise ComputationError(str(e), ms_path="") from e
    params = [
        {
            "name": p.name,
            "type": p.type,
            "default": p.default,
            "description": p.description,
            "subparam": p.subparam,
            "mustexist": p.mustexist,
        }
        for p in spec.params.values()
    ]
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path="",
        data={
            "task": spec.name,
            "description": spec.description,
            "n_params": len(params),
            "params": params,
        },
        casa_calls=[f"parse {xml_dir()}/{spec.name}.xml"],
    )
