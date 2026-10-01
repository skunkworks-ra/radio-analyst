"""
postcal_flag.py — ms_postcal_flag

Post-calibration RFI flagging on the phase calibrator AND science target, after
the final applycal. The pre-cal pipeline flags calibrators only; this routine
extends flagging to the fields that were never cleaned, and bakes the SpW-triage
decision (from ms_spw_amp_severity, reasoned in skill 13) into the FLAG column.

An ordered sequence of direct flagdata(action='apply') passes, preceded by a
single flagmanager save:
  1. clip      — optional ceiling on |CORRECTED - MODEL| (datacolumn='residual'),
                 per field / SpW / parallel-hand correlation
  2. tfcrop    — on the SpWs being KEPT (salvage localized RFI, preserve bandwidth)
  3. rflag     — likewise
  4. manual    — fully flag the drop-tier SpWs (so all downstream steps respect it)

Amplitude clipping is only meaningful against a known model. A clip on
|CORRECTED| of a field with real sky (phase calibrator, science target) clips
against the sky, not the noise, and a threshold pooled over fields is set by the
brightest one. So any clip (clip_sigma or clipmax) requires
datacolumn='residual' AND a real MODEL on every selected field (not the 1 Jy
default); otherwise the tool raises. tfcrop/rflag carry no such requirement.

Why direct passes, not flagdata(mode='list'): CASA 6.7.5 aborts the list-mode
report-aggregation path with KeyError 'nreport' after the flags are computed
(notably when an agent's report is empty). This bit the initial-rflag step on
two separate runs; the same list-mode path underlies this tool, so it issues
one flagdata call per command instead. Single agent per call, no report merge.

field is REQUIRED. Flagging CORRECTED on fields whose calibration is not valid
flags almost everything; the caller scopes this to the phase cal + target.

Script output:
  workdir/postcal_flag.py       — self-contained driver script
"""

from __future__ import annotations

from pathlib import Path

from ms_inspect.util.casa_context import validate_ms_path
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import normalize_field_sel, normalize_spw_sel, response_envelope

TOOL_NAME = "ms_postcal_flag"

_FLAG_VERSION = "before_postcal_flag"

_DATACOL_MAP = {
    "corrected": "CORRECTED_DATA",
    "data": "DATA",
    "model": "MODEL_DATA",
}

# CASA Stokes enum → name, parallel hands only (the clip never touches cross-hands).
_PARALLEL_CORR = {5: "RR", 8: "LL", 9: "XX", 12: "YY"}

# A MODEL pinned at the CASA default: amplitude ~1 Jy with flat phase.
_DEFAULT_MODEL_AMP_TOL = 0.05
_DEFAULT_MODEL_PHASE_RMS_DEG = 1.0


def _parse_spw_ids(spw_sel: str) -> list[int]:
    """Parse a comma-separated SpW selection into whole-SpW ints.

    Supports plain ids ('0,3,5') and inclusive ranges ('0~7', '20~28'); the two
    may be mixed ('16,20~28'). Channel syntax ('0:5~10') is NOT supported — the
    robust clip is computed per whole SpW, so any token carrying a ':channel'
    selection is skipped entirely rather than silently widened to the whole SpW.
    Returns sorted, de-duplicated ids.
    """
    ids: set[int] = set()
    for raw in spw_sel.split(","):
        tok = raw.strip()
        if not tok or ":" in tok:
            continue
        if "~" in tok:
            lo_s, _, hi_s = tok.partition("~")
            lo_s, hi_s = lo_s.strip(), hi_s.strip()
            if lo_s.isdigit() and hi_s.isdigit():
                lo, hi = int(lo_s), int(hi_s)
                if lo <= hi:
                    ids.update(range(lo, hi + 1))
        elif tok.isdigit():
            ids.add(int(tok))
    return sorted(ids)


def match_field_names(names: list[str], field_sel: str) -> list[int]:
    """Resolve a CASA-style field selection against FIELD names. CASA-free.

    Tokens (comma-separated): exact name, shell wildcard ('PER_FIELD_*'),
    integer id ('3') or inclusive id range ('3~7'). Every token must match at
    least one field — an unmatched token raises ValueError rather than silently
    widening the selection to every field.
    """
    import fnmatch

    ids: set[int] = set()
    for raw in field_sel.split(","):
        tok = raw.strip()
        if not tok:
            continue
        hit: set[int] = set()
        if tok.isdigit():
            if int(tok) < len(names):
                hit.add(int(tok))
        elif "~" in tok and all(p.strip().isdigit() for p in tok.split("~", 1)):
            lo, hi = (int(p) for p in tok.split("~", 1))
            hit.update(i for i in range(lo, hi + 1) if i < len(names))
        elif any(c in tok for c in "*?["):
            hit.update(i for i, nm in enumerate(names) if fnmatch.fnmatchcase(nm, tok))
        else:
            hit.update(i for i, nm in enumerate(names) if nm == tok)
        if not hit:
            raise ValueError(f"field token {tok!r} matches no field in the MS")
        ids |= hit
    if not ids:
        raise ValueError(f"field selection {field_sel!r} is empty")
    return sorted(ids)


def check_clip_policy(datacolumn: str, clip_sigma: float | None, clipmax: float | None) -> None:
    """Raise ValueError if an amplitude clip is requested on a non-residual column."""
    if clip_sigma is None and clipmax is None:
        return
    if datacolumn.lower() not in ("residual", "residual_data"):
        raise ValueError(
            f"amplitude clip requested on datacolumn={datacolumn!r}. A clip is only "
            "meaningful on the residual (CORRECTED - MODEL) of a field with a real model; "
            "on CORRECTED it clips the sky. Use datacolumn='residual' on modelled fields, "
            "or set clip_sigma=None and clipmax=None and rely on tfcrop/rflag."
        )


def model_is_default(par_amp: float, par_phase_rms_deg: float) -> bool:
    """True if a field's MODEL looks like the unwritten 1 Jy CASA default. CASA-free."""
    return (
        abs(par_amp - 1.0) <= _DEFAULT_MODEL_AMP_TOL
        and par_phase_rms_deg <= _DEFAULT_MODEL_PHASE_RMS_DEG
    )


def _parallel_corr_by_ddid(ms_str: str) -> list[list[tuple[int, str]]]:
    """For each DATA_DESC_ID, the (index, name) of its parallel-hand correlations,
    read from the POLARIZATION row that DATA_DESCRIPTION actually points to."""
    from ms_inspect.util.casa_context import open_table

    with open_table(ms_str + "/POLARIZATION") as tb:
        corr = [[int(c) for c in tb.getcell("CORR_TYPE", r)] for r in range(tb.nrows())]
    with open_table(ms_str + "/DATA_DESCRIPTION") as tb:
        pol_ids = [int(x) for x in tb.getcol("POLARIZATION_ID")]
    return [
        [(i, _PARALLEL_CORR[c]) for i, c in enumerate(corr[pid]) if c in _PARALLEL_CORR]
        for pid in pol_ids
    ]


def _robust_clip_thresholds(
    ms_str: str,
    field_sel: str,
    keep_spw_ids: list[int],
    clip_sigma: float,
    floor_spw_ids: list[int] | None = None,
    max_samples: int = 20_000,
) -> tuple[dict, dict, list[str]]:
    """Per-(field, SpW, corr) clip ceiling on |CORRECTED - MODEL|.

    sigma = 1.4826 * MAD of Re(residual) on unflagged samples (parallel hands,
    rows sampled to ~max_samples per field/SpW). Ceiling = clip_sigma * sigma.
    With floor_spw_ids, each (field, corr) uses the median sigma over those SpWs
    (a thermal floor from known-clean windows) for every kept SpW instead of the
    SpW's own sigma, which inflates when RFI occupies most of the SpW.

    Raises ValueError if the selection matches nothing or any selected field's
    MODEL is the unwritten 1 Jy default. Returns (thresholds, sigmas, warnings),
    keyed 'field|spw|corr'.
    """
    import numpy as np

    from ms_inspect.util.casa_context import open_table

    warnings: list[str] = []
    with open_table(ms_str + "/FIELD") as tb:
        names = [str(n) for n in tb.getcol("NAME")]
    field_ids = match_field_names(names, field_sel)
    with open_table(ms_str + "/DATA_DESCRIPTION") as tb:
        dd_to_spw = [int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")]
    corr_by_dd = _parallel_corr_by_ddid(ms_str)
    want = set(keep_spw_ids) | set(floor_spw_ids or [])

    sigmas: dict[tuple[str, int, str], float] = {}
    no_model: list[str] = []
    with open_table(ms_str) as tb:
        cols = set(tb.colnames())
        for need in ("CORRECTED_DATA", "MODEL_DATA"):
            if need not in cols:
                raise ValueError(
                    f"{need} not present; a residual clip needs both CORRECTED and MODEL."
                )
        for fid in field_ids:
            par_amps: list[float] = []
            phase_rms: list[float] = []
            for ddid, spw in enumerate(dd_to_spw):
                if spw not in want or not corr_by_dd[ddid]:
                    continue
                sub = tb.query(
                    f"DATA_DESC_ID == {ddid} && FIELD_ID == {fid} && ANTENNA1 != ANTENNA2"
                )
                try:
                    n = int(sub.nrows())
                    if n == 0:
                        continue
                    step = max(1, n // max(1, max_samples // 64))
                    c = sub.getcol("CORRECTED_DATA", startrow=0, nrow=-1, rowincr=step)
                    m = sub.getcol("MODEL_DATA", startrow=0, nrow=-1, rowincr=step)
                    f = sub.getcol("FLAG", startrow=0, nrow=-1, rowincr=step).astype(bool)
                finally:
                    sub.close()
                for ci, cname in corr_by_dd[ddid]:
                    mod = m[ci]
                    par_amps.append(float(np.median(np.abs(mod))))
                    phase_rms.append(float(np.degrees(np.std(np.angle(mod)))))
                    r = (c[ci] - mod)[~f[ci]].real
                    if r.size < 100:
                        continue
                    sigmas[(names[fid], spw, cname)] = float(
                        1.4826 * np.median(np.abs(r - np.median(r)))
                    )
            if par_amps and model_is_default(
                float(np.median(par_amps)), float(np.median(phase_rms))
            ):
                no_model.append(names[fid])
    if no_model:
        raise ValueError(
            f"field(s) {no_model} have MODEL at the 1 Jy default (no real model); a residual "
            "clip there clips the sky. Restrict the clip to fields with a setjy/polcal model."
        )

    thresholds: dict[str, float] = {}
    sig_out: dict[str, float] = {}
    for fid in field_ids:
        fname = names[fid]
        for cname in sorted({k[2] for k in sigmas if k[0] == fname}):
            floor = None
            if floor_spw_ids:
                fl = [
                    sigmas[(fname, s, cname)] for s in floor_spw_ids if (fname, s, cname) in sigmas
                ]
                if fl:
                    floor = float(np.median(fl))
                else:
                    warnings.append(f"{fname}/{cname}: no floor_spw data; using per-SpW sigma.")
            for spw in sorted(keep_spw_ids):
                own = sigmas.get((fname, spw, cname))
                sg = floor if floor is not None else own
                if sg is None:
                    warnings.append(f"{fname} SpW {spw} {cname}: no unflagged residual; no clip.")
                    continue
                key = f"{fname}|{spw}|{cname}"
                thresholds[key] = round(clip_sigma * sg, 6)
                sig_out[key] = round(own, 6) if own is not None else None
    return thresholds, sig_out, warnings


def _build_flag_calls(
    field: str,
    keep_spw: str,
    drop_spw: str,
    datacolumn: str,
    clipmax: float | None,
    clip_thresholds: dict[str, float] | None,
    uvrange: str,
    timedevscale: float,
    freqdevscale: float,
    timecutoff: float,
    freqcutoff: float,
) -> list[dict]:
    """Build the ordered list of flagdata call kwargs (one dict per pass).

    Order is significant: clip(s) first so tfcrop/rflag compute statistics on
    clipped data, then the manual drop-tier flag last. clip_thresholds is keyed
    'field|spw|corr' (from _robust_clip_thresholds). Every call carries
    action='apply' and flagbackup=False (one shared flagmanager save is issued
    by the caller). Rendered to script text and executed from the same spec.
    """
    calls: list[dict] = []
    if clip_thresholds:
        # One clip per 'field|spw|corr' key, each with its own ceiling.
        for key in sorted(clip_thresholds):
            fname, spw_id, corr = key.split("|")
            kw = {
                "mode": "clip",
                "field": fname,
                "spw": spw_id,
                "correlation": corr,
                "datacolumn": datacolumn,
                "clipminmax": [0.0, clip_thresholds[key]],
                "clipoutside": True,
            }
            if uvrange:
                kw["uvrange"] = uvrange
            calls.append(kw)
    elif clipmax is not None:
        kw = {
            "mode": "clip",
            "field": field,
            "datacolumn": datacolumn,
            "clipminmax": [0.0, clipmax],
            "clipoutside": True,
        }
        if uvrange:
            kw["uvrange"] = uvrange
        calls.append(kw)

    tfcrop = {
        "mode": "tfcrop",
        "field": field,
        "datacolumn": datacolumn,
        "timecutoff": timecutoff,
        "freqcutoff": freqcutoff,
    }
    if keep_spw:
        tfcrop["spw"] = keep_spw
    calls.append(tfcrop)

    rflag = {
        "mode": "rflag",
        "field": field,
        "datacolumn": datacolumn,
        "timedevscale": timedevscale,
        "freqdevscale": freqdevscale,
    }
    if keep_spw:
        rflag["spw"] = keep_spw
    calls.append(rflag)

    if drop_spw:
        calls.append({"mode": "manual", "field": field, "spw": drop_spw})

    return calls


def _render_call(kw: dict) -> str:
    """Render one flagdata call spec to a Python source snippet."""
    parts = ["    vis=ms_path"]
    for k, v in kw.items():
        parts.append(f"    {k}={v!r}")
    parts.append("    action='apply'")
    parts.append("    flagbackup=False")
    body = ",\n".join(parts)
    return f"flagdata(\n{body},\n)"


def _build_script(ms_str: str, flag_calls: list[dict], workdir: str = "") -> str:
    from ms_inspect.util.stage_log import RECORD_STAGE_SNIPPET as record

    call_blocks = "\n\n".join(_render_call(kw) for kw in flag_calls)
    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_postcal_flag (ms_modify).
Run with: python postcal_flag.py

Requires: CORRECTED populated on the selected fields (final applycal done).
Any clip below runs on the residual (CORRECTED - MODEL) of fields with a real
model only; thresholds are per field / SpW / parallel-hand correlation.

Direct flagdata(action='apply') passes rather than one mode='list' pass:
CASA 6.7.5 aborts list mode with KeyError 'nreport'. A single flagmanager
save captures the pre-flag state; flagbackup=False on each pass avoids
redundant per-call backups.
\"\"\"
from casatasks import flagdata, flagmanager

{record}

ms_path = {ms_str!r}

# One versioned backup of the pre-flag FLAG state.
flagmanager(vis=ms_path, mode="save", versionname={_FLAG_VERSION!r})

{call_blocks}

# flagdata(action='apply') returns nothing useful, so completion is measured
# with a summary pass. It reports the flagged fraction the stage produced —
# a number, not a verdict — so a pass that flagged nothing is visible in the
# record instead of looking identical to one that worked.
_summary = flagdata(vis={ms_str!r}, mode="summary")
_flagged = (
    float(_summary["flagged"]) / float(_summary["total"]) if _summary.get("total") else None
)
_record_stage({workdir!r}, "postcal_flag", {ms_str!r}, {{"flagged_fraction": _flagged}})
print("Post-calibration flagging complete.")
print("Use ms_flag_summary for the flag delta and ms_spw_amp_severity to re-measure.")
"""


def run(
    ms_path: str,
    workdir: str,
    field: str,
    keep_spw: str = "",
    drop_spw: str = "",
    datacolumn: str = "corrected",
    clip_sigma: float | None = None,
    clipmax: float | None = None,
    floor_spw: str = "",
    uvrange: str = "",
    timedevscale: float = 5.0,
    freqdevscale: float = 5.0,
    timecutoff: float = 4.0,
    freqcutoff: float = 4.0,
    execute: bool = False,
) -> dict:
    """
    Generate (and optionally execute) post-calibration RFI flagging.

    Args:
        ms_path:      Path to the MS (CORRECTED populated on the selected fields).
        workdir:      Existing directory for the generated scripts.
        field:        REQUIRED. The field(s) to flag — the phase calibrator and/or
                      science target whose CORRECTED column is valid after the final
                      applycal. An all-field pass over fields without valid CORRECTED
                      flags almost everything.
        keep_spw:     CASA SpW selection for the SpWs being KEPT — tfcrop + rflag run
                      on these to salvage localized RFI. Empty = all SpWs.
        drop_spw:     CASA SpW selection for the drop-tier SpWs — fully flagged via a
                      manual command so downstream imaging/calibration respects it.
                      Empty = drop nothing.
        datacolumn:   Column to flag on (default 'corrected'). Must be 'residual'
                      when any clip is requested.
        clip_sigma:   Residual clip: ceiling = clip_sigma * 1.4826*MAD(Re residual),
                      per field / kept SpW / parallel-hand correlation. Default None
                      (no clip). Requires datacolumn='residual' and a real MODEL on
                      every selected field; raises otherwise.
        clipmax:      Flat |residual| ceiling, used only when clip_sigma is None. Same
                      residual/model requirement.
        floor_spw:    Optional SpW selection of known-clean windows. If set, each
                      (field, corr) uses the median sigma over these SpWs as a thermal
                      floor for every kept SpW (robust when RFI fills most of a SpW).
        uvrange:      Optional CASA uvrange applied to the clip only (e.g. '>2klambda').
                      The robust clip is uv-blind; on an extended source scope it to
                      longer baselines so real short-spacing flux is not clipped.
        timedevscale: rflag time deviation threshold (default 5.0).
        freqdevscale: rflag frequency deviation threshold (default 5.0).
        timecutoff:   tfcrop time deviation threshold (default 4.0).
        freqcutoff:   tfcrop frequency deviation threshold (default 4.0).
        execute:      If False (default), write scripts and return.
                      If True, run flagdata(mode='list') in-process.

    Returns:
        Standard envelope. Always includes script_path.
    """
    field = normalize_field_sel(field)
    keep_spw = normalize_spw_sel(keep_spw)
    drop_spw = normalize_spw_sel(drop_spw)
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    if not field or not str(field).strip():
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            "field is required. Scope post-cal flagging to the phase calibrator and/or "
            "science target whose CORRECTED column is valid after the final applycal. "
            "An all-field pass over fields without valid CORRECTED flags almost everything.",
            ms_path=ms_path,
        )

    workdir_path = Path(workdir)
    if not workdir_path.exists():
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"workdir does not exist: {workdir}. Create it before calling this tool.",
            ms_path=ms_path,
        )

    script_path = str(workdir_path / "postcal_flag.py")

    from ms_inspect.exceptions import ComputationError

    try:
        check_clip_policy(datacolumn, clip_sigma, clipmax)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    # Residual clip thresholds per field / SpW / parallel-hand correlation.
    # Takes precedence over the flat clipmax fallback.
    clip_thresholds: dict[str, float] | None = None
    clip_sigmas: dict[str, float] | None = None
    if clip_sigma is not None:
        keep_ids = _parse_spw_ids(keep_spw)
        if not keep_ids:
            raise ComputationError(
                "clip_sigma set but keep_spw is empty or not a plain SpW-id list; the "
                "residual clip is computed per kept SpW.",
                ms_path=ms_path,
            )
        floor_ids = _parse_spw_ids(normalize_spw_sel(floor_spw)) or None
        try:
            clip_thresholds, clip_sigmas, clip_warn = _robust_clip_thresholds(
                ms_str, field, keep_ids, clip_sigma, floor_ids
            )
        except ValueError as exc:
            raise ComputationError(str(exc), ms_path=ms_path) from None
        warnings.extend(clip_warn)
        casa_calls.append(
            f"residual clip: {clip_sigma} x 1.4826*MAD(Re(CORRECTED-MODEL)) per field/SpW/corr "
            f"over {field!r}" + (f", floor from SpWs {floor_ids}" if floor_ids else "")
        )
    elif clipmax is not None:
        # Flat residual clip: still needs real models on every selected field.
        try:
            _robust_clip_thresholds(ms_str, field, _parse_spw_ids(keep_spw) or [0], 1.0)
        except ValueError as exc:
            raise ComputationError(str(exc), ms_path=ms_path) from None

    flag_calls = _build_flag_calls(
        field,
        keep_spw,
        drop_spw,
        datacolumn,
        clipmax,
        clip_thresholds,
        uvrange,
        timedevscale,
        freqdevscale,
        timecutoff,
        freqcutoff,
    )

    script_content = _build_script(ms_str, flag_calls, workdir=str(workdir_path))
    Path(script_path).write_text(script_content)
    casa_calls.append(f"write_script → {script_path}")

    base_data: dict = {
        "script_path": fmt_field(script_path),
        "field": fmt_field(field),
        "keep_spw": keep_spw,
        "drop_spw": drop_spw,
        "datacolumn": datacolumn,
        "clip_sigma": clip_sigma,
        "clip_thresholds": clip_thresholds,
        "clip_residual_sigma": clip_sigmas,
        "floor_spw": floor_spw,
        "clipmax": clipmax,
        "uvrange": uvrange,
        "rflag_timedevscale": timedevscale,
        "rflag_freqdevscale": freqdevscale,
        "tfcrop_timecutoff": timecutoff,
        "tfcrop_freqcutoff": freqcutoff,
    }

    if not execute:
        warnings.append(
            f"Script written to {workdir}. Ensure the final applycal has populated "
            "CORRECTED on the selected fields. Then run postcal_flag.py "
            "externally and call ms_flag_summary to capture the delta."
        )
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=ms_path,
            data=base_data,
            warnings=warnings,
            casa_calls=casa_calls,
        )

    try:
        from casatasks import flagdata, flagmanager  # type: ignore[import]
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatasks is not installed or cannot be imported.",
            ms_path=ms_path,
        ) from None

    try:
        # One versioned backup, then a direct action='apply' pass per command —
        # never mode='list' (CASA 6.7.5 aborts it with KeyError 'nreport').
        casa_calls.append(f"flagmanager(mode='save', versionname={_FLAG_VERSION!r})")
        flagmanager(vis=ms_str, mode="save", versionname=_FLAG_VERSION)
        for kw in flag_calls:
            casa_calls.append(f"flagdata(mode={kw['mode']!r}, field={field!r}, action='apply')")
            flagdata(vis=ms_str, action="apply", flagbackup=False, **kw)
    except Exception as exc:
        raise ComputationError(
            f"post-cal flagging failed: {exc}",
            ms_path=ms_path,
        ) from exc

    base_data["flags_applied"] = fmt_field(True)
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=base_data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
