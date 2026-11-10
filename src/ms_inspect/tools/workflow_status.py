"""
tools/workflow_status.py — ms_workflow_status

Rolls up the state of an MS + workdir into a single next-step label.

The stage state comes from workdir/stage_log.jsonl, which the generated
scripts append to as they complete — not from a fixed list of caltable names,
since the caltable path is an argument to every writing tool and belongs to
the caller.

Two kinds of fact, kept apart on purpose:

- The stage log says which stages COMPLETED. It is history, written by the job
  that did the work. Nothing else can supply this — an MS on disk does not
  record which tool produced it.
- The MS probes (intents, CORRECTED_DATA) say what is TRUE NOW. A live read
  beats a log line if someone deleted a column after the fact.

A workdir with no stage log reads as nothing done. That is deliberate: the
system assumes the reduction is driven end to end by these tools. It does mean
a workdir created before the stage log existed cannot be resumed here.

With stokes='IQUV' the chain gains two steps between the target applycal and
the first image, by the same presence rule: 'polcal' until a cross-hand delay
(gaincal, gaintype KCROSS) and a leakage solve (polcal, poltype Df*) are
recorded, then 'applycal_pol_target' until an applycal on the target MS records
both kinds of table in pol_types. The solve kind comes from the keys the tools
record, never from a filename. The position-angle solve (Xf) is reported when
present but is not required.
"""

from __future__ import annotations

from pathlib import Path

from ms_inspect.util.casa_context import open_table
from ms_inspect.util.formatting import field, response_envelope
from ms_inspect.util.stage_log import STAGE_LOG_NAME, completed_stages, products_for, read_stage_log

TOOL_NAME = "ms_workflow_status"

#: Stage names as the writing tools record them.
_IMPORT = "import_asdm"
_INTENTS = "set_intents"
_PREFLAG = "preflag"
_PRIORCALS = "priorcals"
_INITIAL_BANDPASS = "initial_bandpass"
_INITIAL_RFLAG = "initial_rflag"
_APPLYCAL = "applycal"
_TCLEAN = "tclean"

#: Final-solve stages. The reduction has a delay, a bandpass and a gain when
#: all three have recorded a product — by stage, never by filename.
_FINAL_SOLVES = ("gaincal", "bandpass", "fluxscale")

#: Polarisation steps, by the kind each recorded line names.
_POL_KCROSS = "Kcross"
_POL_DTERMS = "Df"
_POL_XF = "Xf"
_POLCAL = "polcal"
_GAINCAL = "gaincal"


def _measurement(entry: dict) -> dict:
    m = entry.get("measurement")
    return m if isinstance(m, dict) else {}


def _pol_state(entries: list[dict], target: Path) -> tuple[list[str], bool, int]:
    """(pol solves completed, pol apply on the target recorded, lines without keys).

    A gaincal, polcal or applycal line written before these tools recorded the
    solve kind has no key to read. It does not count, and it is counted so the
    caller can say so.
    """
    solves: set[str] = set()
    applied = False
    unkeyed = 0
    for e in entries:
        if e.get("exists") is not True:
            continue
        stage, m = e.get("stage"), _measurement(e)
        if stage == _GAINCAL:
            if "gaintype" not in m:
                unkeyed += 1
            elif str(m["gaintype"]).upper() == "KCROSS":
                solves.add(_POL_KCROSS)
        elif stage == _POLCAL:
            poltype = str(m.get("poltype", ""))
            if "poltype" not in m:
                unkeyed += 1
            elif poltype.lower().startswith("df"):
                solves.add(_POL_DTERMS)
            elif poltype.upper().startswith("X"):
                solves.add(_POL_XF)
        elif stage == _APPLYCAL:
            if "pol_types" not in m:
                unkeyed += 1
                continue
            product = e.get("product")
            if not isinstance(product, str):
                continue
            if Path(product).expanduser().resolve() != target:
                continue
            kinds = [str(k).lower() for k in m.get("pol_types") or []]
            if any(k.startswith("kcross") for k in kinds) and any(
                k.startswith("df") for k in kinds
            ):
                applied = True
    order = (_POL_KCROSS, _POL_DTERMS, _POL_XF)
    return [k for k in order if k in solves], applied, unkeyed


def _probe_corrected(ms_str: str) -> tuple[bool | None, str | None]:
    """Is CORRECTED_DATA present. None (with a reason) if the probe failed.

    The MAIN table always exists on a valid MS, so an exception here is a real
    read failure — a lock, a permission, a half-written table — and must not be
    reported as an absent column.
    """
    try:
        with open_table(ms_str) as tb:
            return "CORRECTED_DATA" in set(tb.colnames()), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def run(ms_path: str, workdir: str, stokes: str = "I") -> dict:
    # 1. MS valid.
    #
    # Probed, not validated — an absent path is the import_asdm stage, not an
    # error. Every tool that operates ON an MS still validates.
    p = Path(ms_path).expanduser().resolve()
    ms_str = str(p)
    wd = Path(workdir)
    casa_calls: list[str] = []
    warnings: list[str] = []
    if stokes not in ("I", "IQUV"):
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(f"stokes must be 'I' or 'IQUV', not {stokes!r}", ms_path=ms_path)
    pol = stokes == "IQUV"

    ms_valid = (p / "table.info").exists()
    if not ms_valid:
        warnings.append(
            f"'{p}' is not a Measurement Set"
            f" ({'path does not exist' if not p.exists() else 'no table.info'});"
            " reporting the import stage rather than the MS state."
        )

    # ---------------------------------------------------------------- history
    entries = read_stage_log(wd)
    done = completed_stages(entries)
    if not entries:
        warnings.append(
            f"No {STAGE_LOG_NAME} in {wd}. Every stage reads as not yet run."
            " A workdir written before the stage log existed cannot be resumed here."
        )

    # ------------------------------------------------------------- live state
    #
    # Calibration runs on calibrators.ms; the target applycal writes CORRECTED
    # to the MS this tool was given. Both are reported, never merged — they
    # answer different questions.
    calibrators_ms = wd / "calibrators.ms"
    calibrators_ms_present = calibrators_ms.exists() and (calibrators_ms / "table.info").exists()

    corrected_target: bool | None = False
    corrected_target_error: str | None = None
    if ms_valid:
        corrected_target, corrected_target_error = _probe_corrected(ms_str)
        casa_calls.append("tb.open(MAIN) for colnames — target MS")

    corrected_calibrators: bool | None = False
    corrected_calibrators_error: str | None = None
    if calibrators_ms_present:
        corrected_calibrators, corrected_calibrators_error = _probe_corrected(str(calibrators_ms))
        casa_calls.append("tb.open(MAIN) for colnames — calibrators.ms")

    # An absent STATE subtable legitimately means set_intents has not run. A
    # STATE that exists but cannot be read means the PROBE failed, and must not
    # be reported as "not populated" — that would drive the recommendation to
    # re-run set_intents over data that may already have intents.
    intents_populated: bool | None = False
    intents_error: str | None = None
    if (p / "STATE").exists():
        try:
            with open_table(ms_str + "/STATE") as tb:
                casa_calls.append("tb.open(STATE)")
                intents_populated = tb.nrows() > 0
        except Exception as exc:
            intents_populated = None
            intents_error = f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------- derivation
    #
    # A failed probe stops the derivation there rather than falling through:
    # below a failed probe every later answer would be inferred from an unknown.
    final_solves_done = [s for s in _FINAL_SOLVES if s in done]
    pol_solves_done, pol_applied_target, unkeyed = _pol_state(entries, p)
    pol_solved = _POL_KCROSS in pol_solves_done and _POL_DTERMS in pol_solves_done

    if _IMPORT not in done and not ms_valid:
        next_step = _IMPORT
    elif intents_populated is None:
        next_step = "probe_failed_intents"
    elif _INTENTS not in done and not intents_populated:
        next_step = _INTENTS
    elif _PREFLAG not in done:
        next_step = "apply_preflag"
    elif _PRIORCALS not in done:
        next_step = "generate_priorcals"
    elif _INITIAL_BANDPASS not in done:
        next_step = _INITIAL_BANDPASS
    elif corrected_calibrators is None:
        next_step = "probe_failed_corrected_calibrators"
    elif _INITIAL_RFLAG not in done or not corrected_calibrators:
        next_step = "apply_initial_rflag_then_applycal"
    elif len(final_solves_done) < len(_FINAL_SOLVES):
        next_step = "delay_bandpass_gain"
    elif corrected_target is None:
        next_step = "probe_failed_corrected_target"
    elif _APPLYCAL not in done or not corrected_target:
        next_step = "applycal_target"
    elif pol and not pol_solved:
        next_step = "polcal"
    elif pol and not pol_applied_target:
        next_step = "applycal_pol_target"
    elif _TCLEAN not in done:
        next_step = "first_image"
    else:
        next_step = "selfcal_or_done"

    if intents_error is not None:
        warnings.append(f"STATE subtable exists but could not be read: {intents_error}")
    if corrected_target_error is not None:
        warnings.append(f"Target MS MAIN table could not be read: {corrected_target_error}")
    if corrected_calibrators_error is not None:
        warnings.append(
            f"calibrators.ms MAIN table could not be read: {corrected_calibrators_error}"
        )

    if pol and unkeyed:
        warnings.append(
            f"{unkeyed} gaincal/polcal/applycal line(s) in {STAGE_LOG_NAME} do not record"
            " the solve kind (gaintype, poltype, pol_types). They were written by an older"
            " tool and do not count toward the polarisation steps."
        )

    # The log is history and the MS is now. Where they disagree, say so rather
    # than pick a winner: a stage recorded complete whose product no longer
    # shows in the MS is a real event the next reader needs to see.
    if _APPLYCAL in done and corrected_target is False:
        warnings.append(
            "applycal is recorded complete in the stage log, but CORRECTED_DATA is not"
            f" present on {ms_str}. The log is history; the MS is current state."
        )

    data = {
        "ms_valid": field(ms_valid),
        "stage_log_present": field(bool(entries)),
        "stages_completed": sorted(done),
        "products_recorded": {stage: products_for(entries, stage) for stage in sorted(done)},
        "intents_populated": (
            field(None, "UNAVAILABLE", note=f"STATE read failed: {intents_error}")
            if intents_populated is None
            else field(intents_populated)
        ),
        "calibrators_ms_present": field(calibrators_ms_present),
        "corrected_populated_target": (
            field(None, "UNAVAILABLE", note=f"MAIN colnames read failed: {corrected_target_error}")
            if corrected_target is None
            else field(corrected_target)
        ),
        "corrected_populated_calibrators": (
            field(
                None,
                "UNAVAILABLE",
                note=f"MAIN colnames read failed: {corrected_calibrators_error}",
            )
            if corrected_calibrators is None
            else field(corrected_calibrators)
        ),
        "final_solves_completed": final_solves_done,
        "stokes": stokes,
        "workdir": str(wd),
        "next_recommended_step": next_step,
    }
    if pol:
        data["polcal_solves_completed"] = pol_solves_done
        data["pol_applied_target"] = field(pol_applied_target)
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
