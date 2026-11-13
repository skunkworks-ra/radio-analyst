"""
tools/vis_amp_time_stats.py -- ms_vis_amp_time_stats

Compact per-integration visibility amplitude statistics across time on the
parallel-hand correlations (RR/LL or XX/YY). Replaces a 1.39 MB CASA visstat
per-integration JSON dump with an ~600 B summary + top-K outlier integrations.

Queries one DATA_DESC_ID at a time so Measurement Sets with mixed channel counts
across spectral windows never fail on getcol(), and streams in bounded row chunks
so memory stays O(n_integrations).

Measures only: returns numbers and CompletionFlags, zero verdicts or gates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ms_inspect.exceptions import ComputationError
from ms_inspect.tools.radiometer_estimate import parse_spw_selection
from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.conversions import mjd_seconds_to_utc
from ms_inspect.util.formatting import (
    field as fmt_field,
)
from ms_inspect.util.formatting import (
    normalize_field_sel,
    response_envelope,
)
from ms_inspect.util.selection import match_field_names, parallel_corr_by_ddid

TOOL_NAME = "ms_vis_amp_time_stats"

_ROW_CHUNK = 50_000


def summarize_integration_amplitudes(
    records: list[dict],
    *,
    top_k: int = 10,
) -> dict:
    """
    Pure summary over per-integration records:
    each item in ``records`` has keys:
      scan, time_mjd_s, field_id, field_name, sum_amp, npts, total_pts,
      and optional amp_median, amp_p95.
    """
    n_total = len(records)
    live = [r for r in records if int(r["npts"]) > 0]
    n_live = len(live)
    if n_live == 0:
        return {
            "n_integrations": n_total,
            "n_integrations_unflagged": 0,
            "median_amp": None,
            "mad_amp": None,
            "robust_sigma_amp": None,
            "median_npts": 0,
            "min_npts": 0,
            "max_npts": 0,
            "top_outliers": [],
        }

    means = np.array([float(r["sum_amp"]) / int(r["npts"]) for r in live], dtype=float)
    npts_arr = np.array([int(r["npts"]) for r in live], dtype=int)
    median_amp = float(np.median(means))
    mad_amp = float(np.median(np.abs(means - median_amp)))
    robust_sigma = 1.4826 * mad_amp
    median_npts = int(round(float(np.median(npts_arr))))
    min_npts = int(npts_arr.min())
    max_npts = int(npts_arr.max())

    order = np.argsort(-means)[: max(0, int(top_k))]
    outliers: list[dict] = []
    for idx in order:
        rec = live[int(idx)]
        mean_val = float(means[int(idx)])
        npts = int(rec["npts"])
        tot = int(rec["total_pts"])
        ratio = (mean_val / median_amp) if median_amp > 0 else None
        sigma_above = (
            (mean_val - median_amp) / robust_sigma
            if robust_sigma > 0
            else (0.0 if mean_val == median_amp else None)
        )
        t_mjd = float(rec["time_mjd_s"])
        outliers.append(
            {
                "time_mjd_s": round(t_mjd, 3),
                "utc": mjd_seconds_to_utc(t_mjd),
                "scan": int(rec["scan"]),
                "field_id": int(rec["field_id"]),
                "field_name": str(rec["field_name"]),
                "amp_mean": round(mean_val, 6),
                "amp_median": (
                    round(float(rec["amp_median"]), 6)
                    if rec.get("amp_median") is not None
                    else round(mean_val, 6)
                ),
                "amp_p95": (
                    round(float(rec["amp_p95"]), 6)
                    if rec.get("amp_p95") is not None
                    else round(mean_val, 6)
                ),
                "npts": npts,
                "unflagged_fraction": round(npts / tot, 6) if tot > 0 else 0.0,
                "ratio_to_median": round(ratio, 4) if ratio is not None else None,
                "sigma_above_median": round(sigma_above, 3) if sigma_above is not None else None,
            }
        )

    return {
        "n_integrations": n_total,
        "n_integrations_unflagged": n_live,
        "median_amp": round(median_amp, 6),
        "mad_amp": round(mad_amp, 6),
        "robust_sigma_amp": round(robust_sigma, 6),
        "median_npts": median_npts,
        "min_npts": min_npts,
        "max_npts": max_npts,
        "top_outliers": outliers,
    }


def _resolve_datacolumn(col: str) -> str:
    norm = col.strip().upper()
    aliases = {
        "CORRECTED": "CORRECTED_DATA",
        "CORRECTED_DATA": "CORRECTED_DATA",
        "DATA": "DATA",
        "MODEL": "MODEL_DATA",
        "MODEL_DATA": "MODEL_DATA",
    }
    if norm not in aliases:
        raise ValueError(
            f"Unsupported datacolumn={col!r}; use 'CORRECTED_DATA', 'DATA', or 'MODEL_DATA'."
        )
    return aliases[norm]


def run(
    ms_path: str,
    field: str = "",
    spw: str = "",
    datacolumn: str = "CORRECTED_DATA",
    top_k: int = 10,
) -> dict:
    """
    Per-integration parallel-hand visibility amplitude statistics vs time.

    Args:
        ms_path:    Path to the Measurement Set.
        field:      CASA field selection ('' = all fields).
        spw:        CASA SpW id/range selection ('' = all SpWs).
        datacolumn: 'CORRECTED_DATA' (default), 'DATA', or 'MODEL_DATA'.
        top_k:      Maximum number of highest-amplitude outlier integrations to return.
    """
    if top_k < 0:
        raise ComputationError(f"top_k must be >= 0, got {top_k}", ms_path=ms_path)
    try:
        col_name = _resolve_datacolumn(datacolumn)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

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

    # Key: (scan, round(time, 3), field_id) -> [exact_time, sum_amp, npts, total_pts]
    accum: dict[tuple[int, float, int], list[float]] = {}
    selected_ddids: list[tuple[int, list[int]]] = []
    fid_taql = ",".join(str(fid) for fid in field_ids)

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
            sub = tb.query(
                f"DATA_DESC_ID == {ddid} && FIELD_ID IN [{fid_taql}] && ANTENNA1 != ANTENNA2"
            )
            try:
                nrows = int(sub.nrows())
                if nrows == 0:
                    continue
                selected_ddids.append((ddid, par_idx))
                for start in range(0, nrows, _ROW_CHUNK):
                    cnt = min(_ROW_CHUNK, nrows - start)
                    scans = np.asarray(
                        sub.getcol("SCAN_NUMBER", startrow=start, nrow=cnt), dtype=int
                    )
                    times = np.asarray(sub.getcol("TIME", startrow=start, nrow=cnt), dtype=float)
                    fids = np.asarray(sub.getcol("FIELD_ID", startrow=start, nrow=cnt), dtype=int)
                    frow = np.asarray(sub.getcol("FLAG_ROW", startrow=start, nrow=cnt), dtype=bool)
                    vis = np.asarray(sub.getcol(col_name, startrow=start, nrow=cnt))[par_idx, :, :]
                    flg = np.asarray(sub.getcol("FLAG", startrow=start, nrow=cnt), dtype=bool)[
                        par_idx, :, :
                    ]
                    good = (~flg) & (~frow[None, None, :])
                    amp = np.abs(vis)
                    good &= np.isfinite(amp)

                    row_sum = np.where(good, amp, 0.0).sum(axis=(0, 1))
                    row_npts = good.sum(axis=(0, 1))
                    row_tot = good.shape[0] * good.shape[1]

                    t_q = np.round(times, 3)
                    # Group contiguous or unique (scan, t_q, fid) rows via structured array
                    keys_arr = np.empty(cnt, dtype=[("s", "i8"), ("t", "f8"), ("f", "i8")])
                    keys_arr["s"] = scans
                    keys_arr["t"] = t_q
                    keys_arr["f"] = fids
                    uniq, first_idx, inv, counts = np.unique(
                        keys_arr, return_index=True, return_inverse=True, return_counts=True
                    )
                    sums_u = np.bincount(inv, weights=row_sum)
                    npts_u = np.bincount(inv, weights=row_npts).astype(int)
                    for u_i, uk in enumerate(uniq):
                        key = (int(uk["s"]), float(uk["t"]), int(uk["f"]))
                        slot = accum.get(key)
                        tot_here = int(counts[u_i]) * row_tot
                        if slot is None:
                            accum[key] = [
                                float(times[first_idx[u_i]]),
                                float(sums_u[u_i]),
                                int(npts_u[u_i]),
                                tot_here,
                            ]
                        else:
                            slot[1] += float(sums_u[u_i])
                            slot[2] += int(npts_u[u_i])
                            slot[3] += tot_here
            finally:
                sub.close()

        casa_calls.append(f"tb.query(per DATA_DESC_ID) -> {col_name}, FLAG, TIME, SCAN_NUMBER")

        # Build sorted records by time.
        records: list[dict] = []
        for (sc, _tq, fid), (exact_t, s_amp, n_pts, t_pts) in sorted(
            accum.items(), key=lambda kv: (kv[1][0], kv[0][0], kv[0][2])
        ):
            records.append(
                {
                    "scan": sc,
                    "time_mjd_s": exact_t,
                    "t_q": _tq,
                    "field_id": fid,
                    "field_name": field_names[fid] if 0 <= fid < len(field_names) else str(fid),
                    "sum_amp": s_amp,
                    "npts": n_pts,
                    "total_pts": t_pts,
                }
            )

        # Compute exact amp_median and amp_p95 for the top_k highest-mean integrations.
        live_idx = [i for i, r in enumerate(records) if r["npts"] > 0]
        if live_idx and top_k > 0:
            live_means = np.array(
                [records[i]["sum_amp"] / records[i]["npts"] for i in live_idx], dtype=float
            )
            top_indices = [live_idx[int(j)] for j in np.argsort(-live_means)[:top_k]]
            for rec_idx in top_indices:
                rec = records[rec_idx]
                sc = rec["scan"]
                t0 = rec["time_mjd_s"]
                fid = rec["field_id"]
                pooled: list[np.ndarray] = []
                for ddid, par_idx in selected_ddids:
                    q = tb.query(
                        f"DATA_DESC_ID == {ddid} && SCAN_NUMBER == {sc} && FIELD_ID == {fid} "
                        f"&& ANTENNA1 != ANTENNA2 && ABS(TIME - {t0:.6f}) < 0.002"
                    )
                    try:
                        if q.nrows() == 0:
                            continue
                        frow = np.asarray(q.getcol("FLAG_ROW"), dtype=bool)
                        vis = np.asarray(q.getcol(col_name))[par_idx, :, :]
                        flg = np.asarray(q.getcol("FLAG"), dtype=bool)[par_idx, :, :]
                        good = (~flg) & (~frow[None, None, :])
                        amp = np.abs(vis[good])
                        amp = amp[np.isfinite(amp)]
                        if amp.size > 0:
                            pooled.append(amp)
                    finally:
                        q.close()
                if pooled:
                    all_amps = np.concatenate(pooled)
                    rec["amp_median"] = float(np.median(all_amps))
                    rec["amp_p95"] = float(np.percentile(all_amps, 95))

    summary = summarize_integration_amplitudes(records, top_k=top_k)
    all_flagged = summary["n_integrations_unflagged"] == 0
    unavail_note = "no unflagged parallel-hand visibilities in selection" if all_flagged else None
    flag_kind = "UNAVAILABLE" if all_flagged else "COMPLETE"

    data = {
        "datacolumn": col_name,
        "selected_fields": [field_names[fid] for fid in field_ids],
        "selected_spws": sorted({dd_spws[d] for d, _ in selected_ddids}),
        "n_integrations": fmt_field(summary["n_integrations"]),
        "n_integrations_unflagged": fmt_field(summary["n_integrations_unflagged"]),
        "median_amp": fmt_field(summary["median_amp"], flag=flag_kind, note=unavail_note),
        "mad_amp": fmt_field(summary["mad_amp"], flag=flag_kind),
        "robust_sigma_amp": fmt_field(summary["robust_sigma_amp"], flag=flag_kind),
        "median_npts": fmt_field(summary["median_npts"]),
        "min_npts": fmt_field(summary["min_npts"]),
        "max_npts": fmt_field(summary["max_npts"]),
        "top_k": int(top_k),
        "top_outliers": summary["top_outliers"],
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
