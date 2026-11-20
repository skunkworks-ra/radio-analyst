"""
tools/antenna_amp_stats.py -- ms_antenna_amp_stats

Per-antenna parallel-hand visibility amplitude statistics (raw DATA by default,
or CORRECTED_DATA / MODEL_DATA). Surfaces per-antenna median, min, max, and p95
baseline visibility amplitudes alongside the ratio to the array median so dead
or hot unflagged antennas stand out immediately during inspection.

Queries one DATA_DESC_ID at a time so Measurement Sets with mixed channel counts
across spectral windows never fail on getcol(), and uses bounded row chunks with
optional uniform row striding (max_rows) so large MSs complete quickly.

Measures only: returns numbers, provenance, and CompletionFlags -- never
pass/fail verdicts or dead-antenna booleans.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ms_inspect.exceptions import ComputationError
from ms_inspect.tools.radiometer_estimate import parse_spw_selection
from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.formatting import (
    field as fmt_field,
)
from ms_inspect.util.formatting import (
    normalize_field_sel,
    response_envelope,
)
from ms_inspect.util.selection import match_field_names, parallel_corr_by_ddid

TOOL_NAME = "ms_antenna_amp_stats"

_ROW_CHUNK = 50_000
_DEFAULT_MAX_ROWS = 200_000
_DEFAULT_NEAR_ZERO_RATIO = 0.05
_NEAR_ZERO_ABS_FLOOR = 1e-6


def _resolve_datacolumn(col: str) -> str:
    norm = col.strip().upper()
    aliases = {
        "DATA": "DATA",
        "CORRECTED": "CORRECTED_DATA",
        "CORRECTED_DATA": "CORRECTED_DATA",
        "MODEL": "MODEL_DATA",
        "MODEL_DATA": "MODEL_DATA",
    }
    if norm not in aliases:
        raise ValueError(
            f"Unsupported datacolumn={col!r}; use 'DATA', 'CORRECTED_DATA', or 'MODEL_DATA'."
        )
    return aliases[norm]


def parse_scan_selection(scans: str) -> list[int]:
    """Parse a CASA-style scan selection ('1,3,5~7') into sorted unique scan IDs."""
    text = scans.strip()
    if not text:
        return []
    out: set[int] = set()
    for token in text.split(","):
        part = token.strip()
        if not part:
            continue
        if "~" in part:
            lo_s, hi_s = part.split("~", 1)
            try:
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid scan range {part!r} in scans={scans!r}.") from exc
            if lo < 0 or hi < lo:
                raise ValueError(f"Invalid scan range {part!r} in scans={scans!r}.")
            out.update(range(lo, hi + 1))
        else:
            try:
                val = int(part)
            except ValueError as exc:
                raise ValueError(f"Invalid scan number {part!r} in scans={scans!r}.") from exc
            if val < 0:
                raise ValueError(f"Invalid scan number {part!r} in scans={scans!r}.")
            out.add(val)
    return sorted(out)


def summarize_antenna_amplitudes(
    ant_names: list[str],
    per_ant_row_means: list[np.ndarray],
    per_ant_unflagged_samples: np.ndarray,
    per_ant_total_samples: np.ndarray,
    *,
    strided: bool = False,
    near_zero_ratio: float = _DEFAULT_NEAR_ZERO_RATIO,
) -> dict:
    """
    Pure per-antenna amplitude summary (CASA-free, unit-testable).

    Each antenna's distribution is computed over the per-row mean parallel-hand
    amplitudes across all unflagged baselines touching that antenna.
    """
    n_ant = len(ant_names)
    raw_records: list[dict] = []
    live_medians: list[float] = []

    for aid in range(n_ant):
        vals = per_ant_row_means[aid]
        n_unf = int(per_ant_unflagged_samples[aid])
        n_tot = int(per_ant_total_samples[aid])
        unf_frac = round(n_unf / n_tot, 6) if n_tot > 0 else 0.0
        if vals.size == 0 or n_unf == 0:
            raw_records.append(
                {
                    "antenna_id": aid,
                    "name": str(ant_names[aid]),
                    "n_rows_with_data": 0,
                    "n_unflagged_samples": 0,
                    "total_samples": n_tot,
                    "unflagged_fraction": unf_frac,
                    "amp_median": None,
                    "amp_mad": None,
                    "amp_iqr": None,
                    "amp_min": None,
                    "amp_max": None,
                    "amp_p95": None,
                    "vals": vals,
                }
            )
            continue

        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med)))
        p25, p75, p95 = (float(x) for x in np.percentile(vals, [25, 75, 95]))
        live_medians.append(med)
        raw_records.append(
            {
                "antenna_id": aid,
                "name": str(ant_names[aid]),
                "n_rows_with_data": int(vals.size),
                "n_unflagged_samples": n_unf,
                "total_samples": n_tot,
                "unflagged_fraction": unf_frac,
                "amp_median": med,
                "amp_mad": mad,
                "amp_iqr": p75 - p25,
                "amp_min": float(np.min(vals)),
                "amp_max": float(np.max(vals)),
                "amp_p95": p95,
                "vals": vals,
            }
        )

    if live_medians:
        med_arr = np.asarray(live_medians, dtype=float)
        array_median = float(np.median(med_arr))
        array_mad = float(np.median(np.abs(med_arr - array_median)))
        near_zero_cutoff = max(_NEAR_ZERO_ABS_FLOOR, float(near_zero_ratio) * array_median)
    else:
        array_median = None
        array_mad = None
        near_zero_cutoff = None

    val_flag = "PARTIAL" if strided else "COMPLETE"
    strided_note = "computed on uniformly strided rows (max_rows cap)" if strided else None

    per_antenna: list[dict] = []
    for rec in raw_records:
        med = rec["amp_median"]
        if med is None:
            per_antenna.append(
                {
                    "antenna_id": rec["antenna_id"],
                    "name": rec["name"],
                    "n_rows_with_data": 0,
                    "n_unflagged_samples": 0,
                    "total_samples": rec["total_samples"],
                    "unflagged_fraction": rec["unflagged_fraction"],
                    "amp_median": fmt_field(
                        None, flag="UNAVAILABLE", note="no unflagged parallel-hand visibilities"
                    ),
                    "amp_mad": fmt_field(None, flag="UNAVAILABLE"),
                    "amp_iqr": fmt_field(None, flag="UNAVAILABLE"),
                    "amp_min": fmt_field(None, flag="UNAVAILABLE"),
                    "amp_max": fmt_field(None, flag="UNAVAILABLE"),
                    "amp_p95": fmt_field(None, flag="UNAVAILABLE"),
                    "near_zero_fraction": fmt_field(None, flag="UNAVAILABLE"),
                    "ratio_to_array_median": fmt_field(None, flag="UNAVAILABLE"),
                }
            )
        else:
            ratio = (
                (med / array_median) if (array_median is not None and array_median > 0) else None
            )
            ratio_flag = "UNAVAILABLE" if ratio is None else val_flag
            nz_frac = (
                float(np.mean(rec["vals"] <= near_zero_cutoff))
                if near_zero_cutoff is not None
                else None
            )
            per_antenna.append(
                {
                    "antenna_id": rec["antenna_id"],
                    "name": rec["name"],
                    "n_rows_with_data": rec["n_rows_with_data"],
                    "n_unflagged_samples": rec["n_unflagged_samples"],
                    "total_samples": rec["total_samples"],
                    "unflagged_fraction": rec["unflagged_fraction"],
                    "amp_median": fmt_field(round(med, 6), flag=val_flag, note=strided_note),
                    "amp_mad": fmt_field(round(rec["amp_mad"], 6), flag=val_flag),
                    "amp_iqr": fmt_field(round(rec["amp_iqr"], 6), flag=val_flag),
                    "amp_min": fmt_field(round(rec["amp_min"], 6), flag=val_flag),
                    "amp_max": fmt_field(round(rec["amp_max"], 6), flag=val_flag),
                    "amp_p95": fmt_field(round(rec["amp_p95"], 6), flag=val_flag),
                    "near_zero_fraction": fmt_field(
                        round(nz_frac, 6) if nz_frac is not None else None,
                        flag="UNAVAILABLE" if nz_frac is None else val_flag,
                    ),
                    "ratio_to_array_median": fmt_field(
                        round(ratio, 6) if ratio is not None else None,
                        flag=ratio_flag,
                    ),
                }
            )

    # Sort ascending by ratio_to_array_median so lowest-amplitude antennas appear first;
    # UNAVAILABLE antennas (ratio is None) follow in antenna_id order.
    def _sort_key(item: dict) -> tuple[int, float, int]:
        r = item["ratio_to_array_median"]["value"]
        if r is None:
            return (1, 0.0, int(item["antenna_id"]))
        return (0, float(r), int(item["antenna_id"]))

    per_antenna.sort(key=_sort_key)

    return {
        "n_antennas": n_ant,
        "n_antennas_with_data": len(live_medians),
        "array_median_amp": round(array_median, 6) if array_median is not None else None,
        "array_mad_amp": round(array_mad, 6) if array_mad is not None else None,
        "near_zero_ratio": float(near_zero_ratio),
        "near_zero_cutoff_amp": round(near_zero_cutoff, 6)
        if near_zero_cutoff is not None
        else None,
        "per_antenna": per_antenna,
    }


def run(
    ms_path: str,
    field: str = "",
    spw: str = "",
    scans: str = "",
    datacolumn: str = "DATA",
    exclude_autocorr: bool = True,
    max_rows: int = _DEFAULT_MAX_ROWS,
    near_zero_ratio: float = _DEFAULT_NEAR_ZERO_RATIO,
) -> dict:
    """
    Compute per-antenna parallel-hand visibility amplitude statistics.

    Args:
        ms_path:          Path to the Measurement Set.
        field:            CASA field selection ('' = all fields).
        spw:              CASA SpW id/range selection ('' = all SpWs).
        scans:            CASA scan number/range selection, e.g. '2,3' or '1~5' ('' = all scans).
        datacolumn:       'DATA' (default), 'CORRECTED_DATA', or 'MODEL_DATA'.
        exclude_autocorr: Exclude ANTENNA1 == ANTENNA2 rows (default True).
        max_rows:         Max rows sampled per DATA_DESC_ID (uniform stride above cap).
        near_zero_ratio:  Fraction of array_median_amp below which a row counts as near-zero
                          (default 0.05; absolute floor 1e-6).
    """
    if max_rows <= 0:
        raise ComputationError(f"max_rows must be > 0, got {max_rows}", ms_path=ms_path)
    if near_zero_ratio < 0:
        raise ComputationError(
            f"near_zero_ratio must be >= 0, got {near_zero_ratio}", ms_path=ms_path
        )
    try:
        col_name = _resolve_datacolumn(datacolumn)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None
    try:
        scan_ids = parse_scan_selection(scans)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    with open_table(str(Path(ms_str) / "ANTENNA")) as tb:
        ant_names = [str(x) for x in tb.getcol("NAME")]
    casa_calls.append("tb.open(ANTENNA) -> NAME")
    n_ant = len(ant_names)

    with open_table(str(Path(ms_str) / "FIELD")) as tb:
        field_names = [str(x) for x in tb.getcol("NAME")]
    casa_calls.append("tb.open(FIELD) -> NAME")

    norm_field = normalize_field_sel(field)
    if norm_field:
        try:
            field_ids = match_field_names(field_names, norm_field)
        except ValueError as exc:
            raise ComputationError(str(exc), ms_path=ms_path) from None
    else:
        field_ids = list(range(len(field_names)))

    with open_table(str(Path(ms_str) / "SPECTRAL_WINDOW")) as tb:
        n_spw = int(tb.nrows())
    try:
        selected_spws = set(parse_spw_selection(spw, n_spw))
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    with open_table(str(Path(ms_str) / "DATA_DESCRIPTION")) as tb:
        dd_spws = [int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")]
    corr_by_dd = parallel_corr_by_ddid(ms_str)
    casa_calls.append("parallel_corr_by_ddid() -> POLARIZATION, DATA_DESCRIPTION")

    per_ant_chunks: list[list[np.ndarray]] = [[] for _ in range(n_ant)]
    per_ant_unflagged = np.zeros(n_ant, dtype=np.int64)
    per_ant_total = np.zeros(n_ant, dtype=np.int64)

    selected_spws_seen: set[int] = set()
    rows_total = 0
    rows_scanned = 0
    strided = False

    fid_taql = ",".join(str(fid) for fid in field_ids)
    scan_clause = f" && SCAN_NUMBER IN [{','.join(str(s) for s in scan_ids)}]" if scan_ids else ""
    auto_clause = " && ANTENNA1 != ANTENNA2" if exclude_autocorr else ""

    with open_table(ms_str) as tb:
        if col_name not in set(tb.colnames()):
            raise ComputationError(
                f"{col_name} column not present in {ms_path}.",
                ms_path=ms_path,
            )

        for ddid, spw_id in enumerate(dd_spws):
            if spw_id not in selected_spws:
                continue
            par_idx = [idx for idx, _ in corr_by_dd[ddid]]
            if not par_idx:
                continue
            query_str = (
                f"DATA_DESC_ID == {ddid} && FIELD_ID IN [{fid_taql}]{scan_clause}{auto_clause}"
            )
            sub = tb.query(query_str)
            try:
                nrows = int(sub.nrows())
                if nrows == 0:
                    continue
                selected_spws_seen.add(spw_id)
                rows_total += nrows
                step = max(1, math.ceil(nrows / max_rows))
                if step > 1:
                    strided = True
                # Number of strided rows returned across [0, nrows) with rowincr=step
                n_out_total = math.ceil(nrows / step)
                rows_scanned += n_out_total
                for out_start in range(0, n_out_total, _ROW_CHUNK):
                    cnt = min(_ROW_CHUNK, n_out_total - out_start)
                    start_row = out_start * step
                    ant1 = np.asarray(
                        sub.getcol("ANTENNA1", startrow=start_row, nrow=cnt, rowincr=step),
                        dtype=int,
                    )
                    ant2 = np.asarray(
                        sub.getcol("ANTENNA2", startrow=start_row, nrow=cnt, rowincr=step),
                        dtype=int,
                    )
                    frow = np.asarray(
                        sub.getcol("FLAG_ROW", startrow=start_row, nrow=cnt, rowincr=step),
                        dtype=bool,
                    )
                    vis = np.asarray(
                        sub.getcol(col_name, startrow=start_row, nrow=cnt, rowincr=step)
                    )[par_idx, :, :]
                    flg = np.asarray(
                        sub.getcol("FLAG", startrow=start_row, nrow=cnt, rowincr=step),
                        dtype=bool,
                    )[par_idx, :, :]

                    good = (~flg) & (~frow[None, None, :])
                    amp = np.abs(vis)
                    good &= np.isfinite(amp)

                    row_sum = np.where(good, amp, 0.0).sum(axis=(0, 1))
                    row_npts = good.sum(axis=(0, 1))
                    row_tot = int(good.shape[0] * good.shape[1])

                    valid_a1 = (ant1 >= 0) & (ant1 < n_ant)
                    valid_a2 = (ant2 >= 0) & (ant2 < n_ant)
                    same_ant = ant1 == ant2

                    if valid_a1.any():
                        np.add.at(per_ant_unflagged, ant1[valid_a1], row_npts[valid_a1])
                        np.add.at(per_ant_total, ant1[valid_a1], row_tot)
                    add_a2 = valid_a2 & (~same_ant)
                    if add_a2.any():
                        np.add.at(per_ant_unflagged, ant2[add_a2], row_npts[add_a2])
                        np.add.at(per_ant_total, ant2[add_a2], row_tot)

                    live = row_npts > 0
                    if not live.any():
                        continue
                    row_means = row_sum[live] / row_npts[live]
                    live_a1 = ant1[live]
                    live_a2 = ant2[live]
                    live_same = same_ant[live]

                    # Group live row means by antenna index in O(N log N) via argsort.
                    ant_ids_all = np.concatenate([live_a1, live_a2[~live_same]])
                    means_all = np.concatenate([row_means, row_means[~live_same]])
                    in_bounds = (ant_ids_all >= 0) & (ant_ids_all < n_ant)
                    if not in_bounds.any():
                        continue
                    ant_ids_all = ant_ids_all[in_bounds]
                    means_all = means_all[in_bounds]
                    order = np.argsort(ant_ids_all, kind="mergesort")
                    sorted_ants = ant_ids_all[order]
                    sorted_means = means_all[order]
                    uniq_ants, split_idx = np.unique(sorted_ants, return_index=True)
                    groups = np.split(sorted_means, split_idx[1:])
                    for aid, grp in zip(uniq_ants, groups, strict=False):
                        per_ant_chunks[int(aid)].append(grp)
            finally:
                sub.close()

    casa_calls.append(
        f"tb.query(per DATA_DESC_ID) -> ANTENNA1, ANTENNA2, {col_name}, FLAG, FLAG_ROW"
    )

    per_ant_arrays = [
        np.concatenate(chunks) if chunks else np.empty(0, dtype=float) for chunks in per_ant_chunks
    ]
    summary = summarize_antenna_amplitudes(
        ant_names,
        per_ant_arrays,
        per_ant_unflagged,
        per_ant_total,
        strided=strided,
        near_zero_ratio=near_zero_ratio,
    )

    if strided:
        warnings.append(
            f"Sampled {rows_scanned} of {rows_total} selected rows uniformly "
            f"(max_rows={max_rows} per DATA_DESC_ID)."
        )
    if summary["n_antennas_with_data"] == 0:
        warnings.append("No unflagged parallel-hand visibilities found in selection.")

    arr_flag = (
        "UNAVAILABLE"
        if summary["array_median_amp"] is None
        else ("PARTIAL" if strided else "COMPLETE")
    )
    arr_note = (
        "no unflagged parallel-hand visibilities in selection"
        if summary["array_median_amp"] is None
        else ("computed on uniformly strided rows (max_rows cap)" if strided else None)
    )

    data = {
        "datacolumn": col_name,
        "selected_fields": [field_names[fid] for fid in field_ids],
        "selected_spws": sorted(selected_spws_seen),
        "selected_scans": scan_ids,
        "exclude_autocorr": exclude_autocorr,
        "rows_total": rows_total,
        "rows_scanned": rows_scanned,
        "strided": strided,
        "n_antennas": summary["n_antennas"],
        "n_antennas_with_data": summary["n_antennas_with_data"],
        "array_median_amp": fmt_field(summary["array_median_amp"], flag=arr_flag, note=arr_note),
        "array_mad_amp": fmt_field(summary["array_mad_amp"], flag=arr_flag),
        "near_zero_ratio": summary["near_zero_ratio"],
        "near_zero_cutoff_amp": fmt_field(summary["near_zero_cutoff_amp"], flag=arr_flag),
        "per_antenna": summary["per_antenna"],
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
