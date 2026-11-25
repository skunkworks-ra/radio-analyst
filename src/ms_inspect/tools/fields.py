"""
tools/fields.py — ms_field_list

Layer 1, Tool 2: What are the observed fields, their sky positions,
and their calibration roles?

CASA access: msmd.fieldnames(), msmd.phasecenter(), msmd.intentsforfield()
Falls back to calibrator catalogue matching when intents are absent.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

from ms_inspect.util.array_config import (
    array_baselines,
    config_from_array,
    config_from_execblock,
    config_letters,
)
from ms_inspect.util.calibrators import (
    CalibratorEntry,
    infer_intents_from_role,
    resolve_flux_standard,
    role_from_intents,
    roles_disagree,
)
from ms_inspect.util.calibrators import lookup as cal_lookup
from ms_inspect.util.casa_context import open_msmd, open_table, validate_ms_path
from ms_inspect.util.conversions import (
    baseline_length_klambda,
    mjd_seconds_to_utc,
    projected_uv_m,
    rad_to_deg,
    rad_to_dms,
    rad_to_hms,
)
from ms_inspect.util.formatting import (
    _collect_flags,
    field,
    resolve_sidecar_path,
    response_envelope,
)
from ms_inspect.util.frequencies import field_frequencies
from ms_inspect.util.phase_cal_catalog import (
    EXACT_ARCSEC,
    IDENTITY_ARCSEC,
    callist_band_code,
    expected_flux,
    get_source,
)
from ms_inspect.util.phase_cal_catalog import cone_search as vla_cone_search
from ms_inspect.util.pol_calibrators import lookup_pol
from ms_inspect.util.telescope import TelescopeProfile, resolve_telescope

# CASA gaincal and bandpass default: an antenna with fewer baselines than this
# gets no solution.
_MINBLPERANT = 4

# A calibrator with a list uvrange is usable only if at least this percent of
# the antennas with data keep _MINBLPERANT baselines inside it at every sample
# time. An integer percent keeps the boundary exact.
_MIN_ANTENNA_PERCENT = 70

TOOL_NAME = "ms_field_list"

# Coverage below this raises a warning, and enables the whole-MS scan-pattern
# inference. It does NOT decide any field's role — that is per field, from that
# field's own intents. The response reports the raw fraction and its inputs, so
# the skill can apply its own threshold.
_INTENT_COVERAGE_THRESHOLD = 0.50

# Coordinates suspiciously close to (0, 0) — almost certainly a broken export.
# True (0, 0) on sky is on the meridian at the equator, essentially never a target.
_COORD_SUSPECT_THRESHOLD_DEG = 1.0 / 60.0  # 1 arcminute


def run(ms_path: str, workdir: str | None = None) -> dict:
    """
    Return the list of all observed fields with positions, intents, and
    calibrator role identification.
    """
    p = validate_ms_path(ms_path)
    casa_calls: list[str] = []
    warnings: list[str] = []
    # Read only when a field falls back to the VLA calibrator list.
    telescope_read = False
    telescope: TelescopeProfile | None = None

    with open_msmd(str(p)) as msmd:
        casa_calls.append("msmd.open()")

        # Field names
        field_names: list[str] = list(msmd.fieldnames())
        casa_calls.append("msmd.fieldnames()")
        n_fields = len(field_names)

        if n_fields == 0:
            warnings.append("No fields found in MS.")
            return response_envelope(
                tool_name=TOOL_NAME,
                ms_path=ms_path,
                data={"fields": [], "mosaic_groups": [], "n_fields": 0},
                warnings=warnings,
                casa_calls=casa_calls,
            )

        # Phase centres — returns a dict with 'm0' (RA) and 'm1' (Dec) in radians
        phase_centers: list[dict] = []
        for fid in range(n_fields):
            try:
                pc = msmd.phasecenter(fid)
                phase_centers.append(pc)
            except Exception:
                phase_centers.append({})
        casa_calls.append("msmd.phasecenter(field_id) for each field")

        # Intents per field
        raw_intents: list[set[str]] = []
        for fid in range(n_fields):
            try:
                intents = set(msmd.intentsforfield(fid))
            except Exception:
                intents = set()
            raw_intents.append(intents)
        casa_calls.append("msmd.intentsforfield(field_id) for each field")

        # Source IDs (for mosaic grouping)
        try:
            source_ids: list[int] = list(msmd.sourceidforfield(list(range(n_fields))))
        except Exception:
            source_ids = list(range(n_fields))

        # Scan sequence for pattern-based role inference and per-field schedule
        # evidence. The same scan times give each field's sample times
        # (start, middle and end of each scan) for projected baselines.
        scan_sequence: list[tuple[int, int, float]] = []  # (scan_num, field_id, duration_s)
        field_scans: dict[int, list[tuple[int, float]]] = {}  # fid -> [(scan_num, duration_s)]
        all_scan_numbers: list[int] = []
        field_times: dict[int, list[float]] = {}
        try:
            for snum in sorted(msmd.scannumbers()):
                snum_int = int(snum)
                fids = list(msmd.fieldsforscan(snum))
                if not fids:
                    continue
                times = msmd.timesforscans([snum])
                t0, t1 = float(min(times)), float(max(times))
                dur = t1 - t0 if len(times) > 1 else 0.0
                all_scan_numbers.append(snum_int)
                scan_sequence.append((snum_int, int(fids[0]), dur))
                for f in fids:
                    fi = int(f)
                    field_scans.setdefault(fi, []).append((snum_int, dur))
                    field_times.setdefault(fi, []).extend([t0, 0.5 * (t0 + t1), t1])
            casa_calls.append("msmd.scannumbers/fieldsforscan/timesforscans (scan pattern)")
        except Exception:
            scan_sequence = []
            field_scans = {}
            all_scan_numbers = []
            field_times = {}

        # Observing frequency per field. This tool was field-only until now; the
        # read is here because frequency is what decides whether a flux standard
        # applies to a source (see design_docs/FLUX_STANDARD_DESIGN.md §2.2), and
        # is per FIELD — a field is only observed in the SpWs it was observed in.
        field_freqs = field_frequencies(msmd, n_fields)
        casa_calls.append("msmd.spwsforfield(field_id) + msmd.chanfreqs(spw) for each field")

        # Baselines with data, for the UV-limit check on calibrators that
        # take their limits from the VLA calibrator list.
        array = array_baselines(msmd)
        casa_calls.append("msmd.antennanames() + msmd.antennaposition(ant) + msmd.baselines()")

    # Array configuration, for calibrators whose callist grade differs by
    # configuration with no UV limit to explain it.
    array_config = config_from_execblock(p) or config_from_array(array)

    # ------------------------------------------------------------------
    # Determine if we're in intent-inference mode
    # ------------------------------------------------------------------
    n_with_intents = sum(1 for s in raw_intents if s)
    intent_fraction = n_with_intents / n_fields if n_fields > 0 else 0.0
    heuristic_mode = intent_fraction < _INTENT_COVERAGE_THRESHOLD

    if heuristic_mode:
        warnings.append(
            f"Only {n_with_intents}/{n_fields} fields have scan intent metadata "
            f"({intent_fraction * 100:.0f}% coverage, threshold {_INTENT_COVERAGE_THRESHOLD * 100:.0f}%). "
            "Roles are still resolved per field: a field WITH intents uses them. "
            "Fields without intents fall back to the calibrator catalogue and are "
            "tagged INFERRED — check those individually rather than trusting this "
            "MS-wide figure."
        )

    # ------------------------------------------------------------------
    # Build field records
    # ------------------------------------------------------------------
    fields_out: list[dict] = []

    for fid in range(n_fields):
        name = field_names[fid]
        pc = phase_centers[fid]
        intents = raw_intents[fid]

        # --- Coordinates ---
        ra_rad, dec_rad, coord_flag, coord_note = _extract_coords(pc, name, fid)

        ra_deg = rad_to_deg(ra_rad) if ra_rad is not None else None
        dec_deg = rad_to_deg(dec_rad) if dec_rad is not None else None
        ra_hms = rad_to_hms(ra_rad) if ra_rad is not None else None
        dec_dms = rad_to_dms(dec_rad) if dec_rad is not None else None

        # --- Calibrator catalogue match ---
        cal_entry = cal_lookup(name)
        if cal_entry:
            cal_match = field(
                cal_entry.canonical_name,
                flag="COMPLETE",
                note=f"Matched '{name}' to catalogue entry '{cal_entry.canonical_name}'",
            )
            catalogue_role = field(
                cal_entry.role,
                flag="COMPLETE",
                note=(
                    f"What the catalogue lists {cal_entry.canonical_name} as suitable for. "
                    "A cross-check against the intents, not the answer."
                ),
            )
            cal_resolved = field(cal_entry.resolved, flag="COMPLETE")
            if cal_entry.notes:
                warnings.append(f"[{name}] {cal_entry.notes}")
        else:
            cal_match = field(None, flag="UNAVAILABLE", note="Not in bundled calibrator catalogue")
            catalogue_role = field(None, flag="UNAVAILABLE")
            cal_resolved = None  # filled from the VLA calibrator list below

        # --- Role resolution: this field's own intents decide ---
        #
        # Per FIELD, deliberately. The old code gated the catalogue fallback on
        # a whole-MS coverage threshold, so one field missing its intents inside
        # a well-populated MS got no role at all, even where the catalogue could
        # have answered for it. Coverage is a property of the MS; having intents
        # is a property of the field.
        intent_roles = role_from_intents(intents) if intents else []
        catalogue_roles = cal_entry.role if cal_entry else []

        if intent_roles:
            role_out = field(
                intent_roles,
                flag="COMPLETE",
                note="Derived from this field's scan intents.",
            )
        elif catalogue_roles:
            role_out = field(
                catalogue_roles,
                flag="INFERRED",
                note=(
                    "No intents name a role for this field. This is what the catalogue "
                    f"lists {cal_entry.canonical_name} as suitable for — not evidence of "
                    "how this observation used it."
                ),
            )
        else:
            role_out = field(
                None,
                flag="UNAVAILABLE",
                note="No scan intents name a role, and the field is not in the catalogue.",
            )

        if roles_disagree(intent_roles, catalogue_roles):
            warnings.append(
                f"[{name}] Intents and catalogue DISAGREE about this field's role. "
                f"The MS's scan intents say {intent_roles}; the catalogue lists "
                f"{cal_entry.canonical_name} as {catalogue_roles}. "
                "The intents win — they describe this observation, while the catalogue "
                "describes the source. Verify before calibrating."
            )

        # --- VLA calibrator positional cross-match ---
        vla_cal_match_field = _vla_positional_match(ra_deg, dec_deg, cal_entry)

        # --- Intents ---
        # Also per field. The catalogue fallback used to require heuristic_mode,
        # which meant a lone field missing its intents was never offered it.
        if intents:
            intent_field = field(sorted(intents), flag="COMPLETE")
        elif cal_entry:
            inferred = infer_intents_from_role(cal_entry.role)
            intent_field = field(
                inferred,
                flag="INFERRED",
                note=f"Inferred from calibrator catalogue role: {cal_entry.role}",
            )
        else:
            intent_field = field(
                [],
                flag="UNAVAILABLE",
                note="No intents recorded for this field and no catalogue match for inference",
            )

        # --- Observing frequency ---
        fq = field_freqs[fid] if fid < len(field_freqs) else None
        if fq and fq["min_ghz"] is not None:
            fq_note = f"Span of the {fq['n_spw']} spectral window(s) this field was observed in"
            if fq["excluded_spw"]:
                fq_note += f"; {fq['excluded_spw']} WVR/square-law window(s) excluded"
            freq_out = field(
                {
                    "min_ghz": round(fq["min_ghz"], 6),
                    "max_ghz": round(fq["max_ghz"], 6),
                    "centre_ghz": round(fq["centre_ghz"], 6),
                    "n_spw": fq["n_spw"],
                },
                flag="COMPLETE",
                note=fq_note,
            )
        else:
            freq_out = field(
                None,
                flag="UNAVAILABLE",
                note="No readable spectral window for this field",
            )

        if not telescope_read and vla_cal_match_field["value"] is not None:
            telescope_read = True
            casa_calls.append("tb.open(OBSERVATION).getcol('TELESCOPE_NAME')")
            try:
                telescope = resolve_telescope(str(p))
            except Exception:
                telescope = None

        # --- Resolved status when the bundled catalogue has no entry ---
        if cal_resolved is None:
            track = (
                (ra_rad, dec_rad, field_times[fid])
                if ra_rad is not None and dec_rad is not None and field_times.get(fid)
                else None
            )
            cal_resolved, resolved_warning = _resolved_from_callist(
                vla_cal_match_field, fq, telescope, array, array_config, track
            )
            target_only = set(role_out["value"] or []) == {"target"}
            if resolved_warning and not target_only:
                warnings.append(f"[{name}] {resolved_warning}")

        # --- Flux standard: resolved from THIS field's frequency ---
        #
        # Deliberately after the frequency read, and deliberately not a
        # catalogue echo. The catalogue says which standard describes the
        # SOURCE; whether it describes this OBSERVATION depends on the band the
        # field was observed in. Reporting 'Perley-Butler 2017' COMPLETE on a
        # 230 GHz field was the defect this replaces.
        #
        # resolve_flux_standard lives in calibrators.py because ms_setjy calls
        # the same function. Two copies could disagree, and the tool that acts
        # would be the one that is wrong.
        std = resolve_flux_standard(
            cal_entry,
            fq["min_ghz"] if fq else None,
            fq["max_ghz"] if fq else None,
        )
        cal_standard = field(std.standard, flag=std.flag, note=std.note)

        # Warn only where the operator must do something: pick a different
        # standard, or supply a flux by hand. A constant-brightness-temperature
        # body and an unread frequency carry notes instead — the first is a
        # CASA modelling choice, not a metadata problem, and warning on either
        # would fire on every ALMA dataset.
        if std.needs_manual_flux:
            warnings.append(
                f"[{name}] CASA has no flux standard for this source. It needs an "
                "explicit manual flux density; do not substitute another standard."
            )
        elif std.flag == "UNAVAILABLE" and cal_entry is not None:
            warnings.append(f"[{name}] {std.note}")

        pol_cal_field = _pol_calibrator_field(name)
        sched = _field_schedule_summary(field_scans.get(fid, []), all_scan_numbers)
        role_note = _catalogue_role_note(cal_entry, pol_cal_field)

        record = {
            "field_id": fid,
            "name": name,
            "source_id": source_ids[fid] if fid < len(source_ids) else fid,
            "n_scans": sched["n_scans"],
            "total_on_source_s": sched["total_on_source_s"],
            "scan_schedule": sched["scan_schedule"],
            "ra_j2000_deg": field(
                round(ra_deg, 6) if ra_deg is not None else None, flag=coord_flag, note=coord_note
            ),
            "dec_j2000_deg": field(
                round(dec_deg, 6) if dec_deg is not None else None, flag=coord_flag, note=coord_note
            ),
            "ra_hms": ra_hms,
            "dec_dms": dec_dms,
            "intents": intent_field,
            "observing_frequency": freq_out,
            "calibrator_match": cal_match,
            # field_role, not calibrator_role: the vocabulary includes 'target',
            # which is not a kind of calibrator.
            "field_role": role_out,
            "catalogue_role": catalogue_role,
            "catalogue_role_note": role_note,
            "flux_standard": cal_standard,
            # Whether the frequency gate actually RAN, not whether it passed.
            # flux_standard COMPLETE means both "checked and inside the range"
            # and "constant brightness temperature, no range exists to check".
            # Those are different amounts of evidence and the flag cannot
            # separate them.
            "flux_standard_range_checked": std.range_checked,
            "resolved_source": cal_resolved,
            "vla_cal_match": vla_cal_match_field,
            "vla_cal_flux_estimate": _vla_flux_estimate(vla_cal_match_field, fq, telescope),
            "pol_calibrator": pol_cal_field,
        }
        fields_out.append(record)

    # ------------------------------------------------------------------
    # VLA calibrator-list role inference for fields with no intents
    # ------------------------------------------------------------------
    # A field with no intents and no calibrator-catalogue entry that matches the
    # VLA calibrator list is a phase calibrator, however many scans it has.
    scans_per_field = Counter(fid for _, fid, _ in scan_sequence)
    for rec in fields_out:
        intent_f = rec.get("intents", {})
        vla_f = rec.get("vla_cal_match", {})
        n_scans = scans_per_field[rec["field_id"]]
        if (
            isinstance(intent_f, dict)
            and intent_f.get("flag") == "UNAVAILABLE"
            and isinstance(vla_f, dict)
            and vla_f.get("value")
        ):
            note = (
                "No intents and not in the calibrator catalogue. Matches VLA calibrator "
                f"list entry {vla_f['value'].get('name')} and is observed in {n_scans} "
                f"scan{'' if n_scans == 1 else 's'}."
            )
            rec["intents"] = field(infer_intents_from_role(["phase"]), flag="INFERRED", note=note)
            rec["field_role"] = field(["phase"], flag="INFERRED", note=note)

    # ------------------------------------------------------------------
    # Scan-pattern role inference for UNAVAILABLE fields (heuristic mode only)
    # ------------------------------------------------------------------
    if heuristic_mode and scan_sequence:
        # Build per-field coord lookup (ra_deg, dec_deg)
        coords: dict[int, tuple[float | None, float | None]] = {}
        for rec in fields_out:
            fid = rec["field_id"]
            ra_f = rec.get("ra_j2000_deg", {})
            dec_f = rec.get("dec_j2000_deg", {})
            coords[fid] = (
                ra_f.get("value") if isinstance(ra_f, dict) else ra_f,
                dec_f.get("value") if isinstance(dec_f, dict) else dec_f,
            )

        inferred = _infer_roles_from_scan_pattern(scan_sequence, coords)

        for rec in fields_out:
            fid = rec["field_id"]
            intent_f = rec.get("intents", {})
            if (
                isinstance(intent_f, dict)
                and intent_f.get("flag") == "UNAVAILABLE"
                and fid in inferred
            ):
                roles, reason = inferred[fid]
                rec["intents"] = field(
                    infer_intents_from_role(roles),
                    flag="INFERRED",
                    note=f"Scan-pattern inference: {reason}",
                )

    # ------------------------------------------------------------------
    # nearest_phase_cal enrichment for target fields
    # ------------------------------------------------------------------
    # Classify fields into phase_cals and targets. A polarisation calibrator is
    # its own phase calibrator, so it is never a target's nearest phase cal.
    phase_cal_records = []
    pol_cals_excluded = []
    for rec in fields_out:
        if rec["pol_calibrator"]["value"] is not None:
            pol_cals_excluded.append(rec["name"])
            continue
        role_field = rec.get("field_role", {})
        role_val = role_field.get("value") if isinstance(role_field, dict) else role_field
        intents_field = rec.get("intents", {})
        intents_val = (
            intents_field.get("value") if isinstance(intents_field, dict) else intents_field
        )
        intents_val = intents_val or []
        is_phase = (
            (isinstance(role_val, list) and "phase" in role_val)
            or (isinstance(role_val, str) and "phase" in role_val)
            or any("PHASE" in str(i).upper() for i in intents_val)
        )
        if is_phase:
            ra_f = rec.get("ra_j2000_deg", {})
            dec_f = rec.get("dec_j2000_deg", {})
            ra = ra_f.get("value") if isinstance(ra_f, dict) else ra_f
            dec = dec_f.get("value") if isinstance(dec_f, dict) else dec_f
            phase_cal_records.append({"name": rec["name"], "ra": ra, "dec": dec})

    if pol_cals_excluded:
        warnings.append(
            "Polarisation calibrators left out of the nearest_phase_cal pool (each is its "
            f"own phase calibrator): {', '.join(pol_cals_excluded)}"
        )
    for rec in fields_out:
        role_field = rec.get("field_role", {})
        role_val = role_field.get("value") if isinstance(role_field, dict) else role_field
        intents_field = rec.get("intents", {})
        intents_val = (
            intents_field.get("value") if isinstance(intents_field, dict) else intents_field
        )
        intents_val = intents_val or []
        is_target = (
            role_val is None
            or (isinstance(role_val, list) and not role_val)
            or any("TARGET" in str(i).upper() for i in intents_val)
        )
        if not is_target:
            continue
        ra_f = rec.get("ra_j2000_deg", {})
        dec_f = rec.get("dec_j2000_deg", {})
        tgt_ra = ra_f.get("value") if isinstance(ra_f, dict) else ra_f
        tgt_dec = dec_f.get("value") if isinstance(dec_f, dict) else dec_f
        if not phase_cal_records:
            rec["nearest_phase_cal"] = None
            rec["separation_deg"] = None
            if "no phase calibrator found" not in " ".join(warnings):
                warnings.append("no phase calibrator found — cannot compute separation")
        elif tgt_ra is None or tgt_dec is None:
            rec["nearest_phase_cal"] = None
            rec["separation_deg"] = None
        else:
            best_name = None
            best_sep = float("inf")
            for pc in phase_cal_records:
                if pc["ra"] is None or pc["dec"] is None:
                    continue
                sep = _angular_sep_deg(tgt_ra, tgt_dec, pc["ra"], pc["dec"])
                if sep < best_sep:
                    best_sep = sep
                    best_name = pc["name"]
            rec["nearest_phase_cal"] = best_name
            rec["separation_deg"] = round(best_sep, 2) if best_name is not None else None

    # ------------------------------------------------------------------
    # Mosaic detection and deduplication
    # ------------------------------------------------------------------
    min_dish_diam_m = _min_dish_diameter_m(p)
    if min_dish_diam_m is not None:
        casa_calls.append("tb.open(ANTENNA) -> DISH_DIAMETER")
    pre_slim_flags = _collect_flags({"fields": fields_out})
    mosaic_groups_list = _detect_mosaic_groups(
        fields_out,
        source_ids[:n_fields],
        scans_per_field,
        min_dish_diam_m=min_dish_diam_m,
    )

    detail_path_field = None
    has_large_mosaic = any(g["n_pointings"] >= 3 for g in mosaic_groups_list)
    if has_large_mosaic:
        sidecar_path = resolve_sidecar_path(f"{Path(p).name}.field_list.json", workdir)
        if sidecar_path:
            try:
                with open(sidecar_path, "w") as fh:
                    json.dump({"fields": fields_out}, fh, separators=(",", ":"), default=str)
                detail_path_field = field(sidecar_path)
            except OSError as exc:
                detail_path_field = field(
                    None,
                    flag="UNAVAILABLE",
                    note=f"Could not write full field list sidecar to {sidecar_path}: {exc}",
                )

    for grp in mosaic_groups_list:
        fids = grp["field_ids"]
        warnings.append(
            f"Mosaic '{grp['group_name']}': {grp['n_pointings']} pointings -- fields {fids}"
        )
        if grp["n_pointings"] >= 3:
            gname = grp["group_name"]
            for fid in fids:
                orig = fields_out[fid]
                fields_out[fid] = {
                    "field_id": orig["field_id"],
                    "name": orig["name"],
                    "source_id": orig["source_id"],
                    "mosaic_group": gname,
                    "n_scans": orig["n_scans"],
                    "total_on_source_s": orig["total_on_source_s"],
                    "ra_j2000_deg": orig["ra_j2000_deg"],
                    "dec_j2000_deg": orig["dec_j2000_deg"],
                    "intents": orig["intents"],
                    "field_role": orig["field_role"],
                    "nearest_phase_cal": orig.get("nearest_phase_cal"),
                    "separation_deg": orig.get("separation_deg"),
                }

    data: dict = {
        "n_fields": n_fields,
        # A measurement, not a verdict. This used to be a boolean
        # `heuristic_intents`, set from the threshold below -- but once role
        # resolution became per field, that boolean no longer described any
        # field's role, and it was wrong in both directions: true while a field
        # with intents used them, false while a field without intents fell back
        # to the catalogue. The per-field `field_role` flag is the answer; this
        # is the coverage statistic, with its inputs, for the skill to threshold
        # as it sees fit.
        "n_fields_with_intents": n_with_intents,
        "intent_coverage_fraction": round(intent_fraction, 4),
        "mosaic_groups": mosaic_groups_list,
        "fields": fields_out,
    }
    if detail_path_field is not None:
        data["detail_path"] = detail_path_field

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
        extra_flags=pre_slim_flags,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOSAIC_MAX_SPAN_DEG = 5.0
_MOSAIC_MAX_STEP_DEG = 2.0
_C_LIGHT_M_S = 299_792_458.0
_PB_FWHM_FACTOR = 1.15


def _min_dish_diameter_m(ms_path: Path | str) -> float | None:
    """Return minimum active positive DISH_DIAMETER (metres) from ANTENNA subtable.

    Ignores flagged ANTENNA rows when at least 2 unflagged positive diameters remain;
    returns None if the ANTENNA subtable or positive diameters are unavailable.
    """
    try:
        with open_table(f"{ms_path}/ANTENNA") as tb:
            diams = np.asarray(tb.getcol("DISH_DIAMETER"), dtype=float)
            if diams.size == 0:
                return None
            try:
                flag_row = np.asarray(tb.getcol("FLAG_ROW"), dtype=bool)
            except Exception:
                flag_row = np.zeros(diams.shape, dtype=bool)
    except Exception:
        return None

    pos_mask = np.isfinite(diams) & (diams > 0.0)
    if flag_row.shape == diams.shape:
        active_pos = diams[(~flag_row) & pos_mask]
        if active_pos.size >= 2:
            return float(np.min(active_pos))
    all_pos = diams[pos_mask]
    return float(np.min(all_pos)) if all_pos.size > 0 else None


def _pb_fwhm_deg(
    fids: list[int],
    fields_out: list[dict],
    min_dish_diam_m: float | None,
) -> float | None:
    """Compute primary-beam FWHM in degrees at the lowest observing frequency among fids."""
    if min_dish_diam_m is None or min_dish_diam_m <= 0.0:
        return None
    min_ghzs: list[float] = []
    for fid in fids:
        if fid >= len(fields_out):
            continue
        fq_field = fields_out[fid].get("observing_frequency")
        fq_val = fq_field.get("value") if isinstance(fq_field, dict) else fq_field
        if isinstance(fq_val, dict):
            min_ghz = fq_val.get("min_ghz")
            if isinstance(min_ghz, (int, float)) and math.isfinite(min_ghz) and min_ghz > 0.0:
                min_ghzs.append(float(min_ghz))
    if not min_ghzs:
        return None
    nu_min_hz = min(min_ghzs) * 1e9
    return math.degrees(_PB_FWHM_FACTOR * (_C_LIGHT_M_S / nu_min_hz) / min_dish_diam_m)


def _format_j2000(ra_deg: float, dec_deg: float) -> str:
    """Format (ra_deg, dec_deg) as a CASA J2000 direction string ('J2000 HHhMMmSS.SSs ±DDdMMmSS.Ss')."""
    ra_norm = ra_deg % 360.0
    ra_total_sec = round((ra_norm / 15.0) * 3600.0, 2)
    if ra_total_sec >= 86400.0:
        ra_total_sec -= 86400.0
    ra_h = int(ra_total_sec // 3600)
    ra_rem = ra_total_sec - ra_h * 3600
    ra_m = int(ra_rem // 60)
    ra_s = ra_rem - ra_m * 60

    sign = "+" if dec_deg >= 0.0 else "-"
    dec_total_arcsec = round(abs(dec_deg) * 3600.0, 1)
    dec_d = int(dec_total_arcsec // 3600)
    dec_rem = dec_total_arcsec - dec_d * 3600
    dec_m = int(dec_rem // 60)
    dec_s = dec_rem - dec_m * 60
    return f"J2000 {ra_h:02d}h{ra_m:02d}m{ra_s:05.2f}s {sign}{dec_d:02d}d{dec_m:02d}m{dec_s:04.1f}s"


def _split_sky_components(
    fids: list[int],
    fields_out: list[dict],
    max_step_deg: float = _MOSAIC_MAX_STEP_DEG,
) -> list[list[int]]:
    """Partition candidate field IDs into single-linkage sky-proximity components.

    Two fields are connected when their spherical angular separation is <= max_step_deg.
    If no candidate field has valid coordinates, returns [list(fids)] unchanged.
    Fields without coordinates when other fields have coordinates are not merged into
    sky components (returned as singletons).
    """
    coords: dict[int, tuple[float, float]] = {}
    coordless: list[int] = []
    for fid in fids:
        ra = fields_out[fid]["ra_j2000_deg"]["value"]
        dec = fields_out[fid]["dec_j2000_deg"]["value"]
        if ra is not None and dec is not None:
            coords[fid] = (float(ra), float(dec))
        else:
            coordless.append(fid)

    if not coords:
        return [list(fids)]

    valid_fids = [fid for fid in fids if fid in coords]
    visited: set[int] = set()
    components: list[list[int]] = []
    for start in valid_fids:
        if start in visited:
            continue
        comp: list[int] = []
        stack = [start]
        visited.add(start)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            ra_c, dec_c = coords[cur]
            for nxt in valid_fids:
                if nxt in visited:
                    continue
                ra_n, dec_n = coords[nxt]
                if _angular_sep_deg(ra_c, dec_c, ra_n, dec_n) <= max_step_deg:
                    visited.add(nxt)
                    stack.append(nxt)
        # Preserve original ordering of fids within each component.
        order = {fid: idx for idx, fid in enumerate(fids)}
        comp.sort(key=lambda fid: order[fid])
        components.append(comp)

    for fid in coordless:
        components.append([fid])
    return components


def _is_mosaic_candidate(rec: dict) -> bool:
    """True when a field is an unassigned or target-only non-calibrator field."""
    if rec["calibrator_match"]["value"] is not None:
        return False
    if rec["vla_cal_match"]["value"] is not None:
        return False
    if rec["pol_calibrator"]["value"] is not None:
        return False
    role_val = rec["field_role"]["value"]
    return role_val is None or (isinstance(role_val, list) and set(role_val) <= {"target"})


def _mosaic_stem(name: str) -> str | None:
    """Extract base target name from a mosaic pointing label (e.g. '3C391 C1' -> '3C391')."""
    s = name.strip()
    m = re.match(r"^(.+?)(?:[\s_-]+(?:[A-Za-z]{0,4}\d+))$", s)
    if m:
        return m.group(1).strip()
    m2 = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*?[A-Za-z])(\d+)$", s)
    if m2:
        return m2.group(1).strip()
    return None


def _mosaic_sky_geometry(fids: list[int], fields_out: list[dict]) -> dict | None:
    """Compute circular-unwrapped sky bounding box and extent for a mosaic component."""
    coord_entries: list[tuple[int, float, float]] = []
    for f in fids:
        ra_v = fields_out[f]["ra_j2000_deg"]["value"]
        dec_v = fields_out[f]["dec_j2000_deg"]["value"]
        if ra_v is not None and dec_v is not None:
            coord_entries.append((f, float(ra_v), float(dec_v)))
    if not coord_entries:
        return None

    ras_arr = np.asarray([c[1] for c in coord_entries], dtype=float)
    decs_arr = np.asarray([c[2] for c in coord_entries], dtype=float)
    ra_rads = np.radians(ras_arr)
    ra_mean_deg = (
        math.degrees(math.atan2(float(np.mean(np.sin(ra_rads))), float(np.mean(np.cos(ra_rads)))))
        % 360.0
    )
    ra_offsets = ((ras_arr - ra_mean_deg + 180.0) % 360.0) - 180.0
    min_off = float(np.min(ra_offsets))
    max_off = float(np.max(ra_offsets))
    mid_off = 0.5 * (min_off + max_off)
    delta_ra_deg = max_off - min_off

    ra_min_deg = (ra_mean_deg + min_off) % 360.0
    ra_max_deg = (ra_mean_deg + max_off) % 360.0
    bbox_ra_deg = (ra_mean_deg + mid_off) % 360.0

    dec_min_deg = float(np.min(decs_arr))
    dec_max_deg = float(np.max(decs_arr))
    bbox_dec_deg = 0.5 * (dec_min_deg + dec_max_deg)

    extent_ra = delta_ra_deg * math.cos(math.radians(bbox_dec_deg)) * 60.0
    extent_dec = (dec_max_deg - dec_min_deg) * 60.0

    best_fid, best_sep_arcmin = min(
        (
            (fid, _angular_sep_deg(ra_v, dec_v, bbox_ra_deg, bbox_dec_deg) * 60.0)
            for fid, ra_v, dec_v in coord_entries
        ),
        key=lambda pair: pair[1],
    )

    ra0 = fields_out[fids[0]]["ra_j2000_deg"]["value"]
    dec0 = fields_out[fids[0]]["dec_j2000_deg"]["value"]
    first_field_offset_arcmin: float | None = (
        round(_angular_sep_deg(float(ra0), float(dec0), bbox_ra_deg, bbox_dec_deg) * 60.0, 3)
        if ra0 is not None and dec0 is not None
        else None
    )

    return {
        "ra_range_deg": [round(ra_min_deg, 6), round(ra_max_deg, 6)],
        "dec_range_deg": [round(dec_min_deg, 6), round(dec_max_deg, 6)],
        "bbox_center_ra_deg": round(bbox_ra_deg, 6),
        "bbox_center_dec_deg": round(bbox_dec_deg, 6),
        "bbox_center_j2000": _format_j2000(bbox_ra_deg, bbox_dec_deg),
        "extent_ra_arcmin": round(extent_ra, 3),
        "extent_dec_arcmin": round(extent_dec, 3),
        "max_extent_arcmin": round(max(extent_ra, extent_dec), 3),
        "max_extent_arcsec": max(extent_ra, extent_dec) * 60.0,
        "central_field_id": best_fid,
        "central_field_name": fields_out[best_fid]["name"],
        "central_field_offset_arcmin": round(best_sep_arcmin, 3),
        "first_field_offset_arcmin": first_field_offset_arcmin,
    }


def _has_distinct_sky_pointings(
    geom: dict | None,
    fids: list[int],
    fields_out: list[dict],
    min_dish_diam_m: float | None,
) -> bool:
    """True when coordinates are unavailable or span distinct sky pointings (not co-located EBs)."""
    if geom is None:
        return True
    pb_deg = _pb_fwhm_deg(fids, fields_out, min_dish_diam_m)
    min_extent_arcsec = max(1.0, 0.05 * pb_deg * 3600.0) if pb_deg is not None else 1.0
    return float(geom["max_extent_arcsec"]) > min_extent_arcsec


def _detect_mosaic_groups(
    fields_out: list[dict],
    source_ids: list[int],
    scans_per_field: Counter[int],
    min_dish_diam_m: float | None = None,
) -> list[dict]:
    """Group multi-pointing mosaic target fields by shared source_id or pointing stem."""
    assigned: set[int] = set()
    raw_groups: list[tuple[str, list[int], dict | None]] = []

    # 1. Shared source_id among non-calibrator fields (>= 2 distinct pointings),
    # split into sky-connected components using primary-beam overlap step (fallback 2.0 deg)
    # so unrelated targets sharing SOURCE_ID=0 never merge.
    by_sid: dict[int, list[int]] = {}
    for fid, sid in enumerate(source_ids):
        if fid < len(fields_out) and _is_mosaic_candidate(fields_out[fid]):
            by_sid.setdefault(sid, []).append(fid)
    for _sid, fids in by_sid.items():
        if len(fids) < 2:
            continue
        pb_deg = _pb_fwhm_deg(fids, fields_out, min_dish_diam_m)
        max_step_deg = 1.5 * pb_deg if pb_deg is not None else _MOSAIC_MAX_STEP_DEG
        for comp in _split_sky_components(fids, fields_out, max_step_deg):
            if len(comp) < 2:
                continue
            geom = _mosaic_sky_geometry(comp, fields_out)
            if not _has_distinct_sky_pointings(geom, comp, fields_out, min_dish_diam_m):
                continue
            stems = {_mosaic_stem(fields_out[f]["name"]) for f in comp}
            if len(stems) == 1 and next(iter(stems)):
                gname = str(next(iter(stems)))
            else:
                gname = fields_out[comp[0]]["name"]
            raw_groups.append((gname, comp, geom))
            assigned.update(comp)

    # 2. Stem-matched pointing names among remaining non-calibrator fields (>= 3 distinct pointings),
    # verified via single-linkage nearest-neighbor sky step <= 1.5 * PB_FWHM (fallback 2.0 deg).
    by_stem: dict[str, list[int]] = {}
    for fid, rec in enumerate(fields_out):
        if fid in assigned or not _is_mosaic_candidate(rec):
            continue
        stem = _mosaic_stem(rec["name"])
        if stem:
            by_stem.setdefault(stem, []).append(fid)

    for stem, fids in by_stem.items():
        if len(fids) < 3:
            continue
        pb_deg = _pb_fwhm_deg(fids, fields_out, min_dish_diam_m)
        max_step_deg = 1.5 * pb_deg if pb_deg is not None else _MOSAIC_MAX_STEP_DEG
        for comp in _split_sky_components(fids, fields_out, max_step_deg):
            if len(comp) < 3:
                continue
            geom = _mosaic_sky_geometry(comp, fields_out)
            if not _has_distinct_sky_pointings(geom, comp, fields_out, min_dish_diam_m):
                continue
            raw_groups.append((stem, comp, geom))
            assigned.update(comp)

    raw_groups.sort(key=lambda item: item[1][0])
    groups_out: list[dict] = []
    for gname, fids, geom in raw_groups:
        sids = sorted({int(fields_out[f]["source_id"]) for f in fids})
        fnames = [fields_out[f]["name"] for f in fids]
        if geom is not None:
            ra_range_deg: list[float] | None = geom["ra_range_deg"]
            dec_range_deg: list[float] | None = geom["dec_range_deg"]
            bbox_center_ra_deg: float | None = geom["bbox_center_ra_deg"]
            bbox_center_dec_deg: float | None = geom["bbox_center_dec_deg"]
            bbox_center_j2000: str | None = geom["bbox_center_j2000"]
            extent_ra_arcmin: float | None = geom["extent_ra_arcmin"]
            extent_dec_arcmin: float | None = geom["extent_dec_arcmin"]
            max_extent_arcmin: float | None = geom["max_extent_arcmin"]
            central_field_id: int | None = geom["central_field_id"]
            central_field_name: str | None = geom["central_field_name"]
            central_field_offset_arcmin: float | None = geom["central_field_offset_arcmin"]
            first_field_offset_arcmin: float | None = geom["first_field_offset_arcmin"]
        else:
            ra_range_deg = None
            dec_range_deg = None
            bbox_center_ra_deg = None
            bbox_center_dec_deg = None
            bbox_center_j2000 = None
            extent_ra_arcmin = None
            extent_dec_arcmin = None
            max_extent_arcmin = None
            central_field_id = None
            central_field_name = None
            central_field_offset_arcmin = None
            first_field_offset_arcmin = None

        seps = [
            fields_out[f]["separation_deg"]
            for f in fids
            if fields_out[f].get("separation_deg") is not None
        ]
        pcals = list(
            dict.fromkeys(
                fields_out[f]["nearest_phase_cal"]
                for f in fids
                if fields_out[f].get("nearest_phase_cal") is not None
            )
        )
        nearest_pcal = pcals[0] if len(pcals) == 1 else (pcals or None)
        first = fields_out[fids[0]]
        groups_out.append(
            {
                "group_name": gname,
                "source_ids": sids,
                "n_pointings": len(fids),
                "field_ids": fids,
                "field_names": fnames,
                "ra_range_deg": ra_range_deg,
                "dec_range_deg": dec_range_deg,
                "bbox_center_ra_deg": bbox_center_ra_deg,
                "bbox_center_dec_deg": bbox_center_dec_deg,
                "bbox_center_j2000": bbox_center_j2000,
                "central_field_id": central_field_id,
                "central_field_name": central_field_name,
                "central_field_offset_arcmin": central_field_offset_arcmin,
                "extent_ra_arcmin": extent_ra_arcmin,
                "extent_dec_arcmin": extent_dec_arcmin,
                "max_extent_arcmin": max_extent_arcmin,
                "first_field_offset_arcmin": first_field_offset_arcmin,
                "intents": first["intents"],
                "field_role": first["field_role"],
                "observing_frequency": first["observing_frequency"],
                "nearest_phase_cal": nearest_pcal,
                "separation_deg_range": [round(min(seps), 2), round(max(seps), 2)]
                if seps
                else None,
                "n_scans_total": int(sum(scans_per_field[f] for f in fids)),
            }
        )
    return groups_out


def _extract_coords(
    phasecenter: dict,
    field_name: str,
    field_id: int,
) -> tuple[float | None, float | None, str, str | None]:
    """
    Extract RA/Dec in radians from a CASA phasecenter dict.

    Returns (ra_rad, dec_rad, completeness_flag, note).
    """
    if not phasecenter:
        return None, None, "UNAVAILABLE", f"phasecenter() returned empty for field {field_id}"

    try:
        # CASA phasecenter returns a direction measure dict:
        # {'type': 'direction', 'refer': 'J2000',
        #  'm0': {'unit': 'rad', 'value': <RA>},
        #  'm1': {'unit': 'rad', 'value': <Dec>}}
        ra_rad = float(phasecenter["m0"]["value"])
        dec_rad = float(phasecenter["m1"]["value"])
    except (KeyError, TypeError, ValueError) as e:
        return None, None, "UNAVAILABLE", f"Could not parse phasecenter dict: {e}"

    # Normalise RA to [0, 2π)
    ra_rad = ra_rad % (2 * math.pi)

    # Suspect coordinate check: (0, 0) to within 1 arcminute
    ra_deg = math.degrees(ra_rad)
    dec_deg = math.degrees(dec_rad)
    if abs(ra_deg) < _COORD_SUSPECT_THRESHOLD_DEG and abs(dec_deg) < _COORD_SUSPECT_THRESHOLD_DEG:
        return (
            ra_rad,
            dec_rad,
            "SUSPECT",
            f"Coordinates ({ra_deg:.4f}°, {dec_deg:.4f}°) are within 1 arcmin of (0,0) J2000. "
            "This is almost certainly a broken UVFITS export. "
            "Elevation, parallactic angle, and phase-cal separation will be UNAVAILABLE for this field.",
        )

    return ra_rad, dec_rad, "COMPLETE", None


def _field_schedule_summary(
    scans_for_field: list[tuple[int, float]],
    all_scan_numbers: list[int],
) -> dict:
    """Compact per-field schedule summary (scan count, on-source time, position)."""
    n_scans = len(scans_for_field)
    total_s = round(sum(dur for _, dur in scans_for_field), 1)
    total_ms_scans = len(all_scan_numbers)
    if n_scans == 0 or total_ms_scans == 0:
        return {
            "n_scans": n_scans,
            "total_on_source_s": total_s,
            "scan_schedule": None,
        }

    scan_nums = [s for s, _ in scans_for_field]
    scan_index = {s: idx for idx, s in enumerate(all_scan_numbers)}
    indices = [scan_index[s] for s in scan_nums if s in scan_index]
    if not indices:
        pos = "unknown"
    elif n_scans == 1:
        idx = indices[0]
        if idx == 0 or idx < 0.10 * total_ms_scans:
            pos = "single_scan_at_start"
        elif idx == total_ms_scans - 1 or idx >= 0.90 * total_ms_scans:
            pos = "single_scan_at_end"
        else:
            pos = "single_scan_mid"
    else:
        lo_i, hi_i = min(indices), max(indices)
        span_frac = (hi_i - lo_i) / max(1, total_ms_scans - 1)
        if hi_i < 0.25 * total_ms_scans:
            pos = "start"
        elif lo_i >= 0.75 * total_ms_scans:
            pos = "end"
        elif span_frac >= 0.40 and n_scans >= 4:
            pos = "interleaved"
        elif lo_i < 0.15 * total_ms_scans and hi_i >= 0.85 * total_ms_scans:
            pos = "bookend"
        elif lo_i < 0.15 * total_ms_scans:
            pos = "start_and_mid"
        else:
            pos = "mid"

    sched: dict = {
        "first_scan": scan_nums[0],
        "last_scan": scan_nums[-1],
        "total_ms_scans": total_ms_scans,
        "position": pos,
    }
    if n_scans <= 8:
        sched["scan_numbers"] = scan_nums
    return {
        "n_scans": n_scans,
        "total_on_source_s": total_s,
        "scan_schedule": sched,
    }


def _catalogue_role_note(cal_entry: CalibratorEntry | None, pol_cal_field: dict) -> str | None:
    """Concise explanation of a source's primary and/or polarisation catalogue roles."""
    parts: list[str] = []
    if cal_entry is not None:
        role_str = "/".join(cal_entry.role)
        std_str = f" ({cal_entry.flux_standard})" if cal_entry.flux_standard else ""
        parts.append(f"{cal_entry.canonical_name}: primary {role_str} calibrator{std_str}.")
        if cal_entry.notes:
            parts.append(cal_entry.notes.strip())
    pol_val = pol_cal_field.get("value") if isinstance(pol_cal_field, dict) else None
    if isinstance(pol_val, dict):
        pol_roles = pol_val.get("role") or []
        pol_name = pol_val.get("name") or "?"
        cat = pol_val.get("category") or "?"
        single_ok = pol_val.get("single_scan_sufficient")
        var_note = pol_val.get("variability_note")
        if cal_entry is None:
            parts.append(
                f"{pol_name}: not a primary flux-scale standard (no CASA setjy flux standard); "
                f"pol-calibrator category {cat} (role={pol_roles}, "
                f"single_scan_sufficient={single_ok})."
            )
        else:
            parts.append(
                f"Pol-calibrator category {cat} (role={pol_roles}, "
                f"single_scan_sufficient={single_ok})."
            )
        if var_note:
            parts.append(str(var_note).strip())
    return " ".join(parts) if parts else None


def _pol_calibrator_field(name: str) -> dict:
    """Polarisation-catalogue identity of a field, by name."""
    entry = lookup_pol(name)
    if entry is None:
        return field(None, flag="UNAVAILABLE", note="Not in the polarisation calibrator catalogue")
    return field(
        {
            "name": entry.b1950_name,
            "category": entry.category,
            "role": list(entry.role),
            "single_scan_sufficient": entry.single_scan_sufficient,
            "variability_note": entry.variability_note,
        },
        flag="COMPLETE",
        note=(
            f"Matched '{name}' to pol catalogue entry '{entry.b1950_name}'. A polarisation "
            "calibrator is its own phase calibrator and is not offered as a target's "
            "nearest_phase_cal."
        ),
    )


def _angular_sep_deg(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    """Haversine angular separation on the sphere in degrees."""
    r1 = np.radians(ra1_deg)
    r2 = np.radians(ra2_deg)
    d1 = np.radians(dec1_deg)
    d2 = np.radians(dec2_deg)
    c = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2)
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def _infer_roles_from_scan_pattern(
    scan_sequence: list[tuple[int, int, float]],
    coords: dict[int, tuple[float | None, float | None]],
    phase_cal_sep_deg: float = 20.0,
) -> dict[int, tuple[list[str], str]]:
    """
    Infer calibration roles for fields that have no intent metadata and no
    catalogue match, using only the scan interleave pattern.

    Returns a dict of field_id → (role_list, one-line reason).
    Only fields that can be confidently assigned a role are included.

    Heuristic:
    - The most-observed field (by scan count) is the science target.
    - A field that alternates with the target (appears in scans adjacent to
      target scans) and has shorter median duration is a phase calibrator
      candidate.
    - Angular separation from the target must be < phase_cal_sep_deg.
    - If the candidate appears in ≥ 4 distinct scans spread across the
      observation, note potential leakage cal suitability (PA check needed).
    """
    if not scan_sequence:
        return {}

    # Count scans per field
    from collections import Counter

    scan_count: Counter[int] = Counter(fid for _, fid, _ in scan_sequence)
    if not scan_count:
        return {}

    # Most-observed field = target (if ≥ 2 fields present)
    sorted_by_count = scan_count.most_common()
    target_fid = sorted_by_count[0][0]

    # Build adjacency: for each non-target field, count how many of its scans
    # are immediately adjacent (±1 position) to a target scan
    field_ids_in_order = [fid for _, fid, _ in scan_sequence]
    target_positions = {i for i, fid in enumerate(field_ids_in_order) if fid == target_fid}

    adjacency: Counter[int] = Counter()
    for pos, fid in enumerate(field_ids_in_order):
        if fid == target_fid:
            continue
        if (pos - 1) in target_positions or (pos + 1) in target_positions:
            adjacency[fid] += 1

    # Median scan duration per field
    from statistics import median

    durations: dict[int, list[float]] = {}
    for _, fid, dur in scan_sequence:
        durations.setdefault(fid, []).append(dur)
    median_dur: dict[int, float] = {fid: median(dlist) for fid, dlist in durations.items()}
    target_dur = median_dur.get(target_fid, 0.0)

    target_ra, target_dec = coords.get(target_fid, (None, None))

    result: dict[int, tuple[list[str], str]] = {}

    for fid, adj_count in adjacency.items():
        total = scan_count[fid]
        if total < 2:
            continue  # single scan — too ambiguous
        if adj_count < max(1, total // 2):
            continue  # doesn't reliably bracket target

        # Duration check: phase cals are typically shorter than the target
        fid_dur = median_dur.get(fid, 0.0)
        if target_dur > 0 and fid_dur > target_dur * 1.5:
            continue  # longer than target — unlikely phase cal

        # Angular separation check
        fid_ra, fid_dec = coords.get(fid, (None, None))
        if (
            target_ra is not None
            and target_dec is not None
            and fid_ra is not None
            and fid_dec is not None
        ):
            sep = _angular_sep_deg(target_ra, target_dec, fid_ra, fid_dec)
            if sep > phase_cal_sep_deg:
                continue
            sep_str = f"{sep:.1f}° from target"
        else:
            sep_str = "separation unknown"

        roles = ["phase"]
        reason = (
            f"alternates with field {target_fid} in {adj_count}/{total} scans, "
            f"median duration {fid_dur:.0f}s vs target {target_dur:.0f}s, {sep_str}"
        )

        # Flag potential leakage cal if well-sampled across the observation
        if total >= 4:
            reason += "; ≥4 scans — check PA coverage with ms_parallactic_angle_vs_time for D-term/QU suitability"

        result[fid] = (roles, reason)

    return result


def _uvrange_fit(
    array: dict,
    freq_hz: float,
    uvmin_kl: float | None,
    uvmax_kl: float | None,
    track: tuple[float, float, list[float]] | None = None,
) -> dict:
    """
    How the array fits a UV range at one frequency.

    With ``track`` (J2000 RA and Dec in radians, sample times in MJD seconds)
    the lengths are projected at each sample time. Without it they are
    physical lengths, an upper limit on projected ones.

    Returns the sample with the fewest antennas keeping _MINBLPERANT baselines
    inside (n_kept, n_inside, worst_time: None without a track), the totals
    (n_ant with data, n_baselines, n_samples), and ``lost``: every antenna
    below _MINBLPERANT at one or more samples.
    """
    if track is None:
        times = [None]
        length_m = array["length_m"][None, :]
    else:
        ra, dec, times = track
        length_m = projected_uv_m(array["vector_m"], ra, dec, times)
    kl = baseline_length_klambda(length_m, freq_hz)
    inside = np.ones(kl.shape, dtype=bool)
    if uvmin_kl is not None:
        inside &= kl > uvmin_kl
    if uvmax_kl is not None:
        inside &= kl < uvmax_kl

    n_names, n_bl = len(array["names"]), kl.shape[1]
    ends = np.zeros((n_bl, n_names), dtype=int)
    ends[np.arange(n_bl), array["ant_i"]] = 1
    ends[np.arange(n_bl), array["ant_j"]] = 1
    present = ends.sum(axis=0) > 0
    below = (inside.astype(int) @ ends < _MINBLPERANT) & present  # [n_samples, n_names]
    n_ant = int(present.sum())
    kept = n_ant - below.sum(axis=1)
    worst = int(np.argmin(kept))
    return {
        "n_kept": int(kept[worst]),
        "n_inside": int(inside[worst].sum()),
        "worst_time": times[worst],
        "n_ant": n_ant,
        "n_baselines": n_bl,
        "n_samples": len(times),
        "lost": [array["names"][a] for a in range(n_names) if below[:, a].any()],
    }


def _resolved_from_callist(
    vla_match: dict,
    freq: dict | None,
    telescope: TelescopeProfile | None,
    array: dict | None = None,
    array_config: dict | None = None,
    track: tuple[float, float, list[float]] | None = None,
) -> tuple[dict, str | None]:
    """
    Resolved status from the VLA calibrator list, for a field the bundled
    catalogue does not know. Returns (field, warning or None).

    The list gives, per band, UV limits: ``uvmin_kl`` (structure at short
    spacings) and ``uvmax_kl`` (resolved at long spacings). The band is the one
    at the field's centre frequency. A limit there means the source has
    structure, so value is True. No limit gives False. Both are INFERRED: the
    list is a catalogue view, not a measurement of this observation.

    Whether the uvrange leaves usable data depends on the array, not the band.
    With ``array`` (from util.array_config.array_baselines) the tool counts,
    per antenna, the baselines inside the uvrange. With ``track`` (J2000 RA,
    Dec and the field's sample times) the lengths are projected at each sample;
    without it they are physical, an upper limit. Fewer than
    _MIN_ANTENNA_PERCENT of the antennas keeping _MINBLPERANT baselines at any
    sample gives a do-not-use warning; otherwise the warning names the antennas
    that fall below at some sample. X in all four configurations gives a
    do-not-use warning whatever the array.

    X in some configurations with no UV limit needs the configuration of this
    MS (``array_config``, from util.array_config). X at that configuration, or
    at either half of a hybrid, gives a do-not-use warning. An unknown
    configuration gives a warning that names the X configurations.

    UNAVAILABLE results carry the reason in the note and give no warning.
    The list describes the VLA only, so another telescope gets UNAVAILABLE.
    """
    match = vla_match.get("value")
    if match is None:
        return (
            field(
                None,
                flag="UNAVAILABLE",
                note="Not in the bundled catalogue or the VLA calibrator list.",
            ),
            None,
        )
    if telescope is None or telescope.canonical != "VLA":
        return (
            field(
                None,
                flag="UNAVAILABLE",
                note="Only the VLA calibrator list matched, and it applies to the VLA only.",
            ),
            None,
        )
    if freq is None or freq.get("centre_ghz") is None:
        return (
            field(None, flag="UNAVAILABLE", note="No observing frequency to choose a band."),
            None,
        )

    code = _callist_band(telescope, freq)
    b = match["bands"].get(code) if code else None
    if b is None:
        return (
            field(
                None,
                flag="UNAVAILABLE",
                note=f"The VLA calibrator list has no entry for {match['name']} at band {code or '?'}.",
            ),
            None,
        )

    uvmin, uvmax = b["uvmin_kl"], b["uvmax_kl"]
    if uvmin is not None and uvmax is not None:
        uvrange = f"{uvmin:g}~{uvmax:g}klambda"
    elif uvmin is not None:
        uvrange = f">{uvmin:g}klambda"
    elif uvmax is not None:
        uvrange = f"<{uvmax:g}klambda"
    else:
        uvrange = None
    quals = "/".join(b[f"qual_{c}"] for c in "ABCD")

    note = (
        f"From the VLA calibrator list ({match['name']}) at band {code}: "
        f"quality A/B/C/D {quals}, " + (f"uvrange='{uvrange}'" if uvrange else "no UV limits") + "."
    )
    prefix = f"VLA calibrator list ({match['name']}) at band {code}: "
    # X in every configuration makes the source unusable at this band in any
    # array, with or without a UV limit.
    all_x = all(b[f"qual_{c}"] == "X" for c in "ABCD")
    all_x_warning = (
        prefix + "graded X in every configuration: do not use this field as a calibrator."
    )
    if uvrange is None:
        return field(False, flag="INFERRED", note=note), _partial_x_warning(
            b, prefix, all_x_warning if all_x else None, array_config
        )

    pass_it = f"pass uvrange='{uvrange}' to solves on this field"
    if array is None:
        note += " No antenna positions, so the baselines inside it were not counted."
        warning = prefix + pass_it + "."
    else:
        fit = _uvrange_fit(array, freq["centre_ghz"] * 1e9, uvmin, uvmax, track)
        worst = fit["worst_time"]
        at_worst = f" at {mjd_seconds_to_utc(worst)}" if worst is not None else ""
        if worst is None:
            basis = "an upper limit: physical, not projected, lengths"
        else:
            basis = (
                f"projected at the start, middle and end of each scan, {fit['n_samples']} "
                f"sample times; the fewest{at_worst}"
            )
        note += (
            f" {fit['n_inside']} of {fit['n_baselines']} baselines fall inside it at the "
            f"centre frequency ({basis})."
        )
        some_time = " at one or more sample times" if worst is not None else ""
        if 100 * fit["n_kept"] < _MIN_ANTENNA_PERCENT * fit["n_ant"]:
            warning = prefix + (
                f"uvrange='{uvrange}' leaves {fit['n_kept']} of {fit['n_ant']} antennas with "
                f"{_MINBLPERANT} baselines{at_worst}, below {_MIN_ANTENNA_PERCENT}%: "
                "do not use this field as a calibrator."
            )
        elif fit["lost"]:
            warning = (
                prefix + pass_it + f"; {len(fit['lost'])} of {fit['n_ant']} antennas have "
                f"fewer than {_MINBLPERANT} baselines inside it{some_time} and get no "
                f"solution: {', '.join(fit['lost'])}."
            )
        else:
            warning = prefix + pass_it + "."
    if all_x:
        warning = all_x_warning
    return field(True, flag="INFERRED", note=note), warning


def _partial_x_warning(
    band: dict, prefix: str, all_x_warning: str | None, array_config: dict | None
) -> str | None:
    """Warning for a band entry with no UV limit, from its grade at this MS's configuration."""
    if all_x_warning:
        return all_x_warning
    x_configs = [c for c in "ABCD" if band[f"qual_{c}"] == "X"]
    if not x_configs:
        return None
    name = array_config["value"] if array_config else None
    letters = config_letters(name)
    if letters is None:
        return (
            prefix + f"graded X in configuration {'/'.join(x_configs)} and the configuration "
            "of this MS is unknown: confirm it before using this field as a calibrator."
        )
    bad = [c for c in letters if c in x_configs]
    if not bad:
        return None
    return (
        prefix + f"graded X in configuration {'/'.join(bad)}, and this MS is in "
        f"{name} ({array_config['flag']}): do not use this field as a calibrator."
    )


def _callist_band(telescope: TelescopeProfile | None, freq: dict) -> str | None:
    """Callist band code for this field's frequency (centre, then edges)."""
    if telescope is None:
        return None
    code = None
    for ghz in (freq["centre_ghz"], freq["min_ghz"], freq["max_ghz"]):
        code = telescope.band_code(ghz * 1e9)
        if code:
            break
    return callist_band_code(code)


def _vla_flux_estimate(
    vla_match: dict, freq: dict | None, telescope: TelescopeProfile | None
) -> dict:
    """Callist flux for this field (phase_cal_catalog.expected_flux): the observed
    band's row if it has one, else a power law between the bracketing bands at the
    centre frequency. VLA only, like _resolved_from_callist."""
    match = vla_match.get("value")
    if match is None:
        return field(None, flag="UNAVAILABLE", note="No VLA calibrator list match.")
    if telescope is None or telescope.canonical != "VLA":
        return field(
            None,
            flag="UNAVAILABLE",
            note="The VLA calibrator list applies to the VLA only (telescope not VLA or unread).",
        )
    if freq is None or freq.get("centre_ghz") is None:
        return field(None, flag="UNAVAILABLE", note="No observing frequency.")
    entry = get_source(match["name"])
    if entry is None:
        return field(None, flag="UNAVAILABLE", note=f"{match['name']} not found in the callist.")
    value, flag, note = expected_flux(
        entry,
        freq["centre_ghz"],
        band_code=_callist_band(telescope, freq),
        identity_exact=vla_match.get("flag") == "COMPLETE",
    )
    return field(value, flag=flag, note=note)


def _vla_positional_match(
    ra_deg: float | None,
    dec_deg: float | None,
    cal_entry: CalibratorEntry | None = None,
) -> dict:
    """
    Attempt a positional cross-match against the VLA calibrator database.

    Returns a formatted field() dict with the match result.

    Solar-system bodies are skipped deliberately. They move, so the recorded
    phase centre is a position at one epoch and not an identity. A cone search
    on it either finds nothing or — worse — lands on an unrelated VLA
    calibrator that happens to sit near the ecliptic, and reports a confident
    match. Skipping is stated in the note, not left silent.
    """
    if cal_entry is not None and cal_entry.solar_system:
        return field(
            None,
            flag="UNAVAILABLE",
            note=(
                f"Positional cross-match not attempted: {cal_entry.canonical_name} is a "
                "solar-system body, so its phase centre is an epoch-dependent position "
                "rather than an identity."
            ),
        )

    if ra_deg is None or dec_deg is None:
        return field(None, flag="UNAVAILABLE", note="No coordinates for VLA positional match")

    try:
        result = vla_cone_search(ra_deg, dec_deg)
    except Exception as e:
        return field(
            None,
            flag="UNAVAILABLE",
            note=f"VLA calibrator positional search failed: {e}",
        )

    if result is None:
        return field(
            None, flag="UNAVAILABLE", note=f"No VLA calibrator within {IDENTITY_ARCSEC:g} arcsec"
        )

    entry = result.entry
    separation_arcsec = result.separation_deg * 3600.0
    match_data = {
        "name": entry.iau_name,
        "alt_name": entry.alt_name,
        "separation_arcsec": separation_arcsec,
        "position_code": entry.pos_accuracy,
        "bands": {
            k: {
                "qual_A": v.quality_A,
                "qual_B": v.quality_B,
                "qual_C": v.quality_C,
                "qual_D": v.quality_D,
                "flux_jy": v.flux_jy,
                "uvmin_kl": v.uvmin_kl,
                "uvmax_kl": v.uvmax_kl,
            }
            for k, v in entry.bands.items()
        },
    }

    flag_val = "COMPLETE" if separation_arcsec < EXACT_ARCSEC else "INFERRED"
    note = f"VLA callist match: {entry.iau_name}"
    if entry.alt_name:
        note += f" ({entry.alt_name})"
    note += f" at {separation_arcsec:.3f} arcsec"

    return field(match_data, flag=flag_val, note=note)
