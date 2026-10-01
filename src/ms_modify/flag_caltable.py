"""
flag_caltable.py — ms_flag_caltable

Runs an autoflag pass (rflag or tfcrop) on the *solutions* of a calibration
table, to catch RFI-contaminated outlier solutions that still pass the solve-time
SNR cut. Intended to run after a caltable is created and before it is applied
on-the-fly as a prior in subsequent solves.

Mode is auto-routed from the table's VisCal type (the same keyword
ms_calsol_stats reads):

    B  (bandpass)        → tfcrop   (per-channel spikes)
    G, T (gain)          → rflag    (per-solution amplitude/phase outliers)
    D, Df, Dgen (leakage)→ rflag
    K, Kcross, KAntPos   → refused  — one value per antenna; autoflag is not
                                      meaningful on a delay/position table

Gain tables (G, T) are flagged along time, so rflag needs enough solution
intervals per antenna to have neighbours to compare against. With solint='inf'
and a handful of scans there are only 2-3 points per antenna per field, and rflag
flags real solutions (24A-376: 3C147 went 16% -> 28% flagged on 2 scans). The
tool counts solution intervals per (field, SpW, antenna) and reports them; when
the median is below min_intervals (default 10) auto-routing refuses, and an
explicit mode= override runs with a warning quoting the counts.

A single sigma knob (default 5.0; 6.0 is more conservative) maps to the relevant
flagdata thresholds per mode. The tool reports the flagged fraction before and
after so the caller (skill) can apply its own go/no-go logic — e.g. > 30%
flagged means the a-priori flagging was insufficient and the solve should be
redone, not that sigma should simply be loosened.

Script output:
  workdir/flag_caltable.py — self-contained driver script
"""

from __future__ import annotations

from pathlib import Path

from ms_inspect.util.casa_context import open_table
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_flag_caltable"

# VisCal type (first token, ' Jones' stripped) → autoflag mode.
_MODE_BY_TYPE: dict[str, str] = {
    "B": "tfcrop",
    "G": "rflag",
    "T": "rflag",
    "D": "rflag",
    "Df": "rflag",
    "Dgen": "rflag",
}

# Delay / antenna-position tables: one value per antenna, nothing to autoflag.
_REFUSED_TYPES = {"K", "Kcross", "KAntPos"}

# Types flagged along the time axis: need enough solution intervals per antenna.
_TIME_AXIS_TYPES = {"G", "T"}


def _validate_caltable_path(caltable_path: str) -> Path:
    """Resolve and validate a CASA calibration-table path (exists + table.info)."""
    from ms_inspect.exceptions import ComputationError

    p = Path(caltable_path).expanduser().resolve()
    if not p.exists():
        raise ComputationError(f"Calibration table not found: {p}", ms_path=caltable_path)
    if not (p / "table.info").exists():
        raise ComputationError(
            f"'{p}' exists but is not a CASA table (missing 'table.info').",
            ms_path=caltable_path,
        )
    return p


def _read_viscal_type(caltable_path: str) -> str:
    """Read the VisCal keyword and return the first token (' Jones' stripped)."""
    with open_table(caltable_path) as tb:
        viscal = tb.getkeywords().get("VisCal", "")
    return viscal.replace(" Jones", "").strip()


def summarize_intervals(field_ids, spw_ids, ant_ids, times) -> dict:
    """Solution intervals (distinct TIME values) per (field, SpW, antenna). CASA-free.

    Returns {'min', 'median', 'max', 'n_groups'}; all None when the table is empty.
    """
    import numpy as np

    groups: dict[tuple[int, int, int], set[float]] = {}
    for f, s, a, t in zip(field_ids, spw_ids, ant_ids, times, strict=True):
        groups.setdefault((int(f), int(s), int(a)), set()).add(round(float(t), 3))
    if not groups:
        return {"min": None, "median": None, "max": None, "n_groups": 0}
    counts = np.array([len(v) for v in groups.values()])
    return {
        "min": int(counts.min()),
        "median": float(np.median(counts)),
        "max": int(counts.max()),
        "n_groups": int(counts.size),
    }


def _read_intervals(caltable_path: str) -> dict:
    """Count solution intervals per (field, SpW, antenna) in a caltable."""
    with open_table(caltable_path) as tb:
        return summarize_intervals(
            tb.getcol("FIELD_ID"),
            tb.getcol("SPECTRAL_WINDOW_ID"),
            tb.getcol("ANTENNA1"),
            tb.getcol("TIME"),
        )


def check_intervals(
    viscal_type: str, mode_override: str | None, intervals: dict, min_intervals: int
) -> str | None:
    """Raise (auto-routed) or return a warning (explicit mode) when a time-axis
    table has too few solution intervals per antenna for rflag/tfcrop to judge."""
    from ms_inspect.exceptions import ComputationError

    first = viscal_type.split()[0] if viscal_type else ""
    med = intervals.get("median")
    if first not in _TIME_AXIS_TYPES or med is None or med >= min_intervals:
        return None
    msg = (
        f"{viscal_type} table has a median of {med:g} solution intervals per "
        f"(field, SpW, antenna) (min {intervals['min']}, max {intervals['max']}), "
        f"below min_intervals={min_intervals}. Autoflagging along time with so few "
        "points flags real solutions."
    )
    if mode_override is None:
        raise ComputationError(
            msg + " Inspect with ms_calsol_stats and flag bad antennas explicitly, or "
            "pass mode= explicitly to override.",
            ms_path="",
        )
    return msg + " Running anyway because mode was passed explicitly."


def _resolve_mode(viscal_type: str, mode_override: str | None) -> str:
    """Pick the autoflag mode for this table type, honouring an explicit override."""
    from ms_inspect.exceptions import ComputationError

    if mode_override:
        if mode_override not in ("rflag", "tfcrop"):
            raise ComputationError(
                f"mode must be 'rflag' or 'tfcrop', got {mode_override!r}.",
                ms_path="",
            )
        return mode_override

    first = viscal_type.split()[0] if viscal_type else ""
    if first in _REFUSED_TYPES:
        raise ComputationError(
            f"VisCal type '{viscal_type}' is a delay/position table (one value per "
            "antenna). Autoflagging its solutions is not meaningful — skip it. Inspect "
            "with ms_calsol_stats and flag bad antennas explicitly instead.",
            ms_path="",
        )
    if first not in _MODE_BY_TYPE:
        raise ComputationError(
            f"Cannot auto-route mode for VisCal type '{viscal_type}'. Pass mode explicitly "
            "('rflag' or 'tfcrop') if you are sure this table should be autoflagged.",
            ms_path="",
        )
    return _MODE_BY_TYPE[first]


def _build_script(
    caltable_str: str,
    mode: str,
    datacolumn: str,
    sigma: float,
    flagbackup: bool,
) -> str:
    """Return a self-contained flag_caltable.py driver script."""
    if mode == "tfcrop":
        flag_kwargs = f"timecutoff={sigma}, freqcutoff={sigma}"
    else:  # rflag
        flag_kwargs = f"timedevscale={sigma}, freqdevscale={sigma}"

    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_flag_caltable (ms_modify).
Run with: python flag_caltable.py

Autoflags caltable solutions (mode={mode!r}, datacolumn={datacolumn!r}) at
sigma={sigma}. Prints the flagged fraction before and after so you can decide
whether the a-priori flagging was sufficient (> 30% flagged → improve preflag
and redo the solve rather than loosening sigma).
\"\"\"
from casatasks import flagdata

caltable = {caltable_str!r}


def _frac(summary):
    tot = summary.get("total", 0) or 0
    return (summary.get("flagged", 0) / tot) if tot else 0.0


before = flagdata(vis=caltable, mode="summary", datacolumn={datacolumn!r})
print(f"Flagged fraction before: {{_frac(before):.4f}}")

flagdata(
    vis=caltable,
    mode={mode!r},
    action="apply",
    datacolumn={datacolumn!r},
    {flag_kwargs},
    flagbackup={flagbackup!r},
)

after = flagdata(vis=caltable, mode="summary", datacolumn={datacolumn!r})
print(f"Flagged fraction after:  {{_frac(after):.4f}}")
print(f"Delta: {{_frac(after) - _frac(before):.4f}}")
print("Done. If > 30% flagged, improve a-priori flagging and redo the solve.")
"""


def run(
    caltable_path: str,
    workdir: str,
    sigma: float = 5.0,
    mode: str | None = None,
    datacolumn: str = "CPARAM",
    flagbackup: bool = True,
    min_intervals: int = 10,
    execute: bool = False,
) -> dict:
    """
    Generate (and optionally execute) an autoflag pass on a caltable's solutions.

    Args:
        caltable_path: Path to the CASA calibration table.
        workdir:       Existing directory for the generated script.
        sigma:         Threshold scale (default 5.0; 6.0 is more conservative).
                       Maps to timecutoff/freqcutoff (tfcrop) or
                       timedevscale/freqdevscale (rflag).
        mode:          'rflag' or 'tfcrop'. Default None → auto-route from the
                       table's VisCal type (B→tfcrop, G/T/D→rflag, K→refused).
        datacolumn:    Solution column to flag on. Default 'CPARAM' (complex
                       solutions: B, G, D). Use 'FPARAM' only for real-valued
                       tables.
        flagbackup:    Save a .flagversions backup of the caltable first (default True).
        min_intervals: For gain tables (G, T): minimum median number of solution
                       intervals per (field, SpW, antenna) for autoflagging. Below
                       it, auto-routing refuses; an explicit mode runs with a
                       warning (default 10).
        execute:       If False (default), write flag_caltable.py and return.
                       If True, run the summary→apply→summary sequence in-process
                       and report flagged_frac_before/after/delta.

    Returns:
        Standard response envelope. Always includes script_path, viscal_type,
        resolved mode, datacolumn, and sigma. When execute=True, also includes
        flagged_frac_before, flagged_frac_after, flagged_frac_delta.
    """
    from ms_inspect.exceptions import ComputationError

    p = _validate_caltable_path(caltable_path)
    caltable_str = str(p)

    workdir_path = Path(workdir)
    if not workdir_path.exists():
        raise ComputationError(
            f"workdir does not exist: {workdir}. Create it before calling this tool.",
            ms_path=caltable_path,
        )
    if sigma <= 0:
        raise ComputationError(f"sigma must be > 0, got {sigma}.", ms_path=caltable_path)

    casa_calls: list[str] = []
    warnings: list[str] = []

    viscal_type = _read_viscal_type(caltable_str)
    casa_calls.append(f"tb.getkeywords() → VisCal='{viscal_type} Jones'")
    resolved_mode = _resolve_mode(viscal_type, mode)
    intervals = _read_intervals(caltable_str)
    casa_calls.append("tb.getcol(FIELD_ID, SPECTRAL_WINDOW_ID, ANTENNA1, TIME) → intervals")
    interval_warn = check_intervals(viscal_type, mode, intervals, min_intervals)
    if interval_warn:
        warnings.append(interval_warn)

    script_path = str(workdir_path / "flag_caltable.py")
    script_content = _build_script(
        caltable_str=caltable_str,
        mode=resolved_mode,
        datacolumn=datacolumn,
        sigma=sigma,
        flagbackup=flagbackup,
    )
    Path(script_path).write_text(script_content)
    casa_calls.append(f"write_script → {script_path}")

    base_data: dict = {
        "script_path": fmt_field(script_path),
        "viscal_type": fmt_field(viscal_type),
        "mode": fmt_field(resolved_mode),
        "datacolumn": datacolumn,
        "sigma": sigma,
        "solution_intervals": intervals,
        "min_intervals": min_intervals,
    }

    if not execute:
        warnings.append(
            f"Script written to {script_path}. Run it externally, or call again with "
            "execute=True. If > 30% of solutions are flagged, improve the a-priori "
            "flagging and redo the solve rather than only loosening sigma."
        )
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=caltable_path,
            data=base_data,
            warnings=warnings,
            casa_calls=casa_calls,
        )

    # execute=True: run in-process
    try:
        from casatasks import flagdata  # type: ignore[import]
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatasks is not installed or cannot be imported.",
            ms_path=caltable_path,
        ) from None

    def _frac(summary: dict) -> float:
        tot = summary.get("total", 0) or 0
        return (summary.get("flagged", 0) / tot) if tot else 0.0

    flag_kwargs: dict = (
        {"timecutoff": sigma, "freqcutoff": sigma}
        if resolved_mode == "tfcrop"
        else {"timedevscale": sigma, "freqdevscale": sigma}
    )

    try:
        before = flagdata(vis=caltable_str, mode="summary", datacolumn=datacolumn)
        casa_calls.append("casatasks.flagdata(mode='summary') [before]")
        flagdata(
            vis=caltable_str,
            mode=resolved_mode,
            action="apply",
            datacolumn=datacolumn,
            flagbackup=flagbackup,
            **flag_kwargs,
        )
        casa_calls.append(
            f"casatasks.flagdata(mode={resolved_mode!r}, action='apply', "
            f"datacolumn={datacolumn!r}, {flag_kwargs})"
        )
        after = flagdata(vis=caltable_str, mode="summary", datacolumn=datacolumn)
        casa_calls.append("casatasks.flagdata(mode='summary') [after]")
    except Exception as exc:
        raise ComputationError(
            f"flagdata autoflag on caltable failed: {exc}",
            ms_path=caltable_path,
        ) from exc

    frac_before = _frac(before)
    frac_after = _frac(after)
    delta = frac_after - frac_before
    base_data["flagged_frac_before"] = fmt_field(round(frac_before, 4))
    base_data["flagged_frac_after"] = fmt_field(round(frac_after, 4))
    base_data["flagged_frac_delta"] = fmt_field(round(delta, 4))

    if frac_after > 0.30:
        warnings.append(
            f"Flagged fraction after autoflag is {frac_after:.1%} (> 30%). The a-priori "
            "flagging was likely insufficient — improve preflag and redo this solve "
            "rather than loosening sigma. If it stays high after redoing, try sigma=6.0."
        )

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=caltable_path,
        data=base_data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
