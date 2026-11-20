"""Unit tests for ms_make_mask (src/ms_modify/make_mask.py)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ms_inspect.exceptions import ComputationError
from ms_modify.make_mask import (
    combine_masks,
    fits_mask_to_casa,
    infer_pb_path,
    run,
)


class TestPureHelpers:
    def test_fits_mask_to_casa_4d_and_2d(self):
        # FITS shape (freq=1, stokes=1, dec=3, ra=4) -> CASA (ra=4, dec=3, stokes=1, freq=1)
        f4 = np.zeros((1, 1, 3, 4), dtype=np.float32)
        f4[0, 0, 2, 1] = 1.0
        c4 = fits_mask_to_casa(f4, (4, 3, 1, 1))
        assert c4.shape == (4, 3, 1, 1)
        assert c4.dtype == np.float64
        assert c4[1, 2, 0, 0] == 1.0
        assert c4.sum() == 1.0

        f2 = np.zeros((3, 4), dtype=np.float32)
        f2[2, 1] = 1.0
        c2 = fits_mask_to_casa(f2, (4, 3, 1, 1))
        assert np.array_equal(c2, c4)

    def test_combine_masks_unions_prior_and_clips_pb(self):
        new_m = np.zeros((4, 4, 1, 1), dtype=np.float64)
        new_m[1, 1, 0, 0] = 1.0
        new_m[0, 0, 0, 0] = 1.0  # outside PB

        prior_m = np.zeros((4, 4, 1, 1), dtype=np.float64)
        prior_m[2, 2, 0, 0] = 1.0  # inside PB, preserved via union

        pb = np.full((4, 4, 1, 1), 0.5, dtype=np.float64)
        pb[0, 0, 0, 0] = 0.05  # below pb_level=0.1

        out, n_mask, n_pb = combine_masks(new_m, pb, pb_level=0.1, prior_mask=prior_m)
        assert n_pb == 15
        assert n_mask == 2
        assert out[1, 1, 0, 0] == 1.0
        assert out[2, 2, 0, 0] == 1.0
        assert out[0, 0, 0, 0] == 0.0

    def test_infer_pb_path_handles_image_and_tt0(self, tmp_path):
        img = tmp_path / "src.image"
        pb = tmp_path / "src.pb"
        img.mkdir()
        pb.mkdir()
        assert infer_pb_path(img) == pb

        img_tt0 = tmp_path / "wb.image.tt0"
        pb_tt0 = tmp_path / "wb.pb.tt0"
        img_tt0.mkdir()
        pb_tt0.mkdir()
        assert infer_pb_path(img_tt0) == pb_tt0


class TestRunScriptGeneration:
    def test_writes_script_and_infers_pb(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        img = wd / "target_hogbom.image"
        pb = wd / "target_hogbom.pb"
        prior = wd / "target_r0.mask"
        img.mkdir()
        pb.mkdir()
        prior.mkdir()

        res = run(
            str(img),
            str(wd / "target_r1.mask"),
            str(wd),
            prior_mask=str(prior),
            pb_level=0.15,
            thresh_isl=3.0,
            thresh_pix=5.0,
            png_path=str(wd / "target_r1.png"),
            execute=False,
        )
        assert res["status"] == "ok"
        data = res["data"]
        assert data["completed"]["value"] is False
        assert data["pb_path"]["value"] == str(pb.resolve())
        script = Path(data["script_path"]["value"]).read_text()
        assert 'stop_at="isl"' in script
        assert "pb_level = 0.15" in script
        assert f"prior_mask_path = {str(prior.resolve())!r}" in script
        assert "_record_stage(" in script
        # Script must be valid Python
        compile(script, data["script_path"]["value"], "exec")

    def test_pbcor_input_emits_warning(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        img = wd / "target.image.pbcor"
        img.mkdir()
        res = run(str(img), str(wd / "out.mask"), str(wd), execute=False)
        assert any(".pbcor" in w for w in res["warnings"])

    def test_rejects_bad_thresholds_and_outside_workdir(self, tmp_path):
        wd = tmp_path / "work"
        wd.mkdir()
        img = wd / "target.image"
        img.mkdir()
        with pytest.raises(ComputationError, match="thresh_pix"):
            run(str(img), str(wd / "out.mask"), str(wd), thresh_isl=5.0, thresh_pix=3.0)
        with pytest.raises(ComputationError, match="pb_level"):
            run(str(img), str(wd / "out.mask"), str(wd), pb_level=1.0)
        with pytest.raises(ComputationError):
            run(str(img), str(tmp_path / "outside.mask"), str(wd))


def test_tclean_cleanup_preserves_input_user_mask(tmp_path, real_ms_calibrated):
    from ms_modify.tclean import run as tclean_run

    wd = tmp_path / "work"
    wd.mkdir()
    mask_path = str(wd / "img.mask")
    res = tclean_run(
        real_ms_calibrated,
        str(wd / "img"),
        field="0",
        workdir=str(wd),
        usemask="user",
        mask=mask_path,
        pblimit=0.1,
        execute=False,
    )
    script = Path(res["data"]["script_path"]["value"]).read_text()
    assert "_input_mask = os.path.realpath(" in script
    assert "if _input_mask and os.path.realpath(p) == _input_mask:" in script
