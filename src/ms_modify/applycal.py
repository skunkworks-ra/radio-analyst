"""
applycal.py — ms_applycal

Apply calibration tables to a single field selection, writing the result
to the CORRECTED_DATA column. Called once per field category (flux cal,
phase cal, target) with different gainfield and interp parameters each time.

CASA call sequence:
  applycal(vis, field, gaintable, gainfield, interp, calwt, applymode,
           parang, flagbackup)

When execute=False (default), writes a self-contained script to
workdir/applycal_<ms_stem>_<field_stem>.py and returns immediately.

The three-call pattern for a standard observation:
  ms_applycal(field=flux_field,  gainfield=[..., flux_field],  interp=[..., 'nearest'])
  ms_applycal(field=phase_field, gainfield=[..., phase_field], interp=[..., 'nearest'])
  ms_applycal(field=target,      gainfield=[..., phase_field], interp=[..., 'linear'])
"""

from __future__ import annotations

from pathlib import Path

from ms_inspect.util.casa_context import (
    describe_numeric_fields,
    open_msmd,
    open_table,
    validate_ms_path,
)
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import normalize_field_sel, response_envelope
from ms_inspect.util.logs import write_script
from ms_inspect.util.stage_log import pol_types, record_stage
from ms_modify import debug_mode
from ms_modify.exceptions import ApplycalFailedError
from ms_modify.pathguard import next_script_path

TOOL_NAME = "ms_applycal"
#: CASA tasks this tool calls; the valid debug_params keys (debug_mode.py).
DEBUG_TASKS = ("applycal",)


def _safe_stem(text: str, limit: int = 40) -> str:
    """Filename-safe stem. If sanitizing or truncation changed the text, a short
    hash of the original is appended so distinct selections ('J*' vs 'J?', or
    long lists sharing a prefix) cannot overwrite one another's script."""
    import hashlib
    import re

    stem = re.sub(r"[^A-Za-z0-9._+=-]", "_", text)
    if stem == text and len(stem) <= limit:
        return stem
    digest = hashlib.sha1(text.encode()).hexdigest()[:7]
    return f"{stem[: limit - 8]}_{digest}"


def _script_path(workdir: Path, field: str, ms_str: str = "") -> Path:
    ms_stem = _safe_stem(Path(ms_str).name.removesuffix(".ms")) if ms_str else ""
    prefix = f"applycal_{ms_stem}_" if ms_stem else "applycal_"
    return next_script_path(workdir, f"{prefix}{_safe_stem(field)}.py")


_CASA_FIELD_META_CHARS = frozenset("*?~><^/;!&|()")
_CROSS_CAL_GUARD_VISCAL = frozenset({"G JONES", "T JONES", "G", "T"})


def _collect_gainfield_warnings(
    ms_str: str,
    field: str,
    gaintable: list[str],
    gainfield: list[str],
) -> list[str]:
    """Warn when a G/T Jones table has solutions for ``field`` itself, yet
    ``gainfield`` is empty (multi-field linear mixing) or selects another field.

    Never warns on single-calibrator B/K/Kcross/Df/Xf tables, or when ``field``
    has no solutions of its own in the table (e.g. target using phase cal).
    Non-fatal on unreadable tables or missing CASA metadata.
    """
    if not field or not gaintable:
        return []
    try:
        with open_msmd(ms_str) as msmd:
            field_names = [str(x) for x in msmd.fieldnames()]
    except Exception:
        try:
            with open_table(ms_str + "/FIELD") as tb:
                field_names = [str(x) for x in tb.getcol("NAME")]
        except Exception:
            return []
    if not field_names:
        return []

    from ms_inspect.util.selection import match_field_names

    try:
        target_fids = set(match_field_names(field_names, field))
    except ValueError:
        return []

    out: list[str] = []
    for gt, gf_raw in zip(gaintable, gainfield, strict=False):
        try:
            with open_table(gt) as tb:
                viscal = str(tb.getkeyword("VisCal")).strip()
                if viscal.upper() not in _CROSS_CAL_GUARD_VISCAL:
                    continue
                cal_fids = {int(x) for x in tb.getcol("FIELD_ID")}
        except Exception:
            continue

        own_fids = target_fids & cal_fids
        if not own_fids:
            continue

        gf = gf_raw.strip()
        gt_name = Path(gt).name
        own_names = [field_names[i] for i in sorted(own_fids) if i < len(field_names)]
        if not gf:
            if len(cal_fids) >= 2:
                out.append(
                    f"Cross-calibrator gainfield risk on {gt_name} ({viscal}): "
                    f"field={field!r} ({own_names}) has its own solutions in this multi-field "
                    f"table ({len(cal_fids)} fields), but gainfield='' allows CASA to linearly "
                    f"mix solutions across calibrators. Pass gainfield={field!r} explicitly."
                )
            continue

        try:
            gf_fids = set(match_field_names(field_names, gf))
        except ValueError:
            continue

        if not (own_fids <= gf_fids) or bool(gf_fids - target_fids):
            out.append(
                f"Cross-calibrator gainfield mismatch on {gt_name} ({viscal}): "
                f"field={field!r} ({own_names}) has its own solutions in this table, "
                f"but gainfield={gf!r} selects different field(s). Use gainfield={field!r} "
                "so a calibrator applies its own G/T solutions rather than another field's."
            )
    return out


def _validate_literal_fields(ms_path: str, ms_str: str, field_sel: str) -> None:
    """Reject plain literal field names absent from FIELD before writing a script."""
    if not field_sel or not field_sel.strip():
        return
    literal_tokens = [
        tok.strip()
        for tok in field_sel.split(",")
        if tok.strip()
        and not tok.strip().isdigit()
        and not any(ch in tok for ch in _CASA_FIELD_META_CHARS)
    ]
    if not literal_tokens:
        return
    try:
        with open_msmd(ms_str) as msmd:
            names = list(msmd.fieldnames())
    except Exception:
        return
    known = set(names)
    missing = [tok for tok in literal_tokens if tok not in known]
    if missing:
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"Field(s) {missing} not found in {ms_path}; available fields: {names}. "
            "For a mosaic, pass comma-separated mosaic_groups[].field_names (never group_name).",
            ms_path=ms_path,
        )


def _build_script(
    ms_str: str,
    workdir: str,
    field: str,
    gaintable: list[str],
    gainfield: list[str],
    interp: list[str],
    calwt: bool,
    applymode: str,
    parang: bool,
    flagbackup: bool,
    spwmap: list[list[int]] | None = None,
) -> str:
    # spwmap is omitted entirely when not supplied → CASA default (identity).
    spwmap_line = f"    spwmap={spwmap!r},\n" if spwmap is not None else ""
    from ms_inspect.util.stage_log import POL_TYPES_SNIPPET as pol
    from ms_inspect.util.stage_log import RECORD_STAGE_SNIPPET as record
    from ms_inspect.util.stage_log import TABLE_PROBE_SNIPPET as probe

    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_applycal (ms_modify).
Applies calibration to field: {field!r}
\"\"\"
from casatasks import applycal

{record}
{probe}
{pol}

applycal(
    vis={ms_str!r},
    field={field!r},
    gaintable={gaintable!r},
    gainfield={gainfield!r},
    interp={interp!r},
{spwmap_line}    calwt={calwt},
    applymode={applymode!r},
    parang={parang},
    flagbackup={flagbackup},
)
# applycal returns None, so completion has to be measured rather than read
# off a return value: the column it exists to populate is either there or not.
_corrected = "CORRECTED_DATA" in _table_colnames({ms_str!r})
# The polarisation tables are named by their VisCal type, never by filename.
_pol = _pol_types({gaintable!r})
_record_stage(
    {workdir!r},
    "applycal",
    {ms_str!r},
    {{"field": {field!r}, "corrected_data": _corrected, "parang": {parang}, "pol_types": _pol}},
)
if not _corrected:
    raise RuntimeError(
        "applycal returned but CORRECTED_DATA is not present on "
        + {ms_str!r}
        + " — the stage did not do what it exists to do."
    )
print("Done. CORRECTED_DATA populated for field: {field}")
"""


def run(
    ms_path: str,
    field: str,
    gaintable: list[str],
    workdir: str,
    gainfield: list[str] | None = None,
    interp: list[str] | None = None,
    spwmap: list[list[int]] | None = None,
    calwt: bool = False,
    applymode: str = "calflag",
    parang: bool = True,
    flagbackup: bool = True,
    execute: bool = False,
    debug: bool = False,
    debug_params: dict | None = None,
) -> dict:
    """
    Apply calibration tables to a field and write CORRECTED_DATA.

    Args:
        ms_path:    Path to the Measurement Set.
        field:      CASA field selection to apply calibration to.
        gaintable:  Ordered list of caltable paths to apply.
        workdir:    Existing directory; script is written here.
        gainfield:  Per-table field selection for which solutions to use.
                    Default: [''] * len(gaintable) (use all solutions in each table).
        interp:     Per-table interpolation mode. Use 'nearest' for calibrators,
                    'linear' for the target, 'nearest,nearestflag' for delay tables.
                    Default: ['linear'] * len(gaintable).
        spwmap:     Optional per-table SPW map (list-of-lists aligned to gaintable),
                    e.g. [[], [0,0,0,0], []] to fan an spw-combined table (entry 1)
                    across all SPWs while leaving per-SPW tables on identity. Default
                    None → CASA identity mapping (no change to per-SPW behaviour).
                    Only needed when a table was solved with combine='spw' (a VLA
                    multiband-delay choice); not telescope-general.
        calwt:      Calibrate the weights (default False — VLA weights are not
                    properly normalised; use statwt before imaging instead).
        applymode:  'calflag' (default) applies calibration and flags data whose
                    solutions are flagged, so uncalibrated data cannot reach
                    CORRECTED_DATA. 'calonly' leaves FLAG untouched and passes
                    such data through uncalibrated; use it only for interim
                    applies inside a flagging loop. 'calflagstrict' also flags
                    SpWs with no calibration in one or more tables (calflag
                    passes those through uncalibrated).
        parang:     Apply parallactic angle correction (default True).
        flagbackup: Save a flag backup before applying (default True; pass False
                    on subsequent per-field calls to the same MS when one backup
                    before the batch suffices).
        execute:    If False (default), write script and return.
                    If True, run applycal in-process.

    Returns:
        Standard response envelope with script_path always present.
        When execute=True, also includes corrected_written flag.
    """
    field = normalize_field_sel(field)
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []
    warnings.extend(describe_numeric_fields(ms_path, field))
    _validate_literal_fields(ms_path, ms_str, field)

    if gainfield is None:
        gainfield = [""] * len(gaintable)
    if interp is None:
        interp = ["linear"] * len(gaintable)

    if len(gainfield) != len(gaintable):
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"gainfield length ({len(gainfield)}) must match gaintable length ({len(gaintable)})",
            ms_path=ms_path,
        )

    if len(interp) != len(gaintable):
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"interp length ({len(interp)}) must match gaintable length ({len(gaintable)})",
            ms_path=ms_path,
        )

    if spwmap is not None and len(spwmap) != len(gaintable):
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"spwmap length ({len(spwmap)}) must match gaintable length ({len(gaintable)}). "
            "Pass a per-table list-of-lists, e.g. [[], [0,0,0,0], []].",
            ms_path=ms_path,
        )

    workdir_path = Path(workdir)
    if not workdir_path.exists():
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(
            f"workdir does not exist: {workdir}",
            ms_path=ms_path,
        )

    for gt in gaintable:
        if not Path(gt).exists():
            from ms_inspect.exceptions import ComputationError

            raise ComputationError(
                f"Caltable not found: {gt}",
                ms_path=ms_path,
            )

    warnings.extend(_collect_gainfield_warnings(ms_str, field, gaintable, gainfield))

    script = _script_path(workdir_path, field, ms_str)
    _debug = debug_mode.validate(debug, debug_params, DEBUG_TASKS)
    if _debug:
        warnings.append(debug_mode.note(_debug))
    write_script(
        script,
        _build_script(
            ms_str=ms_str,
            workdir=str(workdir_path),
            field=field,
            gaintable=gaintable,
            gainfield=gainfield,
            interp=interp,
            calwt=calwt,
            applymode=applymode,
            parang=parang,
            flagbackup=flagbackup,
            spwmap=spwmap,
        ),
    )
    debug_mode.inject_file(script, _debug)
    casa_calls.append(f"write_script → {script}")

    if not execute:
        warnings.append(
            f"Script written to {script}. Run it externally. "
            "Inspect CORRECTED_DATA on calibrators before applying to the target."
        )
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=ms_path,
            data={
                "script_path": fmt_field(str(script)),
                "corrected_written": fmt_field(
                    False, flag="UNAVAILABLE", note="script not yet executed"
                ),
                "field": field,
                "n_tables": len(gaintable),
                "applymode": applymode,
                "calwt": calwt,
                "parang": parang,
                "flagbackup": flagbackup,
            },
            warnings=warnings,
            casa_calls=casa_calls,
        )

    # execute=True
    try:
        from casatasks import applycal  # type: ignore[import]

        applycal = debug_mode.wrap("applycal", applycal, _debug)
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatasks is not installed or cannot be imported.",
            ms_path=ms_path,
        ) from None

    casa_calls.append(
        f"casatasks.applycal(field={field!r}, n_tables={len(gaintable)}, "
        f"applymode={applymode!r}) → CORRECTED_DATA"
    )

    try:
        applycal_kwargs: dict = dict(
            vis=ms_str,
            field=field,
            gaintable=gaintable,
            gainfield=gainfield,
            interp=interp,
            calwt=calwt,
            applymode=applymode,
            parang=parang,
            flagbackup=flagbackup,
        )
        if spwmap is not None:
            applycal_kwargs["spwmap"] = spwmap
        applycal(**applycal_kwargs)
    except Exception as e:
        raise ApplycalFailedError(
            f"applycal raised an exception: {e}\n"
            f"Command: applycal(vis={ms_str!r}, field={field!r}, "
            f"n_tables={len(gaintable)}, applymode={applymode!r})",
            ms_path=ms_path,
        ) from e

    # applycal returns None; a clean return proves only that it did not raise.
    # Measure the column instead of trusting the return.
    with open_table(ms_str) as tb:
        corrected_written = "CORRECTED_DATA" in set(tb.colnames())
    record_stage(
        str(workdir_path),
        "applycal",
        ms_str,
        {
            "field": field,
            "corrected_data": corrected_written,
            "parang": parang,
            "pol_types": pol_types(gaintable),
        },
    )
    if not corrected_written:
        raise ApplycalFailedError(
            f"applycal returned but CORRECTED_DATA is not present on {ms_str!r} — "
            "the stage did not do what it exists to do.",
            ms_path=ms_path,
        )

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data={
            "script_path": fmt_field(str(script)),
            "corrected_written": fmt_field(corrected_written),
            "field": field,
            "n_tables": len(gaintable),
            "applymode": applymode,
            "calwt": calwt,
            "parang": parang,
            "flagbackup": flagbackup,
        },
        warnings=warnings,
        casa_calls=casa_calls,
    )
