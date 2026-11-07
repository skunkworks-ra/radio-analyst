"""
debug_mode.py — debug pass-through for the ms_modify write tools.

A write tool exposes a small set of CASA parameters with chosen defaults. In
debug mode the caller may pass further parameters of the CASA task(s) the tool
calls: ``debug=True`` plus ``debug_params={task: {param: value}}``. Each param
name is checked against the installed casatasks XML (task_spec.py); a value
overrides what the tool would have passed.

The tool does not decide when debug is used. The orchestrator passes it on a
retry, and the call (with its debug_params) is recorded in the ledger like any
other.

What debug may not touch (PROTECTED below): the data and product paths, and
the flagdata selection and safety settings (manual_selection.py: a widened
selection flags the whole target). The parameters a tool sets per call (setjy per field, gencal per
caltype) are protected; any other override applies to every call of that task
inside the tool. A flagdata mode='summary' call is never overridden. CASA-free.
"""

from __future__ import annotations

from typing import Any

from ms_inspect.exceptions import ComputationError

#: Parameters debug may never override, per CASA task. Paths: an override would
#: bypass pathguard. The rest, per task:
_PATHS = frozenset({"vis", "caltable", "fluxtable", "outputvis", "imagename", "inpfile"})
PROTECTED: dict[str, frozenset[str]] = {
    # Selection is the tool's own: a widened value ("*", [], None) flags more
    # than the tool was asked to (manual_selection.py). writeflags=False makes a
    # flag pass a silent no-op; flagbackup/savepars/outfile write elsewhere.
    "flagdata": _PATHS
    | {"mode", "action", "flagbackup", "savepars", "writeflags", "outfile", "overwrite"}
    | {"autocorr", "display"},
    # pbcor=True is fixed (CLAUDE.md); savemodel writes MODEL_DATA into the MS;
    # interactive hangs a headless run.
    "tclean": _PATHS | {"pbcor", "savemodel", "interactive"},
    # One tool call runs gencal once per caltype, each with its own parameter
    # (and spw on the opacity call only).
    "gencal": _PATHS | {"caltype", "parameter", "spw"},
    # One tool call runs setjy once per field with that field's own selection,
    # standard and model (ms_setjy's own `standard` is the whole-run override);
    # usescratch=True is what ms_verify_model reads.
    "setjy": _PATHS
    | {"field", "spw", "scan", "timerange", "selectdata", "intent", "observation"}
    | {"standard", "model", "fluxdensity", "spix", "reffreq", "usescratch"},
    "applycal": _PATHS | {"flagbackup"},
}


def protected(task: str) -> frozenset[str]:
    """Parameters of ``task`` that debug may not override."""
    if task == "flagdata":
        from ms_modify.flag_data import SELECTION_KEYS

        return PROTECTED["flagdata"] | set(SELECTION_KEYS)
    return PROTECTED.get(task, _PATHS)


def validate(
    debug: bool, debug_params: dict[str, dict[str, Any]] | None, tasks: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Return the checked debug overrides ({} when none); raise on an unusable call.

    Args:
        debug:        The caller's debug flag.
        debug_params: {task: {param: value}} overrides.
        tasks:        The CASA tasks this tool calls (the only valid keys).
    """
    if not debug_params:
        return {}
    if not debug:
        raise ComputationError(
            "debug_params given without debug=True. Debug parameters are accepted "
            "only in debug mode.",
            ms_path="",
        )
    from ms_inspect.util.task_spec import task_spec

    out: dict[str, dict[str, Any]] = {}
    for task, overrides in debug_params.items():
        if task not in tasks:
            raise ComputationError(
                f"debug_params key {task!r} is not a CASA task this tool calls; "
                f"valid keys: {list(tasks)}.",
                ms_path="",
            )
        if not isinstance(overrides, dict):
            raise ComputationError(
                f"debug_params[{task!r}] must be a dict of parameter -> value.", ms_path=""
            )
        known = task_spec(task).params
        unknown = sorted(set(overrides) - set(known))
        if unknown:
            raise ComputationError(
                f"{task} has no parameter(s) {unknown} in the installed casatasks XML.",
                ms_path="",
            )
        blocked = sorted(set(overrides) & protected(task))
        if blocked:
            raise ComputationError(
                f"debug may not override {task} parameter(s) {blocked}: these are "
                "data/product paths or flagging safety settings.",
                ms_path="",
            )
        out[task] = dict(overrides)
    return out


def wrap(name: str, task, overrides: dict[str, dict[str, Any]]):
    """Return ``task`` with this tool's debug overrides for ``name`` merged in.

    Without overrides for ``name`` the task itself is returned unchanged. A
    ``mode='summary'`` call (the tools' before/after flag measurement) is never
    overridden: debug changes the action, not how its result is measured.
    """
    over = overrides.get(name)
    if not over:
        return task

    def _call(*args, **kwargs):
        if kwargs.get("mode") != "summary":
            kwargs.update(over)
        return task(*args, **kwargs)

    return _call


def inject(script: str, overrides: dict[str, dict[str, Any]]) -> str:
    """Insert the debug rebinding into a generated script.

    The block goes right after the script's first top-level ``from casatasks
    import`` line, and rebinds each overridden task name to a wrapper that merges
    the overrides into every call. Without overrides the script is unchanged.
    """
    if not overrides:
        return script
    lines = script.splitlines(keepends=True)
    i = next((n for n, line in enumerate(lines) if line.startswith("from casatasks import")), None)
    if i is None:
        raise ComputationError(
            "debug mode: generated script has no top-level 'from casatasks import' line.",
            ms_path="",
        )
    block = [
        "\n# --- debug mode: parameters passed by the caller with debug=True ---\n",
        f"_DEBUG_PARAMS = {overrides!r}\n",
        "def _debug_wrap(_name, _task):\n",
        "    def _call(*args, **kwargs):\n",
        "        if kwargs.get('mode') != 'summary':\n",
        "            kwargs.update(_DEBUG_PARAMS[_name])\n",
        "        return _task(*args, **kwargs)\n",
        "    return _call\n",
    ]
    block += [f"{t} = _debug_wrap({t!r}, {t})\n" for t in overrides]
    block.append("# --- end debug mode ---\n\n")
    return "".join(lines[: i + 1] + block + lines[i + 1 :])


def inject_file(path, overrides: dict[str, dict[str, Any]]) -> None:
    """Apply inject() to a script already written to ``path``."""
    if not overrides:
        return
    from pathlib import Path

    p = Path(path)
    p.write_text(inject(p.read_text(), overrides))


def note(overrides: dict[str, dict[str, Any]]) -> str:
    """Warning text naming the debug overrides, for the response envelope."""
    return f"debug mode: CASA parameters overridden by the caller: {overrides!r}."
