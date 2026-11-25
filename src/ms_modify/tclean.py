"""
tclean.py — ms_tclean

Generate a first-pass imaging script using CASA tclean.

All imaging parameters are accepted explicitly — no parameter derivation
is done inside this tool. See skill 11-imaging.md for derivation logic.

When execute=False (default), writes a self-contained script to
workdir/tclean_<imagename_stem>.py (or _2.py, _3.py on retries) and returns
immediately. Run it externally as a background job; tclean on a real mosaic
can take hours.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

import numpy as np

from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.conversions import (
    angular_resolution_arcsec,
    baselines_m,
    rad_to_dms,
    rad_to_hms,
)
from ms_inspect.util.formatting import (
    field as fmt_field,
)
from ms_inspect.util.formatting import (
    normalize_field_sel,
    normalize_spw_sel,
    response_envelope,
)
from ms_inspect.util.logs import write_script
from ms_inspect.util.selection import match_field_names
from ms_inspect.util.stage_log import record_stage
from ms_modify import debug_mode
from ms_modify.exceptions import TcleanFailedError
from ms_modify.pathguard import next_script_path, validate_output_caltable

TOOL_NAME = "ms_tclean"
#: CASA tasks this tool calls; the valid debug_params keys (debug_mode.py).
DEBUG_TASKS = ("tclean",)

#: Deconvolvers that take tclean's `scales` (pixels; 0 is a point component).
SCALE_DECONVOLVERS = ("multiscale", "mtmfs")

#: Allowed masking modes in ms_tclean ('auto-multithresh' is intentionally excluded).
VALID_USEMASKS = ("pb", "user")

#: Allowed savemodel values in ms_tclean.
VALID_SAVEMODELS = ("none", "virtual", "modelcolumn")

#: Gridders that apply primary-beam mosaic/A-term gridding across pointings.
_MOSAIC_GRIDDERS = ("mosaic", "awproject", "awp2")

# Global tclean stopcodes (casatasks imager_deconvolver). Converged = {2, 8}.
_STOPCODE_DESC = {
    1: "iteration limit reached before threshold",
    2: "threshold reached",
    3: "force stop",
    4: "no change in peak residual across two major cycles",
    5: "peak residual diverging (>3x previous major cycle)",
    6: "peak residual diverging (>3x minimum reached)",
    7: "zero mask (nothing to deconvolve)",
    8: "n-sigma / combined exit criterion",
}
_CONVERGED_STOPCODES = {2, 8}
_DIVERGED_STOPCODES = {5, 6}

# Embedded verbatim in generated scripts AND executed below for execute=True so
# both paths share one atomic archiving implementation (zero drift).
# NOTE: keep the words 'start', 'width', 'nchan', 'outframe' out of this snippet
# because cube-arg unit tests assert their absence when unset.
_ARCHIVE_TCLEAN_PRODUCTS_SNIPPET = '''\
_PRODUCT_SUFFIXES = (
    ".image", ".residual", ".psf", ".pb", ".model", ".sumwt", ".mask",
    ".pbcor", ".weight", ".gridwt", ".workdirectory", ".alpha", ".beta",
)


def _archive_tclean_products(workdir, imagename, input_mask=None):
    """Atomically move existing tclean products for imagename into workdir/rejected/.

    Preserves input_mask and refuses to move any CASA Measurement Set.
    Returns a dict mapping original path -> archived path.
    """
    import glob
    import os

    _input_mask = os.path.realpath(input_mask) if input_mask else None
    matches = []
    for p in sorted(glob.glob(glob.escape(imagename) + ".*")):
        if _input_mask and os.path.realpath(p) == _input_mask:
            continue
        rest = p[len(imagename):]
        is_product = any(
            rest == s or rest[: len(s) + 1] == s + "." for s in _PRODUCT_SUFFIXES
        )
        if not is_product:
            continue
        info = os.path.join(p, "table.info")
        if os.path.isfile(info):
            with open(info, errors="replace") as _fh:
                if "Measurement Set" in _fh.readline():
                    raise RuntimeError(
                        f"Refusing to touch {p!r}: table.info identifies it "
                        "as a Measurement Set, not a tclean product."
                    )
        matches.append((p, rest))
    if not matches:
        return {}
    rejected_dir = os.path.join(workdir, "rejected")
    os.makedirs(rejected_dir, exist_ok=True)
    base = os.path.basename(imagename)
    n = 1
    while glob.glob(os.path.join(rejected_dir, glob.escape(f"{base}.attempt{n}") + ".*")):
        n += 1
    moved = {}
    for p, rest in matches:
        dst = os.path.join(rejected_dir, f"{base}.attempt{n}{rest}")
        os.rename(p, dst)
        moved[p] = dst
    return moved
'''

_archive_ns: dict = {}
exec(_ARCHIVE_TCLEAN_PRODUCTS_SNIPPET, _archive_ns)  # noqa: S102 - our own source, defined above
_archive_tclean_products = _archive_ns["_archive_tclean_products"]

_CELL_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z\"']+)?\s*$")
_HMS_RE = re.compile(r"^(\d+)[h:](\d+)[m:](\d+(?:\.\d+)?)s?$", re.IGNORECASE)
_DMS_RE = re.compile(r"^([+-]?)(\d+)[d:.](\d+)[m:.](\d+(?:\.\d+)?)s?$", re.IGNORECASE)
_ANGLE_QTY_RE = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(deg|rad|arcsec|arcmin)$",
    re.IGNORECASE,
)
_FREQ_QTY_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(hz|khz|mhz|ghz|thz)\s*$",
    re.IGNORECASE,
)
_FREQ_SCALES_HZ = {
    "hz": 1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
    "thz": 1e12,
}


def _convergence(summary: object) -> tuple[int | None, str, bool, str | None]:
    """(stopcode, description, converged, warning) from a tclean summary dict."""
    if not isinstance(summary, dict) or "stopcode" not in summary:
        return (
            None,
            "unknown",
            False,
            ("tclean returned no summary dict; convergence could not be verified."),
        )
    code = int(summary["stopcode"])
    desc = _STOPCODE_DESC.get(code, f"unrecognized stopcode {code}")
    if code in _CONVERGED_STOPCODES:
        return code, desc, True, None
    return (
        code,
        desc,
        False,
        (
            f"tclean did NOT converge: stopcode {code} ({desc}). Restored image is "
            "likely deconvolution/sidelobe-limited, not a clean detection — inspect "
            "before reporting."
        ),
    )


def _script_path(workdir: Path, imagename: str) -> Path:
    stem = Path(imagename).name.replace(".", "_")
    return next_script_path(workdir, f"tclean_{stem}.py")


def _parse_cell_arcsec(cell: str) -> float | None:
    """Parse a CASA angular cell string (e.g. '1.5arcsec', '0.06arcmin') to arcseconds."""
    if not isinstance(cell, str):
        return None
    m = _CELL_RE.match(cell)
    if not m:
        return None
    val = float(m.group(1))
    if val <= 0:
        return None
    unit = (m.group(2) or "arcsec").lower()
    scales = {
        "arcsec": 1.0,
        "asec": 1.0,
        '"': 1.0,
        "mas": 1e-3,
        "milliarcsec": 1e-3,
        "arcmin": 60.0,
        "amin": 60.0,
        "'": 60.0,
        "deg": 3600.0,
        "degree": 3600.0,
        "degrees": 3600.0,
        "rad": 180.0 * 3600.0 / math.pi,
        "radian": 180.0 * 3600.0 / math.pi,
        "radians": 180.0 * 3600.0 / math.pi,
    }
    factor = scales.get(unit)
    return val * factor if factor is not None else None


def _parse_angle_token(tok: str, *, is_ra: bool) -> float | None:
    """Parse one CASA RA or Dec token into radians."""
    q = _ANGLE_QTY_RE.match(tok)
    if q:
        val = float(q.group(1))
        unit = q.group(2).lower()
        if unit == "deg":
            return math.radians(val)
        if unit == "rad":
            return val
        if unit == "arcsec":
            return math.radians(val / 3600.0)
        if unit == "arcmin":
            return math.radians(val / 60.0)
        return None
    if is_ra:
        m = _HMS_RE.match(tok)
        if m:
            h, mn, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return math.radians((h + mn / 60.0 + sec / 3600.0) * 15.0)
        return None
    m = _DMS_RE.match(tok)
    if m:
        sign = -1.0 if m.group(1) == "-" else 1.0
        d, mn, sec = int(m.group(2)), int(m.group(3)), float(m.group(4))
        return sign * math.radians(d + mn / 60.0 + sec / 3600.0)
    return None


def _parse_phasecenter(
    phasecenter: str,
    field_names: list[str],
    all_coords: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Resolve a CASA phasecenter string (field ID, field name, or J2000 coords) to (ra, dec) rad."""
    pc = phasecenter.strip()
    if not pc:
        return None
    if pc.isdigit():
        idx = int(pc)
        return all_coords[idx] if 0 <= idx < len(all_coords) else None
    if pc in field_names:
        idx = field_names.index(pc)
        return all_coords[idx] if idx < len(all_coords) else None
    parts = pc.split()
    if len(parts) >= 3:
        ra_tok, dec_tok = parts[-2], parts[-1]
    elif len(parts) == 2:
        ra_tok, dec_tok = parts[0], parts[1]
    else:
        return None
    ra = _parse_angle_token(ra_tok, is_ra=True)
    dec = _parse_angle_token(dec_tok, is_ra=False)
    if ra is None or dec is None:
        return None
    return ra % (2.0 * math.pi), dec


def _ang_sep_rad(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle angular separation in radians (Haversine)."""
    dra = (ra2 - ra1 + math.pi) % (2.0 * math.pi) - math.pi
    ddec = dec2 - dec1
    a = math.sin(ddec / 2.0) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin(dra / 2.0) ** 2
    return 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _mosaic_bbox_geometry(
    coords: list[tuple[float, float]],
) -> tuple[float, float, str, float, float, float]:
    """Compute circular-RA-unwrapped sky bounding box from [(ra_rad, dec_rad), ...].

    Returns (bbox_ra_rad, bbox_dec_rad, bbox_center_j2000, extent_ra_arcsec,
    extent_dec_arcsec, first_field_offset_arcmin).
    """
    two_pi = 2.0 * math.pi
    ras = [r % two_pi for r, _ in coords]
    decs = [d for _, d in coords]
    mean_ra = math.atan2(sum(math.sin(r) for r in ras), sum(math.cos(r) for r in ras)) % two_pi
    unwrapped = [((r - mean_ra + math.pi) % two_pi) - math.pi for r in ras]
    ra_min_rel = min(unwrapped)
    ra_max_rel = max(unwrapped)
    bbox_ra_rad = (mean_ra + 0.5 * (ra_min_rel + ra_max_rel)) % two_pi
    dec_min = min(decs)
    dec_max = max(decs)
    bbox_dec_rad = 0.5 * (dec_min + dec_max)
    cos_dec = max(math.cos(bbox_dec_rad), 1e-6)
    extent_ra_arcsec = math.degrees((ra_max_rel - ra_min_rel) * cos_dec) * 3600.0
    extent_dec_arcsec = math.degrees(dec_max - dec_min) * 3600.0
    bbox_center_j2000 = f"J2000 {rad_to_hms(bbox_ra_rad)} {rad_to_dms(bbox_dec_rad)}"
    first_offset_arcmin = (
        math.degrees(_ang_sep_rad(ras[0], decs[0], bbox_ra_rad, bbox_dec_rad)) * 60.0
    )
    return (
        bbox_ra_rad,
        bbox_dec_rad,
        bbox_center_j2000,
        extent_ra_arcsec,
        extent_dec_arcsec,
        first_offset_arcmin,
    )


def _parse_freq_hz(qty: str | None) -> float | None:
    """Parse a CASA frequency quantity string (e.g. '1419.5MHz', '1.42GHz') to Hz."""
    if not isinstance(qty, str):
        return None
    m = _FREQ_QTY_RE.match(qty)
    if not m:
        return None
    val = float(m.group(1)) * _FREQ_SCALES_HZ[m.group(2).lower()]
    return val if math.isfinite(val) else None


def _cube_freq_bounds_hz(
    specmode: str,
    start: str | None,
    width: str | None,
    nchan: int | None,
) -> tuple[float, float] | None:
    """Return (min_hz, max_hz) for a frequency-specified specmode='cube', else None."""
    if specmode != "cube":
        return None
    if not isinstance(nchan, int) or isinstance(nchan, bool) or nchan <= 0:
        return None
    start_hz = _parse_freq_hz(start)
    width_hz = _parse_freq_hz(width)
    if start_hz is None or start_hz <= 0 or width_hz is None or width_hz == 0:
        return None
    end_hz = start_hz + nchan * width_hz
    lo_hz = min(start_hz, end_hz)
    hi_hz = max(start_hz, end_hz)
    if lo_hz <= 0 or hi_hz <= 0:
        return None
    return lo_hz, hi_hz


def _parse_spw_ids(spw_sel: str, n_spw: int) -> list[int]:
    """Resolve a CASA SPW selection string to sorted integer SPW IDs in [0, n_spw)."""
    sel = normalize_spw_sel(spw_sel).strip()
    if not sel or sel == "*":
        return list(range(n_spw))
    from ms_inspect.tools.radiometer_estimate import parse_spw_selection

    return parse_spw_selection(sel, n_spw)


def _pid_is_alive(pid: int) -> bool:
    """True if PID is alive and not a zombie ('Z' in /proc/<pid>/stat)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(errors="replace")
        rparen = stat_text.rfind(")")
        if rparen != -1:
            rest = stat_text[rparen + 1 :].lstrip()
            if rest.startswith("Z"):
                return False
    except OSError:
        pass
    return True


def _collect_param_warnings(
    *,
    field: str,
    spw: str,
    stokes: str,
    specmode: str,
    deconvolver: str,
    gridder: str,
    wprojplanes: int | None,
    cfcache: str | None,
    pblimit: float,
    pbmask: float,
    usemask: str,
    mask: str | None,
    nsigma: float | None,
    niter: int,
    nchan: int | None,
    start: str | None,
    width: str | None,
    outframe: str | None,
    scales: list[int] | None,
    imagename: str,
    outlierfile_path: Path | None,
    workdir_path: Path,
    ms_str: str,
    n_spw: int | None = None,
) -> list[str]:
    """Pure parameter, outlierfile, stage_log, and live-PID preflight warnings."""
    warnings: list[str] = []

    if usemask == "pb" and mask:
        warnings.append(
            f"mask={mask!r} ignored when usemask='pb'; pass usemask='user' to apply an external mask."
        )
    if gridder == "mosaic" and pblimit > 0:
        warnings.append(
            f"gridder='mosaic' with positive pblimit={pblimit}: pixels with PB < {pblimit} "
            "are blanked, cutting off outer-PB and first-sidelobe emission even when imsize "
            "covers the first sidelobe. Prefer small negative pblimit=-0.01 with explicit "
            "pbmask=0.1 (Phase A) or usemask='user' (ms_make_mask with pb_level=0.1)."
        )
    if (
        gridder == "mosaic"
        and deconvolver == "mtmfs"
        and usemask == "pb"
        and (nsigma is None or nsigma < 4.5)
        and niter > 0
    ):
        warnings.append(
            "gridder='mosaic' with deconvolver='mtmfs' and unmasked usemask='pb' at "
            f"nsigma={nsigma}: cleaning unmasked noise/sidelobes deeply with nterms>1 often "
            "diverges (stopcode=6). Use nsigma=5.0 for the initial shallow usemask='pb' pass, "
            "then switch to a tight PyBDSF mask (ms_make_mask + usemask='user')."
        )
    if usemask == "pb" and pbmask < 0.05 and niter > 0:
        warnings.append(
            f"usemask='pb' with pbmask={pbmask} (< 0.05): cleaning extends into low-gain PB "
            "edges where noise is strongly amplified. Pass pbmask=0.1 (or 0.2) explicitly when "
            "using pblimit=-0.01 with usemask='pb'."
        )
    if usemask == "pb" and nsigma is None and niter > 0:
        warnings.append(
            "usemask='pb' without nsigma: cleaning unmasked PB regions down to a low "
            "threshold can clean into noise and create negative bowls. Consider nsigma=3.0..3.5 "
            "or a tight mask via ms_make_mask + usemask='user'."
        )

    if gridder in ("wproject", "awp2", "awproject") and wprojplanes is None:
        warnings.append(
            f"gridder='{gridder}' with wprojplanes unset: CASA defaults to "
            "wprojplanes=1 (no W-projection). Pass wprojplanes explicitly if "
            "W-terms are significant (Fresnel < 0.9)."
        )

    if scales and deconvolver not in SCALE_DECONVOLVERS:
        warnings.append(
            f"scales={scales} ignored: deconvolver='{deconvolver}' does not take scales "
            f"(only {list(SCALE_DECONVOLVERS)} do)."
        )
    if deconvolver == "multiscale" and not scales:
        warnings.append(
            "deconvolver='multiscale' with no scales: tclean's default scales=[] "
            "gives point components only. Pass scales in pixels, starting at 0."
        )
    if deconvolver == "asp":
        warnings.append(
            "deconvolver='asp' is expensive: it optimizes a set of adaptive-scale "
            "(Aspen) components, and a run takes far longer than hogbom or multiscale "
            "on the same image (not measured here). Use it last, after hogbom and "
            "multiscale, and run the script detached. Its own tclean parameters "
            "(largestscale, fusedthreshold) are reachable only through debug_params."
        )

    # awproject-family full-polarization guardrails (warn-only).
    _is_awp = gridder in ("awp2", "awproject")
    _is_fullpol = bool(set(stokes.upper()) & {"Q", "U", "V"})
    if _is_awp and _is_fullpol and deconvolver == "mtmfs" and specmode == "mvc":
        warnings.append(
            f"gridder='{gridder}' + stokes='{stokes}' + deconvolver='mtmfs' + "
            "specmode='mvc' trips a CASA 6.7.5 shape assertion "
            "(AlwaysAssert shapeIn.isEqual(shapeOut), Lattice.tcc) in the "
            "mtmfs-via-cube PSF Taylor-term path — it dies during PSF creation "
            "before any cleaning. To keep multi-term (Taylor) deconvolution, set "
            "specmode='mfs' with deconvolver='mtmfs'."
        )
    if _is_awp and _is_fullpol:
        warnings.append(
            f"gridder='{gridder}' + stokes='{stokes}': the per-frequency A-term "
            "convolution-function computation (full Mueller CF for full-pol) can "
            "be intractable on a large unaveraged MS — e.g. ~1 h to reach 20% of "
            "just the PSF on a ~160 GB MS. Consider split/time-averaging to a "
            "compact MS first, or gridder='wproject' (image-plane pbcor) for a "
            "near-axis single pointing."
        )
    if cfcache is not None and gridder != "awproject":
        warnings.append(f"cfcache is only used by gridder='awproject'; ignored for '{gridder}'.")
    if gridder == "awproject" and cfcache is None:
        warnings.append(
            "gridder='awproject' without cfcache: convolution functions will be "
            "recomputed from scratch (potentially hours). Set cfcache to a "
            "persistent path to reuse them across runs."
        )
    if specmode != "cube" and any(v is not None for v in (nchan, start, width, outframe)):
        warnings.append(
            f"specmode='{specmode}': cube args (nchan/start/width/outframe) are "
            "ignored. Set specmode='cube' to image a frequency cube."
        )

    if outlierfile_path is not None and gridder == "mosaic":
        of_text = outlierfile_path.read_text(errors="replace").lower()
        if "gridder=standard" not in of_text.replace(" ", ""):
            warnings.append(
                "gridder='mosaic' with outlierfile that does not specify "
                "'gridder=standard': CASA MosaicFTNew aborts (weights all zero) "
                "on off-axis outlier cutouts that exclude pointing centers. "
                "Set 'gridder=standard' inside the outlierfile or use single-call "
                "gridder='standard' + phasecenter for baby peeling."
            )

    if (
        usemask == "user"
        and mask
        and Path(mask).expanduser().resolve() == Path(imagename + ".mask").resolve()
    ):
        warnings.append(
            f"mask path ({mask!r}) equals tclean's own output mask ({imagename + '.mask'!r}): "
            "CASA refuses when both paths match. Use a distinct imagename (e.g. "
            "'<name>_mtmfs_r1' with mask '<name>_r1.mask')."
        )

    # Preflight warning: stage_log.jsonl target spectrum check + SPW provenance check.
    try:
        from ms_inspect.tools.workflow_status import _target_applied, _target_postcal_checked
        from ms_inspect.util.stage_log import read_stage_log

        entries = read_stage_log(workdir_path)
        ms_resolved = Path(ms_str).expanduser().resolve()
        if _target_applied(entries, ms_resolved) and not _target_postcal_checked(
            entries, ms_resolved
        ):
            warnings.append(
                "Pre-imaging target spectrum check missing: stage_log.jsonl records applycal "
                f"on {ms_str} with no subsequent ms_spw_amp_severity, ms_postcal_flag, or "
                "ms_apply_rflag call on this MS. Run ms_spw_amp_severity(ms_path, "
                "datacolumn='CORRECTED_DATA', field=..., workdir=...) and follow "
                "11-imaging.md Step 0.5 before imaging targets."
            )

        # Check whether the latest spw_amp_severity on this MS verified a narrower SPW set.
        latest_sev: dict | None = None
        for entry in entries:
            if entry.get("exists") is not True or entry.get("stage") != "spw_amp_severity":
                continue
            prod = entry.get("product")
            if not isinstance(prod, str):
                continue
            try:
                if Path(prod).expanduser().resolve() != ms_resolved:
                    continue
            except Exception:
                continue
            meas = entry.get("measurement") or {}
            col = str(meas.get("datacolumn", "CORRECTED_DATA")).upper()
            if col != "CORRECTED_DATA":
                continue
            latest_sev = entry

        if latest_sev is not None:
            meas = latest_sev.get("measurement") or {}
            params = latest_sev.get("params") or {}
            if "spw" in meas and meas["spw"] is not None:
                verified_spw = normalize_spw_sel(str(meas["spw"])).strip()
            elif "spw" in params and params["spw"] is not None:
                verified_spw = normalize_spw_sel(str(params["spw"])).strip()
            else:
                verified_spw = ""

            if verified_spw and verified_spw != "*":
                if n_spw is not None and n_spw > 0:
                    try:
                        verified_ids = set(_parse_spw_ids(verified_spw, n_spw))
                        tclean_ids = set(_parse_spw_ids(spw, n_spw))
                        extra = sorted(tclean_ids - verified_ids)
                        if extra:
                            warnings.append(
                                f"SPW provenance mismatch: tclean spw={spw!r} selects SPW(s) "
                                f"{extra} not covered by the latest ms_spw_amp_severity check "
                                f"(spw={verified_spw!r}). Verify those SPWs with "
                                "ms_spw_amp_severity or restrict tclean spw to the verified subset."
                            )
                    except ValueError:
                        pass
                elif not spw or spw == "*":
                    warnings.append(
                        f"SPW provenance mismatch: tclean selects all SPWs (spw={spw!r}), "
                        f"which is wider than the latest ms_spw_amp_severity check "
                        f"(spw={verified_spw!r}). Restrict tclean spw or re-verify all SPWs."
                    )
    except Exception:
        pass

    # Live-PID concurrency warning: warn if another tclean_*.py in workdir is still running.
    try:
        for pid_file in sorted(workdir_path.glob("tclean_*.py.pid")):
            script_base = str(pid_file)[:-4]
            if Path(script_base + ".rc").exists():
                continue
            raw_pid = pid_file.read_text(errors="replace").strip()
            if raw_pid.isdigit() and _pid_is_alive(int(raw_pid)):
                warnings.append(
                    f"Live tclean job detected in workdir: {Path(script_base).name} "
                    f"(pid={raw_pid}, no .rc file). Do not launch a concurrent tclean in the "
                    "same workdir -- poll the running job with run-step.sh until completion."
                )
    except Exception:
        pass

    return warnings


def _collect_ms_geometry_warnings(
    *,
    ms_str: str,
    field: str,
    spw: str,
    gridder: str,
    phasecenter: str,
    cell: str,
    imsize: list[int],
    specmode: str = "mfs",
    nchan: int | None = None,
    start: str | None = None,
    width: str | None = None,
) -> tuple[list[str], int | None]:
    """Read-only subtable preflight checks (FIELD, SPECTRAL_WINDOW, ANTENNA; < 5 ms).

    Returns (warnings, n_spw). All subtable reads are non-fatal.
    """
    warnings: list[str] = []
    field_names: list[str] = []
    all_coords: list[tuple[float, float]] = []
    matched_fids: list[int] = []
    field_read_ok = False

    # 1. FIELD subtable: resolve field selection (including wildcards like 'TARGET_*').
    try:
        with open_table(ms_str + "/FIELD") as tb:
            n_fields = tb.nrows()
            field_names = [str(x) for x in tb.getcol("NAME")]
            for fid in range(n_fields):
                pdir = np.asarray(tb.getcell("PHASE_DIR", fid), dtype=float)
                if pdir.ndim == 2:
                    ra_rad, dec_rad = float(pdir[0, 0]), float(pdir[1, 0])
                else:
                    ra_rad, dec_rad = float(pdir[0]), float(pdir[1])
                all_coords.append((ra_rad % (2.0 * math.pi), dec_rad))
        field_read_ok = True
        if field:
            try:
                matched_fids = match_field_names(field_names, field)
            except ValueError:
                matched_fids = []
        else:
            matched_fids = list(range(len(field_names)))
    except Exception:
        pass

    # 2. SPECTRAL_WINDOW subtable: min/max frequency of selected SPW(s), refined to
    #    sub-band bounds when specmode='cube' specifies frequency start/width/nchan.
    n_spw: int | None = None
    min_freq_hz: float | None = None
    max_freq_hz: float | None = None
    try:
        with open_table(ms_str + "/SPECTRAL_WINDOW") as tb:
            n_spw = tb.nrows()
            if n_spw > 0:
                try:
                    spw_ids = _parse_spw_ids(spw, n_spw)
                except ValueError:
                    spw_ids = list(range(n_spw))
                lo_freqs: list[float] = []
                hi_freqs: list[float] = []
                for sid in spw_ids:
                    ch = np.asarray(tb.getcell("CHAN_FREQ", sid), dtype=float).ravel()
                    if ch.size:
                        lo_freqs.append(float(np.min(ch)))
                        hi_freqs.append(float(np.max(ch)))
                if lo_freqs and hi_freqs:
                    min_freq_hz = min(lo_freqs)
                    max_freq_hz = max(hi_freqs)
    except Exception:
        pass

    cube_bounds = _cube_freq_bounds_hz(specmode, start, width, nchan)
    if cube_bounds is not None:
        c_lo, c_hi = cube_bounds
        if (
            min_freq_hz is not None
            and max_freq_hz is not None
            and c_lo < max_freq_hz
            and c_hi > min_freq_hz
        ):
            min_freq_hz = max(min_freq_hz, c_lo)
            max_freq_hz = min(max_freq_hz, c_hi)
        else:
            min_freq_hz, max_freq_hz = c_lo, c_hi

    # 3. ANTENNA subtable: smallest active dish diameter (widest primary beam for
    #    heterogeneous arrays, e.g. 7 m ACA in ALMA 12m+7m) and max physical baseline.
    dish_diam_m: float | None = None
    max_baseline_m: float | None = None
    try:
        with open_table(ms_str + "/ANTENNA") as tb:
            n_ant = tb.nrows()
            if n_ant > 0:
                positions = np.asarray(tb.getcol("POSITION"), dtype=float)
                diameters = np.asarray(tb.getcol("DISH_DIAMETER"), dtype=float).ravel()
                active_mask = np.ones(n_ant, dtype=bool)
                if "FLAG_ROW" in set(tb.colnames()):
                    fl = np.asarray(tb.getcol("FLAG_ROW"), dtype=bool).ravel()
                    if int(np.sum(~fl)) >= 2:
                        active_mask = ~fl
                pos_diams = diameters[active_mask]
                pos_diams = pos_diams[pos_diams > 0]
                if pos_diams.size:
                    dish_diam_m = float(np.min(pos_diams))
                active_pos = positions[:, active_mask]
                if active_pos.shape[1] >= 2:
                    _, _, lengths = baselines_m(active_pos)
                    if lengths.size:
                        max_baseline_m = float(np.max(lengths))
    except Exception:
        pass

    # Derived sky geometry: tapered Cassegrain PB FWHM (~1.15 * lambda / D_min),
    # distinct-pointing mosaic classification, and sky-angle cutout check.
    matched_coords = [all_coords[i] for i in matched_fids if i < len(all_coords)]
    bbox_info = _mosaic_bbox_geometry(matched_coords) if matched_coords else None

    pb_fwhm_arcsec: float | None = None
    if dish_diam_m is not None and min_freq_hz is not None:
        pb_val = 1.15 * angular_resolution_arcsec(dish_diam_m, min_freq_hz)
        if math.isfinite(pb_val) and pb_val > 0:
            pb_fwhm_arcsec = pb_val

    max_extent_arcsec = max(bbox_info[3], bbox_info[4]) if bbox_info is not None else 0.0
    min_mosaic_extent_arcsec = (
        max(1.0, 0.05 * pb_fwhm_arcsec) if pb_fwhm_arcsec is not None else 1.0
    )
    is_multi_pointing = len(matched_fids) >= 2 and max_extent_arcsec > min_mosaic_extent_arcsec

    cell_arcsec = _parse_cell_arcsec(cell)
    nx = imsize[0]
    ny = imsize[-1]
    fov_ra_arcsec: float | None = nx * cell_arcsec if cell_arcsec is not None else None
    fov_dec_arcsec: float | None = ny * cell_arcsec if cell_arcsec is not None else None
    if fov_ra_arcsec is not None and fov_dec_arcsec is not None and pb_fwhm_arcsec is not None:
        is_small_cutout = bool(phasecenter) and (
            max(fov_ra_arcsec, fov_dec_arcsec) < 1.5 * pb_fwhm_arcsec
        )
    else:
        is_small_cutout = bool(phasecenter) and max(imsize) <= 256

    # 4. Multi-pointing mosaic with gridder='standard' (fixes wildcard 'TARGET_*' bypass;
    #    ignores co-located multi-EB single pointings and small-angle cutouts).
    if field_read_ok:
        if is_multi_pointing and gridder == "standard" and not is_small_cutout:
            warnings.append(
                f"Multiple fields ({len(matched_fids)} matched by {field!r}) selected with "
                "gridder='standard': CASA's 'standard' gridder does not apply mosaic "
                "primary-beam weighting across pointings. Use gridder='mosaic' for "
                "multi-pointing mosaics (11-imaging.md Step 6)."
            )
    elif ("," in field or "~" in field) and gridder == "standard" and not is_small_cutout:
        warnings.append(
            f"Multiple fields ({field!r}) selected with gridder='standard': CASA's "
            "'standard' gridder does not apply mosaic primary-beam weighting across "
            "pointings. Use gridder='mosaic' for multi-pointing mosaics (11-imaging.md Step 6)."
        )

    # 5. Mosaic phasecenter == "" warning (with exact circular-unwrapped bbox center & offset).
    if (
        gridder in _MOSAIC_GRIDDERS
        and is_multi_pointing
        and not phasecenter
        and bbox_info is not None
    ):
        _, _, bbox_center_j2000, _, _, first_offset_arcmin = bbox_info
        first_name = field_names[matched_fids[0]] if matched_fids[0] < len(field_names) else "?"
        warnings.append(
            f"gridder={gridder!r} with {len(matched_fids)} matched fields and phasecenter='': "
            f"CASA defaults phasecenter to the first pointing ({first_name!r}), which is "
            f"offset by {first_offset_arcmin:.2f} arcmin from the mosaic bounding-box midpoint "
            "and can push outer pointings into the FFT edge (toroidal wrap-around). "
            f"Set phasecenter={bbox_center_j2000!r}."
        )

    # 6. Mosaic / AWP FOV vs extent + 3.6 * pb_fwhm(min_freq) (1.8 * pb_fwhm per side to clear
    #    the 1st positive sidelobe; skip standard gridder, co-located single pointings,
    #    small-angle cutouts, and off-axis outlier cutouts).
    if (
        gridder in _MOSAIC_GRIDDERS
        and is_multi_pointing
        and not is_small_cutout
        and cell_arcsec is not None
        and fov_ra_arcsec is not None
        and fov_dec_arcsec is not None
        and min_freq_hz is not None
        and pb_fwhm_arcsec is not None
        and bbox_info is not None
    ):
        bbox_ra, bbox_dec, _, extent_ra_arcsec, extent_dec_arcsec, _ = bbox_info
        req_ra_arcsec = extent_ra_arcsec + 3.6 * pb_fwhm_arcsec
        req_dec_arcsec = extent_dec_arcsec + 3.6 * pb_fwhm_arcsec

        # Determine effective phase center for border-margin check.
        parsed_pc: tuple[float, float] | None = None
        if not phasecenter:
            pc_ra, pc_dec = matched_coords[0]
        else:
            parsed_pc = _parse_phasecenter(phasecenter, field_names, all_coords)
            pc_ra, pc_dec = parsed_pc if parsed_pc is not None else (bbox_ra, bbox_dec)

        # Skip off-axis outlier cutouts whose explicit phasecenter sits outside
        # the mosaic footprint.
        arcsec_to_rad = math.pi / (180.0 * 3600.0)
        off_axis_cutout = (
            bool(phasecenter)
            and parsed_pc is not None
            and _ang_sep_rad(pc_ra, pc_dec, bbox_ra, bbox_dec)
            > (0.5 * math.hypot(extent_ra_arcsec, extent_dec_arcsec) + 0.5 * pb_fwhm_arcsec)
            * arcsec_to_rad
        )

        if not off_axis_cutout:
            cos_pc = max(math.cos(pc_dec), 1e-6)
            two_pi = 2.0 * math.pi
            max_dra_arcsec = max(
                abs(((ra - pc_ra + math.pi) % two_pi - math.pi) * cos_pc)
                * (180.0 * 3600.0 / math.pi)
                for ra, _ in matched_coords
            )
            max_ddec_arcsec = max(
                abs(dec - pc_dec) * (180.0 * 3600.0 / math.pi) for _, dec in matched_coords
            )
            margin_ra_arcsec = 0.5 * fov_ra_arcsec - max_dra_arcsec
            margin_dec_arcsec = 0.5 * fov_dec_arcsec - max_ddec_arcsec
            min_side_req = 1.8 * pb_fwhm_arcsec

            if (
                fov_ra_arcsec < req_ra_arcsec
                or fov_dec_arcsec < req_dec_arcsec
                or margin_ra_arcsec < min_side_req
                or margin_dec_arcsec < min_side_req
            ):
                rec_nx = math.ceil((extent_ra_arcsec + 4.0 * pb_fwhm_arcsec) / cell_arcsec)
                rec_ny = math.ceil((extent_dec_arcsec + 4.0 * pb_fwhm_arcsec) / cell_arcsec)
                warnings.append(
                    f"Mosaic/PB FOV check: imsize={imsize} at cell={cell} "
                    f"({fov_ra_arcsec / 60.0:.1f}' x {fov_dec_arcsec / 60.0:.1f}') leaves "
                    f"outer pointings within ({margin_ra_arcsec / 60.0:.1f}' RA, "
                    f"{margin_dec_arcsec / 60.0:.1f}' Dec) of the border -- below "
                    f"1.8 * PB_FWHM ({min_side_req / 60.0:.1f}' at "
                    f"min_freq={min_freq_hz / 1e9:.3f} GHz, "
                    f"PB_FWHM={pb_fwhm_arcsec / 60.0:.1f}'). "
                    "Clearing the first positive sidelobe prevents toroidal FFT aliasing; "
                    f"pad to extent + 4.0 * PB_FWHM (~[{rec_nx}, {rec_ny}] px (centered) "
                    f"at cell={cell})."
                )

    # 7. Warn-only Nyquist cell advisory using max_freq_hz of selected spw + ANTENNA max baseline.
    if cell_arcsec is not None and max_freq_hz is not None and max_baseline_m is not None:
        approx_beam_arcsec = angular_resolution_arcsec(max_baseline_m, max_freq_hz)
        if math.isfinite(approx_beam_arcsec) and approx_beam_arcsec > 0:
            px_per_beam = approx_beam_arcsec / cell_arcsec
            if px_per_beam < 2.5:
                rec_cell = approx_beam_arcsec / 4.0
                warnings.append(
                    f'Nyquist cell advisory: cell={cell} ({cell_arcsec:.3g}") gives '
                    f"~{px_per_beam:.2f} px per estimated unprojected beam "
                    f'({approx_beam_arcsec:.2f}" = lambda/B_max at '
                    f"max_freq={max_freq_hz / 1e9:.3f} GHz, B_max={max_baseline_m:.0f} m), "
                    f"below 2.5 px/beam. Consider cell~'{rec_cell:.2f}arcsec' (~4 px/beam). "
                    "Caveat: actual restoring beam may be larger due to UV foreshortening, "
                    "weighting, or uvtaper -- verify pixels_per_beam_minor via ms_image_stats."
                )

    return warnings, n_spw


def _build_tclean_kwargs(
    *,
    ms_str: str,
    imagename: str,
    field: str,
    spw: str,
    stokes: str,
    specmode: str,
    deconvolver: str,
    nterms: int | None,
    gridder: str,
    wprojplanes: int | None,
    cfcache: str | None,
    cell: str,
    imsize: list[int],
    weighting: str,
    robust: float,
    niter: int,
    threshold: str,
    savemodel: str,
    pblimit: float,
    pbmask: float,
    usemask: str,
    mask: str | None,
    nsigma: float | None,
    nchan: int | None,
    start: str | None,
    width: str | None,
    outframe: str | None,
    scales: list[int] | None = None,
    phasecenter: str = "",
    outlierfile: str = "",
) -> dict:
    """Single source of truth for tclean arguments shared by _build_script and execute=True."""
    kwargs: dict = {
        "vis": ms_str,
        "imagename": imagename,
        "field": field,
        "stokes": stokes,
        "specmode": specmode,
        "deconvolver": deconvolver,
    }
    if spw:
        kwargs["spw"] = spw
    if phasecenter:
        kwargs["phasecenter"] = phasecenter
    if outlierfile:
        kwargs["outlierfile"] = outlierfile
    if deconvolver == "mtmfs" and nterms is not None:
        kwargs["nterms"] = nterms
    if deconvolver in SCALE_DECONVOLVERS and scales:
        kwargs["scales"] = list(scales)
    if wprojplanes is not None:
        kwargs["wprojplanes"] = wprojplanes
    if cfcache is not None and gridder == "awproject":
        kwargs["cfcache"] = cfcache
    if nsigma is not None:
        kwargs["nsigma"] = nsigma
    if specmode == "cube":
        if nchan is not None:
            kwargs["nchan"] = nchan
        if start is not None:
            kwargs["start"] = start
        if width is not None:
            kwargs["width"] = width
        if outframe is not None:
            kwargs["outframe"] = outframe

    kwargs["gridder"] = gridder
    kwargs["cell"] = [cell]
    kwargs["imsize"] = list(imsize)
    kwargs["weighting"] = weighting
    kwargs["robust"] = robust
    kwargs["niter"] = niter
    kwargs["threshold"] = threshold
    kwargs["pbcor"] = True
    kwargs["pblimit"] = pblimit
    kwargs["usemask"] = usemask
    if usemask == "pb":
        kwargs["pbmask"] = pbmask
    elif usemask == "user" and mask:
        kwargs["mask"] = mask
    kwargs["savemodel"] = savemodel
    kwargs["fullsummary"] = False
    return kwargs


def _build_script(
    workdir: str,
    tclean_kwargs: dict,
    *,
    script_filename: str | None = None,
) -> str:
    ms_str = tclean_kwargs["vis"]
    imagename = tclean_kwargs["imagename"]
    deconvolver = tclean_kwargs["deconvolver"]
    nterms = tclean_kwargs.get("nterms")
    usemask = tclean_kwargs["usemask"]
    mask = tclean_kwargs.get("mask")
    niter = tclean_kwargs["niter"]

    # Same rule the execute=True path uses at the bottom of run(): mtmfs with
    # nterms > 1 (or default None -> 2) writes Taylor terms, so there is no
    # plain .image to record. nterms == 1 writes a plain .image.
    is_mtmfs = deconvolver == "mtmfs" and (nterms is None or nterms > 1)

    call_lines = []
    for key, val in tclean_kwargs.items():
        if key == "vis":
            val_expr = "ms_path"
        elif key == "imagename":
            val_expr = "imagename"
        else:
            val_expr = repr(val)
        call_lines.append(f"    {key:<12} = {val_expr},")
    tclean_call_body = "\n".join(call_lines)

    script_label = script_filename or f"tclean_{Path(imagename).name.replace('.', '_')}.py"

    from ms_inspect.util.stage_log import RECORD_STAGE_SNIPPET as record

    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_tclean (ms_modify).
Run with: python {script_label}
\"\"\"
import os
from casatasks import tclean

ms_path   = {ms_str!r}
{record}
{_ARCHIVE_TCLEAN_PRODUCTS_SNIPPET}
workdir = {workdir!r}

imagename = {imagename!r}
_input_mask = os.path.realpath({mask!r}) if ({usemask!r} == "user" and {mask!r}) else None

# Archive any pre-existing tclean products for this imagename into workdir/rejected/.
_archive_tclean_products(workdir, imagename, _input_mask)

summary = tclean(
{tclean_call_body}
)
_code = summary.get("stopcode") if isinstance(summary, dict) else None
_desc = {{
    1: "iteration limit reached before threshold", 2: "threshold reached",
    3: "force stop", 4: "no change in peak residual",
    5: "diverging (>3x prev major cycle)", 6: "diverging (>3x minimum)",
    7: "zero mask", 8: "n-sigma / combined",
}}.get(_code, "unknown")
# The image existing is not success: a clean that stopped on the iteration
# limit, or diverged, is deconvolution-limited rather than a detection. tclean
# does return a summary, so the stopcode is read rather than measured — record
# it beside the product so the record says which kind of stop this was.
_image = imagename + (".image.tt0" if {is_mtmfs} else ".image")
_diverged = ({niter!r} > 0) and (_code in (5, 6))
_quarantined_image = None
if _diverged and os.path.exists(_image):
    _moved = _archive_tclean_products(workdir, imagename, _input_mask)
    _quarantined_image = _moved.get(_image)
_measurement = {{"stopcode": _code, "converged": _code in (2, 8)}}
if _quarantined_image:
    _measurement["quarantined_to"] = _quarantined_image
try:
    _record_stage(
        workdir,
        "tclean",
        _image,
        _measurement,
    )
except RuntimeError:
    if not _quarantined_image:
        raise
if _code in (2, 8):
    print(f"tclean CONVERGED (stopcode={{_code}}: {{_desc}}):", imagename)
elif _quarantined_image:
    print(
        f"tclean DID NOT CONVERGE (stopcode={{_code}}: {{_desc}}) -- "
        f"diverged products quarantined to {{_quarantined_image}}:",
        imagename,
    )
else:
    print(
        f"tclean DID NOT CONVERGE (stopcode={{_code}}: {{_desc}}) -- image likely "
        "deconvolution-limited, not a clean detection:",
        imagename,
    )
"""


def run(
    ms_path: str,
    imagename: str,
    field: str,
    workdir: str,
    spw: str = "",
    stokes: str = "I",
    specmode: str = "mfs",
    deconvolver: str = "hogbom",
    nterms: int | None = None,
    gridder: str = "standard",
    wprojplanes: int | None = None,
    cfcache: str | None = None,
    cell: str = "1.0arcsec",
    imsize: list[int] | None = None,
    weighting: str = "briggs",
    robust: float = 0.5,
    niter: int = 50000,
    threshold: str = "1.0mJy",
    savemodel: str = "modelcolumn",
    pblimit: float = -0.1,
    pbmask: float | None = None,
    usemask: str = "pb",
    mask: str | None = None,
    nsigma: float | None = None,
    nchan: int | None = None,
    start: str | None = None,
    width: str | None = None,
    outframe: str | None = None,
    scales: list[int] | None = None,
    phasecenter: str = "",
    outlierfile: str = "",
    execute: bool = False,
    debug: bool = False,
    debug_params: dict | None = None,
) -> dict:
    """
    Generate (and optionally execute) a tclean imaging script.

    Validates that CORRECTED_DATA exists in the MS before writing the script.
    pbcor=True is always set — primary beam correction is applied by tclean.

    Args:
        ms_path:     Path to the full Measurement Set.
        imagename:   Base name for all output image products (no suffix).
        field:       CASA field selection for science target(s).
        workdir:     Existing directory for script and image output.
        spw:         CASA SPW selection (default '' = all SPWs). Use to drop
                     RFI-dominated SPWs, e.g. '0~8,10~15' to exclude SPW 9.
        stokes:      Stokes products to image (default 'I').
        specmode:    'mfs', 'cube', or 'mvc' (default 'mfs'). Use 'mvc' with
                     gridder='awp2' — awp2 does not implement conjbeams, and
                     plain 'mfs' needs several major cycles to converge the
                     wideband flux normalization.
        deconvolver: 'hogbom' (default), 'mtmfs', 'multiscale' or 'asp'.
        scales:      Multiscale scales in pixels (0 first); multiscale and mtmfs only.
        nterms:      Taylor terms for mtmfs (default None; pass 2 for mtmfs).
        gridder:     'standard', 'wproject', 'mosaic', 'awproject' or 'awp2'
                     (default 'standard'). First-pass mosaics use 'mosaic'.
        wprojplanes: W-projection planes (None = omit; set for wproject/awp2
                     when W-terms are required per Fresnel criterion). If
                     omitted for those gridders, CASA silently defaults to 1
                     (no W-projection) — a warning is emitted in the response.
        cfcache:     Convolution-function cache path. Applies to
                     gridder='awproject' only (awp2 does not use a cfcache).
                     Without it, awproject recomputes CFs from scratch on
                     every run — potentially many hours.
        cell:        Cell size string, e.g. '2.5arcsec'.
        imsize:      Image size as [nx, ny] (default [512, 512]).
        weighting:   UV weighting scheme (default 'briggs').
        robust:      Briggs robust parameter (default 0.5).
        niter:       Maximum clean iterations (default 50000).
        threshold:   Clean stopping threshold, e.g. '0.5mJy'.
        pblimit:     Primary-beam gain cutoff. Default -0.1 (negative disables
                     PB-based blanking, so low-gain regions and sources out in
                     the PB sidelobes stay visible in the image — important for
                     spotting outliers). CASA's own default is 0.2, which blanks
                     everything below 20% PB. The .pbcor noise rises toward the
                     edge of the PB.
        pbmask:      Clean only where PB >= pbmask (usemask='pb'). None
                     (default) uses abs(pblimit).
        savemodel:   'modelcolumn' writes MODEL_DATA for self-cal (default).
        nchan:       Number of output channels for the cube (specmode='cube'
                     only; None = all). For a polarization frequency cube,
                     one plane per SPW-chunk per skill 11.
        start:       First channel of the cube as a CASA spectral string, e.g.
                     '1.0GHz' or '0' (specmode='cube' only).
        width:       Channel width of the cube, e.g. '64MHz' or '4'
                     (specmode='cube' only).
        outframe:    Output spectral reference frame, e.g. 'LSRK' (specmode=
                     'cube' only). None lets CASA default.
        phasecenter: Optional phase center (e.g. 'J2000 03h30m26.21s +30d03m44.6s'
                     or field ID) for small-box outlier imaging / baby peeling.
        outlierfile: Optional path to a CASA outlier-field definition file.
        execute:     If False (default), write script and return.
                     If True, run tclean in-process (intended for test data only).

    Returns:
        Standard response envelope with script_path always present.
        When execute=True, also includes imagename and completed flag.
    """
    from ms_inspect.exceptions import ComputationError

    field = normalize_field_sel(field)
    spw = normalize_spw_sel(spw)
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    warnings: list[str] = []
    casa_calls: list[str] = []

    if imsize is None:
        imsize = [512, 512]
    elif isinstance(imsize, int) and not isinstance(imsize, bool):
        imsize = [imsize]
    if (
        not isinstance(imsize, (list, tuple))
        or len(imsize) not in (1, 2)
        or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in imsize)
    ):
        raise ComputationError(
            f"imsize must be a 1- or 2-element list of positive integers, got {imsize!r}",
            ms_path=ms_path,
        )
    imsize = list(imsize)

    if savemodel not in VALID_SAVEMODELS:
        raise ComputationError(
            f"Unsupported savemodel={savemodel!r}; must be one of {list(VALID_SAVEMODELS)}.",
            ms_path=ms_path,
        )

    if pbmask is None:
        pbmask = abs(pblimit)

    if usemask not in VALID_USEMASKS:
        raise ComputationError(
            f"Unsupported usemask={usemask!r}; ms_tclean supports {list(VALID_USEMASKS)} "
            "(usemask='auto-multithresh' is intentionally excluded -- supply an external/PyBDSF "
            "mask with usemask='user' and mask=<path>, or use usemask='pb').",
            ms_path=ms_path,
        )
    if usemask == "user" and not (mask and mask.strip()):
        raise ComputationError(
            "usemask='user' requires a non-empty mask path or region string.",
            ms_path=ms_path,
        )
    if nsigma is not None and nsigma < 0:
        raise ComputationError(f"nsigma must be >= 0, got {nsigma}", ms_path=ms_path)

    workdir_path = Path(workdir)
    if not workdir_path.exists():
        raise ComputationError(
            f"workdir does not exist: {workdir}",
            ms_path=ms_path,
        )

    imagename = str(validate_output_caltable(imagename, str(workdir_path), ms_str))

    phasecenter = phasecenter.strip() if phasecenter else ""
    outlierfile_path: Path | None = None
    outlierfile_str = ""
    if outlierfile and outlierfile.strip():
        of_path = Path(outlierfile.strip()).expanduser().resolve()
        if not of_path.is_file():
            raise ComputationError(
                f"outlierfile does not exist: {outlierfile}",
                ms_path=ms_path,
            )
        outlierfile_path = of_path
        outlierfile_str = str(of_path)

    # Verify CORRECTED_DATA column exists.
    # Open failure (casatools not installed, table locked) is non-fatal — add a warning.
    # Missing column is always fatal — tclean on uncalibrated data is a silent science error.
    col_names: list[str] = []
    try:
        with open_table(ms_str) as tb:
            col_names = list(tb.colnames())
        casa_calls.append("tb.open(MS) → colnames() [CORRECTED_DATA check]")
    except Exception as exc:
        warnings.append(f"Could not verify CORRECTED_DATA column: {exc}")

    if col_names and "CORRECTED_DATA" not in col_names:
        from ms_inspect.exceptions import InsufficientMetadataError

        raise InsufficientMetadataError(
            "CORRECTED_DATA column not found in MS. Run ms_applycal before imaging.",
            ms_path=ms_path,
        )

    geo_warnings, n_spw = _collect_ms_geometry_warnings(
        ms_str=ms_str,
        field=field,
        spw=spw,
        gridder=gridder,
        phasecenter=phasecenter,
        cell=cell,
        imsize=imsize,
        specmode=specmode,
        nchan=nchan,
        start=start,
        width=width,
    )
    warnings.extend(
        _collect_param_warnings(
            field=field,
            spw=spw,
            stokes=stokes,
            specmode=specmode,
            deconvolver=deconvolver,
            gridder=gridder,
            wprojplanes=wprojplanes,
            cfcache=cfcache,
            pblimit=pblimit,
            pbmask=pbmask,
            usemask=usemask,
            mask=mask,
            nsigma=nsigma,
            niter=niter,
            nchan=nchan,
            start=start,
            width=width,
            outframe=outframe,
            scales=scales,
            imagename=imagename,
            outlierfile_path=outlierfile_path,
            workdir_path=workdir_path,
            ms_str=ms_str,
            n_spw=n_spw,
        )
    )
    warnings.extend(geo_warnings)

    clean_mask = mask.strip() if (usemask == "user" and mask) else None
    tclean_kwargs = _build_tclean_kwargs(
        ms_str=ms_str,
        imagename=imagename,
        field=field,
        spw=spw,
        stokes=stokes,
        specmode=specmode,
        deconvolver=deconvolver,
        nterms=nterms,
        gridder=gridder,
        wprojplanes=wprojplanes,
        cfcache=cfcache if gridder == "awproject" else None,
        cell=cell,
        imsize=imsize,
        weighting=weighting,
        robust=robust,
        niter=niter,
        threshold=threshold,
        savemodel=savemodel,
        pblimit=pblimit,
        pbmask=pbmask,
        usemask=usemask,
        mask=clean_mask,
        nsigma=nsigma,
        nchan=nchan,
        start=start,
        width=width,
        outframe=outframe,
        scales=scales,
        phasecenter=phasecenter,
        outlierfile=outlierfile_str,
    )

    script_file = _script_path(workdir_path, imagename)
    script_content = _build_script(
        workdir=str(workdir_path),
        tclean_kwargs=tclean_kwargs,
        script_filename=script_file.name,
    )
    _debug = debug_mode.validate(debug, debug_params, DEBUG_TASKS)
    if _debug:
        warnings.append(debug_mode.note(_debug))
    write_script(script_file, script_content)
    debug_mode.inject_file(script_file, _debug)
    casa_calls.append(f"write_script → {script_file}")

    if not execute:
        data = {
            "script_path": fmt_field(str(script_file)),
            "imagename": fmt_field(imagename),
            "completed": fmt_field(False, note="script not yet executed"),
        }
        warnings.append(
            f"Script written to {script_file}. Run it externally as a background job; "
            "tclean on real data can take hours."
        )
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=ms_path,
            data=data,
            warnings=warnings,
            casa_calls=casa_calls,
        )

    # execute=True: run tclean in-process.
    try:
        from casatasks import tclean as _tclean  # type: ignore[import]

        _tclean = debug_mode.wrap("tclean", _tclean, _debug)
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatasks is not installed.",
            ms_path=ms_path,
        ) from None

    # Archive any pre-existing products for this imagename before running tclean.
    _archive_tclean_products(str(workdir_path), imagename, clean_mask)

    casa_calls.append(f"casatasks.tclean(imagename={imagename!r}, ...)")
    try:
        summary = _tclean(**tclean_kwargs)
    except Exception as exc:
        raise TcleanFailedError(
            f"tclean raised: {exc}",
            ms_path=ms_path,
        ) from exc

    # mtmfs (nterms > 1, including CASA default None -> 2) writes Taylor-term
    # images: .image.tt0, .image.tt1, ...; nterms == 1 writes plain .image.
    if deconvolver == "mtmfs" and (nterms is None or nterms > 1):
        image_path = imagename + ".image.tt0"
    else:
        image_path = imagename + ".image"
    completed = Path(image_path).exists()
    if not completed:
        raise TcleanFailedError(
            f"tclean completed without error but {image_path} was not created.",
            ms_path=ms_path,
        )

    # Existence of the image is not success: a clean that stopped on the
    # iteration limit (or diverged) is deconvolution-limited, not a detection.
    stopcode, stop_reason, converged, conv_warn = _convergence(summary)
    if conv_warn:
        warnings.append(conv_warn)

    diverged = niter > 0 and stopcode in _DIVERGED_STOPCODES
    quarantined_to: str | None = None
    if diverged:
        moved = _archive_tclean_products(str(workdir_path), imagename, clean_mask)
        quarantined_to = moved.get(image_path)
        if quarantined_to:
            warnings.append(
                f"Diverged tclean products (stopcode={stopcode}) quarantined to {quarantined_to}."
            )

    measurement: dict = {"stopcode": stopcode, "converged": converged}
    if quarantined_to:
        measurement["quarantined_to"] = quarantined_to
    try:
        record_stage(
            str(workdir_path),
            "tclean",
            image_path,
            measurement,
        )
    except RuntimeError:
        if not quarantined_to:
            raise

    data = {
        "script_path": fmt_field(str(script_file)),
        "imagename": fmt_field(imagename),
        "completed": fmt_field(completed),
        "converged": fmt_field(
            converged, flag="COMPLETE" if stopcode is not None else "UNAVAILABLE"
        ),
        "stopcode": fmt_field(stopcode),
        "stop_reason": fmt_field(stop_reason),
    }
    if quarantined_to:
        data["quarantined_to"] = fmt_field(quarantined_to)
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
