"""
calsol_stats.py — ms_calsol_stats

Inspects a CASA calibration table and returns structured numerical diagnostics
sufficient for the skill to make go/no-go decisions after a calibration solve.

Supports G Jones (complex gain), B Jones (bandpass), and K Jones (delay) tables.
Returns per-(antenna, SPW, field) arrays. Reads one (SPW, field) slice at a time
to bound memory use on large tables.

No interpretation — numbers and flags only.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ms_inspect.util.casa_context import open_table
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_calsol_stats"

# Jones types supported in this tool. Classified by storage/behaviour rather than
# by an explicit allow-list so the polcal tables (KCROSS, Df/D, Xf/X) are covered:
#   - delay types     store a real delay in FPARAM (K, KCROSS)
#   - everything else stores a complex gain/leakage/phase in CPARAM
#   - frequency-dependent types carry a per-channel axis (B, Df, Xf, Bf)
_SUPPORTED_TYPES = {"G", "B", "K", "Kcross", "KCROSS", "Df", "D", "Dflls", "Xf", "X"}


def _is_delay_type(table_type: str) -> bool:
    """True for delay tables (real FPARAM): K (per-antenna) and KCROSS (cross-hand)."""
    return table_type.startswith("K")


def _is_freq_dependent_type(table_type: str) -> bool:
    """True for tables with a per-channel solution axis (B, Df, Xf, Bf)."""
    return table_type == "B" or table_type.startswith(("Df", "Xf", "Bf"))


def _is_complex_type(table_type: str) -> bool:
    """True for complex CPARAM tables (gain, bandpass, leakage, position angle)."""
    return not _is_delay_type(table_type)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nan_list(shape: tuple[int, ...]) -> list:
    """Return a nested list of NaN with the given shape."""
    arr = np.full(shape, np.nan)
    return arr.tolist()


def _phase_scatter_deg(phase_rad: np.ndarray) -> tuple[np.ndarray, list[str | None]]:
    """Phase scatter per correlation, in degrees, and the axis it was taken over.

    phase_rad: [n_corr, n_chan, n_rows], NaN where flagged.

    'time': for each (corr, chan) the circular mean over time is removed and the
    RMS of the wrapped deviations is taken, pooled over channels. A steady
    offset gives 0, not the offset. Used when any channel of the corr has at
    least 2 unflagged times.

    'channel': otherwise (one solution in time, e.g. a bandpass), the corr's
    circular mean over all its samples is removed and the RMS is taken across
    channels. A leftover delay shows here as a phase slope across the band.

    A corr with fewer than 2 unflagged samples in total has no scatter: NaN,
    axis None.
    """
    n_corr = phase_rad.shape[0]
    out = np.full(n_corr, math.nan)
    axes: list[str | None] = [None] * n_corr
    valid = np.isfinite(phase_rad)
    z = np.where(valid, np.exp(1j * np.where(valid, phase_rad, 0.0)), 0.0)
    n_t = valid.sum(axis=2)  # [n_corr, n_chan]
    mean = z.sum(axis=2)
    ref = np.where(np.abs(mean) > 0, mean / np.where(np.abs(mean) > 0, np.abs(mean), 1.0), 1.0)
    dev = np.angle(z * np.conj(ref)[:, :, np.newaxis])  # wrapped, [-pi, pi]
    use = valid & (n_t >= 2)[:, :, np.newaxis]
    for c in range(n_corr):
        d = dev[c][use[c]]
        if d.size:
            out[c] = float(np.sqrt(np.mean(d**2))) * (180.0 / math.pi)
            axes[c] = "time"
            continue
        zc = z[c][valid[c]]
        if zc.size >= 2:
            m = zc.sum()
            d = np.angle(zc * np.conj(m / abs(m))) if abs(m) > 0 else np.angle(zc)
            out[c] = float(np.sqrt(np.mean(d**2))) * (180.0 / math.pi)
            axes[c] = "channel"
    return out, axes


def _phase_mean_deg(phase_rad: np.ndarray) -> float:
    """Circular mean of the phases in degrees, ignoring NaN."""
    valid = phase_rad[~np.isnan(phase_rad)]
    if valid.size == 0:
        return math.nan
    return float(np.angle(np.mean(np.exp(1j * valid)))) * (180.0 / math.pi)


def _safe_mean(arr: np.ndarray) -> float:
    valid = arr[~np.isnan(arr)]
    return float(np.mean(valid)) if valid.size > 0 else math.nan


def _safe_std(arr: np.ndarray) -> float:
    valid = arr[~np.isnan(arr)]
    return float(np.std(valid)) if valid.size > 1 else math.nan


# ---------------------------------------------------------------------------
# Metadata readers
# ---------------------------------------------------------------------------


def _read_ant_names(caltable_path: str) -> list[str]:
    ant_sub = str(Path(caltable_path) / "ANTENNA")
    with open_table(ant_sub) as tb:
        return list(tb.getcol("NAME"))


def _read_field_names(caltable_path: str) -> dict[int, str]:
    """Return {field_id: field_name} from the FIELD subtable."""
    field_sub = str(Path(caltable_path) / "FIELD")
    with open_table(field_sub) as tb:
        names = list(tb.getcol("NAME"))
    return {i: n for i, n in enumerate(names)}


def _read_table_type(caltable_path: str) -> str:
    """Read VisCal keyword and strip ' Jones' suffix."""
    with open_table(caltable_path) as tb:
        keywords = tb.getkeywords()
    viscal = keywords.get("VisCal", "")
    return viscal.replace(" Jones", "").strip()


def _read_axis_ids(caltable_path: str) -> tuple[list[int], list[int]]:
    """Return (sorted spw_ids, sorted field_ids) present in the main table."""
    with open_table(caltable_path) as tb:
        spw_ids = sorted(set(int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")))
        field_ids = sorted(set(int(x) for x in tb.getcol("FIELD_ID")))
    return spw_ids, field_ids


# ---------------------------------------------------------------------------
# Per-(spw, field) slice processor
# ---------------------------------------------------------------------------


def _process_slice(
    caltable_path: str,
    spw: int,
    field: int,
    ant_names: list[str],
    table_type: str,
    n_chan_max: int,
) -> dict:
    """
    Read one (SPW, field) slice and compute per-antenna stats.

    Returns a dict keyed by antenna index with sub-dicts containing:
        flagged_frac, snr_mean, amp_mean, amp_std, phase_mean_deg (circular),
        phase_rms_deg (worst correlation's scatter over time),
        phase_rms_deg_per_corr, amp_array (shape [n_chan_max]), delay_ns (K only),
        n_rows.
    """
    n_ant = len(ant_names)
    result: dict[int, dict] = {}

    with open_table(caltable_path) as tb:
        sub = tb.query(f"SPECTRAL_WINDOW_ID == {spw} AND FIELD_ID == {field}")
        try:
            if sub.nrows() == 0:
                return {}

            ant1 = sub.getcol("ANTENNA1").astype(int)
            flag = sub.getcol("FLAG")  # [n_corr, n_chan, n_rows]
            snr = sub.getcol("SNR")  # [n_corr, n_chan, n_rows]

            param_col = "FPARAM" if _is_delay_type(table_type) else "CPARAM"
            param = sub.getcol(param_col)  # [n_corr, n_chan, n_rows]
        finally:
            sub.close()

    # pivot: per antenna
    for a_idx in range(n_ant):
        mask = ant1 == a_idx
        if not np.any(mask):
            continue

        p_ant = param[:, :, mask]  # [n_corr, n_chan, n_ant_rows]
        f_ant = flag[:, :, mask]  # bool
        s_ant = snr[:, :, mask]

        n_total = f_ant.size
        n_flagged = int(np.sum(f_ant))
        flagged_frac = n_flagged / n_total if n_total > 0 else math.nan

        snr_all = s_ant.ravel().astype(float)
        snr_all[np.isnan(snr_all)] = math.nan

        entry: dict = {
            "n_rows": int(np.sum(mask)),
            "flagged_frac": flagged_frac,
            "snr_mean": _safe_mean(snr_all),
        }

        if _is_delay_type(table_type):
            # FPARAM shape [n_corr, 1, n_rows] — delay in nanoseconds
            # (K = per-antenna delay; KCROSS = single R-L cross-hand delay)
            delay = p_ant[:, 0, :].astype(float)  # [n_corr, n_rows]
            delay[f_ant[:, 0, :]] = math.nan
            entry["delay_ns"] = delay.tolist()  # [n_corr, n_rows] → averaged later
        else:
            # CPARAM — complex
            p_f = p_ant.astype(complex)
            p_f[f_ant] = complex(math.nan, math.nan)

            amp = np.abs(p_f)  # [n_corr, n_chan, n_rows]
            phase = np.angle(p_f)  # radians

            amp_flat = amp.ravel()
            phase_flat = phase.ravel()

            entry["amp_mean"] = _safe_mean(amp_flat)
            entry["amp_std"] = _safe_std(amp_flat)
            entry["phase_mean_deg"] = _phase_mean_deg(phase_flat)
            per_corr, axes = _phase_scatter_deg(phase)
            entry["phase_rms_deg_per_corr"] = per_corr.tolist()
            entry["phase_rms_axes"] = [a for a in axes if a]
            entry["phase_rms_deg"] = (
                float(np.nanmax(per_corr)) if np.any(np.isfinite(per_corr)) else math.nan
            )

            # full amplitude array averaged over corr axis → [n_chan]
            if np.all(np.isnan(amp)):
                amp_chan = np.full(amp.shape[1], math.nan)
            else:
                amp_chan = np.nanmean(amp, axis=(0, 2))  # [n_chan]
            # pad to n_chan_max
            padded = np.full(n_chan_max, math.nan)
            padded[: len(amp_chan)] = amp_chan
            entry["amp_array"] = padded.tolist()

        result[a_idx] = entry

    return result


# ---------------------------------------------------------------------------
# Main run()
# ---------------------------------------------------------------------------


# Max detail rows returned per outlier kind in the tool response. The full
# per-solution enumeration is unbounded — a single dead antenna yields one row
# per SPW×field, which floods the response (hundreds of rows on real data). The
# response keeps the worst offenders plus per-antenna rollups, which is exactly
# what the go/no-go gates key on (which antennas, how many). The complete
# enumeration is recoverable from the raw NPZ sidecar via ms_calsol_stats_detail.
_OUTLIER_DETAIL_CAP = 15

# Minimum finite values for a robust (median, MAD) reference.
_MIN_GROUP_N = 3


def _rollup(entries: list[dict]) -> dict:
    """Per-antenna count rollup, ordered by count descending."""
    by_ant: dict[str, int] = {}
    for e in entries:
        by_ant[e["antenna"]] = by_ant.get(e["antenna"], 0) + 1
    return dict(sorted(by_ant.items(), key=lambda kv: kv[1], reverse=True))


def _robust(vals: np.ndarray) -> tuple[float, float, int] | None:
    """(median, 1.4826*MAD, n) of the finite values, or None if n < 3 or MAD = 0."""
    v = vals[np.isfinite(vals)]
    if v.size < _MIN_GROUP_N:
        return None
    med = float(np.median(v))
    sigma = 1.4826 * float(np.median(np.abs(v - med)))
    return (med, sigma, int(v.size)) if sigma > 0 else None


def amp_outlier_scan(
    amp: np.ndarray,
    ant_names,
    spw_ids,
    field_names,
    amp_sigma: float,
) -> tuple[list[dict], list[dict]]:
    """Amplitude outliers on amp[ant, spw, field], judged per (field, SpW).

    Before fluxscale each field's gains sit at their own level, and a phase
    cal's spectral index tilts that level across a wide band, so one pooled
    median flags whole fields. Each antenna is judged against the median and
    1.4826*MAD of its own (field, SpW) group; n_sigma_field gives the same
    against the whole field.

    Returns (rows, reference). rows: outliers worst first, each with the
    group and field reference values. reference: one entry per field with
    per-SpW arrays (aligned to spw_ids) of the group median, sigma, n, and the
    signed offset of the group median from the field median in field sigmas,
    which shows a whole SpW moving (wideband RFI) even when no antenna is an
    outlier. A group with fewer than 3 finite values or MAD = 0 is null in the
    arrays and contributes no outliers.
    """
    amp = np.asarray(amp, dtype=float)
    while amp.ndim < 3:
        amp = amp[..., np.newaxis]
    _, n_spw, n_field = amp.shape
    rows: list[dict] = []
    reference: list[dict] = []
    for fi in range(n_field):
        fname = str(field_names[fi]) if fi < len(field_names) else ""
        fref = _robust(amp[:, :, fi])
        f_med, f_sig = (fref[0], fref[1]) if fref else (None, None)
        spw_med: list[float | None] = []
        spw_sig: list[float | None] = []
        spw_n: list[int] = []
        spw_off: list[float | None] = []
        for si in range(n_spw):
            col = amp[:, si, fi]
            spw_n.append(int(np.isfinite(col).sum()))
            gref = _robust(col)
            if gref is None:
                spw_med.append(None)
                spw_sig.append(None)
                spw_off.append(None)
                continue
            g_med, g_sig, _ = gref
            spw_med.append(round(g_med, 4))
            spw_sig.append(round(g_sig, 4))
            spw_off.append(round((g_med - f_med) / f_sig, 2) if fref else None)
            for ai, val in enumerate(col):
                if not np.isfinite(val):
                    continue
                n_sigma = abs(val - g_med) / g_sig
                if n_sigma <= amp_sigma:
                    continue
                rows.append(
                    {
                        "antenna": str(ant_names[ai]),
                        "spw": int(spw_ids[si]) if si < len(spw_ids) else si,
                        "field": fname,
                        "amp": round(float(val), 4),
                        "n_sigma": round(float(n_sigma), 2),
                        "ref_median": round(g_med, 4),
                        "ref_sigma": round(g_sig, 4),
                        "n_sigma_field": (round(abs(val - f_med) / f_sig, 2) if fref else None),
                    }
                )
        reference.append(
            {
                "field": fname,
                "field_median": round(f_med, 4) if fref else None,
                "field_sigma": round(f_sig, 4) if fref else None,
                "spw_median": spw_med,
                "spw_sigma": spw_sig,
                "spw_n": spw_n,
                "spw_offset_n_sigma_field": spw_off,
            }
        )
    rows.sort(key=lambda e: e["n_sigma"], reverse=True)
    return rows, reference


def _compute_outliers(
    snr_mean_arr: np.ndarray | None,
    amp_mean_arr: np.ndarray | None,
    ant_names: list[str],
    spw_ids: list[int],
    field_names: list[str],
    snr_min: float,
    amp_sigma_thresh: float,
) -> dict:
    """Compute low_snr and amp_outliers, capped + rolled up per antenna.

    ``low_snr``/``amp_outliers`` stay lists (worst rows first, capped at
    ``_OUTLIER_DETAIL_CAP``) for backward compatibility. Sibling fields give the
    full picture cheaply: ``*_n_total`` (count of all flagged solutions),
    ``*_n_antennas`` (distinct antennas — drives the >20%-of-antennas gate),
    ``*_by_antenna`` (per-antenna counts), ``*_truncated`` (whether rows were
    dropped). Full per-solution detail lives in the NPZ sidecar.
    """
    low_snr: list[dict] = []
    if snr_mean_arr is not None:
        flat = snr_mean_arr.reshape(-1)
        shape = snr_mean_arr.shape
        for flat_idx, val in enumerate(flat):
            if np.isfinite(val) and val < snr_min:
                idx = np.unravel_index(flat_idx, shape)
                low_snr.append(
                    {
                        "antenna": str(ant_names[idx[0]]),
                        "spw": spw_ids[idx[1]] if len(shape) > 1 else 0,
                        "field": field_names[idx[2]] if len(shape) > 2 else "",
                        "snr": round(float(val), 3),
                    }
                )
    low_snr.sort(key=lambda e: e["snr"])  # worst (lowest SNR) first
    low_snr_by_ant = _rollup(low_snr)

    amp_outliers: list[dict] = []
    amp_reference: list[dict] = []
    if amp_mean_arr is not None:
        amp_outliers, amp_reference = amp_outlier_scan(
            amp_mean_arr, ant_names, spw_ids, field_names, amp_sigma_thresh
        )
    amp_by_ant = _rollup(amp_outliers)

    return {
        "low_snr": low_snr[:_OUTLIER_DETAIL_CAP],
        "low_snr_n_total": len(low_snr),
        "low_snr_n_antennas": len(low_snr_by_ant),
        "low_snr_by_antenna": low_snr_by_ant,
        "low_snr_truncated": len(low_snr) > _OUTLIER_DETAIL_CAP,
        "amp_outliers": amp_outliers[:_OUTLIER_DETAIL_CAP],
        "amp_outliers_n_total": len(amp_outliers),
        "amp_outliers_n_antennas": len(amp_by_ant),
        "amp_outliers_by_antenna": amp_by_ant,
        "amp_outliers_truncated": len(amp_outliers) > _OUTLIER_DETAIL_CAP,
        "amp_reference": amp_reference,
        "thresholds": {
            "snr_min": snr_min,
            "amp_sigma": amp_sigma_thresh,
        },
    }


def _save_raw_npz(
    npz_path: str,
    ant_names: list[str],
    spw_ids: list[int],
    field_ids: list[int],
    field_names: list[str],
    arrays: dict[str, np.ndarray | None],
    thresholds: dict,
) -> None:
    """Write the complete raw per-(antenna, SPW, field) arrays to an NPZ sidecar.

    This is the escape hatch behind the response's bounded summary: the full,
    uncapped detail every gate could ever need, queryable via
    ms_calsol_stats_detail. Always written, deterministic per run.
    """
    payload: dict[str, np.ndarray] = {
        "ant_names": np.array(ant_names),
        "spw_ids": np.array(spw_ids),
        "field_ids": np.array(field_ids),
        "field_names": np.array(field_names),
        "snr_min": np.array(thresholds["snr_min"]),
        "amp_sigma": np.array(thresholds["amp_sigma"]),
    }
    for key, arr in arrays.items():
        if arr is not None:
            payload[key] = np.asarray(arr)
    np.savez(npz_path, **payload)


def run(
    caltable_path: str, snr_min: float = 3.0, amp_sigma: float = 5.0, verbosity: str = "compact"
) -> dict:
    """
    Inspect a CASA calibration table and return per-(antenna, SPW, field) stats.

    Args:
        caltable_path: Path to the caltable directory (e.g. gain.g, BP0.b, delay.k).

    Returns:
        Standard response envelope. ms_path field contains caltable_path.
    """
    p = Path(caltable_path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        from ms_inspect.util.formatting import error_envelope

        return error_envelope(
            TOOL_NAME,
            caltable_path,
            "CALTABLE_NOT_FOUND",
            f"Calibration table not found: {p}",
        )

    casa_calls: list[str] = []
    warnings: list[str] = []

    # --- metadata ---
    table_type = _read_table_type(caltable_path)
    casa_calls.append(f"tb.getkeywords() → VisCal='{table_type} Jones'")

    if table_type not in _SUPPORTED_TYPES:
        warnings.append(
            f"VisCal type '{table_type}' is not explicitly recognised; treating it "
            f"as a {'delay (FPARAM)' if _is_delay_type(table_type) else 'complex (CPARAM)'} "
            "table. Verify the reported quantities make sense for this table type."
        )

    ant_names = _read_ant_names(caltable_path)
    casa_calls.append("tb.open(ANTENNA) → NAME")

    field_name_map = _read_field_names(caltable_path)
    casa_calls.append("tb.open(FIELD) → NAME")

    spw_ids, field_ids = _read_axis_ids(caltable_path)
    casa_calls.append("tb.getcol(SPECTRAL_WINDOW_ID, FIELD_ID) → axis ids")

    n_ant = len(ant_names)
    n_spw = len(spw_ids)
    n_field = len(field_ids)
    field_names = [field_name_map.get(f, f"FIELD_{f}") for f in field_ids]

    # spw_id → index and field_id → index lookups
    spw_idx = {s: i for i, s in enumerate(spw_ids)}
    field_idx = {f: i for i, f in enumerate(field_ids)}

    # determine n_chan_max for frequency-dependent tables (B, Df, Xf — amp_array padding)
    n_chan_max = 1
    if _is_freq_dependent_type(table_type):
        with open_table(caltable_path) as tb:
            sub0 = tb.query(f"SPECTRAL_WINDOW_ID == {spw_ids[0]}")
            try:
                if sub0.nrows() > 0:
                    n_chan_max = sub0.getcol("CPARAM").shape[1]
            finally:
                sub0.close()
        # refine: find global max channels across all SPWs
        n_chan_max_global = n_chan_max
        for spw in spw_ids[1:]:
            with open_table(caltable_path) as tb:
                sub = tb.query(f"SPECTRAL_WINDOW_ID == {spw}")
                try:
                    if sub.nrows() > 0:
                        nc = sub.getcol("CPARAM").shape[1]
                        n_chan_max_global = max(n_chan_max_global, nc)
                finally:
                    sub.close()
        n_chan_max = n_chan_max_global
        casa_calls.append(f"tb.query per SPW → n_chan_max={n_chan_max}")

    # --- allocate output arrays ---
    shape = (n_ant, n_spw, n_field)
    flagged_frac_arr = np.full(shape, math.nan)
    snr_mean_arr = np.full(shape, math.nan)

    _complex = _is_complex_type(table_type)
    _freq_dep = _is_freq_dependent_type(table_type)
    amp_mean_arr = np.full(shape, math.nan) if _complex else None
    amp_std_arr = np.full(shape, math.nan) if _complex else None
    phase_mean_arr = np.full(shape, math.nan) if _complex else None
    phase_rms_arr = np.full(shape, math.nan) if _complex else None
    amp_array_4d = np.full((n_ant, n_spw, n_field, n_chan_max), math.nan) if _freq_dep else None

    # delay: store mean delay per (ant, spw, field, n_corr) — inferred from first slice
    delay_arr: np.ndarray | None = None
    # phase scatter per correlation, same lazy allocation
    phase_rms_corr_arr: np.ndarray | None = None
    phase_rms_axes: set[str] = set()

    # --- iterate (spw, field) slices ---
    for spw in spw_ids:
        si = spw_idx[spw]
        for fid in field_ids:
            fi = field_idx[fid]

            slice_data = _process_slice(caltable_path, spw, fid, ant_names, table_type, n_chan_max)
            casa_calls.append(
                f"tb.query(SPECTRAL_WINDOW_ID=={spw} AND FIELD_ID=={fid}) → {len(slice_data)} antennas"
            )

            for a_idx, entry in slice_data.items():
                flagged_frac_arr[a_idx, si, fi] = entry["flagged_frac"]
                snr_mean_arr[a_idx, si, fi] = entry["snr_mean"]

                if _complex:
                    amp_mean_arr[a_idx, si, fi] = entry["amp_mean"]
                    amp_std_arr[a_idx, si, fi] = entry["amp_std"]
                    phase_mean_arr[a_idx, si, fi] = entry["phase_mean_deg"]
                    phase_rms_arr[a_idx, si, fi] = entry["phase_rms_deg"]
                    phase_rms_axes.update(entry["phase_rms_axes"])
                    pc = entry["phase_rms_deg_per_corr"]
                    if phase_rms_corr_arr is None:
                        phase_rms_corr_arr = np.full((n_ant, n_spw, n_field, len(pc)), math.nan)
                    phase_rms_corr_arr[a_idx, si, fi, : len(pc)] = pc
                    if _freq_dep and amp_array_4d is not None:
                        amp_array_4d[a_idx, si, fi, :] = entry["amp_array"]

                if _is_delay_type(table_type):
                    delay_data = np.array(entry["delay_ns"])  # [n_corr, n_rows]
                    n_corr = delay_data.shape[0]
                    if delay_arr is None:
                        delay_arr = np.full((n_ant, n_spw, n_field, n_corr), math.nan)
                    delay_arr[a_idx, si, fi, :] = np.nanmean(delay_data, axis=1)

    # --- scalar summaries ---
    overall_flagged_frac = float(np.nanmean(flagged_frac_arr))
    lost_mask = np.all(flagged_frac_arr == 1.0, axis=(1, 2))  # [n_ant]
    antennas_lost = [ant_names[i] for i in range(n_ant) if lost_mask[i]]
    n_antennas_lost = len(antennas_lost)

    delay_rms_ns = None
    if _is_delay_type(table_type) and delay_arr is not None:
        # RMS across antennas per (spw, field) → [n_spw, n_field]
        delay_rms_ns = np.sqrt(np.nanmean(delay_arr**2, axis=(0, 3))).tolist()  # [n_spw, n_field]

    # --- build response data ---
    def _flag(arr: np.ndarray | None) -> str:
        if arr is None:
            return "UNAVAILABLE"
        return "PARTIAL" if np.any(np.isnan(arr)) else "COMPLETE"

    data: dict = {
        "table_type": fmt_field(
            table_type, flag="COMPLETE" if table_type in _SUPPORTED_TYPES else "UNAVAILABLE"
        ),
        "n_antennas": fmt_field(n_ant),
        "n_spw": fmt_field(n_spw),
        "n_field": fmt_field(n_field),
        "ant_names": fmt_field(ant_names),
        "spw_ids": fmt_field(spw_ids),
        "field_ids": fmt_field(field_ids),
        "field_names": fmt_field(field_names),
        "flagged_frac": fmt_field(flagged_frac_arr.tolist(), flag=_flag(flagged_frac_arr)),
        "snr_mean": fmt_field(snr_mean_arr.tolist(), flag=_flag(snr_mean_arr)),
        "overall_flagged_frac": fmt_field(overall_flagged_frac),
        "n_antennas_lost": fmt_field(n_antennas_lost),
        "antennas_lost": fmt_field(antennas_lost),
    }

    if _complex:
        data["amp_mean"] = fmt_field(amp_mean_arr.tolist(), flag=_flag(amp_mean_arr))
        data["amp_std"] = fmt_field(amp_std_arr.tolist(), flag=_flag(amp_std_arr))
        data["phase_mean_deg"] = fmt_field(phase_mean_arr.tolist(), flag=_flag(phase_mean_arr))
        data["phase_rms_deg"] = fmt_field(
            phase_rms_arr.tolist(),
            flag=_flag(phase_rms_arr),
            note=(
                "Worst correlation's phase scatter. Axis per phase_rms_axis: 'time' = "
                "RMS of wrapped deviations from the circular mean over time per (corr, "
                "chan), pooled over channels; 'channel' (one solution in time, e.g. a "
                "bandpass) = RMS across channels about the corr's circular mean. NaN "
                "only where a cell has fewer than 2 unflagged samples."
            ),
        )
        data["phase_rms_axis"] = fmt_field(sorted(phase_rms_axes))
        if phase_rms_corr_arr is not None:
            data["phase_rms_deg_per_corr"] = fmt_field(
                phase_rms_corr_arr.tolist(),
                flag=_flag(phase_rms_corr_arr),
                note=f"Shape [n_ant={n_ant}, n_spw={n_spw}, n_field={n_field}, n_corr].",
            )

    if _freq_dep and amp_array_4d is not None:
        data["amp_array"] = fmt_field(
            amp_array_4d.tolist(),
            flag=_flag(amp_array_4d),
            note=f"Shape [n_ant={n_ant}, n_spw={n_spw}, n_field={n_field}, n_chan_max={n_chan_max}]. NaN where channel count < n_chan_max or solution absent.",
        )

    if _is_delay_type(table_type):
        if delay_arr is not None:
            data["delay_ns"] = fmt_field(
                delay_arr.tolist(),
                flag=_flag(delay_arr),
                note=f"Shape [n_ant={n_ant}, n_spw={n_spw}, n_field={n_field}, n_corr]. Mean delay per antenna/SPW/field/corr.",
            )
            data["delay_rms_ns"] = fmt_field(
                delay_rms_ns,
                flag="COMPLETE",
                note=f"Shape [n_spw={n_spw}, n_field={n_field}]. RMS across antennas per SPW/field.",
            )
        else:
            data["delay_ns"] = fmt_field(None, flag="UNAVAILABLE", note="No delay solutions found.")
            data["delay_rms_ns"] = fmt_field(None, flag="UNAVAILABLE")

    # --- outliers block (always present) ---
    data["outliers"] = _compute_outliers(
        snr_mean_arr,
        amp_mean_arr if _complex else None,
        ant_names,
        spw_ids,
        field_names,
        snr_min,
        amp_sigma,
    )

    # --- raw NPZ sidecar (always written; full uncapped detail) ---
    npz_path = str(p.parent / f"{p.name}.calsol_stats.npz")
    try:
        _save_raw_npz(
            npz_path,
            ant_names,
            spw_ids,
            field_ids,
            field_names,
            {
                "flagged_frac": flagged_frac_arr,
                "snr_mean": snr_mean_arr,
                "amp_mean": amp_mean_arr,
                "amp_std": amp_std_arr,
                "phase_mean_deg": phase_mean_arr,
                "phase_rms_deg": phase_rms_arr,
                "phase_rms_deg_per_corr": phase_rms_corr_arr,
                "amp_array": amp_array_4d,
                "delay_ns": delay_arr,
            },
            {"snr_min": snr_min, "amp_sigma": amp_sigma},
        )
        casa_calls.append(f"np.savez → {npz_path}")
    except OSError as exc:
        warnings.append(f"Could not write raw NPZ sidecar to {npz_path}: {exc}")
        npz_path = None
    data["npz_path"] = fmt_field(npz_path, flag="COMPLETE" if npz_path else "UNAVAILABLE")

    # --- compact verbosity: per-antenna scalar arrays, no per-channel dumps ---
    # The full-mode output carries [n_ant, n_spw, n_field] arrays plus, for B
    # tables, a [n_ant, n_spw, n_field, n_chan] amplitude cube — tens of
    # thousands of nested floats. Compact mode collapses every quantity to one
    # value per antenna (averaged over spw/field) returned as a flat array
    # aligned to ant_names, and drops the per-channel amp_array entirely. Use
    # ms_calsol_plot for per-channel bandpass shape.
    if verbosity == "compact":

        def _per_ant(arr: np.ndarray | None) -> list | None:
            """Collapse [n_ant, n_spw, field, ...] → one rounded value per antenna."""
            if arr is None:
                return None
            out: list = []
            for i in range(n_ant):
                valid = arr[i][~np.isnan(arr[i])]
                out.append(round(float(np.mean(valid)), 4) if valid.size else None)
            return out

        compact_data: dict = {
            "table_type": table_type,
            "n_antennas": n_ant,
            "n_spw": n_spw,
            "n_field": n_field,
            "ant_names": ant_names,
            "spw_ids": spw_ids,
            "field_ids": field_ids,
            "field_names": field_names,
            "overall_flagged_frac": round(overall_flagged_frac, 4),
            "n_antennas_lost": n_antennas_lost,
            "antennas_lost": antennas_lost,
            "per_antenna_note": (
                "Arrays are aligned to ant_names and averaged over spw/field. "
                "Per-channel bandpass shape is omitted here — use ms_calsol_plot."
            ),
            "flagged_frac": _per_ant(flagged_frac_arr),
            "snr_mean": _per_ant(snr_mean_arr),
            "outliers": data["outliers"],
            "npz_path": npz_path,
        }
        if _complex:
            compact_data["amp_mean"] = _per_ant(amp_mean_arr)
            compact_data["amp_std"] = _per_ant(amp_std_arr)
            compact_data["phase_rms_deg"] = _per_ant(phase_rms_arr)
            compact_data["phase_rms_axis"] = sorted(phase_rms_axes)
            if phase_rms_corr_arr is not None:
                pc_ant = np.full((n_ant, phase_rms_corr_arr.shape[3]), math.nan)
                for i in range(n_ant):
                    for c in range(phase_rms_corr_arr.shape[3]):
                        v = phase_rms_corr_arr[i, :, :, c]
                        v = v[np.isfinite(v)]
                        if v.size:
                            pc_ant[i, c] = np.mean(v)
                compact_data["phase_rms_deg_per_corr"] = [
                    [round(float(x), 4) if np.isfinite(x) else None for x in row] for row in pc_ant
                ]
        if _is_delay_type(table_type) and delay_arr is not None:
            da = np.nanmean(delay_arr, axis=(1, 2, 3))  # [n_ant]
            compact_data["delay_ns"] = [round(float(x), 3) if np.isfinite(x) else None for x in da]
            compact_data["delay_rms_ns"] = delay_rms_ns
        data = compact_data

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=caltable_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
