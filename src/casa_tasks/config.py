"""
config.py — which CASA tasks each server lists, and with which parameters.

Hand-edited policy. ``casa_task_schemas.json`` is the generated translation of
every task; this module selects from it. ``check_config`` fails at server start,
and in the unit tests, if a name here is not in the JSON, so a casatasks upgrade
that renames a task or a parameter fails loudly.

Two servers:

- casa-inspect lists the tasks in ``INSPECT_TASKS``. None of them can change a
  Measurement Set. Writing a separate output file (a listfile, a log, an image
  product) is allowed.
- casa-modify lists every other task.

``use_mcp`` (environment variable ``RADIO_MCP_USE_MCP``, default true):

- true: only the tasks in ``MCP_TASK_PARAMS``, each with only the listed
  parameters. These are the tasks and parameters the ms_* tools expose.
- false: every task, with every parameter except ``GUI_PARAMS``.

A parameter that is not listed takes the CASA default.
"""

from __future__ import annotations

#: Environment variable that selects the parameter subset (see module docstring).
USE_MCP_ENV = "RADIO_MCP_USE_MCP"

#: Tasks that never change a Measurement Set.
INSPECT_TASKS = frozenset(
    {
        "asdmsummary",
        "calstat",
        "imfit",
        "imstat",
        "imval",
        "listcal",
        "listfits",
        "listhistory",
        "listobs",
        "listpartition",
        "listsdm",
        "listvis",
        "slsearch",
        "specflux",
        "uvmodelfit",
        "visstat",
    }
)

#: Tasks that open a window or block on user input. Not listed by either server.
GUI_TASKS = frozenset(
    {"plotants", "plotbandpass", "plotprofilemap", "simalma", "simanalyze", "simobserve"}
)

#: Tasks in the casatasks XML that are not part of the documented API.
NON_API_TASKS = frozenset({"testconcat"})

EXCLUDED_TASKS = GUI_TASKS | NON_API_TASKS

#: Parameters that open a window. Removed from every schema; CASA's default is off.
GUI_PARAMS = frozenset({"interactive", "display", "showplot", "showgui", "graphics"})

#: use_mcp=True: the tasks the ms_* tools call, with the CASA parameters they expose.
MCP_TASK_PARAMS: dict[str, tuple[str, ...]] = {
    "applycal": (
        "vis", "field", "spw", "gaintable", "gainfield", "interp", "spwmap",
        "calwt", "applymode", "parang", "flagbackup",
    ),
    "bandpass": (
        "vis", "caltable", "field", "spw", "scan", "uvrange", "bandtype", "solint",
        "combine", "refant", "minsnr", "minblperant", "fillgaps", "solnorm",
        "gaintable", "interp", "parang",
    ),
    "flagdata": (
        "vis", "mode", "action", "datacolumn", "field", "spw", "antenna", "scan",
        "timerange", "correlation", "uvrange", "intent", "observation", "inpfile",
        "reason", "cmdreason", "flagbackup", "savepars", "outfile", "timecutoff",
        "freqcutoff", "timedevscale", "freqdevscale", "clipminmax", "clipoutside",
        "clipzeros",
        "quackinterval", "quackmode", "tolerance", "extendpols",
    ),
    "flagmanager": ("vis", "mode", "versionname", "comment"),
    "fluxscale": ("vis", "caltable", "fluxtable", "reference", "transfer", "incremental"),
    "gaincal": (
        "vis", "caltable", "field", "spw", "scan", "uvrange", "gaintype", "calmode",
        "solint", "combine", "refant", "minsnr", "minblperant", "solnorm", "smodel",
        "gaintable", "gainfield", "interp", "spwmap", "parang",
    ),
    "gencal": ("vis", "caltable", "caltype", "spw", "antenna", "parameter"),
    "importasdm": (
        "asdm", "vis", "ocorr_mode", "asis", "applyflags", "savecmds", "outfile",
        "overwrite", "with_pointing_correction",
    ),
    "plotweather": ("vis", "doPlot"),
    "polcal": (
        "vis", "caltable", "field", "poltype", "solint", "combine", "refant",
        "gaintable", "gainfield", "interp", "spwmap",
    ),
    "setjy": (
        "vis", "field", "spw", "standard", "scalebychan", "usescratch", "fluxdensity",
        "spix", "reffreq", "polindex", "polangle",
    ),
    "split": ("vis", "outputvis", "field", "spw", "datacolumn", "keepflags"),
    "tclean": (
        "vis", "imagename", "field", "spw", "stokes", "specmode", "nchan", "start",
        "width", "outframe", "gridder", "wprojplanes", "cfcache", "deconvolver",
        "nterms", "cell", "imsize", "weighting", "robust", "niter", "threshold",
        "usemask", "pbmask", "pblimit", "pbcor", "savemodel", "fullsummary",
    ),
}  # fmt: skip

#: Stage names that ms_workflow_status reads from the stage log.
STAGES = (
    "import_asdm",
    "set_intents",
    "preflag",
    "priorcals",
    "setjy",
    "initial_bandpass",
    "initial_rflag",
    "rflag",
    "flag_data",
    "gaincal",
    "bandpass",
    "fluxscale",
    "polcal",
    "applycal",
    "postcal_flag",
    "tclean",
)

#: The product a stage-log line records: (parameter, suffixes). The first
#: suffix whose path exists is the product; if none exists, the first is
#: recorded as missing. tclean with deconvolver='mtmfs' writes only Taylor-term
#: images (.image.tt0, ...), never a plain .image. A task not listed records
#: ``vis``, the convention for a task that changes the MS in place.
PRODUCT: dict[str, tuple[str, tuple[str, ...]]] = {
    "bandpass": ("caltable", ("",)),
    "fluxscale": ("fluxtable", ("",)),
    "gaincal": ("caltable", ("",)),
    "gencal": ("caltable", ("",)),
    "importasdm": ("vis", ("",)),
    "polcal": ("caltable", ("",)),
    "split": ("outputvis", ("",)),
    "tclean": ("imagename", (".image", ".image.tt0")),
}

#: Arguments the casa-modify tools take for the wrapper. Never passed to CASA.
WRAPPER_PARAMS: dict[str, dict] = {
    "stage": {
        "type": "string",
        "enum": list(STAGES),
        "description": (
            "Workflow stage this call completes. With workdir, a successful call appends "
            "one line to <workdir>/stage_log.jsonl. Omit it and nothing is recorded."
        ),
    },
    "workdir": {
        "type": "string",
        "description": "Directory that holds stage_log.jsonl. Used only with stage.",
    },
}


def check_config(schemas: dict) -> None:
    """Raise ValueError if a task or parameter named here is not in the schemas."""
    tasks = schemas["tasks"]
    problems: list[str] = []
    named = INSPECT_TASKS | EXCLUDED_TASKS | set(MCP_TASK_PARAMS) | set(PRODUCT)
    problems += [f"unknown task {t!r}" for t in sorted(named - set(tasks))]
    for task, params in MCP_TASK_PARAMS.items():
        known = tasks.get(task, {}).get("params", {})
        problems += [f"{task}: unknown parameter {p!r}" for p in params if p not in known]
        problems += [f"{task}: GUI parameter {p!r} listed" for p in params if p in GUI_PARAMS]
    for task, (param, _) in PRODUCT.items():
        if param not in tasks.get(task, {}).get("params", {}):
            problems.append(f"{task}: product parameter {param!r} unknown")
    for task, spec in tasks.items():
        clash = set(WRAPPER_PARAMS) & set(spec["params"])
        if clash and task not in INSPECT_TASKS:
            problems.append(f"{task}: CASA parameter(s) {sorted(clash)} clash with wrapper args")
    if problems:
        raise ValueError("casa_tasks config does not match the schemas: " + "; ".join(problems))
