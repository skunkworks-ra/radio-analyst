"""
tools/spw_amp_severity.py — ms_spw_amp_severity

Robust amplitude statistics of a visibility data column, computed PER CHANNEL
and aggregated PER SPW, across all (or selected) fields. Parallel hands only
(RR/LL or XX/YY), pooled: on a bright calibrator the cross-hands sit at the
leakage level, and pooling them with the parallel hands makes the per-channel
distribution bimodal. The measurement that
answers "which SpWs are RFI-dominated, and how much of each can we discard?"

This is a READ-ONLY diagnostic tool. It does not interpret and it does not flag.
It returns robust statistics (median, MAD, robust-sigma, min, max) and a derived
discardable-fraction estimate. The verdict (flag-channels vs drop-SpW) belongs to
the skill; the flagging belongs to ms_modify.

Works on ANY data column ('CORRECTED_DATA', 'DATA', 'MODEL_DATA'), or on
'residual' = |CORRECTED_DATA - MODEL_DATA|, so it can be run before and after a
flagging/applycal step to measure the delta.

Memory strategy
---------------
Single sequential pass. The data column is read in row-sized chunks, one
DATA_DESC_ID at a time (a chunk spanning DDIDs with different channel counts
cannot form a rectangular array — same constraint as rfi.py). For each
(SpW, channel) the tool keeps:

  * exact running min / max / unflagged-count / flagged-count  (O(n_chan), cheap)
  * a bounded uniform reservoir sample of amplitudes              (memory knob)

Robust statistics are computed from the reservoir at the end. Peak (max) is kept
exactly, outside the reservoir, because it is the RFI headline and a sample can
miss the single worst visibility. Total memory is bounded by
n_chan_total * max_samples_per_chan * 8 bytes, independent of MS row count.

The reservoir uses the random-key method (assign each incoming amplitude a
uniform key in [0,1), keep the K smallest keys seen). This is an exact,
order-independent uniform sample over the unflagged population per channel.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ms_inspect.tools.radiometer_estimate import parse_spw_selection
from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.formatting import (
    _collect_flags,
    normalize_field_sel,
    normalize_spw_sel,
    resolve_sidecar_path,
    response_envelope,
    unwrap_fields,
)
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.selection import match_field_names, parallel_corr_by_ddid

TOOL_NAME = "ms_spw_amp_severity"

_DEFAULT_SIGMA = 5.0
_DEFAULT_MAX_SAMPLES = 5000
_DEFAULT_ROW_CHUNK = 20_000
_SEED = 1234  # fixed for reproducibility

# Wire-payload bound on the per-channel drill-down. The measurement is
# memory-bounded by the reservoir; the *response* was not, and channel count is
# set by the dataset, not by this tool — a wideband MS puts tens of thousands of
# per-channel records into one MCP response. The per-SpW aggregates are never
# capped: they are small, and they are what 13-postcal-rfi-flagging.md consumes.
_DEFAULT_MAX_PER_CHAN_RECORDS = 128


class _ChanReservoir:
    """Uniform random-key reservoir + exact min/max/counts for one channel."""

    __slots__ = ("vals", "keys", "vmin", "vmax", "n_unflagged", "n_flagged", "_k")

    def __init__(self, k: int):
        self._k = k
        self.vals = np.empty(0, dtype=np.float64)
        self.keys = np.empty(0, dtype=np.float64)
        self.vmin = np.inf
        self.vmax = -np.inf
        self.n_unflagged = 0
        self.n_flagged = 0

    def add(self, amps: np.ndarray, rng: np.random.Generator) -> None:
        """Add a batch of unflagged amplitudes for this channel."""
        m = amps.size
        if m == 0:
            return
        self.n_unflagged += m
        self.vmin = min(self.vmin, float(amps.min()))
        self.vmax = max(self.vmax, float(amps.max()))
        batch_keys = rng.random(m)
        vals = np.concatenate([self.vals, amps])
        keys = np.concatenate([self.keys, batch_keys])
        if vals.size > self._k:
            keep = np.argpartition(keys, self._k)[: self._k]
            vals = vals[keep]
            keys = keys[keep]
        self.vals = vals
        self.keys = keys

    def stats(self) -> dict | None:
        """Robust statistics from the reservoir, or None if no unflagged data."""
        if self.vals.size == 0:
            return None
        med = float(np.median(self.vals))
        mad = float(np.median(np.abs(self.vals - med)))
        return {
            "median": med,
            "mad": mad,
            "robust_sigma": 1.4826 * mad,
            "min": float(self.vmin),
            "max": float(self.vmax),
            "p95": float(np.percentile(self.vals, 95)),
        }


class _ChanDiffTracker:
    """Exact running RMS/std + bounded uniform reservoir for |V(ch) - V(ch-1)| / sqrt(2).

    Adjacent-channel complex differencing cancels smooth continuum sky emission on
    all baselines (including bright extended sources), leaving thermal
    noise (std / (1.4826 * MAD) ~ 1.0) plus narrow-band/time-variable RFI spikes.
    Exact Chan parallel-variance updates ensure rare high-amplitude bursts are never
    missed by reservoir sampling.
    """

    __slots__ = ("vals", "keys", "n_pairs", "mean", "m2", "sum_sq", "vmax", "_k")

    def __init__(self, k: int):
        self._k = k
        self.vals = np.empty(0, dtype=np.float64)
        self.keys = np.empty(0, dtype=np.float64)
        self.n_pairs = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.sum_sq = 0.0
        self.vmax = -np.inf

    def add(self, dv_abs: np.ndarray, rng: np.random.Generator) -> None:
        m = dv_abs.size
        if m == 0:
            return
        b_mean = float(np.mean(dv_abs))
        b_m2 = float(np.sum((dv_abs - b_mean) ** 2))
        b_ssq = float(np.sum(dv_abs * dv_abs))
        if self.n_pairs == 0:
            self.mean = b_mean
            self.m2 = b_m2
        else:
            delta = b_mean - self.mean
            n_tot = self.n_pairs + m
            self.mean += delta * (m / n_tot)
            self.m2 += b_m2 + delta * delta * (self.n_pairs * m / n_tot)
        self.n_pairs += m
        self.sum_sq += b_ssq
        self.vmax = max(self.vmax, float(dv_abs.max()))

        batch_keys = rng.random(m)
        vals = np.concatenate([self.vals, dv_abs])
        keys = np.concatenate([self.keys, batch_keys])
        if vals.size > self._k:
            keep = np.argpartition(keys, self._k)[: self._k]
            vals = vals[keep]
            keys = keys[keep]
        self.vals = vals
        self.keys = keys

    def stats(self) -> dict | None:
        if self.n_pairs == 0 or self.vals.size == 0:
            return None
        rms = float(np.sqrt(self.sum_sq / self.n_pairs))
        std = float(np.sqrt(max(0.0, self.m2 / self.n_pairs)))
        med = float(np.median(self.vals))
        mad_sig = 1.4826 * float(np.median(np.abs(self.vals - med)))
        std_over_mad = (std / mad_sig) if mad_sig > 0 else None
        gt10_frac = float(np.mean(self.vals > (med + 10.0 * mad_sig))) if mad_sig > 0 else 0.0
        return {
            "n_pairs": self.n_pairs,
            "rms": rms,
            "std": std,
            "median": med,
            "mad_sigma": mad_sig,
            "std_over_mad": std_over_mad,
            "gt10sigma_frac": gt10_frac,
            "max": float(self.vmax),
        }


def _corr_first_axis(arr: np.ndarray) -> np.ndarray:
    """Return amplitude array as [n_chan, n_elements] folding corr + rows together.

    Input shape is [n_corr, n_chan, n_rows], already sliced to the parallel
    hands; we want per-channel pooled over those correlations and rows.
    """
    n_corr, n_chan, n_rows = arr.shape
    # → [n_chan, n_corr, n_rows] → [n_chan, n_corr*n_rows]
    return np.transpose(arr, (1, 0, 2)).reshape(n_chan, n_corr * n_rows)


def _bound_per_chan_payload(
    data: dict,
    max_per_chan_records: int,
    sidecar_path: str | None,
    warnings: list[str],
) -> dict:
    """
    Drop the per-channel drill-down from the wire payload if it is too large.

    All-or-nothing per response: a partial slice of one SpW's channels would be
    a misleading spectrum (the omitted half is where the RFI might be), so
    either every SpW keeps its `per_chan` or none does. The per-SpW aggregates
    are never touched.

    The sidecar is written into `<workdir>/sidecars/` only when truncation
    occurs and a workdir is configured -- NEVER next to `ms_path`.

    Every per_spw entry is required to carry a `per_chan` list. A missing key
    is a construction bug upstream, not a condition to degrade past, so it
    raises rather than silently counting zero.
    """
    import json as _json

    per_spw = data.get("per_spw")
    if not isinstance(per_spw, list):
        raise KeyError("spw_amp_severity: data['per_spw'] missing or not a list")

    for entry in per_spw:
        if "per_chan" not in entry or not isinstance(entry["per_chan"], list):
            raise KeyError(
                f"spw_amp_severity: per_spw entry for spw_id="
                f"{entry.get('spw_id', '<unknown>')} has no 'per_chan' list"
            )

    total = sum(len(entry["per_chan"]) for entry in per_spw)
    data["n_per_chan_records"] = total
    data["max_per_chan_records"] = max_per_chan_records

    if max_per_chan_records <= 0 or total <= max_per_chan_records:
        data["per_chan_truncated"] = fmt_field(False)
        return data

    written: str | None = None
    write_failed = False
    if sidecar_path:
        try:
            with open(sidecar_path, "w") as fh:
                _json.dump(data, fh, separators=(",", ":"), default=str)
            written = sidecar_path
        except OSError as exc:
            write_failed = True
            warnings.append(
                f"Could not write per-channel sidecar to {sidecar_path}: {exc}. "
                "The per-channel detail is dropped from this response; pass a writable "
                "workdir to persist the full per-channel JSON sidecar."
            )

    per_chan_only = {"per_spw": [{"per_chan": entry["per_chan"]} for entry in per_spw]}
    offloaded_flags = _collect_flags(per_chan_only)
    _, offloaded_field_flags = unwrap_fields(per_chan_only)

    for entry in per_spw:
        chans = entry.pop("per_chan")
        entry["n_per_chan_omitted"] = len(chans)
        thresh = entry.get("elevation_threshold")
        if isinstance(thresh, (int, float)):
            elevated = [
                {
                    "chan": c.get("chan"),
                    "freq_ghz": (
                        round(float(c["freq_mhz"]) / 1000.0, 6)
                        if c.get("freq_mhz") is not None
                        else c.get("freq_ghz")
                    ),
                    "median": c.get("median"),
                    "robust_sigma": c.get("robust_sigma"),
                    "discardable_frac": c.get("discardable_frac"),
                }
                for c in chans
                if isinstance(c, dict)
                and isinstance(c.get("median"), (int, float))
                and c["median"] > thresh
            ]
            elevated.sort(key=lambda r: float(r["median"] or 0.0), reverse=True)
            entry["top_elevated_chans"] = elevated[:5]

    data["per_chan_truncated"] = fmt_field(
        True,
        "PARTIAL",
        note=(
            f"{total} per-channel records exceeded max_per_chan_records="
            f"{max_per_chan_records}; per_chan dropped from all "
            f"{len(per_spw)} SpW entries. Per-SpW aggregates are complete."
        ),
    )
    data["n_per_chan_records_dropped"] = total
    if written:
        data["detail_path"] = fmt_field(written, flag="COMPLETE")
        data["detail_note"] = (
            "Full per-channel detail (all SpWs) written to detail_path as compact "
            "JSON; read it directly from the filesystem."
        )
    elif write_failed:
        data["detail_path"] = fmt_field(
            None,
            flag="UNAVAILABLE",
            note="Sidecar write failed; pass a writable workdir to persist per-channel detail.",
        )
        data["detail_note"] = (
            "Sidecar write failed; pass a writable workdir to persist per-channel detail."
        )
    else:
        data["detail_path"] = fmt_field(
            None,
            flag="PARTIAL",
            note="No workdir provided; pass workdir or set RADIO_MCP_DIR to write per-channel sidecar.",
        )
        data["detail_note"] = (
            "Per-channel detail omitted from wire output; pass workdir to write JSON sidecar."
        )
    if offloaded_flags:
        data["_offloaded_flags"] = offloaded_flags
    if offloaded_field_flags:
        data["_offloaded_field_flags"] = offloaded_field_flags
    return data


def run(
    ms_path: str,
    datacolumn: str = "CORRECTED_DATA",
    field: str = "",
    sigma: float = _DEFAULT_SIGMA,
    max_samples_per_chan: int = _DEFAULT_MAX_SAMPLES,
    row_chunk: int = _DEFAULT_ROW_CHUNK,
    max_per_chan_records: int = _DEFAULT_MAX_PER_CHAN_RECORDS,
    workdir: str | None = None,
    spw: str = "",
) -> dict:
    """
    Per-channel robust amplitude stats of a data column, aggregated per SpW.

    Args:
        ms_path:              Path to the Measurement Set.
        datacolumn:           Column to measure: 'CORRECTED_DATA' (default),
                              'DATA', 'MODEL_DATA', or 'residual'
                              (|CORRECTED_DATA - MODEL_DATA|). Use the same tool
                              on two columns to compare before/after a step.
        field:                CASA field selection (empty = all fields): names,
                              wildcards, ids or id ranges. An unmatched token
                              is an error, not a fall back to all fields.
        sigma:                N in the elevation threshold band_floor + N*robust_sigma.
                              Only used to derive the discardable-fraction estimate.
        max_samples_per_chan: Reservoir size per channel (memory knob).
        row_chunk:            Rows read per block (memory knob; smaller = less RAM).
        max_per_chan_records: Wire-payload bound on the per-channel drill-down,
                              counted across all SpWs. If the total exceeds it,
                              `per_chan` is dropped from every SpW and written
                              to a JSON sidecar instead; the per-SpW aggregates
                              are never affected. 0 disables the bound.
        workdir:              Optional workdir for sidecars and stage_log.jsonl.
        spw:                  CASA SpW selection (empty = all SpWs): ids or ranges
                              (e.g. '2~5,8,16~17'). Filtered against
                              DATA_DESCRIPTION -> SPECTRAL_WINDOW_ID before
                              scanning visibility chunks.

    Returns:
        Standard envelope with per_spw → per-channel robust stats + per-SpW
        aggregate severity numbers. No verdict, no flagging.

        When the per-channel payload is truncated the envelope carries
        `per_chan_truncated` (PARTIAL), `n_per_chan_records_dropped`,
        `detail_path` and `detail_note`, and each per_spw entry keeps
        `n_per_chan_omitted`. Truncation is never silent.
    """
    field = normalize_field_sel(field)
    spw = normalize_spw_sel(spw)
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []
    rng = np.random.default_rng(_SEED)

    # ------------------------------------------------------------------
    # DATA_DESCRIPTION → SpW mapping
    # ------------------------------------------------------------------
    with open_table(ms_str + "/DATA_DESCRIPTION") as tb:
        casa_calls.append("tb.open(DATA_DESCRIPTION) → SPECTRAL_WINDOW_ID")
        dd_to_spw: list[int] = [int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")]

    # ------------------------------------------------------------------
    # SpW channel frequencies and channel widths
    # ------------------------------------------------------------------
    spw_chan_freqs: dict[int, np.ndarray] = {}
    spw_chan_widths_hz: dict[int, float | None] = {}
    with open_table(ms_str + "/SPECTRAL_WINDOW") as tb:
        casa_calls.append("tb.open(SPECTRAL_WINDOW) → CHAN_FREQ, CHAN_WIDTH")
        try:
            spw_cols = set(tb.colnames())
        except Exception:
            spw_cols = set()
        has_chan_width = "CHAN_WIDTH" in spw_cols
        for spw_id in range(tb.nrows()):
            try:
                freqs = np.asarray(tb.getcell("CHAN_FREQ", spw_id))
            except Exception:
                freqs = np.array([])
            spw_chan_freqs[spw_id] = freqs

            cw_hz: float | None = None
            if has_chan_width:
                try:
                    cw_arr = np.abs(np.asarray(tb.getcell("CHAN_WIDTH", spw_id), dtype=float))
                    cw_pos = cw_arr[np.isfinite(cw_arr) & (cw_arr > 0.0)]
                    if cw_pos.size > 0:
                        cw_hz = float(np.median(cw_pos))
                except Exception:
                    cw_hz = None
            if cw_hz is None and freqs.size >= 2:
                diffs = np.abs(np.diff(freqs.astype(float, copy=False)))
                diffs_pos = diffs[np.isfinite(diffs) & (diffs > 0.0)]
                if diffs_pos.size > 0:
                    cw_hz = float(np.median(diffs_pos))
            spw_chan_widths_hz[spw_id] = cw_hz

    # ------------------------------------------------------------------
    # Parallel-hand correlations per DATA_DESC_ID
    # ------------------------------------------------------------------
    corr_by_dd = parallel_corr_by_ddid(ms_str)
    casa_calls.append("tb.open(POLARIZATION, DATA_DESCRIPTION) → parallel-hand CORR_TYPE per DDID")

    # ------------------------------------------------------------------
    # Optional field and SpW selection
    # ------------------------------------------------------------------
    from ms_inspect.exceptions import ComputationError

    selected_spws: set[int] | None = None
    if spw:
        if ":" in spw:
            raise ComputationError(
                f"Channel selection syntax (':') is not supported in spw={spw!r}; "
                "pass SpW IDs or ranges only (e.g. '0~3,5').",
                ms_path=ms_path,
            )
        n_spw_total = len(spw_chan_freqs)
        if spw.strip() == "*":
            parsed_spws = list(range(n_spw_total))
        else:
            try:
                parsed_spws = parse_spw_selection(spw, n_spw_total)
            except ValueError as exc:
                raise ComputationError(str(exc), ms_path=ms_path) from exc
        dd_spw_ids = set(dd_to_spw)
        selected_spws = {
            sid for sid in parsed_spws if sid in dd_spw_ids and len(spw_chan_freqs.get(sid, ())) > 0
        }
        if not selected_spws:
            raise ComputationError(
                f"SpW selection {spw!r} matched no observed spectral windows in DATA_DESCRIPTION.",
                ms_path=ms_path,
            )

    field_ids: set[int] | None = None
    if field:
        with open_table(ms_str + "/FIELD") as tb:
            names = list(tb.getcol("NAME"))
        try:
            field_ids = set(match_field_names(names, field))
        except ValueError as exc:
            raise ComputationError(str(exc), ms_path=ms_path) from exc

    # ------------------------------------------------------------------
    # Validate column presence
    # ------------------------------------------------------------------
    residual = datacolumn.lower() == "residual"
    needed = ["CORRECTED_DATA", "MODEL_DATA"] if residual else [datacolumn]
    with open_table(ms_str) as tb:
        missing = [c for c in needed if c not in set(tb.colnames())]
    if missing:
        raise ComputationError(
            f"{', '.join(missing)} column not present in {ms_path}.",
            ms_path=ms_path,
        )

    # ------------------------------------------------------------------
    # Per-(spw, chan) reservoirs + per-SpW/global adjacent-channel diff trackers.
    # Multiple DDIDs may map to one SpW; we feed each DDID's data into its SpW's
    # trackers directly.
    # ------------------------------------------------------------------
    diff_k = max(50_000, max_samples_per_chan * 10)
    spw_reservoirs: dict[int, list[_ChanReservoir]] = {}
    spw_diff_trackers: dict[int, _ChanDiffTracker] = {}
    global_diff_tracker = _ChanDiffTracker(diff_k)
    for spw_id, freqs in spw_chan_freqs.items():
        if selected_spws is not None and spw_id not in selected_spws:
            continue
        n_chan = len(freqs)
        if n_chan > 0:
            spw_reservoirs[spw_id] = [_ChanReservoir(max_samples_per_chan) for _ in range(n_chan)]
            spw_diff_trackers[spw_id] = _ChanDiffTracker(diff_k)

    spw_corrs: dict[int, set[str]] = {}
    field_clause = ""
    if field_ids is not None:
        ids = ",".join(str(i) for i in sorted(field_ids))
        field_clause = f" && FIELD_ID IN [{ids}]"

    with open_table(ms_str) as tb:
        for ddid, spw_id in enumerate(dd_to_spw):
            if spw_id not in spw_reservoirs:
                continue
            par = corr_by_dd[ddid]
            if not par:
                warnings.append(
                    f"DATA_DESC_ID {ddid} (SpW {spw_id}) has no parallel-hand correlation; skipped."
                )
                continue
            par_idx = [i for i, _ in par]
            sub = tb.query(f"DATA_DESC_ID == {ddid}{field_clause}")
            try:
                n_rows = int(sub.nrows())
                if n_rows == 0:
                    continue
                reservoirs = spw_reservoirs[spw_id]
                diff_tracker = spw_diff_trackers[spw_id]
                spw_corrs.setdefault(spw_id, set()).update(name for _, name in par)
                for start in range(0, n_rows, row_chunk):
                    nrow = min(row_chunk, n_rows - start)
                    if residual:
                        data = sub.getcol("CORRECTED_DATA", startrow=start, nrow=nrow)
                        data = data - sub.getcol("MODEL_DATA", startrow=start, nrow=nrow)
                    else:
                        data = sub.getcol(datacolumn, startrow=start, nrow=nrow)
                    flag = sub.getcol("FLAG", startrow=start, nrow=nrow)
                    data = data[par_idx]
                    flag = flag[par_idx]
                    flag_b = flag.astype(bool)
                    amp = np.abs(data)  # [n_par, n_chan, nrow]
                    if data.shape[1] >= 2:
                        nz = amp > 0
                        pair_good = (
                            (~flag_b[:, 1:, :])
                            & (~flag_b[:, :-1, :])
                            & nz[:, 1:, :]
                            & nz[:, :-1, :]
                        )
                        if np.any(pair_good):
                            dv_abs = np.abs(data[:, 1:, :] - data[:, :-1, :])[pair_good].astype(
                                np.float64, copy=False
                            ) / np.sqrt(2.0)
                            diff_tracker.add(dv_abs, rng)
                            global_diff_tracker.add(dv_abs, rng)
                    amp_c = _corr_first_axis(amp)  # [n_chan, n_corr*nrow]
                    flag_c = _corr_first_axis(flag_b)
                    n_chan = amp_c.shape[0]
                    for ch in range(n_chan):
                        good = ~flag_c[ch]
                        reservoirs[ch].n_flagged += int((~good).sum())
                        vals = amp_c[ch][good]
                        # exclude exact zeros (un-populated cells)
                        vals = vals[vals > 0]
                        reservoirs[ch].add(vals, rng)
            finally:
                sub.close()
            cols = "CORRECTED_DATA-MODEL_DATA" if residual else datacolumn
            casa_calls.append(
                f"tb.query(DATA_DESC_ID=={ddid}{field_clause}) → getcol({cols},FLAG) chunked"
            )

    # ------------------------------------------------------------------
    # Pass-1 reduction: per-channel robust stats + per-SpW floor/threshold.
    # Stored, not yet emitted — pass 2 needs the per-SpW threshold first.
    # ------------------------------------------------------------------
    spw_stats: dict[int, dict] = {}
    for spw_id in sorted(spw_reservoirs.keys()):
        reservoirs = spw_reservoirs[spw_id]
        n_chan = len(reservoirs)
        chan_st: list[dict | None] = [reservoirs[ch].stats() for ch in range(n_chan)]
        chan_medians = [st["median"] for st in chan_st if st is not None]
        chan_sigmas = [st["robust_sigma"] for st in chan_st if st is not None]
        if chan_medians:
            band_floor = float(np.median(chan_medians))
            band_sigma = float(np.median(chan_sigmas))
            threshold = band_floor + sigma * band_sigma
        else:
            band_floor = band_sigma = threshold = None
        spw_stats[spw_id] = {
            "chan_st": chan_st,
            "band_floor": band_floor,
            "band_sigma": band_sigma,
            "threshold": threshold,
        }

    # ------------------------------------------------------------------
    # Clean-floor anchor: median of the lowest-quartile band_floors — a robust
    # estimate of the thermal+source floor taken from the QUIETEST SpWs. Severity
    # is anchored to this, not the overall median, so it stays correct even when
    # much of the band is RFI-dominated (a contaminated median understates it).
    # ------------------------------------------------------------------
    valid_floors = sorted(
        s["band_floor"] for s in spw_stats.values() if s["band_floor"] is not None
    )
    if valid_floors:
        q = max(1, len(valid_floors) // 4)
        clean_floor = float(np.median(valid_floors[:q]))
    else:
        clean_floor = None

    # ------------------------------------------------------------------
    # Assemble per-SpW output
    # ------------------------------------------------------------------
    per_spw: list[dict] = []
    for spw_id in sorted(spw_stats.keys()):
        st = spw_stats[spw_id]
        freqs = spw_chan_freqs[spw_id]
        reservoirs = spw_reservoirs[spw_id]
        chan_st = st["chan_st"]
        n_chan = len(chan_st)
        band_floor = st["band_floor"]
        threshold = st["threshold"]

        chan_records: list[dict] = []
        for ch in range(n_chan):
            cst = chan_st[ch]
            freq_mhz = round(float(freqs[ch]) / 1e6, 3) if ch < len(freqs) else None
            if cst is None:
                chan_records.append(
                    {
                        "chan": ch,
                        "freq_mhz": freq_mhz,
                        "n_unflagged": 0,
                        "n_flagged": reservoirs[ch].n_flagged,
                        "median": fmt_field(None, "UNAVAILABLE", note="no unflagged data"),
                    }
                )
                continue
            chan_disc = float(np.mean(reservoirs[ch].vals > threshold))
            chan_records.append(
                {
                    "chan": ch,
                    "freq_mhz": freq_mhz,
                    "n_unflagged": reservoirs[ch].n_unflagged,
                    "n_flagged": reservoirs[ch].n_flagged,
                    "median": round(cst["median"], 6),
                    "mad": round(cst["mad"], 6),
                    "robust_sigma": round(cst["robust_sigma"], 6),
                    "min": round(cst["min"], 6),
                    "max": round(cst["max"], 6),
                    "p95": round(cst["p95"], 6),
                    "peak_to_floor": (
                        round(cst["max"] / cst["median"], 3) if cst["median"] > 0 else None
                    ),
                    "discardable_frac": round(chan_disc, 4),
                }
            )

        spw_n_unflagged = int(sum(reservoirs[ch].n_unflagged for ch in range(n_chan)))
        spw_n_flagged = int(sum(reservoirs[ch].n_flagged for ch in range(n_chan)))
        spw_n_total = spw_n_unflagged + spw_n_flagged
        spw_unflagged_fraction = round(spw_n_unflagged / spw_n_total, 6) if spw_n_total > 0 else 0.0
        centre_freq_hz = float(freqs[n_chan // 2]) if n_chan else None
        centre_freq_mhz = round(centre_freq_hz / 1e6, 3) if centre_freq_hz is not None else None
        centre_freq_ghz = round(centre_freq_hz / 1e9, 6) if centre_freq_hz is not None else None
        chan_width_hz = spw_chan_widths_hz.get(spw_id)
        chan_width_hz_val = round(chan_width_hz, 3) if chan_width_hz is not None else None

        if band_floor is None:
            unavail_note = "no unflagged data"
            per_spw.append(
                {
                    "spw_id": spw_id,
                    "n_channels": n_chan,
                    "centre_freq_mhz": centre_freq_mhz,
                    "centre_freq_ghz": centre_freq_ghz,
                    "chan_width_hz": chan_width_hz_val,
                    "n_unflagged": spw_n_unflagged,
                    "n_flagged": spw_n_flagged,
                    "unflagged_fraction": spw_unflagged_fraction,
                    "correlations_used": sorted(spw_corrs.get(spw_id, set())),
                    "band_floor": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "band_robust_sigma": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "severity": None,
                    "elevation_threshold": None,
                    "estimated_discardable_frac": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "max_peak_to_floor": None,
                    "chan_diff_rms": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_noise_density": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_std": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_mad_sigma": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_std_over_mad": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_gt10sigma_frac": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "chan_diff_max": fmt_field(None, "UNAVAILABLE", note=unavail_note),
                    "per_chan": chan_records,
                }
            )
            warnings.append(f"SpW {spw_id} has no unflagged data in {datacolumn}.")
            continue

        # discardable element fraction over the SpW, weighted by unflagged count.
        num = den = 0.0
        for ch in range(n_chan):
            res = reservoirs[ch]
            if res.vals.size == 0:
                continue
            num += float(np.mean(res.vals > threshold)) * res.n_unflagged
            den += res.n_unflagged
        discardable = (num / den) if den > 0 else 0.0

        severity = round(band_floor / clean_floor, 3) if clean_floor and clean_floor > 0 else None
        ptf_vals = [r["peak_to_floor"] for r in chan_records if r.get("peak_to_floor") is not None]
        diff_st = spw_diff_trackers[spw_id].stats()
        diff_reason = (
            "SpW has < 2 channels" if n_chan < 2 else "no unflagged adjacent channel pairs"
        )
        nd_val = (
            round(diff_st["rms"] * math.sqrt(chan_width_hz), 6)
            if (diff_st and chan_width_hz is not None and chan_width_hz > 0.0)
            else None
        )
        nd_note = (
            diff_reason
            if diff_st is None
            else ("channel width unavailable" if nd_val is None else None)
        )

        per_spw.append(
            {
                "spw_id": spw_id,
                "n_channels": n_chan,
                "centre_freq_mhz": centre_freq_mhz,
                "centre_freq_ghz": centre_freq_ghz,
                "chan_width_hz": chan_width_hz_val,
                "n_unflagged": spw_n_unflagged,
                "n_flagged": spw_n_flagged,
                "unflagged_fraction": spw_unflagged_fraction,
                "correlations_used": sorted(spw_corrs.get(spw_id, set())),
                "band_floor": fmt_field(round(band_floor, 6)),
                "band_robust_sigma": fmt_field(round(st["band_sigma"], 6)),
                "severity": severity,
                "elevation_threshold": round(threshold, 6),
                "estimated_discardable_frac": fmt_field(round(discardable, 4)),
                "max_peak_to_floor": max(ptf_vals) if ptf_vals else None,
                "chan_diff_rms": fmt_field(
                    round(diff_st["rms"], 6) if diff_st else None,
                    flag="COMPLETE" if diff_st else "UNAVAILABLE",
                    note=None if diff_st else diff_reason,
                ),
                "chan_diff_noise_density": fmt_field(
                    nd_val,
                    flag="COMPLETE" if nd_val is not None else "UNAVAILABLE",
                    note=nd_note,
                ),
                "chan_diff_std": fmt_field(
                    round(diff_st["std"], 6) if diff_st else None,
                    flag="COMPLETE" if diff_st else "UNAVAILABLE",
                    note=None if diff_st else diff_reason,
                ),
                "chan_diff_mad_sigma": fmt_field(
                    round(diff_st["mad_sigma"], 6) if diff_st else None,
                    flag="COMPLETE" if diff_st else "UNAVAILABLE",
                    note=None if diff_st else diff_reason,
                ),
                "chan_diff_std_over_mad": fmt_field(
                    round(diff_st["std_over_mad"], 3)
                    if (diff_st and diff_st["std_over_mad"] is not None)
                    else None,
                    flag="COMPLETE"
                    if (diff_st and diff_st["std_over_mad"] is not None)
                    else "UNAVAILABLE",
                    note=None
                    if (diff_st and diff_st["std_over_mad"] is not None)
                    else (diff_reason if diff_st is None else "chan_diff_mad_sigma is zero"),
                ),
                "chan_diff_gt10sigma_frac": fmt_field(
                    round(diff_st["gt10sigma_frac"], 6) if diff_st else None,
                    flag="COMPLETE" if diff_st else "UNAVAILABLE",
                    note=None if diff_st else diff_reason,
                ),
                "chan_diff_max": fmt_field(
                    round(diff_st["max"], 6) if diff_st else None,
                    flag="COMPLETE" if diff_st else "UNAVAILABLE",
                    note=None if diff_st else diff_reason,
                ),
                "per_chan": chan_records,
            }
        )

    global_diff = global_diff_tracker.stats()
    spw_rms_pairs = [
        (e["spw_id"], e["chan_diff_rms"]["value"])
        for e in per_spw
        if isinstance(e.get("chan_diff_rms"), dict)
        and isinstance(e["chan_diff_rms"].get("value"), (int, float))
        and e["chan_diff_rms"]["value"] > 0
    ]
    if spw_rms_pairs:
        rms_vals = [v for _, v in spw_rms_pairs]
        med_rms = float(np.median(rms_vals))
        max_rms_spw, max_rms_val = max(spw_rms_pairs, key=lambda kv: kv[1])
        spw_rms_ratio_val = round(max_rms_val / med_rms, 3) if med_rms > 0 else None
    else:
        max_rms_spw = None
        spw_rms_ratio_val = None

    spw_nd_pairs = [
        (e["spw_id"], e["chan_diff_noise_density"]["value"])
        for e in per_spw
        if isinstance(e.get("chan_diff_noise_density"), dict)
        and isinstance(e["chan_diff_noise_density"].get("value"), (int, float))
        and e["chan_diff_noise_density"]["value"] > 0
    ]
    if spw_nd_pairs:
        nd_vals = [v for _, v in spw_nd_pairs]
        med_nd = float(np.median(nd_vals))
        max_nd_spw, max_nd_val = max(spw_nd_pairs, key=lambda kv: kv[1])
        spw_nd_ratio_val = round(max_nd_val / med_nd, 3) if med_nd > 0 else None
    else:
        max_nd_spw = None
        spw_nd_ratio_val = None

    spw_som_pairs = [
        (e["spw_id"], e["chan_diff_std_over_mad"]["value"])
        for e in per_spw
        if isinstance(e.get("chan_diff_std_over_mad"), dict)
        and isinstance(e["chan_diff_std_over_mad"].get("value"), (int, float))
    ]
    if spw_som_pairs:
        max_som_spw, max_som_val = max(spw_som_pairs, key=lambda kv: kv[1])
    else:
        max_som_spw = None
        max_som_val = None

    data = {
        "datacolumn": datacolumn,
        "clean_floor_anchor": round(clean_floor, 6) if clean_floor is not None else None,
        "field": field,
        "spw": spw,
        "sigma": sigma,
        "max_samples_per_chan": max_samples_per_chan,
        "row_chunk": row_chunk,
        "chan_diff_rms": fmt_field(
            round(global_diff["rms"], 6) if global_diff else None,
            flag="COMPLETE" if global_diff else "UNAVAILABLE",
            note="exact RMS of |V(ch) - V(ch-1)| / sqrt(2) across all unflagged parallel-hand pairs"
            if global_diff
            else "no unflagged adjacent channel pairs",
        ),
        "chan_diff_std": fmt_field(
            round(global_diff["std"], 6) if global_diff else None,
            flag="COMPLETE" if global_diff else "UNAVAILABLE",
            note=None if global_diff else "no unflagged adjacent channel pairs",
        ),
        "chan_diff_mad_sigma": fmt_field(
            round(global_diff["mad_sigma"], 6) if global_diff else None,
            flag="COMPLETE" if global_diff else "UNAVAILABLE",
            note=None if global_diff else "no unflagged adjacent channel pairs",
        ),
        "chan_diff_std_over_mad": fmt_field(
            round(global_diff["std_over_mad"], 3)
            if (global_diff and global_diff["std_over_mad"] is not None)
            else None,
            flag="COMPLETE"
            if (global_diff and global_diff["std_over_mad"] is not None)
            else "UNAVAILABLE",
            note="std / (1.4826 * MAD) of |V(ch) - V(ch-1)| / sqrt(2); ~1.0 for thermal noise, >>1 for RFI"
            if (global_diff and global_diff["std_over_mad"] is not None)
            else "no unflagged adjacent channel pairs or zero MAD",
        ),
        "chan_diff_gt10sigma_frac": fmt_field(
            round(global_diff["gt10sigma_frac"], 6) if global_diff else None,
            flag="COMPLETE" if global_diff else "UNAVAILABLE",
            note="fraction of unflagged adjacent-channel diff pairs > median + 10 * mad_sigma"
            if global_diff
            else "no unflagged adjacent channel pairs",
        ),
        "max_spw_chan_diff_std_over_mad": fmt_field(
            round(max_som_val, 3) if max_som_val is not None else None,
            flag="COMPLETE" if max_som_val is not None else "UNAVAILABLE",
            note=f"worst SpW (spw {max_som_spw})"
            if max_som_val is not None
            else "no SpW with adjacent-channel diff stats",
        ),
        "spw_rms_ratio": fmt_field(
            spw_rms_ratio_val,
            flag="COMPLETE" if spw_rms_ratio_val is not None else "UNAVAILABLE",
            note=(
                f"max_spw_rms (spw {max_rms_spw}) / median_spw_rms across {len(spw_rms_pairs)} SpW(s)"
                if spw_rms_ratio_val is not None
                else "no SpW with positive chan_diff_rms"
            ),
        ),
        "spw_rms_max_spw_id": max_rms_spw,
        "spw_noise_density_ratio": fmt_field(
            spw_nd_ratio_val,
            flag="COMPLETE" if spw_nd_ratio_val is not None else "UNAVAILABLE",
            note=(
                f"max_spw_noise_density (spw {max_nd_spw}) / median_spw_noise_density "
                f"across {len(spw_nd_pairs)} SpW(s) (Jy * Hz^1/2)"
                if spw_nd_ratio_val is not None
                else "no SpW with positive chan_diff_noise_density"
            ),
        ),
        "spw_noise_density_max_spw_id": max_nd_spw,
        "note": (
            "Parallel hands only, pooled (correlations_used per SpW). "
            "band_floor = median of per-channel medians (robust SpW floor). "
            "clean_floor_anchor = median of the lowest-quartile band_floors (thermal "
            "floor from the quietest SpWs). severity = band_floor / clean_floor_anchor. "
            "chan_diff_* measures adjacent-channel complex differences |V(ch) - V(ch-1)| / sqrt(2), "
            "which cancels smooth continuum sky emission on all baselines (including extended "
            "sources): clean thermal noise has chan_diff_std_over_mad ~ 1.0, chan_diff_gt10sigma_frac ~ 0, "
            "and bandwidth-normalized chan_diff_noise_density = chan_diff_rms * sqrt(chan_width_hz) "
            "(Jy * Hz^{1/2}) comparable across mixed-channel-width SpWs (spw_noise_density_ratio ~ 1.0); "
            "unflagged RFI elevates these sharply."
        ),
        "n_spw": len(per_spw),
        "per_spw": per_spw,
    }

    data = _bound_per_chan_payload(
        data,
        max_per_chan_records=max_per_chan_records,
        sidecar_path=resolve_sidecar_path(f"{Path(p).name}.spw_amp_severity.json", workdir),
        warnings=warnings,
    )

    # Record a lightweight check marker in stage_log.jsonl when inspecting
    # CORRECTED_DATA with a workdir, so ms_workflow_status and ms_tclean can
    # tell whether target spectrum verification ran after applycal.
    if workdir and datacolumn.upper() == "CORRECTED_DATA":
        try:
            wd_path = Path(workdir)
            if wd_path.is_dir():
                from ms_inspect.util.stage_log import record_stage

                record_stage(
                    str(wd_path),
                    "spw_amp_severity",
                    str(p),
                    {
                        "datacolumn": datacolumn.upper(),
                        "field": field or "",
                        "spw": spw or "",
                        "chan_diff_std_over_mad": data["chan_diff_std_over_mad"]["value"],
                        "max_spw_chan_diff_std_over_mad": data["max_spw_chan_diff_std_over_mad"][
                            "value"
                        ],
                        "chan_diff_gt10sigma_frac": data["chan_diff_gt10sigma_frac"]["value"],
                        "spw_rms_ratio": data["spw_rms_ratio"]["value"],
                        "spw_noise_density_ratio": data["spw_noise_density_ratio"]["value"],
                    },
                )
        except Exception:
            pass

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
