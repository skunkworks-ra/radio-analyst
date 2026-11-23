"""
tools/corrected_stats.py — ms_corrected_stats

Per-field amplitude and phase statistics of a visibility data column
(CORRECTED_DATA by default) on the parallel-hand correlations over a chosen
channel range. The standard "is the calibration clean?" sanity check: after
applycal, a well-calibrated point-source calibrator should sit at its flux
density with low amplitude scatter and near-zero phase.

Measures only — returns numbers and flags, no verdicts. The skill compares the
returned amplitude against the expected flux density and the phase RMS against
its thresholds.

Reads in row chunks and samples uniformly above max_rows to bound memory.
Band-edge channels are excluded via chan_start/chan_end (the bandpass divides
out the edge roll-off and inflates noise there), so the caller passes the same
in-band range used for the gain/delay solves.
"""

from __future__ import annotations

import math

import numpy as np

from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import normalize_field_sel, response_envelope
from ms_inspect.util.selection import parallel_corr_by_ddid

TOOL_NAME = "ms_corrected_stats"

_DEFAULT_MAX_ROWS = 500_000
# CASA Stokes codes for parallel-hand correlations: RR, LL, XX, YY.
_PARALLEL_CODES = {5, 8, 9, 12}


def _parallel_indices(corr_codes: list[int]) -> list[int]:
    """Return the correlation-axis indices that are parallel-hand (RR/LL/XX/YY)."""
    idx = [i for i, c in enumerate(corr_codes) if int(c) in _PARALLEL_CODES]
    # Fall back to all correlations if none matched (unknown basis).
    return idx if idx else list(range(len(corr_codes)))


def _collect_channel_averaged_vis(
    data: np.ndarray,
    flag: np.ndarray,
    par_idx: list[int],
    chan_start: int | None,
    chan_end: int | None,
) -> np.ndarray:
    """Vector-average parallel-hand unflagged visibilities across [chan_start:chan_end]."""
    cs = 0 if chan_start is None else max(0, chan_start)
    ce = data.shape[1] if chan_end is None else min(data.shape[1], chan_end)
    if cs >= ce or not par_idx:
        return np.empty(0, dtype=complex)
    d = data[par_idx, cs:ce, :]
    good = ~flag[par_idx, cs:ce, :]
    cnt = good.sum(axis=1)  # [n_par, n_rows]
    dsum = np.where(good, d, 0).sum(axis=1)
    vavg = np.divide(dsum, cnt, out=np.full(dsum.shape, np.nan, dtype=complex), where=cnt > 0)
    vis = vavg.ravel()
    valid = np.isfinite(vis.real) & np.isfinite(vis.imag) & (np.abs(vis) > 0)
    return vis[valid]


def _stats_from_vis(vis: np.ndarray) -> dict:
    n_samples = int(vis.size)
    if n_samples == 0:
        return {
            "n_samples": 0,
            "amp_median": None,
            "amp_robust_std": None,
            "amp_p95": None,
            "phase_rms_deg": None,
        }
    amp = np.abs(vis)
    phase = np.angle(vis) * (180.0 / math.pi)
    median = float(np.median(amp))
    mad = float(np.median(np.abs(amp - median)))
    return {
        "n_samples": n_samples,
        "amp_median": round(median, 6),
        "amp_robust_std": round(1.4826 * mad, 6),
        "amp_p95": round(float(np.percentile(amp, 95)), 6),
        "phase_rms_deg": round(float(np.sqrt(np.mean(phase**2))), 3),
    }


def _field_stats(
    data: np.ndarray,
    flag: np.ndarray,
    par_idx: list[int],
    chan_start: int | None,
    chan_end: int | None,
) -> dict:
    """
    Compute amplitude/phase stats for one field's visibility block.

    Args:
        data: complex array [n_corr, n_chan, n_rows].
        flag: bool array, same shape (True = flagged).
        par_idx: parallel-hand correlation indices.
        chan_start, chan_end: inclusive/exclusive channel slice bounds
            (Python slice semantics); None means open-ended.

    The visibilities are vector-averaged over the channel range per
    (correlation, row) BEFORE computing statistics. This is essential: a single
    narrow channel on a faint calibrator has SNR ~ 1, so raw per-visibility
    amplitude is Rician-biased high and phase is near-random. Averaging the
    in-band channels boosts SNR by ~sqrt(n_chan) so the amplitude approaches the
    true flux density and the phase scatter reflects calibration, not noise.

    Returns a dict of plain Python floats/ints (no field() wrappers).
    """
    return _stats_from_vis(_collect_channel_averaged_vis(data, flag, par_idx, chan_start, chan_end))


def _corr_codes(ms_str: str) -> list[int]:
    """Read CORR_TYPE for the first polarization setup (legacy helper)."""
    from pathlib import Path

    with open_table(str(Path(ms_str) / "POLARIZATION")) as tb:
        return [int(x) for x in tb.getcell("CORR_TYPE", 0)]


def _field_id_map(ms_str: str) -> dict[int, str]:
    from pathlib import Path

    with open_table(str(Path(ms_str) / "FIELD")) as tb:
        names = list(tb.getcol("NAME"))
    return {i: n for i, n in enumerate(names)}


def run(
    ms_path: str,
    field: str = "",
    chan_start: int | None = None,
    chan_end: int | None = None,
    datacolumn: str = "CORRECTED_DATA",
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> dict:
    """
    Per-field parallel-hand amplitude/phase stats of a data column.

    Args:
        ms_path:    Path to the MS (with the requested data column populated).
        field:      CASA field-name selection (comma-separated) or '' for all.
        chan_start: First channel to include (default 0). Use to drop band edges.
        chan_end:   One past the last channel (default n_chan).
        datacolumn: 'CORRECTED_DATA' (default), 'DATA', or 'MODEL_DATA'.
        max_rows:   Per-field row cap; rows are uniformly sampled above this.

    Returns:
        Standard envelope with per_field amplitude median / robust std / p95 and
        phase RMS over the parallel-hand correlations and chosen channel range.
    """
    field = normalize_field_sel(field)
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    name_map = _field_id_map(ms_str)
    casa_calls.append("tb.open(FIELD) → NAME")
    wanted_names = {n.strip() for n in field.split(",") if n.strip()}
    target_ids = [fid for fid, nm in name_map.items() if (not wanted_names or nm in wanted_names)]
    if not target_ids:
        warnings.append(f"No fields matched selection '{field}'.")
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=ms_path,
            data={"per_field": [], "datacolumn": datacolumn},
            warnings=warnings,
            casa_calls=casa_calls,
        )

    corr_by_dd = parallel_corr_by_ddid(ms_str)
    par_idx_by_dd = [[idx for idx, _ in pairs] for pairs in corr_by_dd]
    casa_calls.append(
        f"tb.open(POLARIZATION, DATA_DESCRIPTION) -> parallel idx per DDID={par_idx_by_dd}"
    )

    per_field: list[dict] = []
    with open_table(ms_str) as tb:
        col_names = set(tb.colnames())
        if datacolumn not in col_names:
            from ms_inspect.exceptions import ComputationError

            raise ComputationError(
                f"{datacolumn} column not present in {ms_path}.",
                ms_path=ms_path,
            )
        for fid in target_ids:
            sub = tb.query(f"FIELD_ID == {fid}")
            try:
                n_rows = int(sub.nrows())
                dd_ids = sorted({int(x) for x in sub.getcol("DATA_DESC_ID")}) if n_rows else []
            finally:
                sub.close()
            if n_rows == 0:
                continue
            step = max(1, -(-n_rows // max_rows))
            if step > 1:
                warnings.append(f"Field {name_map[fid]}: {n_rows} rows sampled every {step}th.")
            # Query per DATA_DESC_ID so mixed-correlation (e.g. [RR,LL] setup +
            # [RR,RL,LR,LL] science) and mixed-channel SPWs never crash getcol or
            # mis-index cross-hands as parallel hands.
            vis_parts: list[np.ndarray] = []
            for dd in dd_ids:
                par_idx = (
                    par_idx_by_dd[dd] if dd < len(par_idx_by_dd) and par_idx_by_dd[dd] else [0]
                )
                dsub = tb.query(f"FIELD_ID == {fid} && DATA_DESC_ID == {dd}")
                try:
                    if int(dsub.nrows()) == 0:
                        continue
                    data = dsub.getcol(datacolumn, rowincr=step)
                    flag = dsub.getcol("FLAG", rowincr=step)
                finally:
                    dsub.close()
                vis_parts.append(
                    _collect_channel_averaged_vis(data, flag, par_idx, chan_start, chan_end)
                )
            pooled = np.concatenate(vis_parts) if vis_parts else np.empty(0, dtype=complex)
            stats = _stats_from_vis(pooled)
            casa_calls.append(
                f"tb.query(FIELD_ID=={fid} && DATA_DESC_ID in {dd_ids}) -> "
                f"{datacolumn}, FLAG (rowincr={step})"
            )
            flagged = stats["amp_median"] is None
            per_field.append(
                {
                    "field_id": fid,
                    "field_name": name_map[fid],
                    "n_samples": fmt_field(stats["n_samples"]),
                    "amp_median": fmt_field(
                        stats["amp_median"],
                        flag="UNAVAILABLE" if flagged else "COMPLETE",
                        note="all data flagged" if flagged else None,
                    ),
                    "amp_robust_std": fmt_field(stats["amp_robust_std"]),
                    "amp_p95": fmt_field(stats["amp_p95"]),
                    "phase_rms_deg": fmt_field(stats["phase_rms_deg"]),
                }
            )

    data_out = {
        "datacolumn": datacolumn,
        "chan_start": chan_start,
        "chan_end": chan_end,
        "parallel_corr_indices": par_idx,
        "averaging": "vector-averaged over the channel range per (corr, row) before stats",
        "per_field": per_field,
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data_out,
        warnings=warnings,
        casa_calls=casa_calls,
    )
