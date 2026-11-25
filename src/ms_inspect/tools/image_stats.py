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

import contextlib
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


def _min_beam_minor_arcsec(beam_info: dict) -> float | None:
    """Return the minimum restoring-beam minor axis (arcsec) across all planes."""
    if not isinstance(beam_info, dict):
        return None
    if "minor" in beam_info:
        try:
            val = _quantity_to_arcsec(beam_info["minor"])
            return val if math.isfinite(val) and val > 0.0 else None
        except (KeyError, TypeError, ValueError):
            return None

    beams = beam_info.get("beams")
    if not isinstance(beams, dict):
        return None

    minors: list[float] = []
    for chan_entry in beams.values():
        if not isinstance(chan_entry, dict):
            continue
        if "minor" in chan_entry:
            try:
                val = _quantity_to_arcsec(chan_entry["minor"])
                if math.isfinite(val) and val > 0.0:
                    minors.append(val)
            except (KeyError, TypeError, ValueError):
                pass
            continue
        for pol_entry in chan_entry.values():
            if not isinstance(pol_entry, dict) or "minor" not in pol_entry:
                continue
            try:
                val = _quantity_to_arcsec(pol_entry["minor"])
                if math.isfinite(val) and val > 0.0:
                    minors.append(val)
            except (KeyError, TypeError, ValueError):
                pass
    return min(minors) if minors else None


def _max_pixel_size_arcsec(ia, casa_calls: list[str]) -> float | None:
    """Return max(|cdelt_x_arcsec|, |cdelt_y_arcsec|) from ia.coordsys().increment()."""
    import numpy as np

    csys = None
    try:
        try:
            csys = ia.coordsys()
            inc = csys.increment()
        except Exception:
            return None

        # Quantity-format dict (if increment(format='q') or mock returns quantities)
        if isinstance(inc, dict) and isinstance(inc.get("quantity"), dict):
            qdict = inc["quantity"]
            q0 = qdict.get("*1")
            q1 = qdict.get("*2")
            if not (isinstance(q0, dict) and isinstance(q1, dict)):
                vals = [v for v in qdict.values() if isinstance(v, dict) and "value" in v]
                if len(vals) < 2:
                    return None
                q0, q1 = vals[0], vals[1]
            try:
                dx = abs(_quantity_to_arcsec(q0))
                dy = abs(_quantity_to_arcsec(q1))
            except (KeyError, TypeError, ValueError):
                return None
            if math.isfinite(dx) and math.isfinite(dy) and max(dx, dy) > 0.0:
                casa_calls.append("ia.coordsys().increment() [pixel_size]")
                return max(dx, dy)
            return None

        numeric = inc.get("numeric") if isinstance(inc, dict) else inc
        if not isinstance(numeric, (list, tuple, np.ndarray)) or len(numeric) < 2:
            return None

        units: list[str] = []
        try:
            raw_units = csys.units()
            if isinstance(raw_units, (list, tuple, np.ndarray)):
                units = [str(x).strip() for x in raw_units]
        except Exception:
            units = []

        u0 = units[0] if len(units) > 0 and units[0] else "rad"
        u1 = units[1] if len(units) > 1 and units[1] else "rad"
        try:
            dx = abs(_quantity_to_arcsec({"value": float(numeric[0]), "unit": u0}))
            dy = abs(_quantity_to_arcsec({"value": float(numeric[1]), "unit": u1}))
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return None
        cell_max = max(dx, dy)
        if cell_max <= 0.0:
            return None
        casa_calls.append("ia.coordsys().increment() [pixel_size]")
        return cell_max
    finally:
        if csys is not None and hasattr(csys, "done"):
            with contextlib.suppress(Exception):
                csys.done()


def _edge_pb_max(
    image_path: str,
    casa_calls: list[str],
    warnings: list[str],
) -> dict:
    """Max finite pixel value of sibling .pb / .pb.tt0 across the outer 2-pixel rim over all planes."""
    _, pb_path = _siblings(image_path)
    if not pb_path.exists():
        return fmt_field(None, flag="UNAVAILABLE", note=f"sibling {pb_path.name} not found")

    import numpy as np

    rim_slices: list[np.ndarray] | None = None
    try:
        with open_image(str(pb_path)) as ia_pb:
            shape: list[int] | None = None
            if hasattr(ia_pb, "shape"):
                try:
                    raw_shape = ia_pb.shape()
                    if isinstance(raw_shape, (list, tuple, np.ndarray)) and len(raw_shape) >= 2:
                        shape = [int(n) for n in raw_shape]
                except Exception:
                    shape = None

            # Prefer 4 outer 2-pixel border slab reads (blc/trc) to avoid loading multi-GB
            # full-pol cubes into RAM when only the 2px rim is needed.
            if shape is not None and shape[0] > 4 and shape[1] > 4 and all(n > 0 for n in shape):
                nx, ny = shape[0], shape[1]
                tail_blc = [0] * (len(shape) - 2)
                tail_trc = [n - 1 for n in shape[2:]]
                slab_boxes = (
                    ([0, 0, *tail_blc], [1, ny - 1, *tail_trc]),
                    ([nx - 2, 0, *tail_blc], [nx - 1, ny - 1, *tail_trc]),
                    ([2, 0, *tail_blc], [nx - 3, 1, *tail_trc]),
                    ([2, ny - 2, *tail_blc], [nx - 3, ny - 1, *tail_trc]),
                )
                slabs: list[np.ndarray] = []
                slab_ok = True
                fallback_full: np.ndarray | None = None
                for blc, trc in slab_boxes:
                    try:
                        slab = np.asarray(ia_pb.getchunk(blc=blc, trc=trc), dtype=float)
                    except TypeError:
                        slab_ok = False
                        break
                    expected_shape = tuple(t - b + 1 for b, t in zip(blc, trc, strict=True))
                    if slab.shape == expected_shape:
                        slabs.append(slab)
                    elif slab.shape == tuple(shape):
                        # Bare MagicMock ignored blc/trc and returned the full array.
                        fallback_full = slab
                        slab_ok = False
                        break
                    else:
                        slab_ok = False
                        break
                if slab_ok:
                    rim_slices = slabs
                elif fallback_full is not None:
                    rim_slices = [
                        fallback_full[:2, ...],
                        fallback_full[-2:, ...],
                        fallback_full[:, :2, ...],
                        fallback_full[:, -2:, ...],
                    ]

            if rim_slices is None:
                pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
                if pb_pix.ndim < 2 or pb_pix.shape[0] == 0 or pb_pix.shape[1] == 0:
                    return fmt_field(
                        None,
                        flag="UNAVAILABLE",
                        note=f"invalid spatial shape {pb_pix.shape} in {pb_path.name}",
                    )
                rim_slices = [
                    pb_pix[:2, ...],
                    pb_pix[-2:, ...],
                    pb_pix[:, :2, ...],
                    pb_pix[:, -2:, ...],
                ]
    except Exception as exc:
        warnings.append(f"Could not read sibling PB image ({pb_path.name}) for edge_pb_max: {exc}")
        return fmt_field(None, flag="UNAVAILABLE", note=f"read failed: {exc}")

    casa_calls.append(f"ia.getchunk() on {pb_path.name} [edge_pb_max 2px rim]")
    edge_max: float | None = None
    for sl in rim_slices:
        finite = sl[np.isfinite(sl)]
        if finite.size > 0:
            val = float(np.max(finite))
            edge_max = val if edge_max is None else max(edge_max, val)

    if edge_max is None:
        return fmt_field(
            None, flag="UNAVAILABLE", note=f"no finite border pixels in {pb_path.name}"
        )

    return fmt_field(
        round(edge_max, 6),
        note=f"max finite {pb_path.name} across outer 2-pixel border over all planes",
    )


def _siblings(image_path: str) -> tuple[Path, Path]:
    """(.residual, .pb) next to an .image or .image.pbcor (including .tt0 variants)."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for suffix, tt in (
        (".image.pbcor.tt0", ".tt0"),
        (".image.tt0.pbcor", ".tt0"),
        (".image.tt0", ".tt0"),
        (".image.pbcor", ""),
        (".image", ""),
    ):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            return p.parent / f"{base}.residual{tt}", p.parent / f"{base}.pb{tt}"
    return p.parent / f"{name}.residual", p.parent / f"{name}.pb"


def _sibling_flat_image(image_path: str) -> Path | None:
    """Flat-noise .image (or .image.tt0) sibling when image_path is a .pbcor image."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for pbcor_suf, flat_suf in (
        (".image.pbcor.tt0", ".image.tt0"),
        (".image.tt0.pbcor", ".image.tt0"),
        (".image.pbcor", ".image"),
    ):
        if name.endswith(pbcor_suf):
            cand = p.parent / f"{name[: -len(pbcor_suf)]}{flat_suf}"
            return cand if cand.exists() else None
    return None


def _sibling_mask(image_path: str) -> Path | None:
    """Sibling CASA .mask directory next to an .image / .image.pbcor (including mtmfs .tt0)."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for suffix, tt in (
        (".image.pbcor.tt0", ".tt0"),
        (".image.tt0.pbcor", ".tt0"),
        (".image.tt0", ".tt0"),
        (".image.pbcor", ""),
        (".image", ""),
    ):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            candidates = [p.parent / f"{base}.mask"]
            if tt:
                candidates.append(p.parent / f"{base}.mask{tt}")
            for cand in candidates:
                if cand.exists():
                    return cand
            return None
    cand = p.parent / f"{name}.mask"
    return cand if cand.exists() else None


def _sibling_model(image_path: str) -> Path | None:
    """Sibling CASA .model (or .model.tt0) directory next to an .image / .image.pbcor."""
    p = Path(image_path).expanduser().resolve()
    name = p.name
    for suffix, tt in (
        (".image.pbcor.tt0", ".tt0"),
        (".image.tt0.pbcor", ".tt0"),
        (".image.tt0", ".tt0"),
        (".image.pbcor", ""),
        (".image", ""),
    ):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            candidates = [p.parent / f"{base}.model{tt}"]
            if tt:
                candidates.append(p.parent / f"{base}.model")
            for cand in candidates:
                if cand.exists():
                    return cand
            return None
    cand = p.parent / f"{name}.model"
    return cand if cand.exists() else None


def _format_j2000(ra_deg: float, dec_deg: float) -> str:
    """Format (ra_deg, dec_deg) as a CASA J2000 direction string."""
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


def _pixel_to_sky_deg(ia_res, pixel_idx: tuple[int, ...]) -> tuple[float | None, float | None]:
    """Convert an N-D pixel index on ia_res to (ra_deg, dec_deg), or (None, None)."""
    try:
        csys = ia_res.coordsys()
        w = csys.toworld([float(i) for i in pixel_idx])
        numeric = w["numeric"] if isinstance(w, dict) and "numeric" in w else w
        if numeric is None or len(numeric) < 2:
            return None, None
        units: list[str] = []
        try:
            u = csys.units()
            units = [str(x).lower() for x in u] if u else []
        except Exception:
            units = []
        u0 = units[0] if len(units) > 0 else "rad"
        u1 = units[1] if len(units) > 1 else "rad"
        ra_deg = float(numeric[0]) * _DEG_PER_UNIT.get(u0, 180.0 / math.pi)
        dec_deg = float(numeric[1]) * _DEG_PER_UNIT.get(u1, 180.0 / math.pi)
        if not (math.isfinite(ra_deg) and math.isfinite(dec_deg)):
            return None, None
        return ra_deg % 360.0, dec_deg
    except Exception:
        return None, None


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


def _full_residual_peak_stats(
    image_path: str,
    pb_level: float,
    ref_rms_jy: float | None,
    casa_calls: list[str],
    warnings: list[str],
) -> dict:
    """Full-unmasked residual peak metrics across all PB > 0 (and outer annulus 0 < PB < pb_level).

    Reports sky coordinates (RA, Dec, J2000) of the outer-PB peak so an agent
    can cross-match it against ms_field_list (is it the phasecal?) or target it
    directly with phasecenter / outlierfile for baby peeling.
    """
    residual, pb = _siblings(image_path)
    keys = (
        "residual_full_peak_jy",
        "residual_full_peak_snr",
        "residual_full_peak_pb",
        "residual_outer_pb_peak_jy",
        "residual_outer_pb_peak_snr",
        "residual_outer_pb_peak_pb",
        "residual_outer_pb_peak_ra_deg",
        "residual_outer_pb_peak_dec_deg",
        "residual_outer_pb_peak_j2000",
    )

    def _unavail(reason: str) -> dict:
        return {k: fmt_field(None, flag="UNAVAILABLE", note=reason) for k in keys}

    missing = [str(x.name) for x in (residual, pb) if not x.exists()]
    if missing:
        return _unavail(f"sibling image not found: {', '.join(missing)}")

    import numpy as np

    outer_ra: float | None = None
    outer_dec: float | None = None
    outer_j2000: str | None = None
    try:
        with open_image(str(pb)) as ia_pb:
            pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
        with open_image(str(residual)) as ia_res:
            res_pix = np.asarray(ia_res.getchunk(), dtype=float)
            pb_bcast = _broadcast_pb(pb_pix, res_pix.shape)
            if pb_bcast is None:
                reason = f"shape mismatch: residual {res_pix.shape}, pb {pb_pix.shape}"
                warnings.append(f"Full-map residual peak stats skipped ({reason}).")
                return _unavail(reason)

            casa_calls.append(f"ia.getchunk() on {residual.name} where {pb.name} > 0 [full_map]")
            full_valid = (pb_bcast > 0.0) & np.isfinite(res_pix) & np.isfinite(pb_bcast)
            if not np.any(full_valid):
                return _unavail(f"no finite pixels with {pb.name} > 0")

            full_abs = np.abs(res_pix[full_valid])
            full_pbs = pb_bcast[full_valid]
            idx = int(np.argmax(full_abs))
            full_peak_jy = float(full_abs[idx])
            full_peak_pb = float(full_pbs[idx])
            full_peak_snr = (
                (full_peak_jy / ref_rms_jy) if (ref_rms_jy is not None and ref_rms_jy > 0) else None
            )

            outer_valid = full_valid & (pb_bcast < pb_level)
            if np.any(outer_valid):
                outer_scores = np.where(outer_valid, np.abs(res_pix), -1.0)
                outer_idx = tuple(
                    int(i) for i in np.unravel_index(int(np.argmax(outer_scores)), res_pix.shape)
                )
                outer_peak_jy: float | None = float(abs(res_pix[outer_idx]))
                outer_peak_pb: float | None = float(pb_bcast[outer_idx])
                outer_peak_snr: float | None = (
                    (outer_peak_jy / ref_rms_jy)
                    if (ref_rms_jy is not None and ref_rms_jy > 0)
                    else None
                )
                outer_ra, outer_dec = _pixel_to_sky_deg(ia_res, outer_idx)
                if outer_ra is not None and outer_dec is not None:
                    outer_j2000 = _format_j2000(outer_ra, outer_dec)
                outer_note = f"max(|{residual.name}|) in 0 < {pb.name} < {pb_level}"
            else:
                outer_peak_jy = None
                outer_peak_pb = None
                outer_peak_snr = None
                outer_note = f"no finite pixels in 0 < {pb.name} < {pb_level}"
    except Exception as exc:
        warnings.append(f"Could not read full-map residual images: {exc}")
        return _unavail(f"read failed: {exc}")

    coord_note = (
        f"sky coordinate at residual_outer_pb_peak_jy (0 < PB < {pb_level})"
        if outer_j2000 is not None
        else (outer_note if outer_peak_jy is None else "coordsys.toworld() unavailable")
    )

    return {
        "residual_full_peak_jy": fmt_field(
            round(full_peak_jy, 9),
            note=f"max(|{residual.name}|) across all {pb.name} > 0",
        ),
        "residual_full_peak_snr": fmt_field(
            round(full_peak_snr, 2) if full_peak_snr is not None else None,
            flag="COMPLETE" if full_peak_snr is not None else "UNAVAILABLE",
            note="residual_full_peak_jy / off-source residual RMS across all PB > 0"
            if full_peak_snr is not None
            else "off-source residual RMS unavailable or zero",
        ),
        "residual_full_peak_pb": fmt_field(
            round(full_peak_pb, 4),
            note=f"{pb.name} gain at residual_full_peak_jy pixel",
        ),
        "residual_outer_pb_peak_jy": fmt_field(
            round(outer_peak_jy, 9) if outer_peak_jy is not None else None,
            flag="COMPLETE" if outer_peak_jy is not None else "UNAVAILABLE",
            note=outer_note,
        ),
        "residual_outer_pb_peak_snr": fmt_field(
            round(outer_peak_snr, 2) if outer_peak_snr is not None else None,
            flag="COMPLETE" if outer_peak_snr is not None else "UNAVAILABLE",
            note=f"residual_outer_pb_peak_jy / off-source residual RMS (0 < PB < {pb_level})"
            if outer_peak_snr is not None
            else outer_note,
        ),
        "residual_outer_pb_peak_pb": fmt_field(
            round(outer_peak_pb, 4) if outer_peak_pb is not None else None,
            flag="COMPLETE" if outer_peak_pb is not None else "UNAVAILABLE",
            note=f"{pb.name} gain at residual_outer_pb_peak_jy pixel"
            if outer_peak_pb is not None
            else outer_note,
        ),
        "residual_outer_pb_peak_ra_deg": fmt_field(
            round(outer_ra, 6) if outer_ra is not None else None,
            flag="COMPLETE" if outer_ra is not None else "UNAVAILABLE",
            note=coord_note,
        ),
        "residual_outer_pb_peak_dec_deg": fmt_field(
            round(outer_dec, 6) if outer_dec is not None else None,
            flag="COMPLETE" if outer_dec is not None else "UNAVAILABLE",
            note=coord_note,
        ),
        "residual_outer_pb_peak_j2000": fmt_field(
            outer_j2000,
            flag="COMPLETE" if outer_j2000 is not None else "UNAVAILABLE",
            note=coord_note,
        ),
    }


def _model_positivity_stats(
    image_path: str,
    pb_level: float,
    has_signed_stokes: bool,
    casa_calls: list[str],
    warnings: list[str],
) -> dict:
    """Programmatic Stokes I positivity diagnostics on sibling .model / .model.tt0.

    Replaces visual inspection of .model for non-vision models: a physical
    Stokes I clean model is predominantly positive; growing negative flux or
    negative-dominated pixels signal overcleaning, bad scales, or divergence.
    """
    keys = (
        "model_nonzero_pixels",
        "model_neg_pixel_fraction",
        "model_sum_pos_jy",
        "model_sum_neg_jy",
        "model_neg_to_pos_flux_ratio",
        "model_max_jy",
        "model_min_jy",
        "model_neg_to_pos_peak_ratio",
        "model_outer_pb_flux_frac",
    )

    def _unavail(reason: str) -> dict:
        return {k: fmt_field(None, flag="UNAVAILABLE", note=reason) for k in keys}

    if has_signed_stokes:
        return _unavail("positivity metrics not defined for signed Stokes (Q/U/V/cross-hands)")

    model_path = _sibling_model(image_path)
    if model_path is None or not model_path.exists():
        return _unavail("sibling .model not found")

    import numpy as np

    try:
        with open_image(str(model_path)) as ia_mod:
            mod_pix = np.asarray(ia_mod.getchunk(), dtype=float)
    except Exception as exc:
        warnings.append(f"Could not read sibling model image ({model_path.name}): {exc}")
        return _unavail(f"read failed: {exc}")

    casa_calls.append(f"ia.getchunk() on {model_path.name} [model_positivity]")
    finite = np.isfinite(mod_pix)
    if not np.any(finite):
        return _unavail(f"no finite pixels in {model_path.name}")

    vals = mod_pix[finite]
    nz = vals[vals != 0.0]
    n_nz = int(nz.size)
    pos = nz[nz > 0.0]
    neg = nz[nz < 0.0]
    sum_pos = float(pos.sum()) if pos.size else 0.0
    sum_neg = float(neg.sum()) if neg.size else 0.0
    max_v = float(np.max(vals))
    min_v = float(np.min(vals))

    neg_px_frac = (int(neg.size) / n_nz) if n_nz > 0 else None
    neg_to_pos_flux = (abs(sum_neg) / sum_pos) if sum_pos > 0.0 else None
    neg_to_pos_peak = (abs(min(0.0, min_v)) / max_v) if max_v > 0.0 else None

    outer_flux_frac: float | None = None
    outer_note = "sibling .pb not found"
    _, pb_path = _siblings(image_path)
    if pb_path.exists():
        try:
            with open_image(str(pb_path)) as ia_pb:
                pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
            pb_bcast = _broadcast_pb(pb_pix, mod_pix.shape)
            total_abs = float(np.sum(np.abs(nz))) if n_nz > 0 else 0.0
            if pb_bcast is None:
                outer_note = f"shape mismatch: model {mod_pix.shape}, pb {pb_pix.shape}"
            elif total_abs <= 0.0:
                outer_note = "model is empty (zero flux)"
            else:
                outer_mask = finite & np.isfinite(pb_bcast) & (pb_bcast < pb_level)
                outer_abs = float(np.sum(np.abs(mod_pix[outer_mask])))
                outer_flux_frac = outer_abs / total_abs
                outer_note = f"sum(|{model_path.name}| where PB < {pb_level}) / sum(|model|)"
        except Exception as exc:
            outer_note = f"sibling .pb read failed: {exc}"

    return {
        "model_nonzero_pixels": fmt_field(
            n_nz,
            note=f"nonzero pixels in {model_path.name} ({int(pos.size)} pos, {int(neg.size)} neg)",
        ),
        "model_neg_pixel_fraction": fmt_field(
            round(neg_px_frac, 4) if neg_px_frac is not None else None,
            flag="COMPLETE" if neg_px_frac is not None else "UNAVAILABLE",
            note="negative nonzero pixels / total nonzero pixels"
            if neg_px_frac is not None
            else "model is empty",
        ),
        "model_sum_pos_jy": fmt_field(
            round(sum_pos, 9),
            note=f"sum of positive clean components in {model_path.name}",
        ),
        "model_sum_neg_jy": fmt_field(
            round(sum_neg, 9),
            note=f"sum of negative clean components in {model_path.name}",
        ),
        "model_neg_to_pos_flux_ratio": fmt_field(
            round(neg_to_pos_flux, 4) if neg_to_pos_flux is not None else None,
            flag="COMPLETE" if neg_to_pos_flux is not None else "UNAVAILABLE",
            note="abs(model_sum_neg_jy) / model_sum_pos_jy"
            if neg_to_pos_flux is not None
            else "model_sum_pos_jy <= 0",
        ),
        "model_max_jy": fmt_field(round(max_v, 9), note=f"max pixel in {model_path.name}"),
        "model_min_jy": fmt_field(round(min_v, 9), note=f"min pixel in {model_path.name}"),
        "model_neg_to_pos_peak_ratio": fmt_field(
            round(neg_to_pos_peak, 4) if neg_to_pos_peak is not None else None,
            flag="COMPLETE" if neg_to_pos_peak is not None else "UNAVAILABLE",
            note="abs(min(0, model_min_jy)) / model_max_jy"
            if neg_to_pos_peak is not None
            else "model_max_jy <= 0",
        ),
        "model_outer_pb_flux_frac": fmt_field(
            round(outer_flux_frac, 4) if outer_flux_frac is not None else None,
            flag="COMPLETE" if outer_flux_frac is not None else "UNAVAILABLE",
            note=outer_note,
        ),
    }


def _in_model_residual_stats(
    image_path: str,
    pb_level: float,
    ref_rms_jy: float | None,
    casa_calls: list[str],
    warnings: list[str],
) -> dict:
    """Residual RMS/peak/ratio on |model| > 0 inside PB >= pb_level.

    Always computed when sibling .residual, .pb, and .model exist so shallow
    unmasked (usemask='pb') passes -- where .mask is absent or covers 100% of
    PB >= pb_level and residual_out_mask_rms_jy is unavailable -- still expose
    uncleaned on-source residuals directly.
    """
    keys = (
        "residual_in_model_rms_jy",
        "residual_in_model_peak_jy",
        "residual_in_model_peak_snr",
        "residual_in_model_rms_ratio",
    )

    def _unavail(reason: str) -> dict:
        return {k: fmt_field(None, flag="UNAVAILABLE", note=reason) for k in keys}

    residual, pb = _siblings(image_path)
    model_path = _sibling_model(image_path)
    missing = [str(x.name) for x in (residual, pb) if not x.exists()]
    if model_path is None or not model_path.exists():
        missing.append(".model")
    if missing:
        return _unavail(f"sibling image not found: {', '.join(missing)}")

    import numpy as np

    try:
        with open_image(str(pb)) as ia_pb:
            pb_pix = np.asarray(ia_pb.getchunk(), dtype=float)
        with open_image(str(residual)) as ia_res:
            res_pix = np.asarray(ia_res.getchunk(), dtype=float)
        with open_image(str(model_path)) as ia_mod:
            mod_pix = np.asarray(ia_mod.getchunk(), dtype=float)
    except Exception as exc:
        warnings.append(f"Could not read in-model residual images: {exc}")
        return _unavail(f"read failed: {exc}")

    pb_bcast = _broadcast_pb(pb_pix, res_pix.shape)
    mod_bcast = _broadcast_pb(mod_pix, res_pix.shape)
    if pb_bcast is None or mod_bcast is None:
        reason = (
            f"shape mismatch: residual {res_pix.shape}, pb {pb_pix.shape}, model {mod_pix.shape}"
        )
        warnings.append(f"In-model residual stats skipped ({reason}).")
        return _unavail(reason)

    casa_calls.append(
        f"ia.getchunk() on {residual.name} over |{model_path.name}| > 0 where {pb.name} >= {pb_level}"
    )
    valid = (pb_bcast >= pb_level) & np.isfinite(res_pix) & np.isfinite(mod_bcast)
    in_mod = valid & (np.abs(mod_bcast) > 0.0)
    if not np.any(in_mod):
        return _unavail(f"no nonzero pixels in {model_path.name} inside {pb.name} >= {pb_level}")

    in_vals = res_pix[in_mod]
    in_rms = float(np.sqrt(np.mean(in_vals * in_vals)))
    in_peak = float(np.max(np.abs(in_vals)))

    # Off-source denominator: prefer outside-mask MAD RMS when available, else
    # MAD RMS of |model| == 0 pixels inside PB >= pb_level, else whole-PB ref_rms_jy.
    off_rms: float | None = None
    off_label = ""
    if ref_rms_jy is not None and ref_rms_jy > 0:
        off_rms = float(ref_rms_jy)
        off_label = "off-source residual RMS"
    off_mod = valid & (np.abs(mod_bcast) == 0.0)
    if off_rms is None and np.any(off_mod):
        off_vals = res_pix[off_mod]
        off_med = float(np.median(off_vals))
        cand = _MAD_TO_SIGMA * float(np.median(np.abs(off_vals - off_med)))
        if cand > 0:
            off_rms = cand
            off_label = f"1.4826 x MAD of {residual.name} where |{model_path.name}| == 0"

    ratio = (in_rms / off_rms) if (off_rms is not None and off_rms > 0) else None
    peak_snr = (in_peak / off_rms) if (off_rms is not None and off_rms > 0) else None
    in_note = (
        f"RMS (sqrt(mean(x^2))) of {residual.name} on |{model_path.name}| > 0 "
        f"where {pb.name} >= {pb_level} ({int(in_vals.size)} px)"
    )
    return {
        "residual_in_model_rms_jy": fmt_field(round(in_rms, 9), note=in_note),
        "residual_in_model_peak_jy": fmt_field(
            round(in_peak, 9),
            note=f"max(|{residual.name}|) on |{model_path.name}| > 0 inside {pb.name} >= {pb_level}",
        ),
        "residual_in_model_peak_snr": fmt_field(
            round(peak_snr, 2) if peak_snr is not None else None,
            flag="COMPLETE" if peak_snr is not None else "UNAVAILABLE",
            note=f"residual_in_model_peak_jy / {off_label}"
            if peak_snr is not None
            else "off-source residual RMS unavailable or zero",
        ),
        "residual_in_model_rms_ratio": fmt_field(
            round(ratio, 3) if ratio is not None else None,
            flag="COMPLETE" if ratio is not None else "UNAVAILABLE",
            note=f"residual_in_model_rms_jy / {off_label}"
            if ratio is not None
            else "off-source residual RMS unavailable or zero",
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
        min_beam_minor: float | None = None
        try:
            beam_info = ia.restoringbeam()
            casa_calls.append("ia.restoringbeam()")
            beam_major, beam_minor, beam_pa = _extract_beam(beam_info)
            min_beam_minor = _min_beam_minor_arcsec(beam_info)
        except Exception as exc:
            warnings.append(f"Could not read restoring beam from image: {exc}")
            beam_major = beam_minor = beam_pa = None

        max_cdelt_arcsec = _max_pixel_size_arcsec(ia, casa_calls)

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
    data["edge_pb_max"] = _edge_pb_max(image_path, casa_calls, warnings)
    mask_stats = _mask_partitioned_residual_stats(
        image_path, pb_level, mask_path, casa_calls, warnings
    )
    data.update(mask_stats)
    ref_rms_jy = (
        mask_stats["residual_out_mask_rms_jy"]["value"]
        if mask_stats["residual_out_mask_rms_jy"]["value"] is not None
        else res_rms
    )
    data.update(_full_residual_peak_stats(image_path, pb_level, ref_rms_jy, casa_calls, warnings))
    data.update(
        _model_positivity_stats(image_path, pb_level, has_signed_stokes, casa_calls, warnings)
    )
    in_model_stats = _in_model_residual_stats(
        image_path,
        pb_level,
        mask_stats["residual_out_mask_rms_jy"]["value"],
        casa_calls,
        warnings,
    )
    data.update(in_model_stats)
    # When .mask is absent or covers 100% of PB >= pb_level (e.g. usemask='pb'),
    # expose the |model| > 0 ratio via residual_in_to_out_rms_ratio as well so
    # shallow pb-mask passes never hide uncleaned source residuals behind null.
    if (
        data["residual_in_to_out_rms_ratio"]["value"] is None
        and in_model_stats["residual_in_model_rms_ratio"]["value"] is not None
    ):
        data["residual_in_to_out_rms_ratio"] = fmt_field(
            in_model_stats["residual_in_model_rms_ratio"]["value"],
            note=(
                "fallback to residual_in_model_rms_ratio (|model| > 0 vs |model| == 0 "
                f"inside PB >= {pb_level}; no outside-mask pixels available)"
            ),
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

    if min_beam_minor is not None and max_cdelt_arcsec is not None and max_cdelt_arcsec > 0.0:
        data["pixels_per_beam_minor"] = fmt_field(
            round(min_beam_minor / max_cdelt_arcsec, 3),
            note=(
                f'min(beam_minor_arcsec) across all planes ({round(min_beam_minor, 4)}") '
                f'/ max(|cdelt_x|, |cdelt_y|) ({round(max_cdelt_arcsec, 4)}")'
            ),
        )
    else:
        ppb_reason = (
            "restoring beam minor axis unavailable"
            if min_beam_minor is None
            else "spatial pixel increment unavailable from coordsys().increment()"
        )
        data["pixels_per_beam_minor"] = fmt_field(None, flag="UNAVAILABLE", note=ppb_reason)

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
