"""
casa_task.py — ms_casa_task: run any CASA task that has no dedicated tool.

The parameter list comes from the CASA task schemas (task_spec.py), so
every task CASA ships is reachable without a hand-written wrapper. A task that
has a dedicated tool is refused here: that tool carries checks of its own (SpW
coverage, field-ID mapping, CORRECTED_DATA checks, ...), and its debug mode
passes extra CASA parameters.

The generic guard. The XML marks inputs that must exist (mustexist) but does
not mark outputs, so outputs are found by parameter name (OUTPUT_PARAMS, plus
`vis` where the XML does not require it to exist):
  - every param name is checked against the task's schema
  - an output must be inside workdir, must not be the input MS, and must not be
    an existing Measurement Set (pathguard.validate_output_caltable)
  - an existing output caltable is archived to ``.attemptN``; any other
    existing output is refused. An IN_OR_OUT name (vis, imagename, ...) that
    already exists (for a prefix, any ``<prefix>.*``) is an input worked on in
    place (fixvis, deconvolve); one that does not exist yet is an output. An
    import task's vis is always an output, so an existing one is refused.
  - concat into an existing concatvis is refused (it would append in place)
  - flagcmd / flagmanager change the MS flags in place: the script saves a flag
    version first (FLAG only; weights and data columns are not backed up)
  - tasks that write into an existing input are listed in ``modifies_in_place``
    (INFERRED: the XML does not say which inputs are written)
  - paths that are checked are written into the script as absolute paths
  - ``execute=False`` (default) writes a self-contained script into workdir;
    the script writes the task's return value to ``<script>.result.json``

Refused outright: rmtables (it deletes any table path it is given).

No gate on the science: the tool does not judge the task or its values.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.logs import write_script
from ms_inspect.util.stage_log import record_stage
from ms_inspect.util.task_spec import task_spec

TOOL_NAME = "ms_casa_task"

#: Output-path parameter names across the casatasks XML (all 127 tasks checked).
#: An output is one of these that the XML does not mark mustexist="true".
OUTPUT_PARAMS = (
    "caltable",
    "fluxtable",
    "outputvis",
    "outvis",
    "concatvis",
    "outfile",
    "output",
    "output_cont",
    "linefile",
    "contfile",
    "fitsimage",
    "fitsfile",
    "imagename",
    "listfile",
    "logfile",
    "figfile",
    "plotfile",
    "bltable",
    "rawdatafile",
)
#: Output names that are also inputs in some tasks (sdbaseline applies an
#: existing bltable; deconvolve works on an existing image): one that exists
#: is an input, one that does not is an output. Import tasks are the
#: exception for vis: it is always their output.
IN_OR_OUT = ("vis", "imagename", "bltable", "rawdatafile")
#: Outputs that are caltables: archived aside on a re-run, like the wrappers do.
CALTABLE_OUTPUTS = ("caltable", "fluxtable")
#: Input data paths, tried in order, for the resource lock and the MS checks.
INPUT_PARAMS = ("vis", "imagename", "infile", "caltable")
#: Tasks that rewrite MS flags in place; the script saves a flag version first.
FLAG_WRITERS = ("flagcmd", "flagmanager")
#: Refused: no guard here can make them safe.
REFUSED = {"rmtables": "it deletes any table path it is given"}

#: CASA task -> the module of the dedicated tool that runs it. A task listed here
#: is refused. Tasks a tool only uses as one step (split in ms_apply_preflag,
#: gencal in ms_generate_priorcals) stay open: their other uses have no
#: dedicated tool.
DEDICATED = {
    "applycal": "ms_modify.applycal",
    "bandpass": "ms_modify.bandpass",
    "flagdata": "ms_modify.flag_data",
    "fluxscale": "ms_modify.fluxscale",
    "gaincal": "ms_modify.gaincal",
    "polcal": "ms_modify.polcal",
    "setjy": "ms_modify.setjy",
    "tclean": "ms_modify.tclean",
    "importasdm": "ms_create.import_asdm",
}


def wrapped_tasks() -> dict[str, str]:
    """CASA task -> name of the dedicated tool that runs it (that module's TOOL_NAME)."""
    import importlib

    return {t: importlib.import_module(m).TOOL_NAME for t, m in DEDICATED.items()}


def _abs(p: Any) -> str:
    return str(Path(str(p)).expanduser().resolve())


def _prefix_exists(p: str) -> bool:
    return Path(p).exists() or bool(glob.glob(glob.escape(p) + ".*"))


def _classify(task: str, params: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """(outputs {param: abs path}, existing inputs [abs path]) for this call.

    Only single string values are paths here; a list value (immath imagename,
    concat vis) is left as given and its entries are reported as inputs.
    """
    spec = task_spec(task).params
    outputs: dict[str, str] = {}
    inputs: list[str] = []
    for k, v in params.items():
        if k not in spec or not v:
            continue
        if isinstance(v, (list, tuple)):
            if k in INPUT_PARAMS:
                inputs += [_abs(x) for x in v if isinstance(x, str) and x]
            continue
        if not isinstance(v, str):
            continue
        is_out_name = k in OUTPUT_PARAMS or k == "vis"
        if spec[k].mustexist or not is_out_name:
            if k in INPUT_PARAMS:
                inputs.append(_abs(v))
            continue
        importing = task.startswith("import") and k == "vis"
        if k in IN_OR_OUT and not importing and _prefix_exists(_abs(v)):
            # An existing MS or image is worked on in place (fixvis, deconvolve,
            # widebandpbcor); one that does not exist yet is what the task writes
            # (importuvfits, importfits).
            inputs.append(_abs(v))
            continue
        outputs[k] = _abs(v)
    return outputs, inputs


#: Parameters whose value names a path the call reads or writes, and so locks.
LOCK_PARAMS = tuple(dict.fromkeys(INPUT_PARAMS + OUTPUT_PARAMS + IN_OR_OUT + ("gaintable",)))


def lock_paths(params: dict[str, Any], workdir: str) -> list[str]:
    """Every path the call reads or writes, absolute; the workdir if it names none.

    Inputs and outputs both: two calls that write the same caltable or image
    must not run at once, even when they read different data. A list value
    (concat's vis, a gaintable list) contributes every entry. run_tool removes
    duplicates and takes the locks in one fixed order.
    """
    paths: list[str] = []
    for k in LOCK_PARAMS:
        v = params.get(k)
        for x in v if isinstance(v, (list, tuple)) else [v]:
            if isinstance(x, str) and x:
                paths.append(os.path.abspath(os.path.expanduser(x)))
    return paths or [workdir]


_JSON_DEFAULT_SNIPPET = '''\
def _json_default(o):
    """numpy-aware JSON encoding for a CASA task's return value."""
    try:
        import numpy as _np
        if isinstance(o, _np.ndarray):
            return _json_safe(o.tolist())
        if isinstance(o, _np.generic):
            o = o.item()
            if not isinstance(o, complex):
                return o
    except ImportError:
        pass
    if isinstance(o, complex):
        return [o.real, o.imag]
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def _json_safe(o):
    if isinstance(o, complex):
        return [o.real, o.imag]
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o
'''


def _build_script(
    task: str,
    params: dict[str, Any],
    workdir: str,
    caltables: list[str],
    product: str,
    result_path: str,
    flag_backup_vis: str,
    measurement: dict,
) -> str:
    from ms_inspect.util.stage_log import RECORD_STAGE_SNIPPET as record
    from ms_modify.pathguard import SAFE_RM_TABLE_SNIPPET as safe_rm

    rm_lines = "".join(f"_safe_rm_table({p!r})\n" for p in caltables)
    backup = ""
    if flag_backup_vis:
        backup = (
            "from casatasks import flagmanager as _flagmanager\n"
            f"_flagmanager(vis={flag_backup_vis!r}, mode='save', "
            f"versionname='before_ms_casa_task_{task}', "
            "comment='saved by ms_casa_task before a flag change')\n"
        )
    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_casa_task (ms_modify): casatasks.{task}.
\"\"\"
import glob
import json
import os
from casatasks import {task}

{safe_rm}
{record}
{_JSON_DEFAULT_SNIPPET}
{rm_lines}{backup}PARAMS = {params!r}
_result = {task}(**PARAMS)
with open({result_path!r}, "w") as _fh:
    json.dump(_json_safe(_result), _fh, default=_json_default)
_product = {product!r}
if not os.path.exists(_product):
    _product = (sorted(glob.glob(glob.escape(_product) + ".*")) or [_product])[0]
_record_stage({workdir!r}, "ms_casa_task:{task}", _product, {measurement!r})
print("Done: {task}. Return value in {result_path}")
"""


def run(task: str, params: dict[str, Any], workdir: str, execute: bool = False) -> dict:
    """
    Run casatasks.<task>(**params), or write the script that does.

    Args:
        task:     CASA task name, e.g. 'statwt'.
        params:   Task parameters; names checked against the task schema.
        workdir:  Existing directory for the script, outputs and result file.
        execute:  If False (default), write the script and return.

    Returns:
        Envelope with script_path, outputs, modifies_in_place, params as run, and
        (execute=True) the path of the task's return value.
    """
    if task in REFUSED:
        raise ComputationError(f"ms_casa_task does not run {task!r}: {REFUSED[task]}.", ms_path="")
    wrapped = wrapped_tasks()
    if task in wrapped:
        raise ComputationError(
            f"ms_casa_task does not run {task!r}: {wrapped[task]} wraps it, with its own "
            "checks. Extra CASA parameters go through that tool's debug mode.",
            ms_path="",
        )
    try:
        spec = task_spec(task)
    except ValueError as e:
        raise ComputationError(str(e), ms_path="") from e
    unknown = sorted(set(params) - set(spec.params))
    if unknown:
        raise ComputationError(
            f"{task} has no parameter(s) {unknown} in the CASA task schemas.",
            ms_path="",
        )

    workdir_path = Path(workdir).expanduser().resolve()
    if not workdir_path.is_dir():
        raise ComputationError(f"workdir does not exist: {workdir_path}", ms_path="")

    outputs, inputs = _classify(task, params)
    data_in = inputs[0] if inputs else ""
    from ms_modify.pathguard import validate_output_caltable

    caltables: list[str] = []
    for key, out in outputs.items():
        validate_output_caltable(out, str(workdir_path), data_in or str(workdir_path))
        if key in CALTABLE_OUTPUTS:
            caltables.append(out)
        elif _prefix_exists(out):
            raise ComputationError(
                f"{task} output {key}={out!r} already exists; ms_casa_task archives only "
                "caltables. Choose a new path.",
                ms_path=data_in,
            )

    # Checked paths go into the script as absolute paths, so it does not depend
    # on the directory it is run from.
    run_params = dict(params)
    for k, v in params.items():
        if isinstance(v, str) and v and (k in outputs or (k in INPUT_PARAMS and _abs(v) in inputs)):
            run_params[k] = _abs(v)

    in_place = [] if outputs else inputs
    flag_backup_vis = ""
    if task in FLAG_WRITERS and isinstance(run_params.get("vis"), str):
        mode = str(run_params.get("mode", "")).lower()
        if task == "flagcmd" or mode not in ("list", "save", ""):
            flag_backup_vis = run_params["vis"]

    product = next(iter(outputs.values()), "") or data_in or str(workdir_path)
    measurement = {"modifies_in_place": in_place} if in_place else {}
    script = workdir_path / f"casa_task_{task}.py"
    result_path = str(script) + ".result.json"
    write_script(
        script,
        _build_script(
            task,
            run_params,
            str(workdir_path),
            caltables,
            product,
            result_path,
            flag_backup_vis,
            measurement,
        ),
    )
    casa_calls = [f"write_script → {script}"]
    warnings: list[str] = []
    if flag_backup_vis:
        warnings.append(
            f"{task} changes the flags of {flag_backup_vis} in place: the script saves flag "
            f"version 'before_ms_casa_task_{task}' first (FLAG only; weights and data "
            "columns are not backed up)."
        )
    data: dict[str, Any] = {
        "task": task,
        "script_path": fmt_field(str(script)),
        "result_path": fmt_field(None, flag="UNAVAILABLE", note="script not yet executed"),
        "outputs": outputs,
        "modifies_in_place": fmt_field(
            in_place,
            flag="INFERRED",
            note=(
                "Existing inputs of a call with no output parameter. The XML does not say "
                "which inputs a task writes; a read-only task (listobs, visstat) lands here too."
            ),
        ),
        "params": run_params,
    }
    if not execute:
        warnings.append(f"Script written to {script}. Run it externally.")
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=data_in,
            data=data,
            warnings=warnings,
            casa_calls=casa_calls,
        )

    import importlib

    try:
        casatasks = importlib.import_module("casatasks")
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatasks is not installed or cannot be imported.", ms_path=data_in
        ) from None
    from ms_modify.pathguard import SAFE_RM_TABLE_SNIPPET

    ns: dict[str, Any] = {}
    exec(SAFE_RM_TABLE_SNIPPET, {"os": __import__("os")}, ns)  # noqa: S102 - our own snippet
    exec(_JSON_DEFAULT_SNIPPET, ns)  # noqa: S102 - our own snippet
    for ct in caltables:
        ns["_safe_rm_table"](ct)
    if flag_backup_vis:
        casatasks.flagmanager(
            vis=flag_backup_vis, mode="save", versionname=f"before_ms_casa_task_{task}"
        )
        casa_calls.append(f"casatasks.flagmanager(mode='save') on {flag_backup_vis}")
    casa_calls.append(f"casatasks.{task}(**params)")
    try:
        result = getattr(casatasks, task)(**run_params)
        Path(result_path).write_text(
            json.dumps(ns["_json_safe"](result), default=ns["_json_default"])
        )
        if not Path(product).exists():
            product = (sorted(glob.glob(glob.escape(product) + ".*")) or [product])[0]
        record_stage(str(workdir_path), f"ms_casa_task:{task}", product, measurement or None)
    except Exception as e:
        raise ComputationError(f"{task} failed: {e}", ms_path=data_in) from e
    data["result_path"] = fmt_field(result_path)
    return response_envelope(
        tool_name=TOOL_NAME, ms_path=data_in, data=data, warnings=warnings, casa_calls=casa_calls
    )
