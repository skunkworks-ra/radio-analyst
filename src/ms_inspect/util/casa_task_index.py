"""
util/casa_task_index.py — CASA task name -> documentation/source URL index.

Maps a CASA task name to:
  - its casadocs API page (the "casatasks.<section>.<task>.html" URL — the
    <section> segment is a stable per-page grouping that does not match the
    docs site's own display headings, e.g. "Single Dish" -> "single")
  - its casa6 source file on the NRAO Bitbucket server, via the raw-content
    endpoint (not the paginated /browse HTML viewer)

Both URLs are template substitutions against a bundled task->section table.
This index was built by fetching https://casadocs.readthedocs.io/en/stable/
api/casatasks.html directly (2026-09-16) and spot-checking the source
convention (casatasks/src/private/task_<name>.py) against 7 of 10 sections.

Determinism guarantee: static data, no live web fetch, no CASA dependency.
Callers (the casa-docs skill) do the actual WebFetch of the returned URLs.
"""

from __future__ import annotations

from dataclasses import dataclass

DOCS_URL_TEMPLATE = (
    "https://casadocs.readthedocs.io/en/stable/api/tt/casatasks.{section}.{task}.html"
)
SOURCE_URL_TEMPLATE = (
    "https://open-bitbucket.nrao.edu/projects/CASA/repos/casa6/raw/"
    "casatasks/src/private/task_{task}.py?at=refs/heads/master"
)

# task name -> casadocs section slug (not the display heading)
TASK_SECTIONS: dict[str, str] = {
    # data (docs heading: "Input / Output")
    "exportasdm": "data",
    "exportfits": "data",
    "exportuvfits": "data",
    "getephemtable": "data",
    "importasdm": "data",
    "importatca": "data",
    "importfits": "data",
    "importfitsidi": "data",
    "importgmrt": "data",
    "importmiriad": "data",
    "importuvfits": "data",
    "importvla": "data",
    "splattotable": "data",
    # information
    "asdmsummary": "information",
    "calstat": "information",
    "imhead": "information",
    "imhistory": "information",
    "imstat": "information",
    "listcal": "information",
    "listfits": "information",
    "listhistory": "information",
    "listobs": "information",
    "listpartition": "information",
    "listsdm": "information",
    "listvis": "information",
    "slsearch": "information",
    "vishead": "information",
    "visstat": "information",
    # flagging
    "flagcmd": "flagging",
    "flagdata": "flagging",
    "flagmanager": "flagging",
    "msuvbinflag": "flagging",
    # calibration
    "accor": "calibration",
    "appendantab": "calibration",
    "applycal": "calibration",
    "bandpass": "calibration",
    "blcal": "calibration",
    "clearcal": "calibration",
    "defintent": "calibration",
    "fluxscale": "calibration",
    "fringefit": "calibration",
    "gaincal": "calibration",
    "gencal": "calibration",
    "getantposalma": "calibration",
    "getcalmodvla": "calibration",
    "initweights": "calibration",
    "pccor": "calibration",
    "polcal": "calibration",
    "polfromgain": "calibration",
    "rerefant": "calibration",
    "smoothcal": "calibration",
    "wvrgcal": "calibration",
    # imaging
    "apparentsens": "imaging",
    "deconvolve": "imaging",
    "delmod": "imaging",
    "feather": "imaging",
    "ft": "imaging",
    "impbcor": "imaging",
    "makemask": "imaging",
    "predictcomp": "imaging",
    "sdintimaging": "imaging",
    "setjy": "imaging",
    "tclean": "imaging",
    "widebandpbcor": "imaging",
    # single (docs heading: "Single Dish")
    "getjyperkalma": "single",
    "importasap": "single",
    "importnro": "single",
    "nrobeamaverage": "single",
    "sdatmcor": "single",
    "sdbaseline": "single",
    "sdcal": "single",
    "sdfit": "single",
    "sdfixscan": "single",
    "sdgaincal": "single",
    "sdpolaverage": "single",
    "sdsidebandsplit": "single",
    "sdsmooth": "single",
    "sdtimeaverage": "single",
    "tsdimaging": "single",
    # manipulation
    "clearstat": "manipulation",
    "concat": "manipulation",
    "conjugatevis": "manipulation",
    "cvel": "manipulation",
    "cvel2": "manipulation",
    "fixplanets": "manipulation",
    "fixvis": "manipulation",
    "hanningsmooth": "manipulation",
    "mstransform": "manipulation",
    "msuvbin": "manipulation",
    "partition": "manipulation",
    "phaseshift": "manipulation",
    "rmtables": "manipulation",
    "split": "manipulation",
    "statwt": "manipulation",
    "uvcontsub": "manipulation",
    "uvcontsub_old": "manipulation",
    "uvmodelfit": "manipulation",
    "uvsub": "manipulation",
    "virtualconcat": "manipulation",
    # analysis
    "imbaseline": "analysis",
    "imcollapse": "analysis",
    "imcontsub": "analysis",
    "imdev": "analysis",
    "imfit": "analysis",
    "immath": "analysis",
    "immoments": "analysis",
    "impv": "analysis",
    "imrebin": "analysis",
    "imreframe": "analysis",
    "imregrid": "analysis",
    "imsmooth": "analysis",
    "imsubimage": "analysis",
    "imtrans": "analysis",
    "imval": "analysis",
    "rmfit": "analysis",
    "specfit": "analysis",
    "specflux": "analysis",
    "specsmooth": "analysis",
    "spxfit": "analysis",
    # visualization
    "plotants": "visualization",
    "plotbandpass": "visualization",
    "plotprofilemap": "visualization",
    "plotweather": "visualization",
    # simulation
    "simalma": "simulation",
    "simanalyze": "simulation",
    "simobserve": "simulation",
}


@dataclass
class CasaTaskLocation:
    task_name: str
    section: str
    docs_url: str
    source_url: str


def lookup(task_name: str) -> CasaTaskLocation | None:
    """Resolve a CASA task name to its docs and source URLs.

    Case-insensitive; returns None if the task is not in the bundled index
    (e.g. a task added to CASA since this index was built).
    """
    key = task_name.strip().lower()
    section = TASK_SECTIONS.get(key)
    if section is None:
        return None
    return CasaTaskLocation(
        task_name=key,
        section=section,
        docs_url=DOCS_URL_TEMPLATE.format(section=section, task=key),
        source_url=SOURCE_URL_TEMPLATE.format(task=key),
    )
