"""
tools/radiometer_estimate.py -- ms_radiometer_estimate

Deterministic radiometer thermal noise estimate for continuum/cube imaging:

    sigma_natural = SEFD / (eta_c * sqrt(2 * n_pol * n_baselines_eff * on_source_s * eff_bw_hz))
    thermal_rms_jy = weighting_factor * sigma_natural

Measures MS quantities (active unflagged antennas, per-pointing on-source time,
channel bandwidth, unflagged visibility fraction on active cross-hand baselines)
and combines them with the bundled TelescopeProfile SEFD. Ships every input and
assumed constant alongside thermal_rms_jy with explicit CompletionFlags and zero
boolean gates or threshold verdicts.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.casa_context import open_table, validate_ms_path
from ms_inspect.util.formatting import (
    field as fmt_field,
)
from ms_inspect.util.formatting import (
    normalize_field_sel,
    normalize_spw_sel,
    response_envelope,
)
from ms_inspect.util.selection import match_field_names, parallel_corr_by_ddid
from ms_inspect.util.telescope import TelescopeProfile, resolve_telescope

TOOL_NAME = "ms_radiometer_estimate"

_DEFAULT_ETA_C = 0.93
_MAX_SAMPLE_ROWS_PER_DDID = 200_000
_BRIGGS_ANCHORS = (
    (-2.0, 1.80),
    (-0.5, 1.55),
    (0.0, 1.35),
    (0.5, 1.20),
    (2.0, 1.00),
)


def parse_spw_selection(spw_sel: str, n_spw: int) -> list[int]:
    """Resolve a CASA SpW id/range string ('', '0~7', '0,2,4~6') against [0, n_spw)."""
    sel = normalize_spw_sel(spw_sel)
    if not sel:
        return list(range(n_spw))
    ids: set[int] = set()
    for raw in sel.split(","):
        tok = raw.strip().split(":", 1)[0].strip()
        if not tok:
            continue
        if tok.isdigit():
            val = int(tok)
            if val >= n_spw:
                raise ValueError(f"SpW {val} out of range (n_spw={n_spw})")
            ids.add(val)
        elif "~" in tok and all(p.strip().isdigit() for p in tok.split("~", 1)):
            lo, hi = (int(p.strip()) for p in tok.split("~", 1))
            matched = [s for s in range(lo, hi + 1) if s < n_spw]
            if not matched:
                raise ValueError(f"SpW range {tok!r} out of range (n_spw={n_spw})")
            ids.update(matched)
        else:
            raise ValueError(f"Unsupported SpW token {raw!r}")
    if not ids:
        raise ValueError(f"SpW selection {spw_sel!r} matched no spectral windows")
    return sorted(ids)


def resolve_weighting_factor(weighting: str, robust: float) -> tuple[float, str, str | None]:
    """Return (weighting_factor, flag, note) for natural / uniform / briggs."""
    w = weighting.strip().lower()
    if w == "natural":
        return 1.0, "COMPLETE", None
    if w == "uniform":
        return (
            1.80,
            "INFERRED",
            "representative uniform-weighting noise multiplier; exact value depends on uv density",
        )
    if w == "briggs":
        xs = np.array([pt[0] for pt in _BRIGGS_ANCHORS], dtype=float)
        ys = np.array([pt[1] for pt in _BRIGGS_ANCHORS], dtype=float)
        factor = float(np.interp(float(robust), xs, ys))
        return (
            round(factor, 4),
            "INFERRED",
            f"empirical Briggs noise multiplier at robust={robust:g} (1.20 at robust=0.5 per VLA OSS)",
        )
    raise ValueError(f"weighting must be 'natural', 'uniform', or 'briggs', got {weighting!r}")


def resolve_n_pol(stokes: str, max_parallel_hands: int) -> int:
    """Number of independent polarization hands contributing to one Stokes image."""
    s = stokes.strip().upper()
    if s in ("RR", "LL", "XX", "YY", "PP", "QQ"):
        return 1
    if s in ("I", "Q", "U", "V", "IQUV", "IV", "QU"):
        return 2 if max_parallel_hands >= 2 else 1
    raise ValueError(
        f"Unsupported stokes={stokes!r}; use 'I', 'Q', 'U', 'V', 'IQUV', or a single hand ('RR', 'LL', 'XX', 'YY')."
    )


def compute_radiometer_estimate(
    *,
    sefd_jy: float | None,
    sefd_note: str | None,
    n_ant_total: int,
    n_ant_unflagged: int,
    on_source_s: float,
    on_source_total_s: float,
    n_fields_selected: int,
    total_bw_hz: float,
    unflagged_fraction: float,
    n_pol: int,
    eta_c: float,
    weighting: str,
    robust: float,
    eff_bw_hz: float | None = None,
) -> dict:
    """Pure radiometer calculation returning field()-wrapped outputs and inputs."""
    w_factor, w_flag, w_note = resolve_weighting_factor(weighting, robust)
    n_baselines_eff = n_ant_unflagged * (n_ant_unflagged - 1) // 2
    if eff_bw_hz is None:
        eff_bw_hz = total_bw_hz * unflagged_fraction

    on_src_note = (
        f"median per-field integration across {n_fields_selected} fields (per-pointing mosaic noise)"
        if n_fields_selected > 1
        else None
    )

    if sefd_jy is None or sefd_jy <= 0:
        reason = sefd_note or "SEFD unavailable for telescope/band"
        sigma_nat_field = fmt_field(None, flag="UNAVAILABLE", note=reason)
        rms_field = fmt_field(None, flag="UNAVAILABLE", note=reason)
        sefd_field = fmt_field(None, flag="UNAVAILABLE", note=reason)
    elif n_baselines_eff <= 0 or on_source_s <= 0 or eff_bw_hz <= 0:
        reason = (
            f"zero effective sensitivity product (n_baselines_eff={n_baselines_eff}, "
            f"on_source_s={on_source_s:.3f}, eff_bw_hz={eff_bw_hz:.3f})"
        )
        sigma_nat_field = fmt_field(None, flag="UNAVAILABLE", note=reason)
        rms_field = fmt_field(None, flag="UNAVAILABLE", note=reason)
        sefd_field = fmt_field(round(float(sefd_jy), 3))
    else:
        denom = eta_c * math.sqrt(2.0 * n_pol * n_baselines_eff * on_source_s * eff_bw_hz)
        sigma_nat = float(sefd_jy) / denom
        thermal_rms = w_factor * sigma_nat
        sigma_nat_field = fmt_field(
            round(sigma_nat, 9),
            flag="INFERRED",
            note="uses bundled band SEFD and assumed eta_c",
        )
        rms_field = fmt_field(
            round(thermal_rms, 9),
            flag="INFERRED",
            note="weighting_factor * sigma_natural_jy",
        )
        sefd_field = fmt_field(round(float(sefd_jy), 3))

    return {
        "thermal_rms_jy": rms_field,
        "sigma_natural_jy": sigma_nat_field,
        "sefd_jy": sefd_field,
        "n_ant_total": fmt_field(int(n_ant_total)),
        "n_ant_unflagged": fmt_field(int(n_ant_unflagged)),
        "n_baselines_eff": fmt_field(int(n_baselines_eff)),
        "on_source_s": fmt_field(round(float(on_source_s), 3), note=on_src_note),
        "on_source_total_s": fmt_field(round(float(on_source_total_s), 3)),
        "total_bw_hz": fmt_field(round(float(total_bw_hz), 3)),
        "eff_bw_hz": fmt_field(round(float(eff_bw_hz), 3)),
        "unflagged_fraction": fmt_field(
            round(float(unflagged_fraction), 6),
            flag="UNAVAILABLE" if n_baselines_eff == 0 else "COMPLETE",
            note="active cross-hand baselines only"
            if n_baselines_eff > 0
            else "no unflagged baselines",
        ),
        "n_pol": fmt_field(int(n_pol)),
        "eta_c": fmt_field(
            round(float(eta_c), 4),
            flag="INFERRED",
            note="correlator efficiency (0.93 standard 8-bit; VLA 3-bit is ~0.80)",
        ),
        "weighting": weighting.strip().lower(),
        "robust": float(robust),
        "weighting_factor": fmt_field(w_factor, flag=w_flag, note=w_note),
    }


def _default_target_field_ids(ms_str: str, n_fields: int) -> tuple[list[int], str | None]:
    """Select OBSERVE_TARGET fields when field='' and STATE has target intents; else all fields."""
    state_dir = Path(ms_str) / "STATE"
    if not state_dir.exists():
        return list(range(n_fields)), None
    try:
        with open_table(str(state_dir)) as stb:
            if stb.nrows() == 0:
                return list(range(n_fields)), None
            modes = [str(x) for x in stb.getcol("OBS_MODE")]
        target_states = {idx for idx, m in enumerate(modes) if "TARGET" in m.upper()}
        if not target_states:
            return list(range(n_fields)), None
        with open_table(ms_str) as tb:
            if tb.nrows() == 0:
                return list(range(n_fields)), None
            fids = np.asarray(tb.getcol("FIELD_ID"), dtype=int)
            sids = np.asarray(tb.getcol("STATE_ID"), dtype=int)
        mask = np.isin(sids, list(target_states))
        matched = sorted({int(x) for x in fids[mask] if 0 <= int(x) < n_fields})
        if matched:
            return matched, "auto-selected target fields from STATE.OBS_MODE"
    except Exception:
        pass
    return list(range(n_fields)), None


def _resolve_band_and_sefd(
    profile: TelescopeProfile | None,
    spw_freqs_hz: list[tuple[int, float, float, str]],
    eff_bw_by_spw: dict[int, float] | None = None,
) -> tuple[str | None, float | None, str | None]:
    """Effective-bandwidth-weighted harmonic SEFD across selected SpWs from TelescopeProfile."""
    if profile is None:
        return None, None, "unrecognised telescope; no bundled SEFD profile"
    if not profile.sefd:
        return None, None, f"no SEFD table bundled for {profile.canonical}"
    codes: list[str] = []
    valid_entries: list[tuple[int, float, float, float]] = []
    missing_spws: list[int] = []
    for spw_id, centre_hz, bw_hz, spw_name in spw_freqs_hz:
        code = profile.band_code(centre_hz, spw_name)
        sefd = profile.sefd_for_freq(centre_hz, spw_name)
        if code is not None and code not in codes:
            codes.append(code)
        if sefd is None or sefd <= 0 or bw_hz <= 0:
            missing_spws.append(spw_id)
        else:
            eff_bw = (
                float(eff_bw_by_spw[spw_id])
                if eff_bw_by_spw is not None and spw_id in eff_bw_by_spw
                else float(bw_hz)
            )
            valid_entries.append((spw_id, float(bw_hz), max(0.0, eff_bw), float(sefd)))
    band_str = "/".join(codes) if codes else None
    if not valid_entries:
        return band_str, None, f"SEFD unavailable for {profile.canonical} band={band_str!r}"
    use_eff = sum(e[2] for e in valid_entries) > 0.0
    inv_sq_bw = 0.0
    bw_sum = 0.0
    for _spw_id, bw_hz, eff_bw, sefd in valid_entries:
        w = eff_bw if use_eff else bw_hz
        inv_sq_bw += w / (sefd * sefd)
        bw_sum += w
    if inv_sq_bw <= 0 or bw_sum <= 0:
        return band_str, None, f"SEFD unavailable for {profile.canonical} band={band_str!r}"
    eff_sefd = math.sqrt(bw_sum / inv_sq_bw)
    note = (
        f"SEFD missing for SpWs {missing_spws}; computed from remaining SpWs"
        if missing_spws
        else None
    )
    return band_str, eff_sefd, note


def run(
    ms_path: str,
    field: str = "",
    spw: str = "",
    stokes: str = "I",
    weighting: str = "briggs",
    robust: float = 0.5,
) -> dict:
    """
    Deterministic radiometer thermal noise estimate for an MS selection.

    Args:
        ms_path:   Path to the Measurement Set.
        field:     CASA field selection (name, wildcard, id, range). Empty selects
                   OBSERVE_TARGET fields when present, else all fields.
        spw:       CASA SpW id/range selection ('' = all SpWs observed on field).
        stokes:    Target Stokes parameter ('I', 'Q', 'U', 'V', 'IQUV', or single hand).
        weighting: 'natural', 'briggs' (default), or 'uniform'.
        robust:    Briggs robust parameter when weighting='briggs' (default 0.5).
    """
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    try:
        resolve_weighting_factor(weighting, robust)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    profile = resolve_telescope(ms_str)
    casa_calls.append("resolve_telescope() -> OBSERVATION.TELESCOPE_NAME")
    with open_table(str(Path(ms_str) / "OBSERVATION")) as tb:
        raw_tel = str(tb.getcol("TELESCOPE_NAME")[0]).strip() if tb.nrows() > 0 else "UNKNOWN"
    telescope_name = profile.canonical if profile is not None else raw_tel

    with open_table(str(Path(ms_str) / "ANTENNA")) as tb:
        n_ant_total = int(tb.nrows())
    casa_calls.append("tb.open(ANTENNA) -> nrows")

    with open_table(str(Path(ms_str) / "FIELD")) as tb:
        field_names = [str(x) for x in tb.getcol("NAME")]
    casa_calls.append("tb.open(FIELD) -> NAME")

    norm_field = normalize_field_sel(field)
    field_auto_note: str | None = None
    if norm_field:
        try:
            field_ids = match_field_names(field_names, norm_field)
        except ValueError as exc:
            raise ComputationError(str(exc), ms_path=ms_path) from None
    else:
        field_ids, field_auto_note = _default_target_field_ids(ms_str, len(field_names))
        if field_auto_note:
            warnings.append(field_auto_note)

    with open_table(str(Path(ms_str) / "SPECTRAL_WINDOW")) as tb:
        n_spw = int(tb.nrows())
        spw_meta: dict[int, tuple[float, float, str]] = {}
        for sid in range(n_spw):
            cf = np.asarray(tb.getcell("CHAN_FREQ", sid), dtype=float)
            cw = np.abs(np.asarray(tb.getcell("CHAN_WIDTH", sid), dtype=float))
            sname = str(tb.getcell("NAME", sid)) if "NAME" in tb.colnames() else ""
            spw_meta[sid] = (
                float(cf.mean()) if cf.size else 0.0,
                float(cw.sum()) if cw.size else 0.0,
                sname,
            )
    casa_calls.append("tb.open(SPECTRAL_WINDOW) -> CHAN_FREQ, CHAN_WIDTH")

    try:
        requested_spws = set(parse_spw_selection(spw, n_spw))
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    with open_table(str(Path(ms_str) / "DATA_DESCRIPTION")) as tb:
        dd_spws = [int(x) for x in tb.getcol("SPECTRAL_WINDOW_ID")]
    corr_by_dd = parallel_corr_by_ddid(ms_str)
    max_par_hands = max((len(c) for c in corr_by_dd), default=1)
    try:
        n_pol = resolve_n_pol(stokes, max_par_hands)
    except ValueError as exc:
        raise ComputationError(str(exc), ms_path=ms_path) from None

    # Query per DATA_DESC_ID (safe on mixed-channel SpWs).
    active_ants: set[int] = set()
    ant_unflagged_counts: dict[int, int] = {}
    ddid_vis_counts: dict[
        int, tuple[int, int]
    ] = {}  # ddid -> (unflagged, total) on active baselines
    field_time_steps: dict[int, dict[float, float]] = {fid: {} for fid in field_ids}
    observed_spws: set[int] = set()

    fid_list_taql = ",".join(str(fid) for fid in field_ids)
    with open_table(ms_str) as tb:
        has_exposure = "EXPOSURE" in tb.colnames()
        dur_col = "EXPOSURE" if has_exposure else "INTERVAL"
        for ddid, spw_id in enumerate(dd_spws):
            if spw_id not in requested_spws:
                continue
            par_indices = [idx for idx, _ in corr_by_dd[ddid]] or [0]
            sub = tb.query(
                f"DATA_DESC_ID == {ddid} && FIELD_ID IN [{fid_list_taql}] && ANTENNA1 != ANTENNA2"
            )
            try:
                nrows = int(sub.nrows())
                if nrows == 0:
                    continue
                observed_spws.add(spw_id)
                step = max(1, nrows // _MAX_SAMPLE_ROWS_PER_DDID)
                times = np.asarray(sub.getcol("TIME"), dtype=float)
                durs = np.asarray(sub.getcol(dur_col), dtype=float)
                fids = np.asarray(sub.getcol("FIELD_ID"), dtype=int)
                # Record unique integration durations per field across all rows; FLAG_ROW is counted
                # once inside per-SpW par_flags so flagged integrations are not double-counted.
                use_rows = np.ones(nrows, dtype=bool)
                for fid_val in np.unique(fids[use_rows]):
                    m = use_rows & (fids == fid_val)
                    t_r = np.round(times[m], 3)
                    _, uniq_idx = np.unique(t_r, return_index=True)
                    fmap = field_time_steps.setdefault(int(fid_val), {})
                    for tk, dv in zip(t_r[uniq_idx], durs[m][uniq_idx], strict=False):
                        if tk not in fmap or float(dv) > fmap[tk]:
                            fmap[tk] = max(0.0, float(dv))

                a1 = np.asarray(sub.getcol("ANTENNA1", rowincr=step), dtype=int)
                a2 = np.asarray(sub.getcol("ANTENNA2", rowincr=step), dtype=int)
                frow_s = np.asarray(sub.getcol("FLAG_ROW", rowincr=step), dtype=bool)
                flags = np.asarray(sub.getcol("FLAG", rowincr=step), dtype=bool)
                par_flags = flags[par_indices, :, :] | frow_s[None, None, :]
                unfl_per_row = (~par_flags).sum(axis=(0, 1))
                tot_per_row = par_flags.shape[0] * par_flags.shape[1]

                # Track active antennas (any unflagged visibility).
                live_rows = unfl_per_row > 0
                if np.any(live_rows):
                    for ant_id in np.unique(np.concatenate([a1[live_rows], a2[live_rows]])):
                        active_ants.add(int(ant_id))
                        ant_unflagged_counts[int(ant_id)] = (
                            ant_unflagged_counts.get(int(ant_id), 0) + 1
                        )

                ddid_vis_counts[ddid] = (
                    int(unfl_per_row.sum()),
                    int(tot_per_row * len(unfl_per_row)),
                    a1,
                    a2,
                    unfl_per_row,
                    tot_per_row,
                )  # type: ignore[assignment]
            finally:
                sub.close()
    casa_calls.append(f"tb.query(per DATA_DESC_ID) -> TIME, {dur_col}, FLAG")

    n_ant_unflagged = len(active_ants)
    spw_unfl_counts: dict[int, int] = {}
    spw_tot_counts: dict[int, int] = {}
    for ddid, tup in ddid_vis_counts.items():
        spw_id = dd_spws[ddid]
        _u_all, _t_all, a1, a2, unfl_per_row, tot_per_row = tup  # type: ignore[misc]
        if active_ants:
            both_live = np.isin(a1, list(active_ants)) & np.isin(a2, list(active_ants))
            spw_unfl_counts[spw_id] = spw_unfl_counts.get(spw_id, 0) + int(
                unfl_per_row[both_live].sum()
            )
            spw_tot_counts[spw_id] = spw_tot_counts.get(spw_id, 0) + int(
                tot_per_row * int(both_live.sum())
            )

    used_spws = sorted(observed_spws) if observed_spws else sorted(requested_spws)
    spw_eff_bw: dict[int, float] = {}
    for sid in used_spws:
        tot_spw = spw_tot_counts.get(sid, 0)
        unfl_spw = spw_unfl_counts.get(sid, 0)
        unfl_frac_spw = (unfl_spw / tot_spw) if tot_spw > 0 else 0.0
        spw_eff_bw[sid] = spw_meta[sid][1] * unfl_frac_spw

    spw_tuples = [(sid, spw_meta[sid][0], spw_meta[sid][1], spw_meta[sid][2]) for sid in used_spws]
    band_code, sefd_jy, sefd_note = _resolve_band_and_sefd(
        profile, spw_tuples, eff_bw_by_spw=spw_eff_bw
    )
    if sefd_note:
        warnings.append(sefd_note)

    if profile is not None and profile.sefd:
        sefd_spws = [
            sid
            for sid in used_spws
            if spw_meta[sid][1] > 0
            and (s_val := profile.sefd_for_freq(spw_meta[sid][0], spw_meta[sid][2])) is not None
            and s_val > 0
        ]
        bw_spws = sefd_spws if sefd_spws else used_spws
    else:
        bw_spws = used_spws

    total_bw_hz = sum(spw_meta[sid][1] for sid in bw_spws)
    eff_bw_hz = sum(spw_eff_bw[sid] for sid in bw_spws)
    unflagged_fraction = (eff_bw_hz / total_bw_hz) if total_bw_hz > 0 else 0.0
    center_freq_hz = (
        sum(spw_meta[sid][0] * spw_meta[sid][1] for sid in bw_spws) / total_bw_hz
        if total_bw_hz > 0
        else (float(np.mean([spw_meta[sid][0] for sid in bw_spws])) if bw_spws else 0.0)
    )

    per_field_durations = [sum(tmap.values()) for fid, tmap in field_time_steps.items() if tmap]
    on_source_total_s = float(sum(per_field_durations))
    if not per_field_durations:
        on_source_s = 0.0
    elif len(per_field_durations) == 1:
        on_source_s = per_field_durations[0]
    else:
        on_source_s = float(np.median(per_field_durations))

    calc = compute_radiometer_estimate(
        sefd_jy=sefd_jy,
        sefd_note=sefd_note,
        n_ant_total=n_ant_total,
        n_ant_unflagged=n_ant_unflagged,
        on_source_s=on_source_s,
        on_source_total_s=on_source_total_s,
        n_fields_selected=len(field_ids),
        total_bw_hz=total_bw_hz,
        unflagged_fraction=unflagged_fraction,
        n_pol=n_pol,
        eta_c=_DEFAULT_ETA_C,
        weighting=weighting,
        robust=robust,
        eff_bw_hz=eff_bw_hz,
    )

    data = {
        "telescope_name": fmt_field(
            telescope_name,
            flag="COMPLETE" if profile is not None else "UNAVAILABLE",
            note=None if profile is not None else f"unrecognised raw name {raw_tel!r}",
        ),
        "band_code": fmt_field(
            band_code,
            flag="COMPLETE" if band_code is not None else "UNAVAILABLE",
            note=None if band_code is not None else "band could not be resolved",
        ),
        "center_freq_hz": fmt_field(round(center_freq_hz, 3)),
        "selected_fields": [field_names[fid] for fid in field_ids],
        "n_fields_selected": len(field_ids),
        "selected_spws": used_spws,
        "stokes": stokes.strip().upper(),
        **calc,
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
