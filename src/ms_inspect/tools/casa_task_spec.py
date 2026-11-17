"""
casa_task_spec.py -- casa_task_spec: the parameters of a CASA task.

Read from the checked-in CASA task schemas (util/task_spec.py), made for the
pinned CASA version. Read-only; no MS is opened.

data.docs_path is the absolute path of the task's CASA Docs page in the
casa-docs skill, or None when that page is not copied (GUI tasks, testconcat).
"""

from __future__ import annotations

import os
from pathlib import Path

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.formatting import field as fmt_field
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
    base = Path(root).expanduser().resolve() if root else Path(__file__).resolve().parents[3]
    return base / ".claude" / "skills" / "casa-docs" / "tasks"


def docs_path(task: str) -> str | None:
    """Absolute path of the task's CASA Docs page, or None if not copied."""
    path = _docs_dir() / f"{task}.rst"
    return str(path) if path.is_file() else None


def run(task: str, param_names: list[str] | None = None) -> dict:
    """
    Parameters of casatasks.<task>: name, type, default, description, and whether
    the XML marks it a sub-parameter or an input path that must exist.

    An empty task name returns the list of task names instead. When ``param_names``
    is non-empty, filters ``params`` to those named parameters in XML order and
    surfaces ``n_params_total`` alongside ``n_params``.
    """
    requested: list[str] = []
    if param_names is not None and len(param_names) > 0:
        seen: set[str] = set()
        for raw in param_names:
            cleaned = raw.strip() if isinstance(raw, str) else ""
            if not cleaned:
                raise ComputationError(
                    "param_names must contain only non-empty parameter names.",
                    ms_path="",
                )
            if cleaned not in seen:
                seen.add(cleaned)
                requested.append(cleaned)

    if not task.strip():
        if requested:
            raise ComputationError("param_names requires a non-empty task name.", ms_path="")
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

    if requested:
        unknown = [n for n in requested if n not in spec.params]
        if unknown:
            raise ComputationError(
                f"CASA task {spec.name!r} has no parameter(s) {unknown}; "
                f"valid parameters ({len(spec.params)}): {list(spec.params)}.",
                ms_path="",
            )
        want = set(requested)
        selected_specs = [p for p in spec.params.values() if p.name in want]
    else:
        selected_specs = list(spec.params.values())

    params = [
        {
            "name": p.name,
            "type": p.type,
            "default": p.default,
            "description": p.description,
            "subparam": p.subparam,
            "mustexist": p.mustexist,
        }
        for p in selected_specs
    ]
    warnings: list[str] = []
    ddir = _docs_dir()
    dp = docs_path(spec.name)
    if dp is not None:
        docs_field = fmt_field(dp)
    elif not ddir.is_dir():
        warnings.append(f"CASA Docs directory not found at {ddir} (check RADIO_ANALYST_ROOT).")
        docs_field = fmt_field(
            None,
            flag="UNAVAILABLE",
            note=f"CASA Docs directory missing: {ddir}",
        )
    else:
        docs_field = fmt_field(
            None,
            flag="UNAVAILABLE",
            note=f"No vendored CASA Docs page for '{spec.name}' (GUI task or omitted upstream).",
        )
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path="",
        data={
            "task": spec.name,
            "description": spec.description,
            "docs_path": docs_field,
            "n_params": len(params),
            "n_params_total": len(spec.params),
            "params": params,
        },
        warnings=warnings,
        casa_calls=[f"CASA task schemas (casatasks {schema_version()}): {spec.name}"],
    )
