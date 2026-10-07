"""
tools/residual_stats.py — ms_residual_stats

Computes per-SPW and per-channel amplitude statistics of CORRECTED − MODEL
for a given field, on the parallel hands only (RR/LL or XX/YY). Use before
and after ms_apply_initial_rflag to characterise the residual distribution
and verify flagging thresholds.

Reads CORRECTED_DATA and MODEL_DATA columns via casatools table.
Only unflagged rows are included in statistics.
A max_rows limit prevents memory exhaustion on large MSs.
"""

from __future__ import annotations

import numpy as np

from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.selection import parallel_corr_by_ddid

TOOL_NAME = "ms_residual_stats"

_DEFAULT_MAX_ROWS = 500_000

# Wire-payload bound on the per-channel arrays, counted in channels across all
# SpWs. Same bound and sidecar behaviour as ms_spw_amp_severity.
_DEFAULT_MAX_PER_CHAN_RECORDS = 2000
_CHAN_KEYS = ("chan_n_unflagged", "chan_median_amp", "chan_robust_sigma", "chan_p95_amp")


def _spw_stats(amp: np.ndarray, flag: np.ndarray) -> dict:
    """Per-SpW and per-channel stats of residual amplitudes. CASA-free.

    amp, flag: (n_par, n_chan, n_rows), already sliced to the parallel hands.
    """
    n_flagged = int(flag.sum())
    good = ~flag
    n_unflagged = int(good.sum())
    n_chan = amp.shape[1]

    chan_median: list[float | None] = []
    chan_sigma: list[float | None] = []
    chan_p95: list[float | None] = []
    chan_n: list[int] = []
    for ch in range(n_chan):
        v = amp[:, ch, :][good[:, ch, :]]
        chan_n.append(int(v.size))
        if v.size == 0:
            chan_median.append(None)
            chan_sigma.append(None)
            chan_p95.append(None)
            continue
        med = float(np.median(v))
        chan_median.append(round(med, 6))
        chan_sigma.append(round(1.4826 * float(np.median(np.abs(v - med))), 6))
        chan_p95.append(round(float(np.percentile(v, 95)), 6))

    out: dict = {"n_unflagged": fmt_field(n_unflagged), "n_flagged": fmt_field(n_flagged)}
    if n_unflagged == 0:
        out.update(
            {
                "median_amp": fmt_field(None, flag="UNAVAILABLE", note="all data flagged"),
                "std_amp": fmt_field(None, flag="UNAVAILABLE"),
                "p95_amp": fmt_field(None, flag="UNAVAILABLE"),
            }
        )
    else:
        amp_good = amp[good]
        out.update(
            {
                "median_amp": fmt_field(round(float(np.median(amp_good)), 6)),
                "std_amp": fmt_field(round(float(np.std(amp_good)), 6)),
                "p95_amp": fmt_field(round(float(np.percentile(amp_good, 95)), 6)),
            }
        )
    out.update(
        {
            "chan_n_unflagged": chan_n,
            "chan_median_amp": chan_median,
            "chan_robust_sigma": chan_sigma,
            "chan_p95_amp": chan_p95,
        }
    )
    return out


def _bound_chan_payload(
    data: dict,
    max_per_chan_records: int,
    sidecar_path: str,
    warnings: list[str],
) -> dict:
    """Drop the chan_* arrays from every SpW if the total channel count exceeds
    max_per_chan_records, writing the full data to a JSON sidecar instead.

    All-or-nothing, as in ms_spw_amp_severity: either every SpW keeps its
    chan_* arrays or none does. Per-SpW aggregates are never touched. The
    sidecar is written only when truncation occurs.
    """
    import json as _json

    per_spw = data["per_spw"]
    total = sum(len(e.get("chan_median_amp", [])) for e in per_spw)
    data["n_per_chan_records"] = total
    data["max_per_chan_records"] = max_per_chan_records
    if max_per_chan_records <= 0 or total <= max_per_chan_records:
        data["per_chan_truncated"] = fmt_field(False)
        return data

    written: str | None = sidecar_path
    try:
        with open(sidecar_path, "w") as fh:
            _json.dump(data, fh, separators=(",", ":"), default=str)
    except OSError as exc:
        written = None
        warnings.append(
            f"Could not write per-channel sidecar to {sidecar_path}: {exc}. "
            "The per-channel arrays are dropped from this response and are not "
            "on disk; re-run with max_per_chan_records=0 to receive them inline."
        )

    for e in per_spw:
        e["n_chan_omitted"] = len(e.get("chan_median_amp", []))
        for k in _CHAN_KEYS:
            e.pop(k, None)

    data["per_chan_truncated"] = fmt_field(
        True,
        "PARTIAL",
        note=(
            f"{total} per-channel records exceeded max_per_chan_records="
            f"{max_per_chan_records}; chan_* arrays dropped from all "
            f"{len(per_spw)} SpW entries. Per-SpW aggregates are complete."
        ),
    )
    data["detail_path"] = fmt_field(written, flag="COMPLETE" if written else "UNAVAILABLE")
    data["detail_note"] = (
        "Full per-channel arrays (all SpWs) written to detail_path as compact "
        "JSON. Alternatively re-run with a larger max_per_chan_records, or 0 "
        "for no bound."
        if written
        else "Sidecar write failed; re-run with max_per_chan_records=0 to "
        "receive the per-channel arrays inline."
    )
    return data


def run(
    ms_path: str,
    field_id: int,
    max_rows: int = _DEFAULT_MAX_ROWS,
    max_per_chan_records: int = _DEFAULT_MAX_PER_CHAN_RECORDS,
) -> dict:
    """
    Compute per-SPW amplitude stats of CORRECTED − MODEL for a field.

    Args:
        ms_path:  Path to the MS (calibrators.ms with CORRECTED + MODEL).
        field_id: Integer FIELD_ID to analyse (use ms_field_list to find it).
        max_rows: Maximum number of rows to read (default 500 000).
                  Rows are sampled uniformly if the MS is larger.
        max_per_chan_records: Wire-payload bound on the chan_* arrays, counted
                  in channels across all SpWs. Above it the arrays are dropped
                  from every SpW and written to a JSON sidecar next to the MS.
                  0 disables the bound.

    Returns:
        Standard response envelope with per-spw amplitude statistics of
        CORRECTED−MODEL (parallel hands): median, std, p95, n_unflagged,
        n_flagged, plus per-channel chan_median_amp / chan_robust_sigma /
        chan_p95_amp / chan_n_unflagged arrays.
    """
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # Read total row count
    # ------------------------------------------------------------------
    with open_table(ms_str) as tb:
        n_total = int(tb.nrows())
        casa_calls.append("tb.open(MAIN) → nrows()")

    if n_total == 0:
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=ms_path,
            data={"per_spw": [], "n_rows_read": fmt_field(0)},
            warnings=["MS MAIN table has zero rows."],
            casa_calls=casa_calls,
        )

    # ------------------------------------------------------------------
    # DDID → SpW and parallel-hand correlations
    # ------------------------------------------------------------------
    with open_table(ms_str + "/DATA_DESCRIPTION") as tb:
        dd_to_spw = [int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")]
    corr_by_dd = parallel_corr_by_ddid(ms_str)
    casa_calls.append("tb.open(DATA_DESCRIPTION, POLARIZATION) → SpW + parallel-hand CORR_TYPE")

    per_spw: list[dict] = []
    with open_table(ms_str) as tb:
        col_names = set(tb.colnames())
        if "CORRECTED_DATA" not in col_names:
            from ms_inspect.exceptions import ComputationError

            raise ComputationError(
                "CORRECTED_DATA column not present. Run initial_bandpass.py first.",
                ms_path=ms_path,
            )
        if "MODEL_DATA" not in col_names:
            warnings.append(
                "MODEL_DATA column not present. Run setjy.py first. "
                "Residual stats will not be available."
            )
            return response_envelope(
                tool_name=TOOL_NAME,
                ms_path=ms_path,
                data={"per_spw": [], "n_rows_read": fmt_field(0)},
                warnings=warnings,
                casa_calls=casa_calls,
            )

        sub = tb.query(f"FIELD_ID == {field_id}")
        n_field_rows = int(sub.nrows())
        dd_ids = np.unique(sub.getcol("DATA_DESC_ID")) if n_field_rows else np.array([], int)
        sub.close()
        casa_calls.append(f"tb.query(FIELD_ID=={field_id}) → {n_field_rows} rows")

        if n_field_rows == 0:
            warnings.append(f"No rows found for FIELD_ID={field_id}.")
            return response_envelope(
                tool_name=TOOL_NAME,
                ms_path=ms_path,
                data={"per_spw": [], "n_rows_read": fmt_field(0)},
                warnings=warnings,
                casa_calls=casa_calls,
            )

        # One stride over the whole field keeps the total read near max_rows.
        step = max(1, -(-n_field_rows // max_rows))
        if step > 1:
            warnings.append(
                f"MS has {n_field_rows} rows for this field; reading every {step}th row. "
                "Increase max_rows for higher accuracy."
            )

        n_rows_read = 0
        # One DDID at a time: DDIDs with different channel counts cannot share
        # one getcol array.
        for dd in dd_ids:
            dd = int(dd)
            par = corr_by_dd[dd]
            if not par:
                warnings.append(f"DATA_DESC_ID {dd} has no parallel-hand correlation; skipped.")
                continue
            par_idx = [i for i, _ in par]
            sub = tb.query(f"FIELD_ID == {field_id} && DATA_DESC_ID == {dd}")
            try:
                corrected = sub.getcol("CORRECTED_DATA", rowincr=step)
                model = sub.getcol("MODEL_DATA", rowincr=step)
                flag = sub.getcol("FLAG", rowincr=step)
            finally:
                sub.close()
            n_rows_read += int(corrected.shape[2])
            amp = np.abs(corrected[par_idx] - model[par_idx])  # (n_par, n_chan, n_rows)
            stats = _spw_stats(amp, flag[par_idx].astype(bool))
            per_spw.append(
                {
                    "data_desc_id": dd,
                    "spw_id": dd_to_spw[dd],
                    "correlations_used": [name for _, name in par],
                    **stats,
                }
            )
        casa_calls.append(
            f"tb.query(FIELD_ID=={field_id} && DATA_DESC_ID==dd) → "
            f"getcol(CORRECTED_DATA, MODEL_DATA, FLAG, rowincr={step}) per DDID"
        )

    data = {
        "field_id": field_id,
        "n_rows_read": fmt_field(n_rows_read),
        "n_data_desc_ids": fmt_field(len(dd_ids)),
        "note": (
            "|CORRECTED - MODEL| on the parallel hands only, pooled. Per-SpW "
            "median/std/p95 pool all channels; chan_* arrays give the same "
            "per channel (robust_sigma = 1.4826 * MAD), null where fully flagged."
        ),
        "per_spw": per_spw,
    }

    data = _bound_chan_payload(
        data,
        max_per_chan_records=max_per_chan_records,
        sidecar_path=f"{ms_str}.residual_stats.field{field_id}.json",
        warnings=warnings,
    )

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
