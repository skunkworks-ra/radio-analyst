"""
tools/image_stats.py — ms_image_stats

Post-imaging quality metrics from a CASA native image.

Reads the restored (or pbcor) image and returns:
  - rms_jy:                  robust RMS (1.4826 × MAD, noise estimate)
  - peak_jy:                 peak pixel value
  - min_jy:                  minimum finite pixel of image_path inside sibling .pb >= pb_level (or whole-image fallback)
  - flat_noise_peak_jy / flat_noise_min_jy: peak/min on sibling flat-noise .image (inside .pb >= pb_level)
  - negative_to_peak_ratio:  abs(min(0, flat_noise_min_jy)) / flat_noise_peak_jy for Stokes I / total intensity
  - mask-partitioned residual metrics inside .pb >= pb_level when sibling (or explicit) .mask exists:
    mask_pixels, mask_fraction_in_pb, residual_out_mask_{rms_jy,peak_jy,min_jy,peak_snr},
    residual_in_mask_{rms_jy,peak_jy,peak_snr}, residual_in_to_out_rms_ratio
  - dynamic_range:           abs(peak) / rms
  - beam_major_arcsec, beam_minor_arcsec, beam_pa_deg: restoring beam

For a multi-plane image (frequency cube and/or multi-Stokes, e.g. an IQUV
polarization cube) it additionally returns `n_planes` and `planes` — a
per-(Stokes, channel) list of rms_jy / peak_jy / dynamic_range. The scalar
fields above remain whole-image summaries.

`residual_rms_jy` is the noise to compare with the radiometer estimate: the
robust RMS of the sibling `.residual` image where the sibling `.pb` is at or
above `pb_level`. The whole-image `rms_jy` of a `.pbcor` image includes the
PB edge, where the noise is divided by a small gain. `rms_region` carries the
two paths, the PB level and the pixel count. `png_path`, if given, writes
plane 0 as a PNG with the PB contour at `pb_level`, for the model to look at.

`detection` is a descriptive label over dynamic_range, and
`detection_thresholds` carries the two constants behind it. Neither is a
go/no-go: whether a given peak-to-noise is sufficient depends on the science
goal, and that judgement lives in the skill (11-imaging.md), along with all
other interpretation (fractional polarization, spectral flatness).

All parameters are read from the image header and pixel data;
no MS access is performed.
"""

from __future__ import annotations

import math
from itertools import product
from pathlib import Path

from ms_inspect.util.casa_context import open_image
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_image_stats"

_MAD_TO_SIGMA = 1.4826

# Signed Stokes parameters where a negative extremum is a real polarized signal
# (e.g. Q = -50 mJy/beam) rather than an imaging bowling artifact.
_SIGNED_STOKES = frozenset({"Q", "U", "V", "RL", "LR", "XY", "YX"})

_ARCSEC_PER_UNIT: dict[str, float] = {
    "arcsec": 1.0,
    "arcsecs": 1.0,
    "arcsecond": 1.0,
    "arcseconds": 1.0,
    '"': 1.0,
    "''": 1.0,
    "arcmin": 60.0,
    "arcmins": 60.0,
    "arcminute": 60.0,
    "arcminutes": 60.0,
    "'": 60.0,
    "deg": 3600.0,
    "degs": 3600.0,
    "degree": 3600.0,
    "degrees": 3600.0,
    "rad": 180.0 * 3600.0 / math.pi,
    "rads": 180.0 * 3600.0 / math.pi,
    "radian": 180.0 * 3600.0 / math.pi,
    "radians": 180.0 * 3600.0 / math.pi,
    "mas": 1e-3,
    "marcsec": 1e-3,
    "uas": 1e-6,
    "uarcsec": 1e-6,
}

_DEG_PER_UNIT: dict[str, float] = {
    "deg": 1.0,
    "degs": 1.0,
    "degree": 1.0,
    "degrees": 1.0,
    "rad": 180.0 / math.pi,
    "rads": 180.0 / math.pi,
    "radian": 180.0 / math.pi,
    "radians": 180.0 / math.pi,
    "arcmin": 1.0 / 60.0,
    "arcmins": 1.0 / 60.0,
    "arcminute": 1.0 / 60.0,
    "arcminutes": 1.0 / 60.0,
    "'": 1.0 / 60.0,
    "arcsec": 1.0 / 3600.0,
    "arcsecs": 1.0 / 3600.0,
    "arcsecond": 1.0 / 3600.0,
    "arcseconds": 1.0 / 3600.0,
    '"': 1.0 / 3600.0,
    "''": 1.0 / 3600.0,
}


def _select_peak(max_v: float, min_v: float | None, stokes: str | None) -> float:
    """Return signed extremum for polarized Stokes (Q, U, V, cross-hands), else max_v."""
    if stokes in _SIGNED_STOKES and min_v is not None and math.isfinite(min_v):
        return float(min_v) if abs(min_v) > abs(max_v) else float(max_v)
    return float(max_v)


def _single_plane_stokes(ia) -> str | None:
    """Return the Stokes label of a single-plane image if determinable, else None."""
    try:
        csys = ia.coordsys()
        sn = csys.stokes()
        if sn and len(sn) == 1 and isinstance(sn[0], str):
            return sn[0]
    except Exception:
        return None
    return None


def _broadcast_pb(pb_pix, target_shape: tuple[int, ...]):
    """Broadcast pb_pix to target_shape when spatial axes match and extra axes are 1 or equal."""
    import numpy as np

    if pb_pix.shape == target_shape:
        return pb_pix
    if (
        pb_pix.ndim == len(target_shape)
        and pb_pix.shape[:2] == target_shape[:2]
        and all(p in (1, t) for p, t in zip(pb_pix.shape[2:], target_shape[2:], strict=True))
    ):
        return np.broadcast_to(pb_pix, target_shape)
    return None


def _quantity_to_arcsec(q: dict) -> float:
    """Convert a CASA angular quantity dict {'value': ..., 'unit': ...} to arcsec."""
    val = float(q["value"])
    unit = str(q.get("unit", "arcsec")).strip()
    if not unit:
        return val
    scale = _ARCSEC_PER_UNIT.get(unit)
    if scale is None:
        scale = _ARCSEC_PER_UNIT.get(unit.lower())
    if scale is not None:
        return val * scale
    import astropy.units as u

    return float((val * u.Unit(unit)).to_value(u.arcsec))


def _quantity_to_deg(q: dict) -> float:
    """Convert a CASA angular quantity dict {'value': ..., 'unit': ...} to deg."""
    val = float(q["value"])
    unit = str(q.get("unit", "deg")).strip()
    if not unit:
        return val
    scale = _DEG_PER_UNIT.get(unit)
    if scale is None:
        scale = _DEG_PER_UNIT.get(unit.lower())
    if scale is not None:
        return val * scale
    import astropy.units as u

    return float((val * u.Unit(unit)).to_value(u.deg))


# Peak-to-noise (dynamic range) label boundaries. These are descriptive
# thresholds, not a go/no-go: what peak-to-noise is sufficient depends on the
# science goal, and that judgement lives in 11-imaging.md. Both constants are
# returned in the response so the label can be recomputed under a different
# tolerance.
#   <= 5        : undetected
#   > 5, < 10   : marginal
#   >= 10       : detection
_P2N_UNDETECTED = 5.0
_P2N_MARGINAL = 10.0


def _classify_detection(dr: float | None) -> str:
    """Descriptive peak-to-noise label. No pass/fail semantics."""
    if dr is None:
        return "unknown"
    if dr <= _P2N_UNDETECTED:
        return "undetected"
    if dr < _P2N_MARGINAL:
        return "marginal"
    return "detection"


def _plane_labels(
    remaining_axes: list[int],
    remaining_shape: list[int],
    stokes_pix_axis: int | None,
    spec_pix_axis: int | None,
    stokes_names: list[str] | None = None,
) -> list[dict]:
    """Label each (stokes, channel) plane in C-order over the non-spatial axes.

    `remaining_axes` are the image pixel axes left after collapsing the two
    spatial axes (e.g. [2, 3] for a [RA, Dec, Stokes, Freq] image), in image
    order. `remaining_shape` is their lengths in the same order. The returned
    list is aligned with itertools.product(*[range(n) for n in remaining_shape])
    — i.e. C-order, matching how a CASA statistics array flattens.

    stokes_pix_axis / spec_pix_axis are the image pixel-axis numbers for the
    Stokes and spectral coordinates (or None if absent). stokes_names, if given,
    maps a Stokes pixel index to its label ('I', 'Q', ...).
    """
    labels: list[dict] = []
    for combo in product(*[range(n) for n in remaining_shape]):
        entry: dict = {}
        for axis, idx in zip(remaining_axes, combo, strict=True):
            if axis == stokes_pix_axis:
                entry["stokes_index"] = idx
                if stokes_names is not None and idx < len(stokes_names):
                    entry["stokes"] = stokes_names[idx]
            elif axis == spec_pix_axis:
                entry["chan"] = idx
        labels.append(entry)
    return labels


def _find_pixel_axis(csys, kind: str) -> int | None:
    """Return the image pixel-axis number for a coordinate kind, or None.

    Wraps coordsys.findcoordinate(), whose casatools return shape is a record
    with a 'return' flag and a 'pixel' array. Defensive against API variation.
    """
    try:
        rec = csys.findcoordinate(kind)
    except Exception:
        return None
    if not isinstance(rec, dict):
        return None
    if not rec.get("return", True):
        return None
    pix = rec.get("pixel")
    if pix is None or len(pix) == 0:
        return None
    return int(pix[0])


def _per_plane_stats(
    ia,
    casa_calls: list[str],
    warnings: list[str],
    image_path: str = "",
    pb_level: float = 0.1,
) -> list[dict] | None:
    """Per-(Stokes, channel) rms/peak/DR for a multi-plane image.

    When a sibling .pb image exists on disk with broadcastable shape (e.g.
    [nx, ny, 1, nchan] or [nx, ny, nstokes, nchan]), per-plane statistics are
    restricted to pixels where pb >= pb_level so primary-beam division on
    .image.pbcor cubes does not corrupt edge noise or peaks. Falls back to
    ia.statistics(axes=[0, 1]) when no sibling .pb exists.

    Returns None for a single-plane image (the scalar path handles it) or when
    the image shape / statistics cannot be resolved.
    """
    try:
        shape = [int(n) for n in ia.shape()]
    except Exception:
        return None
    if len(shape) <= 2:
        return None
    n_planes = 1
    for n in shape[2:]:
        n_planes *= n
    if n_planes <= 1:
        return None

    remaining_axes = list(range(2, len(shape)))
    remaining_shape = [shape[a] for a in remaining_axes]

    stokes_pix_axis = spec_pix_axis = None
    stokes_names: list[str] | None = None
    try:
        csys = ia.coordsys()
        casa_calls.append("ia.coordsys() [plane axis identification]")
        stokes_pix_axis = _find_pixel_axis(csys, "stokes")
        spec_pix_axis = _find_pixel_axis(csys, "spectral")
        try:
            sn = csys.stokes()
            stokes_names = [str(s) for s in sn] if sn else None
        except Exception:
            stokes_names = None
    except Exception as exc:
        warnings.append(f"Could not read coordinate system for plane labels: {exc}")

    import numpy as np

    labels = _plane_labels(
        remaining_axes, remaining_shape, stokes_pix_axis, spec_pix_axis, stokes_names
    )

    # Prefer PB-restricted per-plane statistics when a sibling .pb exists.
    if image_path:
        _, pb_path = _siblings(image_path)
        if pb_path.exists():
            try:
                with open_image(str(pb_path)) as ia_pb:
                    pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
                img_pix = np.asarray(ia.getchunk(), dtype=float)
                pb_bcast = _broadcast_pb(pb_pix, tuple(shape))
                if pb_bcast is not None and img_pix.shape == tuple(shape):
                    casa_calls.append(
                        f"ia.getchunk() on {Path(image_path).name} where "
                        f"{pb_path.name} >= {pb_level} [per-plane]"
                    )
                    planes_pb: list[dict] = []
                    for lab, combo in zip(
                        labels, product(*[range(n) for n in remaining_shape]), strict=True
                    ):
                        sl = (slice(None), slice(None), *combo)
                        plane_img = img_pix[sl]
                        plane_pb = pb_bcast[sl]
                        vals = plane_img[(plane_pb >= pb_level) & np.isfinite(plane_img)]
                        if vals.size > 0:
                            med_v = float(np.median(vals))
                            mad_v = float(np.median(np.abs(vals - med_v)))
                            rms_v = _MAD_TO_SIGMA * mad_v
                            max_v = float(np.max(vals))
                            min_v = float(np.min(vals))
                            peak_v = _select_peak(max_v, min_v, lab.get("stokes"))
                            dr = abs(peak_v) / rms_v if rms_v > 0 else None
                        else:
                            rms_v = 0.0
                            peak_v = 0.0
                            dr = None
                        entry = dict(lab)
                        entry["rms_jy"] = round(rms_v, 9)
                        entry["peak_jy"] = round(peak_v, 9)
                        entry["dynamic_range"] = round(dr, 1) if dr is not None else None
                        entry["detection"] = _classify_detection(dr)
                        planes_pb.append(entry)
                    return planes_pb
                warnings.append(
                    f"Sibling PB shape {pb_pix.shape} incompatible with image shape "
                    f"{tuple(shape)}; falling back to unmasked per-plane statistics."
                )
            except Exception as exc:
                warnings.append(
                    f"Could not apply sibling PB mask ({pb_path.name}) to per-plane stats: {exc}"
                )

    try:
        sr = ia.statistics(axes=[0, 1], robust=True)
        ss = ia.statistics(axes=[0, 1])
        casa_calls.append("ia.statistics(axes=[0,1]) [per-plane]")
    except Exception as exc:
        warnings.append(f"Per-plane statistics failed: {exc}")
        return None

    mad = np.asarray(sr.get("medabsdevmed"), dtype=float).reshape(-1)
    mx = np.asarray(ss.get("max"), dtype=float).reshape(-1)
    mn_raw = ss.get("min")
    mn = (
        np.asarray(mn_raw, dtype=float).reshape(-1)
        if mn_raw is not None
        else np.full(n_planes, math.nan)
    )
    if mad.size != n_planes or mx.size != n_planes or mn.size != n_planes:
        warnings.append(
            f"Per-plane statistics array size ({mad.size}/{mx.size}) does not match "
            f"plane count ({n_planes}); skipping per-plane breakdown."
        )
        return None

    planes: list[dict] = []
    for lab, mad_v, max_v, min_v in zip(labels, mad, mx, mn, strict=True):
        rms_v = _MAD_TO_SIGMA * float(mad_v)
        min_opt = float(min_v) if math.isfinite(min_v) else None
        peak_v = _select_peak(float(max_v), min_opt, lab.get("stokes"))
        dr = abs(peak_v) / rms_v if rms_v > 0 else None
        entry = dict(lab)
        entry["rms_jy"] = round(rms_v, 9)
        entry["peak_jy"] = round(peak_v, 9)
        entry["dynamic_range"] = round(dr, 1) if dr is not None else None
        entry["detection"] = _classify_detection(dr)
        planes.append(entry)
    return planes


def _extract_beam(beam_info: dict) -> tuple[float | None, float | None, float | None]:
    """Return (major_arcsec, minor_arcsec, pa_deg) from ia.restoringbeam() output."""
    if "major" in beam_info:
        major = _quantity_to_arcsec(beam_info["major"])
        minor = _quantity_to_arcsec(beam_info["minor"])
        pa = _quantity_to_deg(beam_info["positionangle"])
        return major, minor, pa

    # Multi-beam image (cube or mtmfs): use channel 0 as representative.
    try:
        first = beam_info["beams"]["*0"]["*0"]
        return (
            _quantity_to_arcsec(first["major"]),
            _quantity_to_arcsec(first["minor"]),
            _quantity_to_deg(first["positionangle"]),
        )
    except (KeyError, TypeError):
        return None, None, None


def _siblings(image_path: str) -> tuple[Path, Path]:
    """(.residual, .pb) next to an .image or .image.pbcor (or .tt0 variants)."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for suffix in (".image.pbcor.tt0", ".image.tt0", ".image.pbcor", ".image"):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            tt = ".tt0" if suffix.endswith(".tt0") else ""
            return p.parent / f"{base}.residual{tt}", p.parent / f"{base}.pb{tt}"
    return p.parent / f"{name}.residual", p.parent / f"{name}.pb"


def _sibling_flat_image(image_path: str) -> Path | None:
    """Flat-noise .image (or .image.tt0) sibling when image_path is a .pbcor image."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for pbcor_suf, flat_suf in ((".image.pbcor.tt0", ".image.tt0"), (".image.pbcor", ".image")):
        if name.endswith(pbcor_suf):
            cand = p.parent / f"{name[: -len(pbcor_suf)]}{flat_suf}"
            return cand if cand.exists() else None
    return None


def _sibling_mask(image_path: str) -> Path | None:
    """Sibling CASA .mask directory next to an .image / .image.pbcor (including mtmfs .tt0)."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for suffix in (".image.pbcor.tt0", ".image.tt0", ".image.pbcor", ".image"):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            tt = ".tt0" if suffix.endswith(".tt0") else ""
            candidates = [p.parent / f"{base}.mask"]
            if tt:
                candidates.append(p.parent / f"{base}.mask{tt}")
            for cand in candidates:
                if cand.exists():
                    return cand
            return None
    cand = p.parent / f"{name}.mask"
    return cand if cand.exists() else None


def _residual_rms(
    image_path: str, pb_level: float, casa_calls: list[str]
) -> tuple[float | None, dict, str | None]:
    """Robust RMS of the sibling .residual where the sibling .pb >= pb_level."""
    residual, pb = _siblings(image_path)
    region = {
        "residual_path": str(residual),
        "pb_path": str(pb),
        "pb_level": pb_level,
        "n_pixels": None,
    }
    missing = [str(x) for x in (residual, pb) if not x.exists()]
    if missing:
        return None, region, f"not found: {', '.join(missing)}"
    import numpy as np

    with open_image(str(pb)) as ia_pb:
        pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
    with open_image(str(residual)) as ia_res:
        res_pix = np.asarray(ia_res.getchunk(), dtype=float)
    casa_calls.append(f"ia.getchunk() on {residual.name} where {pb.name} >= {pb_level}")
    pb_bcast = _broadcast_pb(pb_pix, res_pix.shape)
    if pb_bcast is None:
        return None, region, f"shape mismatch: pb {pb_pix.shape}, residual {res_pix.shape}"
    vals = res_pix[(pb_bcast >= pb_level) & np.isfinite(res_pix)]
    region["n_pixels"] = int(vals.size)
    if vals.size == 0:
        return None, region, f"no pixels with pb >= {pb_level}"
    mad = float(np.median(np.abs(vals - np.median(vals))))
    return _MAD_TO_SIGMA * mad, region, None


def _pb_masked_extrema(
    ia,
    image_path: str,
    pb_level: float,
    fallback_max: float | None,
    fallback_min: float | None,
    casa_calls: list[str],
    warnings: list[str],
    tag: str = "min_jy",
) -> tuple[float | None, float | None, str]:
    """(max, min) finite pixel values inside sibling .pb >= pb_level, else whole-image fallback."""
    _, pb_path = _siblings(image_path)
    img_name = Path(image_path).name
    if not pb_path.exists():
        if fallback_min is None and fallback_max is None:
            return (
                None,
                None,
                f"extrema not returned by ia.statistics() and {pb_path.name} not found",
            )
        return fallback_max, fallback_min, f"whole-image on {img_name} (sibling .pb not found)"

    import numpy as np

    try:
        with open_image(str(pb_path)) as ia_pb:
            pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
        img_pix = np.asarray(ia.getchunk(), dtype=float)
        pb_bcast = _broadcast_pb(pb_pix, img_pix.shape)
        if pb_bcast is None:
            warnings.append(
                f"Sibling PB shape {pb_pix.shape} incompatible with image shape "
                f"{img_pix.shape}; falling back to whole-image {tag}."
            )
            return (
                fallback_max,
                fallback_min,
                f"whole-image on {img_name} (sibling .pb shape mismatch)",
            )
        casa_calls.append(f"ia.getchunk() on {img_name} where {pb_path.name} >= {pb_level} [{tag}]")
        vals = img_pix[(pb_bcast >= pb_level) & np.isfinite(img_pix)]
        if vals.size == 0:
            return None, None, f"no finite pixels on {img_name} with {pb_path.name} >= {pb_level}"
        return (
            float(np.max(vals)),
            float(np.min(vals)),
            f"inside {pb_path.name} >= {pb_level} on {img_name}",
        )
    except Exception as exc:
        warnings.append(
            f"Could not apply sibling PB mask ({pb_path.name}) for {tag}: {exc}; "
            f"falling back to whole-image {tag}."
        )
        return fallback_max, fallback_min, f"whole-image on {img_name} (sibling .pb read failed)"


def _pb_masked_min(
    ia,
    image_path: str,
    pb_level: float,
    fallback_min: float | None,
    casa_calls: list[str],
    warnings: list[str],
) -> tuple[float | None, str]:
    """Minimum finite pixel value inside sibling .pb >= pb_level, else whole-image fallback."""
    _, min_v, note = _pb_masked_extrema(
        ia, image_path, pb_level, None, fallback_min, casa_calls, warnings, tag="min_jy"
    )
    return min_v, f"min pixel {note}" if min_v is not None else note


def _flat_noise_extrema(
    ia,
    image_path: str,
    pb_level: float,
    primary_max: float | None,
    primary_min: float | None,
    primary_note: str,
    casa_calls: list[str],
    warnings: list[str],
) -> tuple[float | None, float | None, str]:
    """(peak, min, note) on sibling flat-noise .image inside PB >= pb_level, else image_path."""
    flat_path = _sibling_flat_image(image_path)
    if flat_path is None:
        return primary_max, primary_min, primary_note

    try:
        with open_image(str(flat_path)) as ia_flat:
            st = ia_flat.statistics()
            fmax = float(st["max"][0]) if st.get("max") is not None and len(st["max"]) > 0 else None
            fmin = float(st["min"][0]) if st.get("min") is not None and len(st["min"]) > 0 else None
            return _pb_masked_extrema(
                ia_flat,
                str(flat_path),
                pb_level,
                fmax,
                fmin,
                casa_calls,
                warnings,
                tag="flat_noise",
            )
    except Exception as exc:
        warnings.append(
            f"Could not read sibling flat-noise image ({flat_path.name}): {exc}; "
            "falling back to image_path extrema."
        )
        return primary_max, primary_min, f"{primary_note} (flat-noise sibling read failed)"


def _mask_partitioned_residual_stats(
    image_path: str,
    pb_level: float,
    mask_path: str | None,
    casa_calls: list[str],
    warnings: list[str],
) -> dict:
    """Residual RMS/peak/SNR split inside vs outside the clean mask within PB >= pb_level."""
    residual, pb = _siblings(image_path)
    resolved_mask: Path | None = (
        Path(mask_path).expanduser().resolve() if mask_path else _sibling_mask(image_path)
    )

    def _unavailable_all(reason: str) -> dict:
        keys = (
            "mask_pixels",
            "mask_fraction_in_pb",
            "residual_out_mask_rms_jy",
            "residual_out_mask_peak_jy",
            "residual_out_mask_min_jy",
            "residual_out_mask_peak_snr",
            "residual_in_mask_rms_jy",
            "residual_in_mask_peak_jy",
            "residual_in_mask_peak_snr",
            "residual_in_to_out_rms_ratio",
        )
        return {k: fmt_field(None, flag="UNAVAILABLE", note=reason) for k in keys}

    if resolved_mask is None or not resolved_mask.exists():
        reason = f"mask_path not found: {mask_path}" if mask_path else "sibling .mask not found"
        return _unavailable_all(reason)

    missing = [str(x.name) for x in (residual, pb) if not x.exists()]
    if missing:
        return _unavailable_all(f"sibling image not found: {', '.join(missing)}")

    import numpy as np

    try:
        with open_image(str(pb)) as ia_pb:
            pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
        with open_image(str(residual)) as ia_res:
            res_pix = np.asarray(ia_res.getchunk(), dtype=float)
        with open_image(str(resolved_mask)) as ia_msk:
            msk_pix = np.asarray(ia_msk.getchunk(), dtype=float)
    except Exception as exc:
        warnings.append(f"Could not read mask-partitioned residual images: {exc}")
        return _unavailable_all(f"read failed: {exc}")

    pb_bcast = _broadcast_pb(pb_pix, res_pix.shape)
    msk_bcast = _broadcast_pb(msk_pix, res_pix.shape)
    if pb_bcast is None or msk_bcast is None:
        reason = (
            f"shape mismatch: residual {res_pix.shape}, pb {pb_pix.shape}, mask {msk_pix.shape}"
        )
        warnings.append(f"Mask-partitioned residual stats skipped ({reason}).")
        return _unavailable_all(reason)

    casa_calls.append(
        f"ia.getchunk() on {residual.name} partitioned by {resolved_mask.name} "
        f"where {pb.name} >= {pb_level}"
    )

    valid = (pb_bcast >= pb_level) & np.isfinite(res_pix)
    n_valid = int(valid.sum())
    if n_valid == 0:
        return _unavailable_all(f"no finite pixels with {pb.name} >= {pb_level}")

    msk_bool = np.nan_to_num(msk_bcast, nan=0.0) > 0.5
    in_vals = res_pix[valid & msk_bool]
    out_vals = res_pix[valid & ~msk_bool]
    n_in = int(in_vals.size)
    n_out = int(out_vals.size)

    mask_frac = round(n_in / n_valid, 6)

    out_rms: float | None = None
    out_peak: float | None = None
    out_min: float | None = None
    out_peak_snr: float | None = None
    if n_out > 0:
        out_med = float(np.median(out_vals))
        out_rms = _MAD_TO_SIGMA * float(np.median(np.abs(out_vals - out_med)))
        out_peak = float(np.max(out_vals))
        out_min = float(np.min(out_vals))
        if out_rms > 0:
            out_peak_snr = out_peak / out_rms

    in_rms: float | None = None
    in_peak: float | None = None
    in_peak_snr: float | None = None
    in_to_out_ratio: float | None = None
    if n_in > 0:
        in_rms = float(np.sqrt(np.mean(in_vals * in_vals)))
        in_peak = float(np.max(np.abs(in_vals)))
        if out_rms is not None and out_rms > 0:
            in_peak_snr = in_peak / out_rms
            in_to_out_ratio = in_rms / out_rms

    mask_label = resolved_mask.name
    out_note = (
        f"1.4826 x MAD of {residual.name} outside {mask_label} where {pb.name} >= {pb_level}"
        if out_rms is not None
        else f"no pixels outside {mask_label} with {pb.name} >= {pb_level}"
    )
    in_note = (
        f"RMS (sqrt(mean(x^2))) of {residual.name} inside {mask_label} where {pb.name} >= {pb_level}"
        if in_rms is not None
        else f"no pixels inside {mask_label} with {pb.name} >= {pb_level}"
    )

    return {
        "mask_pixels": fmt_field(
            n_in, note=f"masked pixels inside {pb.name} >= {pb_level} ({mask_label})"
        ),
        "mask_fraction_in_pb": fmt_field(
            mask_frac, note=f"{n_in} / {n_valid} pixels inside {pb.name} >= {pb_level}"
        ),
        "residual_out_mask_rms_jy": fmt_field(
            round(out_rms, 9) if out_rms is not None else None,
            flag="COMPLETE" if out_rms is not None else "UNAVAILABLE",
            note=out_note,
        ),
        "residual_out_mask_peak_jy": fmt_field(
            round(out_peak, 9) if out_peak is not None else None,
            flag="COMPLETE" if out_peak is not None else "UNAVAILABLE",
            note=f"max positive pixel outside {mask_label}" if out_peak is not None else out_note,
        ),
        "residual_out_mask_min_jy": fmt_field(
            round(out_min, 9) if out_min is not None else None,
            flag="COMPLETE" if out_min is not None else "UNAVAILABLE",
            note=f"min pixel outside {mask_label}" if out_min is not None else out_note,
        ),
        "residual_out_mask_peak_snr": fmt_field(
            round(out_peak_snr, 2) if out_peak_snr is not None else None,
            flag="COMPLETE" if out_peak_snr is not None else "UNAVAILABLE",
            note="residual_out_mask_peak_jy / residual_out_mask_rms_jy"
            if out_peak_snr is not None
            else "outside-mask RMS unavailable or zero",
        ),
        "residual_in_mask_rms_jy": fmt_field(
            round(in_rms, 9) if in_rms is not None else None,
            flag="COMPLETE" if in_rms is not None else "UNAVAILABLE",
            note=in_note,
        ),
        "residual_in_mask_peak_jy": fmt_field(
            round(in_peak, 9) if in_peak is not None else None,
            flag="COMPLETE" if in_peak is not None else "UNAVAILABLE",
            note=f"max(|residual|) inside {mask_label}" if in_peak is not None else in_note,
        ),
        "residual_in_mask_peak_snr": fmt_field(
            round(in_peak_snr, 2) if in_peak_snr is not None else None,
            flag="COMPLETE" if in_peak_snr is not None else "UNAVAILABLE",
            note="residual_in_mask_peak_jy / residual_out_mask_rms_jy"
            if in_peak_snr is not None
            else "inside-mask peak or outside-mask RMS unavailable",
        ),
        "residual_in_to_out_rms_ratio": fmt_field(
            round(in_to_out_ratio, 3) if in_to_out_ratio is not None else None,
            flag="COMPLETE" if in_to_out_ratio is not None else "UNAVAILABLE",
            note="residual_in_mask_rms_jy / residual_out_mask_rms_jy"
            if in_to_out_ratio is not None
            else "inside-mask or outside-mask RMS unavailable",
        ),
    }


def _write_png(image_path: str, png_path: str, pb_level: float) -> str:
    """Plane 0 as a PNG, viridis over the 1st to 99.9th percentile, PB contour in white."""
    import numpy as np
    from bokeh.palettes import Viridis256
    from PIL import Image

    with open_image(image_path) as ia:
        shape = [int(n) for n in ia.shape()]
        trc = [shape[0] - 1, shape[1] - 1] + [0] * (len(shape) - 2)
        plane = np.asarray(ia.getchunk(blc=[0] * len(shape), trc=trc), dtype=float)
    plane = plane.reshape(shape[0], shape[1]).T[::-1]  # CASA (x, y) -> rows top-down
    finite = plane[np.isfinite(plane)]
    lo, hi = (
        (float(np.percentile(finite, 1)), float(np.percentile(finite, 99.9)))
        if finite.size
        else (0.0, 1.0)
    )
    idx = np.clip((np.nan_to_num(plane, nan=lo) - lo) / ((hi - lo) or 1.0), 0, 1)
    lut = np.array([[int(h[i : i + 2], 16) for i in (1, 3, 5)] for h in Viridis256], np.uint8)
    rgb = lut[(idx * 255).astype(int)]
    _, pb = _siblings(image_path)
    if pb.exists():
        with open_image(str(pb)) as ia_pb:
            pbs = [int(n) for n in ia_pb.shape()]
            pbtrc = [pbs[0] - 1, pbs[1] - 1] + [0] * (len(pbs) - 2)
            pbp = np.asarray(ia_pb.getchunk(blc=[0] * len(pbs), trc=pbtrc), dtype=float)
        inside = (pbp.reshape(pbs[0], pbs[1]).T[::-1] >= pb_level).astype(np.int8)
        if inside.shape == idx.shape:
            edge = (np.abs(np.diff(inside, axis=0, prepend=inside[:1])) > 0) | (
                np.abs(np.diff(inside, axis=1, prepend=inside[:, :1])) > 0
            )
            rgb[edge] = 255
    Image.fromarray(rgb).save(png_path)
    return f"plane 0; colour 1st to 99.9th percentile ({lo:.4g} to {hi:.4g} Jy/beam); white line pb = {pb_level}"


def run(
    image_path: str,
    psf_path: str | None = None,
    pb_level: float = 0.1,
    png_path: str | None = None,
    mask_path: str | None = None,
) -> dict:
    """
    Compute quality metrics for a CASA image.

    Uses ia.statistics(robust=True) for a MAD-based noise estimate that is
    insensitive to residual source flux in the image plane.

    Args:
        image_path: Path to the CASA image directory (e.g. imagename.image.pbcor).
        psf_path:   Optional path to the PSF image (imagename.psf).
                    If provided, the restoring beam is also read from the PSF
                    header as a cross-check; the primary beam is always taken
                    from image_path.
        pb_level:   PB level for the residual RMS region (default 0.1).
        png_path:   If given, write plane 0 as a PNG here.

    Returns:
        Standard response envelope with rms_jy, peak_jy, dynamic_range,
        beam_major_arcsec, beam_minor_arcsec, beam_pa_deg.
    """
    casa_calls: list[str] = []
    warnings: list[str] = []

    # ------------------------------------------------------------------
    # Open primary image
    # ------------------------------------------------------------------
    with open_image(image_path) as ia:
        # Robust statistics: MAD-based noise estimate.
        stats_robust = ia.statistics(robust=True)
        casa_calls.append(f"ia.statistics(robust=True) on {Path(image_path).name}")

        mad_arr = stats_robust.get("medabsdevmed")
        if mad_arr is None or len(mad_arr) == 0:
            warnings.append(
                "ia.statistics(robust=True) did not return medabsdevmed; falling back to rms."
            )
            stats_simple = ia.statistics()
            rms_val = float(stats_simple["rms"][0])
            casa_calls.append("ia.statistics() fallback for rms")
        else:
            rms_val = _MAD_TO_SIGMA * float(mad_arr[0])

        # Peak: use simple statistics for max/min pixel value.
        stats_simple = ia.statistics()
        casa_calls.append(f"ia.statistics() on {Path(image_path).name}")
        max_val = float(stats_simple["max"][0])
        min_arr = stats_simple.get("min")
        min_val = float(min_arr[0]) if min_arr is not None and len(min_arr) > 0 else None

        # Per-plane breakdown for cubes / multi-Stokes images (None otherwise).
        planes = _per_plane_stats(
            ia, casa_calls, warnings, image_path=image_path, pb_level=pb_level
        )
        single_stokes = _single_plane_stokes(ia)
        pb_max_val, min_jy_val, extrema_note = _pb_masked_extrema(
            ia, image_path, pb_level, max_val, min_val, casa_calls, warnings, tag="min_jy"
        )
        peak_val = _select_peak(
            pb_max_val if pb_max_val is not None else max_val,
            min_jy_val if min_jy_val is not None else min_val,
            single_stokes,
        )
        min_jy_note = (
            f"whole-image min ({extrema_note})"
            if extrema_note.startswith("whole-image")
            else (f"min pixel {extrema_note}" if min_jy_val is not None else extrema_note)
        )
        flat_peak_val, flat_min_val, flat_note = _flat_noise_extrema(
            ia,
            image_path,
            pb_level,
            pb_max_val,
            min_jy_val,
            extrema_note,
            casa_calls,
            warnings,
        )

        # Beam from image header.
        try:
            beam_info = ia.restoringbeam()
            casa_calls.append("ia.restoringbeam()")
            beam_major, beam_minor, beam_pa = _extract_beam(beam_info)
        except Exception as exc:
            warnings.append(f"Could not read restoring beam from image: {exc}")
            beam_major = beam_minor = beam_pa = None

    # ------------------------------------------------------------------
    # Optional PSF beam cross-check
    # ------------------------------------------------------------------
    psf_beam_major: float | None = None
    if psf_path is not None:
        psf_p = Path(psf_path).expanduser().resolve()
        if not psf_p.exists():
            warnings.append(f"psf_path does not exist: {psf_path} — skipping PSF beam read.")
        else:
            try:
                with open_image(str(psf_p)) as ia_psf:
                    psf_beam_info = ia_psf.restoringbeam()
                    casa_calls.append(f"ia.restoringbeam() on {psf_p.name}")
                psf_beam_major, psf_beam_minor, psf_beam_pa = _extract_beam(psf_beam_info)
            except Exception as exc:
                warnings.append(f"Could not read beam from PSF image: {exc}")

    # ------------------------------------------------------------------
    # Dynamic range and negative-to-peak ratio
    # ------------------------------------------------------------------
    if rms_val > 0:
        dynamic_range = abs(peak_val) / rms_val
    else:
        dynamic_range = None
        warnings.append("RMS is zero or negative; dynamic range not computable.")

    has_signed_stokes = single_stokes in _SIGNED_STOKES or (
        planes is not None and any(p.get("stokes") in _SIGNED_STOKES for p in planes)
    )
    if has_signed_stokes:
        neg_to_peak = None
        neg_to_peak_note = (
            f"not defined for signed Stokes {single_stokes}"
            if single_stokes in _SIGNED_STOKES
            else "not defined across multi-Stokes image containing signed Q/U/V"
        )
    elif flat_min_val is None:
        neg_to_peak = None
        neg_to_peak_note = "flat_noise_min_jy unavailable"
    elif flat_peak_val is None or flat_peak_val <= 0:
        neg_to_peak = None
        neg_to_peak_note = "flat_noise_peak_jy <= 0"
    else:
        neg_to_peak = abs(min(0.0, flat_min_val)) / flat_peak_val
        neg_to_peak_note = f"abs(min(0, flat_noise_min_jy)) / flat_noise_peak_jy ({flat_note})"

    # ------------------------------------------------------------------
    # Build response
    # ------------------------------------------------------------------
    data: dict = {
        "image_path": fmt_field(str(Path(image_path).expanduser().resolve())),
        "rms_jy": fmt_field(round(rms_val, 9)),
        "peak_jy": fmt_field(round(peak_val, 9)),
        "min_jy": fmt_field(
            round(min_jy_val, 9) if min_jy_val is not None else None,
            flag="COMPLETE" if min_jy_val is not None else "UNAVAILABLE",
            note=min_jy_note,
        ),
        "flat_noise_peak_jy": fmt_field(
            round(flat_peak_val, 9) if flat_peak_val is not None else None,
            flag="COMPLETE" if flat_peak_val is not None else "UNAVAILABLE",
            note=f"peak pixel {flat_note}" if flat_peak_val is not None else flat_note,
        ),
        "flat_noise_min_jy": fmt_field(
            round(flat_min_val, 9) if flat_min_val is not None else None,
            flag="COMPLETE" if flat_min_val is not None else "UNAVAILABLE",
            note=f"min pixel {flat_note}" if flat_min_val is not None else flat_note,
        ),
        "negative_to_peak_ratio": fmt_field(
            round(neg_to_peak, 4) if neg_to_peak is not None else None,
            flag="COMPLETE" if neg_to_peak is not None else "UNAVAILABLE",
            note=neg_to_peak_note,
        ),
        "dynamic_range": fmt_field(
            round(dynamic_range, 1) if dynamic_range is not None else None,
            flag="COMPLETE" if dynamic_range is not None else "UNAVAILABLE",
        ),
        "detection": fmt_field(
            _classify_detection(dynamic_range),
            flag="COMPLETE" if dynamic_range is not None else "UNAVAILABLE",
        ),
        # Returned so the label is checkable and recomputable under a
        # different tolerance. dynamic_range <= undetected_at, or >=
        # detection_at, are the two boundaries.
        "detection_thresholds": fmt_field(
            {
                "undetected_at_or_below": _P2N_UNDETECTED,
                "detection_at_or_above": _P2N_MARGINAL,
                "quantity": "peak-to-noise (dynamic_range)",
            }
        ),
    }

    res_rms, region, why = _residual_rms(image_path, pb_level, casa_calls)
    data["residual_rms_jy"] = fmt_field(
        round(res_rms, 9) if res_rms is not None else None,
        flag="COMPLETE" if res_rms is not None else "UNAVAILABLE",
        note=why or "1.4826 x MAD of .residual where .pb >= pb_level",
    )
    data["residual_dynamic_range"] = fmt_field(
        round(abs(peak_val) / res_rms, 1) if res_rms else None,
        flag="COMPLETE" if res_rms else "UNAVAILABLE",
        note="peak_jy / residual_rms_jy",
    )
    data["rms_region"] = fmt_field(region)
    data.update(
        _mask_partitioned_residual_stats(image_path, pb_level, mask_path, casa_calls, warnings)
    )

    if png_path:
        try:
            note = _write_png(image_path, png_path, pb_level)
            data["png_path"] = fmt_field(png_path, note=note)
        except Exception as exc:
            data["png_path"] = fmt_field(None, flag="UNAVAILABLE", note=str(exc))

    if beam_major is not None:
        data["beam_major_arcsec"] = fmt_field(round(beam_major, 4))
        data["beam_minor_arcsec"] = fmt_field(round(beam_minor, 4))
        data["beam_pa_deg"] = fmt_field(round(beam_pa, 2))
    else:
        data["beam_major_arcsec"] = fmt_field(
            None, flag="UNAVAILABLE", note="beam not found in image header"
        )
        data["beam_minor_arcsec"] = fmt_field(None, flag="UNAVAILABLE")
        data["beam_pa_deg"] = fmt_field(None, flag="UNAVAILABLE")

    if psf_path is not None and psf_beam_major is not None:
        data["psf_beam_major_arcsec"] = fmt_field(round(psf_beam_major, 4))
        data["psf_beam_minor_arcsec"] = fmt_field(round(psf_beam_minor, 4))
        data["psf_beam_pa_deg"] = fmt_field(round(psf_beam_pa, 2))

    # Per-plane breakdown (cube / multi-Stokes). The scalar fields above are
    # whole-image summaries; `planes` carries per-(Stokes, channel) values.
    if planes is not None:
        data["n_planes"] = fmt_field(len(planes))
        data["planes"] = fmt_field(planes)

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=image_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
