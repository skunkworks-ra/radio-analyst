"""
make_mask.py -- ms_make_mask

Generate a native CASA `.mask` image from a flat-noise CASA `.image` using
PyBDSF island detection (`bdsf.process_image(..., stop_at='isl')`).

Why a native CASA `.mask` (and not a bare FITS file):
- Bridges CASA -> temporary FITS (blanking PB < pb_level to NaN so unblanked
  `pblimit < 0` corners never bias RMS or trigger `bstat` divide-by-zero) ->
  PyBDSF `island_mask` -> native 4D CASA `.mask` cloned directly from
  `image_path`'s exact `coordsys` and shape (`0.0`/`1.0`, `unit=''`).
- Supports iterative mask refinement via `prior_mask`: pixelwise logical OR of
  the new PyBDSF islands with the prior CASA `.mask`, clipped to `PB >= pb_level`.
- Designed for `ms_tclean(usemask='user', mask=<mask_path>)` without CASA's
  slow `auto-multithresh`.

Measures only: returns mask path, island count, RMS, pixel counts, and mask
fraction -- never pass/fail verdicts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.casa_context import open_image
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.logs import write_script
from ms_inspect.util.stage_log import record_stage

TOOL_NAME = "ms_make_mask"


def infer_pb_path(image_path: Path) -> Path | None:
    """Infer companion `.pb` image path from a CASA `.image` (or `.image.tt0`) path."""
    name = image_path.name
    parent = image_path.parent
    candidates: list[Path] = []
    if name.endswith(".image.tt0"):
        stem = name[: -len(".image.tt0")]
        candidates.extend([parent / f"{stem}.pb.tt0", parent / f"{stem}.pb"])
    elif name.endswith(".image.tt0.pbcor"):
        stem = name[: -len(".image.tt0.pbcor")]
        candidates.extend([parent / f"{stem}.pb.tt0", parent / f"{stem}.pb"])
    elif name.endswith(".image.pbcor.tt0"):
        stem = name[: -len(".image.pbcor.tt0")]
        candidates.extend([parent / f"{stem}.pb.tt0", parent / f"{stem}.pb"])
    elif name.endswith(".image.pbcor"):
        stem = name[: -len(".image.pbcor")]
        candidates.append(parent / f"{stem}.pb")
    elif name.endswith(".image"):
        stem = name[: -len(".image")]
        candidates.append(parent / f"{stem}.pb")
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def fits_mask_to_casa(mask_fits: np.ndarray, expected_shape: tuple[int, ...]) -> np.ndarray:
    """Convert a PyBDSF FITS island mask array to CASA `(ra, dec, stokes, freq)` float64."""
    arr = np.asarray(mask_fits)
    if arr.ndim == 4:
        out = np.transpose(arr, (3, 2, 1, 0))
    elif arr.ndim == 3:
        out = np.transpose(arr, (2, 1, 0))[:, :, :, None]
    elif arr.ndim == 2:
        out = arr.T[:, :, None, None]
    else:
        raise ComputationError(
            f"Unexpected FITS mask dimensionality {arr.ndim} (shape {arr.shape}).",
            ms_path="",
        )
    if out.shape != expected_shape:
        # Broadcast singleton trailing axes if needed (e.g. 2D mask onto 4D image)
        if out.shape[:2] == expected_shape[:2] and len(expected_shape) == 4:
            out = np.broadcast_to(out, expected_shape).copy()
        else:
            raise ComputationError(
                f"Mask shape {out.shape} does not match image shape {expected_shape}.",
                ms_path="",
            )
    return (np.nan_to_num(out, nan=0.0) > 0.5).astype(np.float64)


def combine_masks(
    new_mask: np.ndarray,
    pb_arr: np.ndarray | None,
    pb_level: float,
    prior_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, int, int]:
    """
    Combine new PyBDSF mask with optional prior_mask (logical OR) and clip to PB >= pb_level.

    Returns `(combined_mask_float64, n_mask_px, n_pb_px)`.
    """
    m = np.nan_to_num(np.asarray(new_mask, dtype=np.float64), nan=0.0) > 0.5
    if prior_mask is not None:
        pm = np.nan_to_num(np.asarray(prior_mask, dtype=np.float64), nan=0.0) > 0.5
        if pm.shape != m.shape:
            raise ComputationError(
                f"prior_mask shape {pm.shape} does not match image shape {m.shape}.",
                ms_path="",
            )
        m = m | pm
    if pb_arr is not None:
        pb_valid = np.isfinite(pb_arr) & (pb_arr >= pb_level)
        if pb_valid.shape != m.shape:
            raise ComputationError(
                f"pb image shape {pb_valid.shape} does not match image shape {m.shape}.",
                ms_path="",
            )
        m = m & pb_valid
        n_pb_px = int(pb_valid.sum())
    else:
        n_pb_px = int(m.size)
    out = m.astype(np.float64)
    return out, int(m.sum()), n_pb_px


def _script_path(workdir: Path, mask_path: str) -> Path:
    stem = Path(mask_path).name.replace(".", "_")
    return workdir / f"make_mask_{stem}.py"


def _build_script(
    *,
    workdir: str,
    image_str: str,
    mask_str: str,
    pb_str: str | None,
    pb_level: float,
    prior_mask_str: str | None,
    thresh_isl: float,
    thresh_pix: float,
    atrous_do: bool,
    adaptive_rms_box: bool,
    png_str: str | None,
) -> str:
    from ms_inspect.util.stage_log import RECORD_STAGE_SNIPPET as record

    stem = Path(mask_str).name.replace(".", "_")
    return f"""\
#!/usr/bin/env python
\"\"\"
Auto-generated by ms_make_mask (ms_modify).
Run with: python make_mask_{stem}.py
\"\"\"
import os
import shutil
import tempfile
from pathlib import Path

import bdsf
import numpy as np
from astropy.io import fits
from casatasks import exportfits
from casatools import image

{record}

workdir = {workdir!r}
image_path = {image_str!r}
mask_path = {mask_str!r}
pb_path = {pb_str!r}
pb_level = {pb_level}
prior_mask_path = {prior_mask_str!r}
thresh_isl = {thresh_isl}
thresh_pix = {thresh_pix}
atrous_do = {atrous_do!r}
adaptive_rms_box = {adaptive_rms_box!r}
png_path = {png_str!r}

tmp_dir = Path(tempfile.mkdtemp(prefix="ra_pybdsf_", dir=workdir))
try:
    tmp_fits = tmp_dir / "input.fits"
    tmp_mask_fits = tmp_dir / "island_mask.fits"
    exportfits(imagename=image_path, fitsimage=str(tmp_fits), dropdeg=False, overwrite=True)

    ia = image()
    ia.open(image_path)
    try:
        img_arr = np.asarray(ia.getchunk(), dtype=np.float64)
        img_shape = tuple(ia.shape())
    finally:
        ia.close()

    pb_arr = None
    if pb_path:
        ia.open(pb_path)
        try:
            pb_arr = np.asarray(ia.getchunk(), dtype=np.float64)
        finally:
            ia.close()
        pb_valid_fits = np.transpose(np.isfinite(pb_arr) & (pb_arr >= pb_level), (3, 2, 1, 0))
        with fits.open(tmp_fits, mode="update") as hdul:
            data = np.asarray(hdul[0].data, dtype=np.float32)
            hdul[0].data = np.where(pb_valid_fits, data, np.nan)
            hdul.flush()

    bimg = bdsf.process_image(
        str(tmp_fits),
        thresh_isl=thresh_isl,
        thresh_pix=thresh_pix,
        atrous_do=atrous_do,
        adaptive_rms_box=adaptive_rms_box,
        stop_at="isl",
        quiet=True,
    )
    bimg.export_image(
        outfile=str(tmp_mask_fits),
        img_type="island_mask",
        img_format="fits",
        clobber=True,
    )
    with fits.open(tmp_mask_fits) as hdul:
        mf = np.asarray(hdul[0].data)
    if mf.ndim == 4:
        mask_casa = np.transpose(mf, (3, 2, 1, 0))
    elif mf.ndim == 2:
        mask_casa = mf.T[:, :, None, None]
    else:
        raise RuntimeError(f"Unexpected FITS mask shape: {{mf.shape}}")
    mask_bool = np.nan_to_num(mask_casa, nan=0.0) > 0.5

    prior_px = None
    if prior_mask_path:
        ia.open(prior_mask_path)
        try:
            prior_arr = np.asarray(ia.getchunk(), dtype=np.float64)
        finally:
            ia.close()
        prior_bool = np.nan_to_num(prior_arr, nan=0.0) > 0.5
        if pb_arr is not None:
            prior_px = int((prior_bool & np.isfinite(pb_arr) & (pb_arr >= pb_level)).sum())
        else:
            prior_px = int(prior_bool.sum())
        mask_bool = mask_bool | prior_bool

    if pb_arr is not None:
        pb_valid = np.isfinite(pb_arr) & (pb_arr >= pb_level)
        mask_bool = mask_bool & pb_valid
        n_pb_px = int(pb_valid.sum())
    else:
        n_pb_px = int(mask_bool.size)

    mask_out = mask_bool.astype(np.float64)
    if os.path.exists(mask_path):
        shutil.rmtree(mask_path)
    ia_out = image()
    ia_out.fromimage(outfile=mask_path, infile=image_path, overwrite=True)
    try:
        ia_out.putchunk(mask_out)
        ia_out.setbrightnessunit("")
    finally:
        ia_out.close()

    n_mask_px = int(mask_bool.sum())
    mask_frac = round(n_mask_px / max(1, n_pb_px), 6)
    new_mask_px = n_mask_px - prior_px if prior_px is not None else n_mask_px
    mask_growth_frac = (
        round(new_mask_px / prior_px, 6) if (prior_px is not None and prior_px > 0) else None
    )

    if png_path:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        img2d = img_arr[:, :, 0, 0]
        m2d = mask_out[:, :, 0, 0]
        ref = img2d[(pb_arr[:, :, 0, 0] >= pb_level)] if pb_arr is not None else img2d[np.isfinite(img2d)]
        vlo, vhi = (np.nanpercentile(ref, [1, 99.8]) if ref.size else (0.0, 1.0))
        fig, ax = plt.subplots(figsize=(6, 6), dpi=130)
        ax.imshow(img2d.T, origin="lower", cmap="inferno", vmin=vlo, vmax=vhi)
        if pb_arr is not None:
            ax.contour(pb_arr[:, :, 0, 0].T, levels=[pb_level], colors="white", linewidths=1.0, linestyles="--")
        if n_mask_px > 0:
            ax.contour(m2d.T, levels=[0.5], colors="cyan", linewidths=1.1)
        ax.set_title(f"{{Path(mask_path).name}} ({{bimg.nisl}} isl, {{n_mask_px}} px, {{100*mask_frac:.1f}}% PB)")
        fig.tight_layout()
        fig.savefig(png_path)
        plt.close(fig)

    _record_stage(
        workdir,
        "make_mask",
        mask_path,
        {{
            "n_islands": int(bimg.nisl),
            "clipped_rms_jy": float(bimg.clipped_rms),
            "mask_pixels": n_mask_px,
            "pb_pixels": n_pb_px,
            "mask_fraction_in_pb": mask_frac,
            "prior_mask_pixels": prior_px,
            "new_mask_pixels": new_mask_px,
            "mask_growth_fraction": mask_growth_frac,
        }},
    )
    print(f"make_mask OK: {{mask_path}} ({{bimg.nisl}} islands, {{n_mask_px}} px, {{100*mask_frac:.2f}}% of PB)")
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)
"""


def _execute_make_mask(
    *,
    workdir_path: Path,
    image_str: str,
    mask_str: str,
    pb_str: str | None,
    pb_level: float,
    prior_mask_str: str | None,
    thresh_isl: float,
    thresh_pix: float,
    atrous_do: bool,
    adaptive_rms_box: bool,
    png_str: str | None,
) -> dict:
    import tempfile

    try:
        import bdsf
    except ImportError:
        raise ComputationError(
            "PyBDSF (`bdsf`) is not installed in this environment.",
            ms_path=image_str,
        ) from None
    try:
        from astropy.io import fits
        from casatasks import exportfits
        from casatools import image as casa_image
    except ImportError as exc:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(f"Required imaging dependency unavailable: {exc}") from None

    tmp_dir = Path(tempfile.mkdtemp(prefix="ra_pybdsf_", dir=str(workdir_path)))
    try:
        tmp_fits = tmp_dir / "input.fits"
        tmp_mask_fits = tmp_dir / "island_mask.fits"
        exportfits(imagename=image_str, fitsimage=str(tmp_fits), dropdeg=False, overwrite=True)

        with open_image(image_str) as ia:
            img_arr = np.asarray(ia.getchunk(), dtype=np.float64)
            img_shape = tuple(int(x) for x in ia.shape())

        pb_arr: np.ndarray | None = None
        if pb_str is not None:
            with open_image(pb_str) as ia:
                pb_arr = np.asarray(ia.getchunk(), dtype=np.float64)
            pb_valid_fits = np.transpose(np.isfinite(pb_arr) & (pb_arr >= pb_level), (3, 2, 1, 0))
            with fits.open(tmp_fits, mode="update") as hdul:
                data = np.asarray(hdul[0].data, dtype=np.float32)
                hdul[0].data = np.where(pb_valid_fits, data, np.nan)
                hdul.flush()

        bimg = bdsf.process_image(
            str(tmp_fits),
            thresh_isl=thresh_isl,
            thresh_pix=thresh_pix,
            atrous_do=atrous_do,
            adaptive_rms_box=adaptive_rms_box,
            stop_at="isl",
            quiet=True,
        )
        bimg.export_image(
            outfile=str(tmp_mask_fits),
            img_type="island_mask",
            img_format="fits",
            clobber=True,
        )
        with fits.open(tmp_mask_fits) as hdul:
            mf = np.asarray(hdul[0].data)
        new_mask = fits_mask_to_casa(mf, img_shape)

        prior_arr: np.ndarray | None = None
        prior_px: int | None = None
        if prior_mask_str is not None:
            with open_image(prior_mask_str) as ia:
                prior_arr = np.asarray(ia.getchunk(), dtype=np.float64)
            prior_bool = np.nan_to_num(prior_arr, nan=0.0) > 0.5
            if pb_arr is not None:
                prior_px = int((prior_bool & np.isfinite(pb_arr) & (pb_arr >= pb_level)).sum())
            else:
                prior_px = int(prior_bool.sum())

        combined, n_mask_px, n_pb_px = combine_masks(
            new_mask, pb_arr, pb_level, prior_mask=prior_arr
        )
        new_mask_px = n_mask_px - prior_px if prior_px is not None else n_mask_px
        mask_growth_frac = (
            round(new_mask_px / prior_px, 6) if (prior_px is not None and prior_px > 0) else None
        )

        mask_p = Path(mask_str)
        if mask_p.exists():
            shutil.rmtree(mask_p)
        ia_out = casa_image()
        ia_out.fromimage(outfile=mask_str, infile=image_str, overwrite=True)
        try:
            ia_out.putchunk(combined)
            ia_out.setbrightnessunit("")
        finally:
            ia_out.close()

        mask_frac = round(n_mask_px / max(1, n_pb_px), 6)

        if png_str is not None:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            img2d = img_arr[:, :, 0, 0]
            m2d = combined[:, :, 0, 0]
            ref = (
                img2d[pb_arr[:, :, 0, 0] >= pb_level]
                if pb_arr is not None
                else img2d[np.isfinite(img2d)]
            )
            vlo, vhi = (
                (float(x) for x in np.nanpercentile(ref, [1, 99.8])) if ref.size else (0.0, 1.0)
            )
            fig, ax = plt.subplots(figsize=(6, 6), dpi=130)
            ax.imshow(img2d.T, origin="lower", cmap="inferno", vmin=vlo, vmax=vhi)
            if pb_arr is not None:
                ax.contour(
                    pb_arr[:, :, 0, 0].T,
                    levels=[pb_level],
                    colors="white",
                    linewidths=1.0,
                    linestyles="--",
                )
            if n_mask_px > 0:
                ax.contour(m2d.T, levels=[0.5], colors="cyan", linewidths=1.1)
            ax.set_title(
                f"{mask_p.name} ({bimg.nisl} isl, {n_mask_px} px, {100 * mask_frac:.1f}% PB)"
            )
            fig.tight_layout()
            fig.savefig(png_str)
            plt.close(fig)

        return {
            "n_islands": int(bimg.nisl),
            "clipped_rms_jy": round(float(bimg.clipped_rms), 8),
            "mask_pixels": n_mask_px,
            "pb_pixels": n_pb_px,
            "mask_fraction_in_pb": mask_frac,
            "prior_mask_pixels": prior_px,
            "new_mask_pixels": new_mask_px,
            "mask_growth_fraction": mask_growth_frac,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run(
    image_path: str,
    mask_path: str,
    workdir: str,
    pb_path: str | None = None,
    pb_level: float = 0.1,
    prior_mask: str | None = None,
    thresh_isl: float = 3.0,
    thresh_pix: float = 5.0,
    atrous_do: bool = False,
    adaptive_rms_box: bool = False,
    png_path: str | None = None,
    execute: bool = False,
) -> dict:
    """
    Generate (or execute) a PyBDSF native CASA `.mask` image from a flat-noise `.image`.

    Args:
        image_path:       Path to flat-noise CASA `.image` (or `.image.tt0`).
        mask_path:        Output path for native CASA `.mask` image inside `workdir`.
        workdir:          Existing working directory.
        pb_path:          Optional companion `.pb` image (auto-inferred if None).
        pb_level:         PB cutoff (default 0.1); pixels with PB < pb_level are blanked.
        prior_mask:       Optional previous CASA `.mask` to OR with new islands.
        thresh_isl:       PyBDSF island boundary threshold in sigma (default 3.0).
        thresh_pix:       PyBDSF peak threshold in sigma (default 5.0).
        atrous_do:        PyBDSF wavelet decomposition for diffuse emission (default False).
        adaptive_rms_box: PyBDSF adaptive local RMS box (default False).
        png_path:         Optional diagnostic overlay PNG path inside `workdir`.
        execute:          False (default) writes script; True builds the `.mask` in-process.
    """
    warnings: list[str] = []
    casa_calls: list[str] = []

    if thresh_isl <= 0 or thresh_pix <= 0:
        raise ComputationError(
            f"thresh_isl ({thresh_isl}) and thresh_pix ({thresh_pix}) must be > 0.",
            ms_path=image_path,
        )
    if thresh_pix < thresh_isl:
        raise ComputationError(
            f"thresh_pix ({thresh_pix}) must be >= thresh_isl ({thresh_isl}).",
            ms_path=image_path,
        )
    if pb_level < 0 or pb_level >= 1.0:
        raise ComputationError(
            f"pb_level must be in [0, 1), got {pb_level}.",
            ms_path=image_path,
        )

    img_p = Path(image_path).expanduser().resolve()
    if not img_p.exists():
        raise ComputationError(f"image_path does not exist: {image_path}", ms_path=image_path)
    if img_p.name.endswith(".pbcor"):
        warnings.append(
            "image_path appears to be a .pbcor image; pass the flat-noise .image instead so "
            "PB edge noise amplification does not bias PyBDSF RMS estimation."
        )

    workdir_path = Path(workdir).expanduser().resolve()
    if not workdir_path.is_dir():
        raise ComputationError(f"workdir does not exist: {workdir}", ms_path=image_path)

    from ms_modify.pathguard import validate_output_caltable

    resolved_mask = str(validate_output_caltable(mask_path, str(workdir_path), str(img_p)))

    resolved_pb: str | None = None
    if pb_path:
        pb_p = Path(pb_path).expanduser().resolve()
        if not pb_p.exists():
            raise ComputationError(f"pb_path does not exist: {pb_path}", ms_path=image_path)
        resolved_pb = str(pb_p)
    else:
        inferred = infer_pb_path(img_p)
        if inferred is not None:
            resolved_pb = str(inferred)
        else:
            warnings.append(
                "No companion .pb image found; PyBDSF will run without primary-beam blanking."
            )

    resolved_prior: str | None = None
    if prior_mask:
        pm_p = Path(prior_mask).expanduser().resolve()
        if not pm_p.exists():
            raise ComputationError(f"prior_mask does not exist: {prior_mask}", ms_path=image_path)
        resolved_prior = str(pm_p)

    resolved_png: str | None = None
    if png_path:
        resolved_png = str(validate_output_caltable(png_path, str(workdir_path), str(img_p)))

    script_file = _script_path(workdir_path, resolved_mask)
    script_content = _build_script(
        workdir=str(workdir_path),
        image_str=str(img_p),
        mask_str=resolved_mask,
        pb_str=resolved_pb,
        pb_level=pb_level,
        prior_mask_str=resolved_prior,
        thresh_isl=thresh_isl,
        thresh_pix=thresh_pix,
        atrous_do=atrous_do,
        adaptive_rms_box=adaptive_rms_box,
        png_str=resolved_png,
    )
    write_script(script_file, script_content)
    casa_calls.append(f"write_script -> {script_file}")

    if not execute:
        data = {
            "script_path": fmt_field(str(script_file)),
            "mask_path": fmt_field(resolved_mask),
            "pb_path": fmt_field(resolved_pb, flag="COMPLETE" if resolved_pb else "UNAVAILABLE"),
            "prior_mask": fmt_field(resolved_prior),
            "completed": fmt_field(False, note="script not yet executed"),
        }
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=image_path,
            data=data,
            warnings=warnings,
            casa_calls=casa_calls,
        )

    stats = _execute_make_mask(
        workdir_path=workdir_path,
        image_str=str(img_p),
        mask_str=resolved_mask,
        pb_str=resolved_pb,
        pb_level=pb_level,
        prior_mask_str=resolved_prior,
        thresh_isl=thresh_isl,
        thresh_pix=thresh_pix,
        atrous_do=atrous_do,
        adaptive_rms_box=adaptive_rms_box,
        png_str=resolved_png,
    )
    casa_calls.append(
        f"exportfits -> bdsf.process_image(stop_at='isl', thresh_isl={thresh_isl}, "
        f"thresh_pix={thresh_pix}) -> casatools.image.fromimage({resolved_mask})"
    )
    record_stage(
        str(workdir_path),
        "make_mask",
        resolved_mask,
        {
            "n_islands": stats["n_islands"],
            "clipped_rms_jy": stats["clipped_rms_jy"],
            "mask_pixels": stats["mask_pixels"],
            "pb_pixels": stats["pb_pixels"],
            "mask_fraction_in_pb": stats["mask_fraction_in_pb"],
            "prior_mask_pixels": stats["prior_mask_pixels"],
            "new_mask_pixels": stats["new_mask_pixels"],
            "mask_growth_fraction": stats["mask_growth_fraction"],
        },
    )
    if stats["mask_pixels"] == 0:
        warnings.append(
            "PyBDSF produced an empty mask (0 pixels above threshold); passing an empty "
            "mask to tclean will trigger stopcode=7 (zero mask)."
        )

    growth_val = stats["mask_growth_fraction"]
    growth_note = (
        "(mask_pixels - prior_mask_pixels) / prior_mask_pixels"
        if growth_val is not None
        else ("prior_mask had 0 pixels" if stats["prior_mask_pixels"] == 0 else "no prior_mask")
    )

    data = {
        "script_path": fmt_field(str(script_file)),
        "mask_path": fmt_field(resolved_mask),
        "pb_path": fmt_field(resolved_pb, flag="COMPLETE" if resolved_pb else "UNAVAILABLE"),
        "prior_mask": fmt_field(resolved_prior),
        "png_path": fmt_field(resolved_png) if resolved_png else fmt_field(None),
        "completed": fmt_field(True),
        "thresh_isl": thresh_isl,
        "thresh_pix": thresh_pix,
        "pb_level": pb_level,
        "n_islands": fmt_field(stats["n_islands"]),
        "clipped_rms_jy": fmt_field(stats["clipped_rms_jy"]),
        "mask_pixels": fmt_field(stats["mask_pixels"]),
        "pb_pixels": fmt_field(stats["pb_pixels"]),
        "mask_fraction_in_pb": fmt_field(stats["mask_fraction_in_pb"]),
        "prior_mask_pixels": fmt_field(stats["prior_mask_pixels"]),
        "new_mask_pixels": fmt_field(stats["new_mask_pixels"]),
        "mask_growth_fraction": fmt_field(
            growth_val,
            flag="COMPLETE" if growth_val is not None else "UNAVAILABLE",
            note=growth_note,
        ),
    }
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=image_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
