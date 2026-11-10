"""
casa_task_spec.py — casa_task_spec: the parameters of a CASA task.

Read from the checked-in CASA task schemas (util/task_spec.py), made for the
pinned CASA version. Read-only; no MS is opened.

data.docs_path is the absolute path of the task's CASA Docs page in the
casa-docs skill, or None when that page is not copied (GUI tasks, testconcat).
"""

from __future__ import annotations

import os
from pathlib import Path

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.task_spec import schema_version, task_names, task_spec

TOOL_NAME = "ms_casa_task_spec"


def _docs_dir() -> Path:
    """tasks/ of the casa-docs skill.

    Under a plugin install the server runs from a copy of src/ that has no
    .claude/ above it, so scripts/plugin/launch.sh exports RADIO_ANALYST_ROOT,
    the directory the plugin's skills ship in. CLAUDE_PLUGIN_ROOT is not used:
    it need not be set in the server's environment. Without the variable, the
    repo layout is used.
    """
    root = os.environ.get("RADIO_ANALYST_ROOT")
    base = Path(root) if root else Path(__file__).resolve().parents[3]
    return base / ".claude" / "skills" / "casa-docs" / "tasks"


def docs_path(task: str) -> str | None:
    """Absolute path of the task's CASA Docs page, or None if not copied."""
    path = _docs_dir() / f"{task}.rst"
    return str(path) if path.is_file() else None


def run(task: str) -> dict:
    """
    Parameters of casatasks.<task>: name, type, default, description, and whether
    the XML marks it a sub-parameter or an input path that must exist.

    An empty task name returns the list of task names instead.
    """
    if not task.strip():
        names = task_names()
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path="",
            data={"n_tasks": len(names), "tasks": names},
            casa_calls=[f"CASA task schemas (casatasks {schema_version()})"],
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
            "docs_path": docs_path(spec.name),
            "n_params": len(params),
            "params": params,
        },
        casa_calls=[f"CASA task schemas (casatasks {schema_version()}): {spec.name}"],
    )
