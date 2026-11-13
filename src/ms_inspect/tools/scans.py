"""
tools/scans.py — ms_scan_list and ms_scan_intent_summary

Layer 1, Tools 3 & 4.

ms_scan_list:          Time-ordered scan sequence with field, duration, intents.
ms_scan_intent_summary: Time fractions per intent across the full observation.

CASA access: msmd.scansforfield(), msmd.timesforscans(),
             msmd.intentsforscans(), msmd.fieldsforscan()
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ms_inspect.util.casa_context import open_msmd, validate_ms_path
from ms_inspect.util.conversions import mjd_seconds_to_utc, seconds_to_human
from ms_inspect.util.formatting import (
    field,
    offload_detail,
    resolve_sidecar_path,
    response_envelope,
)

TOOL_SCAN_LIST = "ms_scan_list"
TOOL_INTENT_SUMMARY = "ms_scan_intent_summary"
_MAX_INLINE_SCANS = 20


def _compact_scan_ranges(scan_nums: list[int]) -> str:
    """Format sorted scan numbers into compact ranges (e.g. '1~3,7,10~14')."""
    if not scan_nums:
        return ""
    nums = sorted(set(scan_nums))
    parts: list[str] = []
    start = end = nums[0]
    for n in nums[1:]:
        if n == end + 1:
            end = n
        else:
            parts.append(f"{start}~{end}" if end > start else str(start))
            start = end = n
    parts.append(f"{start}~{end}" if end > start else str(start))
    return ",".join(parts)


def run_scan_list(
    ms_path: str,
    workdir: str | None = None,
    *,
    _offload: bool = True,
) -> dict:
    """
    Return the time-ordered list of all scans in the MS.

    Each record includes: scan number, field id/name, intent, start/end UTC,
    duration, integration time, and spectral windows observed.
    """
    p = validate_ms_path(ms_path)
    casa_calls: list[str] = []
    warnings: list[str] = []

    with open_msmd(str(p)) as msmd:
        casa_calls.append("msmd.open()")

        field_names: list[str] = list(msmd.fieldnames())
        casa_calls.append("msmd.fieldnames()")

        scan_numbers: list[int] = sorted(msmd.scannumbers())
        casa_calls.append("msmd.scannumbers()")

        if not scan_numbers:
            warnings.append("No scans found in MS.")
            return response_envelope(
                tool_name=TOOL_SCAN_LIST,
                ms_path=ms_path,
                data={"n_scans": 0, "scans": []},
                warnings=warnings,
                casa_calls=casa_calls,
            )

        scans_out: list[dict] = []

        for scan_num in scan_numbers:
            # Field for this scan
            try:
                field_ids: list[int] = list(msmd.fieldsforscan(scan_num))
                fid = field_ids[0] if field_ids else -1
                fname = field_names[fid] if 0 <= fid < len(field_names) else f"FIELD_{fid}"
            except Exception:
                fid = -1
                fname = "UNKNOWN"

            # Intents — try per-scan first, fall back to field-level.
            # Some MSs have STATE subtable linkage broken, causing intentsforscan()
            # to return empty even when intentsforfield() works correctly.
            # Note: CASA 6.x API is intentsforscan(int), not intentsforscans([int]).
            try:
                scan_intents: list[str] = sorted(msmd.intentsforscan(scan_num))
                if not scan_intents and fid >= 0:
                    scan_intents = sorted(msmd.intentsforfield(fid))
                intent_flag = "COMPLETE" if scan_intents else "UNAVAILABLE"
            except Exception:
                scan_intents = []
                intent_flag = "UNAVAILABLE"

            # Time range
            try:
                # Sorted unique integration centres (MJD seconds)
                times = np.unique(np.asarray(msmd.timesforscans([scan_num]), dtype=float))
                t_start = float(times.min())
                t_end = float(times.max())
                duration_s = t_end - t_start
                # times are centres of integrations; corrected below by one dump.
            except Exception as e:
                warnings.append(f"Could not get times for scan {scan_num}: {e}")
                times = None
                t_start = t_end = duration_s = float("nan")

            # Integration (dump) time for this scan — derived from the times
            # array itself. NOTE: msmd.exposuretime(scan=...) hard-segfaults
            # CASA 6.7.x on some MSs (G55/AB1345), taking the whole process down
            # (uncatchable), so we never call it. Median positive step is robust.
            integration_s = float("nan")
            try:
                if times is not None and times.size >= 2:
                    steps = np.diff(times)
                    steps = steps[steps > 0]
                    if steps.size:
                        integration_s = float(np.median(steps))
                # Correct duration: add one integration to account for last sample
                if integration_s == integration_s and duration_s == duration_s:
                    duration_s += integration_s
            except Exception:
                integration_s = float("nan")

            # SpWs for this scan
            try:
                spw_ids: list[int] = sorted(msmd.spwsforscan(scan_num))
                spw_field = field(spw_ids, flag="COMPLETE")
            except Exception:
                spw_field = field(None, flag="UNAVAILABLE")

            # Number of integrations
            n_integrations: int | None = None
            if integration_s > 0 and integration_s == integration_s:
                n_integrations = max(1, round(duration_s / integration_s))

            record = {
                "scan_number": scan_num,
                "field_id": fid,
                "field_name": fname,
                "intents": field(scan_intents, flag=intent_flag),
                "start_utc": field(
                    mjd_seconds_to_utc(t_start) if t_start == t_start else None,
                    flag="COMPLETE" if t_start == t_start else "UNAVAILABLE",
                ),
                "end_utc": field(
                    mjd_seconds_to_utc(t_end) if t_end == t_end else None,
                    flag="COMPLETE" if t_end == t_end else "UNAVAILABLE",
                ),
                "duration_s": field(
                    round(duration_s, 2) if duration_s == duration_s else None,
                    flag="COMPLETE" if duration_s == duration_s else "UNAVAILABLE",
                ),
                "duration_human": seconds_to_human(duration_s)
                if duration_s == duration_s
                else "N/A",
                "integration_s": field(
                    round(integration_s, 3) if integration_s == integration_s else None,
                    flag="COMPLETE" if integration_s == integration_s else "UNAVAILABLE",
                ),
                "n_integrations": n_integrations,
                "spw_ids": spw_field,
            }
            scans_out.append(record)

    # Check for large time gaps between consecutive scans (potential missing data)
    _check_scan_gaps(scans_out, warnings)

    # Build compact per-field and per-intent summaries so orientation never needs
    # all 100+ raw scan dicts inline.
    field_order: list[int] = []
    field_agg: dict[int, dict] = {}
    intent_agg: dict[str, dict] = {}
    total_dur = 0.0
    valid_starts: list[str] = []
    valid_ends: list[str] = []

    for rec in scans_out:
        fid = int(rec["field_id"])
        fname = str(rec["field_name"])
        dur_v = rec["duration_s"]["value"]
        dur_f = float(dur_v) if dur_v is not None else 0.0
        total_dur += dur_f
        s_utc = rec["start_utc"]["value"]
        e_utc = rec["end_utc"]["value"]
        if s_utc:
            valid_starts.append(s_utc)
        if e_utc:
            valid_ends.append(e_utc)

        if fid not in field_agg:
            field_order.append(fid)
            field_agg[fid] = {
                "field_id": fid,
                "field_name": fname,
                "n_scans": 0,
                "duration_s": 0.0,
                "intents": set(),
                "scan_nums": [],
            }
        fa = field_agg[fid]
        fa["n_scans"] += 1
        fa["duration_s"] += dur_f
        fa["scan_nums"].append(int(rec["scan_number"]))
        intents_list = rec["intents"]["value"] or []
        fa["intents"].update(intents_list)

        for intent_lbl in intents_list or ["UNASSIGNED"]:
            ia = intent_agg.setdefault(
                intent_lbl, {"intent": intent_lbl, "n_scans": 0, "duration_s": 0.0}
            )
            ia["n_scans"] += 1
            ia["duration_s"] += dur_f

    by_field = [
        {
            "field_id": field_agg[fid]["field_id"],
            "field_name": field_agg[fid]["field_name"],
            "n_scans": field_agg[fid]["n_scans"],
            "duration_s": round(field_agg[fid]["duration_s"], 2),
            "intents": sorted(field_agg[fid]["intents"]),
            "scan_range": _compact_scan_ranges(field_agg[fid]["scan_nums"]),
        }
        for fid in field_order
    ]
    by_intent = [
        {
            "intent": k,
            "n_scans": v["n_scans"],
            "duration_s": round(v["duration_s"], 2),
        }
        for k, v in sorted(intent_agg.items(), key=lambda kv: -kv[1]["duration_s"])
    ]

    data: dict = {
        "n_scans": len(scans_out),
        "n_fields": len(set(s["field_name"] for s in scans_out)),
        "total_duration_s": round(total_dur, 2),
        "obs_start_utc": valid_starts[0] if valid_starts else None,
        "obs_end_utc": valid_ends[-1] if valid_ends else None,
        "by_field": by_field,
        "by_intent": by_intent,
        "scans": scans_out,
    }

    if _offload and (len(scans_out) > _MAX_INLINE_SCANS or workdir):
        data = offload_detail(
            data, ["scans"], resolve_sidecar_path(f"{Path(p).name}.scan_list.json", workdir)
        )

    return response_envelope(
        tool_name=TOOL_SCAN_LIST,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )


def run_scan_intent_summary(ms_path: str) -> dict:
    """
    Summarise how total observing time is distributed across scan intents.

    Aggregates scan durations from ms_scan_list and groups by intent.
    If intents are absent, groups by field name instead.
    """
    # Reuse scan list -- keep scans inline for internal aggregation
    scan_result = run_scan_list(ms_path, _offload=False)

    warnings: list[str] = list(scan_result.get("warnings", []))
    scans: list[dict] = scan_result["data"]["scans"]

    if not scans:
        return response_envelope(
            tool_name=TOOL_INTENT_SUMMARY,
            ms_path=ms_path,
            data={"total_duration_s": 0, "by_intent": [], "intent_completeness": "UNAVAILABLE"},
            warnings=warnings,
            casa_calls=["(aggregated from ms_scan_list)"],
        )

    # Compute total duration
    durations: list[float] = []
    for s in scans:
        dur_val = s.get("duration_s", {})
        v = dur_val.get("value") if isinstance(dur_val, dict) else dur_val
        if v is not None and v == v:  # nan check
            durations.append(float(v))

    total_s = sum(durations)

    # Check whether intents are available
    has_intents = any(
        s["intents"].get("flag") == "COMPLETE" and s["intents"].get("value") for s in scans
    )
    intent_completeness: str = "COMPLETE" if has_intents else "UNAVAILABLE"

    # Aggregate by intent (or by field if no intents)
    by_group: dict[str, float] = {}

    for s in scans:
        dur_val = s.get("duration_s", {})
        dur = float(dur_val["value"]) if isinstance(dur_val, dict) and dur_val.get("value") else 0.0

        intent_data = s.get("intents", {})
        intents: list[str] = []
        if isinstance(intent_data, dict):
            intents = intent_data.get("value") or []

        if intents:
            for intent in intents:
                by_group[intent] = by_group.get(intent, 0.0) + dur / max(len(intents), 1)
        else:
            key = f"FIELD:{s['field_name']}"
            by_group[key] = by_group.get(key, 0.0) + dur

    if not has_intents:
        warnings.append(
            "No scan intents found — time breakdown is by field name instead of intent. "
            "Run ms_field_list to see if calibrator catalogue inference is possible."
        )

    # Sort by total time descending
    by_intent_list = sorted(
        [
            {
                "intent": intent,
                "total_s": round(t, 2),
                "fraction": round(t / total_s, 4) if total_s > 0 else 0.0,
                "human": seconds_to_human(t),
            }
            for intent, t in by_group.items()
        ],
        key=lambda x: x["total_s"],
        reverse=True,
    )

    data = {
        "total_duration_s": round(total_s, 2),
        "total_duration_human": seconds_to_human(total_s),
        "n_intents": len(by_intent_list),
        "intent_completeness": intent_completeness,
        "by_intent": by_intent_list,
    }

    return response_envelope(
        tool_name=TOOL_INTENT_SUMMARY,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=["(aggregated from ms_scan_list — no additional CASA calls)"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_scan_gaps(scans: list[dict], warnings: list[str]) -> None:
    """
    Warn if consecutive scans have a large time gap (> 10 minutes),
    which may indicate missing data or a multi-session concatenated MS.
    """
    for i in range(len(scans) - 1):
        scans[i].get("end_utc", {})
        scans[i + 1].get("start_utc", {})

        # We need the raw MJD values for gap calculation; they're buried in the
        # formatted UTC strings. Approximate from duration and scan numbers only.
        dur_i = scans[i].get("duration_s", {})
        scans[i + 1].get("duration_s", {})
        dur_i["value"] if isinstance(dur_i, dict) else None

        # We can't compute exact gap without raw MJD — flag large n_scan gaps
        snum_i = scans[i]["scan_number"]
        snum_i1 = scans[i + 1]["scan_number"]
        if snum_i1 - snum_i > 5:
            warnings.append(
                f"Scan number jump from {snum_i} to {snum_i1} "
                f"({snum_i1 - snum_i - 1} missing scan numbers). "
                "This may indicate deleted or missing scans."
            )
