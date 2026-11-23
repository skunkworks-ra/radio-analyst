"""
Unit tests for ms_image_stats (src/ms_inspect/tools/image_stats.py).

No CASA required — tests the _extract_beam helper and the path-not-found
error path using a mock ia.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ms_inspect.tools.image_stats import _extract_beam, _plane_labels


class TestExtractBeam:
    def test_single_beam(self):
        beam_info = {
            "major": {"value": 2.5, "unit": "arcsec"},
            "minor": {"value": 1.8, "unit": "arcsec"},
            "positionangle": {"value": 45.0, "unit": "deg"},
        }
        major, minor, pa = _extract_beam(beam_info)
        assert major == pytest.approx(2.5)
        assert minor == pytest.approx(1.8)
        assert pa == pytest.approx(45.0)

    def test_multi_beam_cube(self):
        beam_info = {
            "nChannels": 2,
            "nStokes": 1,
            "beams": {
                "*0": {
                    "*0": {
                        "major": {"value": 3.0, "unit": "arcsec"},
                        "minor": {"value": 2.0, "unit": "arcsec"},
                        "positionangle": {"value": 10.0, "unit": "deg"},
                    }
                },
                "*1": {
                    "*0": {
                        "major": {"value": 3.1, "unit": "arcsec"},
                        "minor": {"value": 2.1, "unit": "arcsec"},
                        "positionangle": {"value": 11.0, "unit": "deg"},
                    }
                },
            },
        }
        major, minor, pa = _extract_beam(beam_info)
        assert major == pytest.approx(3.0)
        assert minor == pytest.approx(2.0)
        assert pa == pytest.approx(10.0)

    def test_missing_beam_returns_none(self):
        major, minor, pa = _extract_beam({})
        assert major is None
        assert minor is None
        assert pa is None

    def test_beam_angular_unit_conversions(self):
        import math

        # Single-beam in deg / arcmin / rad
        beam_deg = {
            "major": {"value": 1.0 / 3600.0, "unit": "deg"},
            "minor": {"value": 0.5 / 60.0, "unit": "arcmin"},
            "positionangle": {"value": math.pi / 4.0, "unit": "rad"},
        }
        major, minor, pa = _extract_beam(beam_deg)
        assert major == pytest.approx(1.0)
        assert minor == pytest.approx(0.5)
        assert pa == pytest.approx(45.0)

        # Multi-beam in mas and rad
        beam_mas = {
            "beams": {
                "*0": {
                    "*0": {
                        "major": {"value": 2500.0, "unit": "mas"},
                        "minor": {"value": math.radians(1.5 / 3600.0), "unit": "rad"},
                        "positionangle": {"value": -30.0, "unit": "deg"},
                    }
                }
            }
        }
        major2, minor2, pa2 = _extract_beam(beam_mas)
        assert major2 == pytest.approx(2.5)
        assert minor2 == pytest.approx(1.5)
        assert pa2 == pytest.approx(-30.0)


class TestPlaneLabels:
    def test_iquv_cube_order(self):
        # Image axes [RA, Dec, Stokes, Freq]; remaining axes [2, 3].
        # Stokes axis=2 (len 4), spectral axis=3 (len 2).
        labels = _plane_labels(
            remaining_axes=[2, 3],
            remaining_shape=[4, 2],
            stokes_pix_axis=2,
            spec_pix_axis=3,
            stokes_names=["I", "Q", "U", "V"],
        )
        # C-order: stokes varies slowest, channel fastest.
        assert len(labels) == 8
        assert labels[0] == {"stokes_index": 0, "stokes": "I", "chan": 0}
        assert labels[1] == {"stokes_index": 0, "stokes": "I", "chan": 1}
        assert labels[2] == {"stokes_index": 1, "stokes": "Q", "chan": 0}
        assert labels[-1] == {"stokes_index": 3, "stokes": "V", "chan": 1}

    def test_freq_first_axis_order(self):
        # Image axes [RA, Dec, Freq, Stokes]; remaining [2, 3].
        labels = _plane_labels(
            remaining_axes=[2, 3],
            remaining_shape=[3, 2],
            stokes_pix_axis=3,
            spec_pix_axis=2,
            stokes_names=["I", "V"],
        )
        assert labels[0] == {"chan": 0, "stokes_index": 0, "stokes": "I"}
        assert labels[1] == {"chan": 0, "stokes_index": 1, "stokes": "V"}
        assert labels[2] == {"chan": 1, "stokes_index": 0, "stokes": "I"}

    def test_no_stokes_names_falls_back_to_index(self):
        labels = _plane_labels([2], [2], stokes_pix_axis=2, spec_pix_axis=None)
        assert labels[0] == {"stokes_index": 0}
        assert labels[1] == {"stokes_index": 1}


class TestClassifyDetection:
    """Three descriptive levels, no pass/fail component.

    Covers the pure label function only. It does not cover the response
    envelope, which needs a real CASA image.
    """

    def test_thresholds(self):
        from ms_inspect.tools.image_stats import _classify_detection

        assert _classify_detection(3.0) == "undetected"
        assert _classify_detection(5.0) == "undetected"  # boundary, inclusive
        assert _classify_detection(7.0) == "marginal"
        assert _classify_detection(10.0) == "detection"  # boundary, inclusive
        assert _classify_detection(120.0) == "detection"
        assert _classify_detection(None) == "unknown"

    def test_returns_a_bare_label_not_a_gate(self):
        """The old contract returned (label, passed). Nothing may reintroduce it."""
        from ms_inspect.tools.image_stats import _classify_detection

        assert isinstance(_classify_detection(7.0), str)

    def test_low_constant_is_reachable(self):
        """With two levels both branches below 10 returned 'marginal' and the
        5.0 constant carried no information. Three levels make it usable."""
        from ms_inspect.tools.image_stats import (
            _P2N_MARGINAL,
            _P2N_UNDETECTED,
            _classify_detection,
        )

        assert _classify_detection(_P2N_UNDETECTED - 0.1) == "undetected"
        assert _classify_detection(_P2N_UNDETECTED + 0.1) == "marginal"
        assert _classify_detection(_P2N_MARGINAL) == "detection"


class TestNoGateFields:
    """The no-gates contract: this module must not ship a boolean verdict."""

    def test_source_has_no_detection_pass(self):
        import inspect

        from ms_inspect.tools import image_stats

        src = inspect.getsource(image_stats)
        assert "detection_pass" not in src
        assert "do not report this as a detection" not in src


class TestRunPathValidation:
    def test_missing_image_raises(self):
        from ms_inspect.exceptions import MSNotFoundError

        with pytest.raises(MSNotFoundError):
            from ms_inspect.tools.image_stats import run

            run("/nonexistent/path/target.image")

    def test_missing_psf_warns_and_continues(self, tmp_path):
        """A missing psf_path should add a warning but not abort."""
        image_dir = tmp_path / "target.image"
        image_dir.mkdir()

        fake_stats_robust = {"medabsdevmed": [0.001]}
        fake_stats = {"max": [0.5], "rms": [0.002]}
        fake_beam = {
            "major": {"value": 2.5, "unit": "arcsec"},
            "minor": {"value": 1.8, "unit": "arcsec"},
            "positionangle": {"value": 30.0, "unit": "deg"},
        }

        mock_ia = MagicMock()
        mock_ia.open.return_value = True
        mock_ia.statistics.side_effect = [fake_stats_robust, fake_stats]
        mock_ia.restoringbeam.return_value = fake_beam

        mock_casatools = MagicMock()
        mock_casatools.image.return_value = mock_ia

        with patch("ms_inspect.util.casa_context._require_casatools", return_value=mock_casatools):
            from ms_inspect.tools.image_stats import run

            result = run(str(image_dir), psf_path="/no/such/psf.psf")

        assert result["status"] == "ok"
        assert any("psf_path does not exist" in w for w in result["warnings"])
        assert result["data"]["rms_jy"]["value"] == pytest.approx(1.4826 * 0.001, rel=1e-4)
        assert result["data"]["peak_jy"]["value"] == pytest.approx(0.5)
        assert result["data"]["dynamic_range"]["value"] == pytest.approx(
            0.5 / (1.4826 * 0.001), rel=1e-3
        )


class TestResidualRms:
    def test_siblings(self):
        from ms_inspect.tools.image_stats import _siblings

        for name, res, pb in [
            ("t.image.pbcor", "t.residual", "t.pb"),
            ("t.image", "t.residual", "t.pb"),
            ("t.image.tt0", "t.residual.tt0", "t.pb.tt0"),
            ("t.image.pbcor.tt0", "t.residual.tt0", "t.pb.tt0"),
        ]:
            r, p = _siblings(f"/d/{name}")
            assert (r.name, p.name) == (res, pb)

    def test_missing_siblings_unavailable(self, tmp_path):
        from ms_inspect.tools.image_stats import _residual_rms

        calls: list[str] = []
        rms, region, why = _residual_rms(str(tmp_path / "t.image.pbcor"), 0.1, calls)
        assert rms is None
        assert "not found" in why
        assert region["pb_level"] == 0.1

    def test_rms_only_inside_pb(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        rng = np.random.default_rng(0)
        res = rng.normal(0, 1.0, (64, 64))
        res[:, :32] *= 100.0  # loud edge, outside the PB level
        pb = np.zeros((64, 64))
        pb[:, 32:] = 0.5
        arrays = {"t.residual": res, "t.pb": pb}
        for n in arrays:
            (tmp_path / n).mkdir()

        def fake_open(path):
            ia = MagicMock()
            ia.getchunk.return_value = arrays[Path(path).name]
            cm = MagicMock()
            cm.__enter__.return_value = ia
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            rms, region, why = image_stats._residual_rms(str(tmp_path / "t.image.pbcor"), 0.1, [])
        assert why is None
        assert region["n_pixels"] == 64 * 32
        assert 0.9 < rms < 1.1


class TestSignedStokesAndPbMaskedPlanes:
    """CR-3: Signed Q/U/V peaks and PB-masked per-plane stats on .image.pbcor cubes."""

    def _mock_csys(self, stokes_names, stokes_axis=2, spec_axis=3):
        csys = MagicMock()
        csys.stokes.return_value = stokes_names

        def _find(kind):
            if kind == "stokes" and stokes_axis is not None:
                return {"return": True, "pixel": [stokes_axis]}
            if kind == "spectral" and spec_axis is not None:
                return {"return": True, "pixel": [spec_axis]}
            return {"return": False, "pixel": []}

        csys.findcoordinate.side_effect = _find
        return csys

    def test_unmasked_fallback_preserves_negative_quv_peaks(self):
        import numpy as np

        from ms_inspect.tools.image_stats import _MAD_TO_SIGMA, _per_plane_stats

        ia = MagicMock()
        ia.shape.return_value = [16, 16, 4, 1]  # I, Q, U, V; 1 channel
        ia.coordsys.return_value = self._mock_csys(["I", "Q", "U", "V"])
        # Stokes I: max=+0.10, min=-0.20 (negative bowl -> Stokes I still reports +0.10)
        # Stokes Q: max=+0.0003, min=-0.050 (-50 mJy polarized source -> reports -0.050!)
        # Stokes U: max=+0.030, min=-0.0002 -> reports +0.030
        # Stokes V: max=+0.0002, min=-0.0003 -> reports -0.0003 (noise, undetected)
        ia.statistics.side_effect = [
            {"medabsdevmed": np.array([0.001, 0.001, 0.001, 0.001])},
            {
                "max": np.array([0.10, 0.0003, 0.030, 0.0002]),
                "min": np.array([-0.20, -0.050, -0.0002, -0.0003]),
            },
        ]
        planes = _per_plane_stats(ia, [], [])
        assert planes is not None and len(planes) == 4
        by_stokes = {p["stokes"]: p for p in planes}

        assert by_stokes["I"]["peak_jy"] == pytest.approx(0.10)
        assert by_stokes["Q"]["peak_jy"] == pytest.approx(-0.050)
        assert by_stokes["Q"]["dynamic_range"] == pytest.approx(
            0.050 / (_MAD_TO_SIGMA * 0.001), rel=1e-2
        )
        assert by_stokes["Q"]["detection"] == "detection"
        assert by_stokes["U"]["peak_jy"] == pytest.approx(0.030)
        assert by_stokes["U"]["detection"] == "detection"
        assert by_stokes["V"]["peak_jy"] == pytest.approx(-0.0003)
        assert by_stokes["V"]["detection"] == "undetected"

    def test_single_plane_negative_stokes_q_detected(self, tmp_path):
        from ms_inspect.tools import image_stats

        img_dir = tmp_path / "q_map.image"
        img_dir.mkdir()
        ia = MagicMock()
        ia.shape.return_value = [32, 32, 1, 1]
        ia.coordsys.return_value = self._mock_csys(["Q"])
        ia.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.0003], "min": [-0.050], "rms": [0.0015]},
        ]
        ia.restoringbeam.return_value = {
            "major": {"value": 2.0, "unit": "arcsec"},
            "minor": {"value": 2.0, "unit": "arcsec"},
            "positionangle": {"value": 0.0, "unit": "deg"},
        }
        cm = MagicMock()
        cm.__enter__.return_value = ia
        with patch.object(image_stats, "open_image", return_value=cm):
            res = image_stats.run(str(img_dir))
        assert res["data"]["peak_jy"]["value"] == pytest.approx(-0.050)
        assert res["data"]["detection"]["value"] == "detection"

    def test_pbcor_cube_per_plane_masks_edge_noise_and_broadcasts_pb(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        rng = np.random.default_rng(42)
        # Shape [32, 32, 4, 2] for IQUV x 2 channels; sibling .pb has [32, 32, 1, 2]
        cube = rng.normal(0.0, 0.001, (32, 32, 4, 2))
        # Outside PB (x < 16): 100x PB-divided edge noise spikes (+0.5 / -0.5 Jy)
        cube[:16, :, :, :] *= 200.0
        # Inside PB (x >= 16): plant +0.20 Jy in I and -0.040 Jy in Q at (24, 24)
        cube[24, 24, 0, :] = 0.20
        cube[24, 24, 1, :] = -0.040

        pb = np.full((32, 32, 1, 2), 0.02, dtype=float)
        pb[16:, :, :, :] = 0.8

        img_dir = tmp_path / "cube_iquv.image.pbcor"
        pb_dir = tmp_path / "cube_iquv.pb"
        img_dir.mkdir()
        pb_dir.mkdir()

        ia_img = MagicMock()
        ia_img.shape.return_value = list(cube.shape)
        ia_img.coordsys.return_value = self._mock_csys(["I", "Q", "U", "V"])
        ia_img.getchunk.return_value = cube

        ia_pb = MagicMock()
        ia_pb.shape.return_value = list(pb.shape)
        ia_pb.getchunk.return_value = pb

        def fake_open(path):
            cm = MagicMock()
            cm.__enter__.return_value = ia_pb if Path(path).name.endswith(".pb") else ia_img
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            planes = image_stats._per_plane_stats(
                ia_img, [], [], image_path=str(img_dir), pb_level=0.1
            )

        assert planes is not None and len(planes) == 8
        q0 = next(p for p in planes if p["stokes"] == "Q" and p["chan"] == 0)
        i0 = next(p for p in planes if p["stokes"] == "I" and p["chan"] == 0)
        v0 = next(p for p in planes if p["stokes"] == "V" and p["chan"] == 0)

        # Edge noise (200x) was masked out: per-plane RMS stays ~0.001 Jy, not ~0.2 Jy!
        assert 0.0007 < q0["rms_jy"] < 0.0014
        assert q0["peak_jy"] == pytest.approx(-0.040, abs=1e-4)
        assert q0["detection"] == "detection"
        assert i0["peak_jy"] == pytest.approx(0.20, abs=1e-4)
        assert v0["detection"] == "undetected"


class TestMinJyAndNegativeBowl:
    """PB-masked min_jy and negative_to_peak_ratio for Stokes I bowl diagnostics."""

    def _mock_csys(self, stokes_names, stokes_axis=2, spec_axis=3):
        csys = MagicMock()
        csys.stokes.return_value = stokes_names

        def _find(kind):
            if kind == "stokes" and stokes_axis is not None:
                return {"return": True, "pixel": [stokes_axis]}
            if kind == "spectral" and spec_axis is not None:
                return {"return": True, "pixel": [spec_axis]}
            return {"return": False, "pixel": []}

        csys.findcoordinate.side_effect = _find
        return csys

    def _beam(self):
        return {
            "major": {"value": 2.0, "unit": "arcsec"},
            "minor": {"value": 2.0, "unit": "arcsec"},
            "positionangle": {"value": 0.0, "unit": "deg"},
        }

    def test_pb_masked_min_and_severe_bowl_ratio(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        img = np.zeros((32, 32, 1, 1), dtype=float)
        # Edge noise spike outside PB (< 0.1): -0.90 Jy must be ignored
        img[2, 2, 0, 0] = -0.90
        # Inside PB (>= 0.1): peak +0.20 Jy, clean bowl -0.05 Jy -> ratio = 0.25
        img[20, 20, 0, 0] = 0.20
        img[22, 22, 0, 0] = -0.05

        pb = np.full((32, 32, 1, 1), 0.02, dtype=float)
        pb[16:, :, :, :] = 0.8

        img_dir = tmp_path / "target.image.pbcor"
        pb_dir = tmp_path / "target.pb"
        img_dir.mkdir()
        pb_dir.mkdir()

        ia_img = MagicMock()
        ia_img.shape.return_value = list(img.shape)
        ia_img.coordsys.return_value = self._mock_csys(["I"])
        ia_img.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.20], "min": [-0.90], "rms": [0.01]},
        ]
        ia_img.getchunk.return_value = img
        ia_img.restoringbeam.return_value = self._beam()

        ia_pb = MagicMock()
        ia_pb.getchunk.return_value = pb

        def fake_open(path):
            cm = MagicMock()
            cm.__enter__.return_value = ia_pb if Path(path).name.endswith(".pb") else ia_img
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            res = image_stats.run(str(img_dir), pb_level=0.1)

        assert res["data"]["min_jy"]["value"] == pytest.approx(-0.05)
        assert res["data"]["min_jy"]["flag"] == "COMPLETE"
        assert "target.pb >= 0.1" in res["data"]["min_jy"]["note"]
        assert res["data"]["negative_to_peak_ratio"]["value"] == pytest.approx(0.25)
        assert res["data"]["negative_to_peak_ratio"]["flag"] == "COMPLETE"

    def test_positive_only_image_has_zero_bowl_ratio_and_fallback_without_pb(self, tmp_path):
        from ms_inspect.tools import image_stats

        img_dir = tmp_path / "clean.image"
        img_dir.mkdir()

        ia = MagicMock()
        ia.shape.return_value = [32, 32, 1, 1]
        ia.coordsys.return_value = self._mock_csys(["I"])
        ia.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.10], "min": [0.0005], "rms": [0.002]},
        ]
        ia.restoringbeam.return_value = self._beam()

        cm = MagicMock()
        cm.__enter__.return_value = ia
        with patch.object(image_stats, "open_image", return_value=cm):
            res = image_stats.run(str(img_dir))

        assert res["data"]["min_jy"]["value"] == pytest.approx(0.0005)
        assert res["data"]["min_jy"]["flag"] == "COMPLETE"
        assert "whole-image min" in res["data"]["min_jy"]["note"]
        assert res["data"]["negative_to_peak_ratio"]["value"] == pytest.approx(0.0)
        assert res["data"]["negative_to_peak_ratio"]["flag"] == "COMPLETE"

    def test_signed_stokes_marks_negative_to_peak_ratio_unavailable(self, tmp_path):
        from ms_inspect.tools import image_stats

        img_dir = tmp_path / "stokes_q.image"
        img_dir.mkdir()

        ia = MagicMock()
        ia.shape.return_value = [32, 32, 1, 1]
        ia.coordsys.return_value = self._mock_csys(["Q"])
        ia.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.002], "min": [-0.050], "rms": [0.002]},
        ]
        ia.restoringbeam.return_value = self._beam()

        cm = MagicMock()
        cm.__enter__.return_value = ia
        with patch.object(image_stats, "open_image", return_value=cm):
            res = image_stats.run(str(img_dir))

        assert res["data"]["min_jy"]["value"] == pytest.approx(-0.050)
        assert res["data"]["min_jy"]["flag"] == "COMPLETE"
        assert res["data"]["negative_to_peak_ratio"]["value"] is None
        assert res["data"]["negative_to_peak_ratio"]["flag"] == "UNAVAILABLE"
        assert "signed Stokes Q" in res["data"]["negative_to_peak_ratio"]["note"]

    def test_iquv_cube_marks_negative_to_peak_ratio_unavailable(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        img_dir = tmp_path / "cube_iquv.image"
        img_dir.mkdir()

        ia = MagicMock()
        ia.shape.return_value = [16, 16, 4, 1]
        ia.coordsys.return_value = self._mock_csys(["I", "Q", "U", "V"])
        ia.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.10], "min": [-0.05], "rms": [0.002]},
            {"medabsdevmed": np.array([0.001, 0.001, 0.001, 0.001])},
            {
                "max": np.array([0.10, 0.001, 0.02, 0.0002]),
                "min": np.array([-0.002, -0.05, -0.001, -0.0003]),
            },
        ]
        ia.restoringbeam.return_value = self._beam()

        cm = MagicMock()
        cm.__enter__.return_value = ia
        with patch.object(image_stats, "open_image", return_value=cm):
            res = image_stats.run(str(img_dir))

        assert res["data"]["min_jy"]["value"] == pytest.approx(-0.05)
        assert res["data"]["negative_to_peak_ratio"]["value"] is None
        assert res["data"]["negative_to_peak_ratio"]["flag"] == "UNAVAILABLE"
        assert "multi-Stokes" in res["data"]["negative_to_peak_ratio"]["note"]

    def test_pbcor_uses_sibling_flat_noise_image_for_negative_to_peak_ratio(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        # .pbcor has 10x PB-edge noise spike (-0.04 Jy -> 0.20 ratio on pbcor)
        pbcor = np.zeros((32, 32, 1, 1), dtype=float)
        pbcor[20, 20, 0, 0] = 0.20
        pbcor[17, 17, 0, 0] = -0.04  # at PB=0.12 edge

        # Flat-noise .image has peak 0.20 Jy and real min -0.0018 Jy -> true bowl = 0.009
        flat = np.zeros((32, 32, 1, 1), dtype=float)
        flat[20, 20, 0, 0] = 0.20
        flat[22, 22, 0, 0] = -0.0018

        pb = np.full((32, 32, 1, 1), 0.02, dtype=float)
        pb[16:, :, :, :] = 0.8
        pb[17, 17, 0, 0] = 0.12

        pbcor_dir = tmp_path / "target.image.pbcor"
        flat_dir = tmp_path / "target.image"
        pb_dir = tmp_path / "target.pb"
        for d in (pbcor_dir, flat_dir, pb_dir):
            d.mkdir()

        ia_pbcor = MagicMock()
        ia_pbcor.shape.return_value = list(pbcor.shape)
        ia_pbcor.coordsys.return_value = self._mock_csys(["I"])
        ia_pbcor.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [0.20], "min": [-0.04], "rms": [0.005]},
        ]
        ia_pbcor.getchunk.return_value = pbcor
        ia_pbcor.restoringbeam.return_value = self._beam()

        ia_flat = MagicMock()
        ia_flat.statistics.return_value = {"max": [0.20], "min": [-0.0018]}
        ia_flat.getchunk.return_value = flat

        ia_pb = MagicMock()
        ia_pb.getchunk.return_value = pb

        def fake_open(path):
            name = Path(path).name
            cm = MagicMock()
            if name == "target.pb":
                cm.__enter__.return_value = ia_pb
            elif name == "target.image":
                cm.__enter__.return_value = ia_flat
            else:
                cm.__enter__.return_value = ia_pbcor
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            res = image_stats.run(str(pbcor_dir), pb_level=0.1)

        d = res["data"]
        assert d["min_jy"]["value"] == pytest.approx(-0.04)
        assert d["flat_noise_min_jy"]["value"] == pytest.approx(-0.0018)
        assert d["flat_noise_peak_jy"]["value"] == pytest.approx(0.20)
        assert d["negative_to_peak_ratio"]["value"] == pytest.approx(0.009)
        assert "target.image" in d["negative_to_peak_ratio"]["note"]
        assert d["mask_pixels"]["flag"] == "UNAVAILABLE"

    def test_mask_partitioned_residual_stats_separates_in_and_out_of_mask(self, tmp_path):
        import numpy as np

        from ms_inspect.tools import image_stats

        rng = np.random.default_rng(7)
        pb = np.zeros((64, 64, 1, 1), dtype=float)
        pb[16:48, 16:48, 0, 0] = 0.8  # 1024 valid PB pixels

        mask = np.zeros((64, 64, 1, 1), dtype=float)
        mask[28:36, 28:36, 0, 0] = 1.0  # 64 masked pixels (6.25% of PB)

        res_arr = rng.normal(0.0, 0.001, (64, 64, 1, 1))
        # Plant uncleaned inside-mask flux (+0.010 Jy ~ 10 sigma)
        res_arr[30:34, 30:34, 0, 0] = 0.010
        # Plant unmasked outside-mask compact source (+0.008 Jy ~ 8 sigma)
        res_arr[20, 20, 0, 0] = 0.008
        # Plant loud edge outside PB (must be ignored)
        res_arr[0, 0, 0, 0] = 5.0

        pbcor_dir = tmp_path / "src.image.pbcor"
        res_dir = tmp_path / "src.residual"
        pb_dir = tmp_path / "src.pb"
        msk_dir = tmp_path / "src.mask"
        for d in (pbcor_dir, res_dir, pb_dir, msk_dir):
            d.mkdir()

        arrays = {
            "src.residual": res_arr,
            "src.pb": pb,
            "src.mask": mask,
        }

        def fake_open(path):
            ia = MagicMock()
            ia.getchunk.return_value = arrays[Path(path).name]
            cm = MagicMock()
            cm.__enter__.return_value = ia
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            out = image_stats._mask_partitioned_residual_stats(
                str(pbcor_dir), pb_level=0.1, mask_path=None, casa_calls=[], warnings=[]
            )

        assert out["mask_pixels"]["value"] == 64
        assert out["mask_fraction_in_pb"]["value"] == pytest.approx(64 / 1024, rel=1e-4)
        assert 0.0008 < out["residual_out_mask_rms_jy"]["value"] < 0.0012
        assert out["residual_out_mask_peak_jy"]["value"] == pytest.approx(0.008)
        assert 6.5 < out["residual_out_mask_peak_snr"]["value"] < 10.0
        assert out["residual_in_mask_peak_jy"]["value"] == pytest.approx(0.010)
        assert out["residual_in_mask_peak_snr"]["value"] > 8.0
        assert out["residual_in_to_out_rms_ratio"]["value"] > 4.0

    def test_sibling_mask_and_flat_image_mtmfs(self, tmp_path):
        from ms_inspect.tools.image_stats import _sibling_flat_image, _sibling_mask

        pbcor = tmp_path / "wb.image.pbcor.tt0"
        flat = tmp_path / "wb.image.tt0"
        msk = tmp_path / "wb.mask"
        for d in (pbcor, flat, msk):
            d.mkdir()
        assert _sibling_flat_image(str(pbcor)) == flat
        assert _sibling_mask(str(pbcor)) == msk

    def test_pb_masked_peak_ignores_outer_pbcor_edge_spike(self, tmp_path):
        """With pblimit=-0.01 mosaics, PB-divided edge spikes at PB=0.02 must NOT
        corrupt peak_jy / dynamic_range when pb_level=0.1 masks to PB >= 0.1."""
        import numpy as np

        from ms_inspect.tools import image_stats

        rng = np.random.default_rng(11)
        pb = np.full((32, 32, 1, 1), 0.02, dtype=float)
        pb[8:24, 8:24, 0, 0] = 0.8

        pbcor_arr = rng.normal(0.0, 0.001, (32, 32, 1, 1))
        pbcor_arr[16, 16, 0, 0] = 0.50  # true source inside PB >= 0.1
        pbcor_arr[0, 0, 0, 0] = 50.0  # 100x PB-divided noise spike outside PB!

        pbcor_dir = tmp_path / "mosaic.image.pbcor"
        pb_dir = tmp_path / "mosaic.pb"
        pbcor_dir.mkdir()
        pb_dir.mkdir()

        csys = MagicMock()
        csys.stokes.return_value = ["I"]
        csys.findcoordinate.side_effect = lambda kind: (
            {"return": True, "pixel": [2]} if kind == "stokes" else {"return": False, "pixel": []}
        )

        ia_pbcor = MagicMock()
        ia_pbcor.shape.return_value = [32, 32, 1, 1]
        ia_pbcor.coordsys.return_value = csys
        ia_pbcor.getchunk.return_value = pbcor_arr
        ia_pbcor.statistics.side_effect = [
            {"medabsdevmed": [0.001]},
            {"max": [50.0], "min": [-5.0], "rms": [0.5]},
        ]
        ia_pbcor.restoringbeam.return_value = {
            "major": {"value": 3.0, "unit": "arcsec"},
            "minor": {"value": 3.0, "unit": "arcsec"},
            "positionangle": {"value": 0.0, "unit": "deg"},
        }

        ia_pb = MagicMock()
        ia_pb.shape.return_value = [32, 32, 1, 1]
        ia_pb.getchunk.return_value = pb

        def fake_open(path):
            cm = MagicMock()
            cm.__enter__.return_value = ia_pb if Path(path).name.endswith(".pb") else ia_pbcor
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            res = image_stats.run(str(pbcor_dir), pb_level=0.1)

        assert res["data"]["peak_jy"]["value"] == pytest.approx(0.50)
        assert res["data"]["dynamic_range"]["value"] < 1000.0

    def test_tt0_pbcor_siblings_and_full_map_outer_pb_residual_detection(self, tmp_path):
        """CASA mtmfs writes .image.tt0.pbcor (as well as .image.pbcor.tt0), and
        _full_residual_peak_stats exposes a 35-sigma outer-PB source even when pb_level=0.1."""
        import numpy as np

        from ms_inspect.tools import image_stats

        pbcor = tmp_path / "mtmfs.image.tt0.pbcor"
        flat = tmp_path / "mtmfs.image.tt0"
        res_dir = tmp_path / "mtmfs.residual.tt0"
        pb_dir = tmp_path / "mtmfs.pb.tt0"
        msk_dir = tmp_path / "mtmfs.mask"
        for d in (pbcor, flat, res_dir, pb_dir, msk_dir):
            d.mkdir()

        assert image_stats._siblings(str(pbcor)) == (res_dir, pb_dir)
        assert image_stats._sibling_flat_image(str(pbcor)) == flat
        assert image_stats._sibling_mask(str(pbcor)) == msk_dir

        rng = np.random.default_rng(13)
        pb = np.zeros((64, 64, 1, 1), dtype=float)
        pb[16:48, 16:48, 0, 0] = 0.8
        pb[4:16, 4:16, 0, 0] = 0.05

        res_arr = rng.normal(0.0, 0.0002, (64, 64, 1, 1))
        res_arr[8, 8, 0, 0] = 0.007

        arrays = {"mtmfs.residual.tt0": res_arr, "mtmfs.pb.tt0": pb}

        def fake_open(path):
            ia = MagicMock()
            ia.getchunk.return_value = arrays[Path(path).name]
            cm = MagicMock()
            cm.__enter__.return_value = ia
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            full = image_stats._full_residual_peak_stats(
                str(pbcor), pb_level=0.1, ref_rms_jy=0.0002, casa_calls=[], warnings=[]
            )

        assert full["residual_full_peak_jy"]["value"] == pytest.approx(0.007)
        assert full["residual_full_peak_snr"]["value"] == pytest.approx(35.0)
        assert full["residual_full_peak_pb"]["value"] == pytest.approx(0.05)
        assert full["residual_outer_pb_peak_jy"]["value"] == pytest.approx(0.007)
        assert full["residual_outer_pb_peak_snr"]["value"] == pytest.approx(35.0)
        assert full["residual_outer_pb_peak_pb"]["value"] == pytest.approx(0.05)

    def test_outer_pb_sky_coords_and_model_positivity_stats(self, tmp_path):
        """ms_image_stats returns J2000 coords for outer-PB peak and programmatic .model positivity."""
        import math

        import numpy as np

        from ms_inspect.tools import image_stats

        pbcor = tmp_path / "mfs.image.tt0.pbcor"
        res_dir = tmp_path / "mfs.residual.tt0"
        pb_dir = tmp_path / "mfs.pb.tt0"
        mod_dir = tmp_path / "mfs.model.tt0"
        for d in (pbcor, res_dir, pb_dir, mod_dir):
            d.mkdir()

        assert image_stats._sibling_model(str(pbcor)) == mod_dir

        pb = np.zeros((32, 32, 1, 1), dtype=float)
        pb[8:24, 8:24, 0, 0] = 0.8
        pb[2:8, 2:8, 0, 0] = 0.045

        res_arr = np.zeros((32, 32, 1, 1), dtype=float)
        res_arr[4, 5, 0, 0] = 0.0055

        mod_arr = np.zeros((32, 32, 1, 1), dtype=float)
        mod_arr[16, 16, 0, 0] = 0.10
        mod_arr[16, 17, 0, 0] = 0.05
        mod_arr[15, 16, 0, 0] = -0.015
        mod_arr[4, 5, 0, 0] = 0.015  # outer PB flux

        arrays = {
            "mfs.residual.tt0": res_arr,
            "mfs.pb.tt0": pb,
            "mfs.model.tt0": mod_arr,
        }

        def fake_open(path):
            ia = MagicMock()
            ia.getchunk.return_value = arrays[Path(path).name]
            csys = MagicMock()
            csys.toworld.return_value = {
                "numeric": [math.radians(52.6092), math.radians(30.0624), 0.0, 1.5e9]
            }
            csys.units.return_value = ["rad", "rad", "", "Hz"]
            ia.coordsys.return_value = csys
            cm = MagicMock()
            cm.__enter__.return_value = ia
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            full = image_stats._full_residual_peak_stats(
                str(pbcor), pb_level=0.1, ref_rms_jy=0.00016, casa_calls=[], warnings=[]
            )
            mod = image_stats._model_positivity_stats(
                str(pbcor), pb_level=0.1, has_signed_stokes=False, casa_calls=[], warnings=[]
            )
            mod_q = image_stats._model_positivity_stats(
                str(pbcor), pb_level=0.1, has_signed_stokes=True, casa_calls=[], warnings=[]
            )

        assert full["residual_outer_pb_peak_ra_deg"]["value"] == pytest.approx(52.6092, abs=1e-4)
        assert full["residual_outer_pb_peak_dec_deg"]["value"] == pytest.approx(30.0624, abs=1e-4)
        assert full["residual_outer_pb_peak_j2000"]["value"] == "J2000 03h30m26.21s +30d03m44.6s"

        assert mod["model_nonzero_pixels"]["value"] == 4
        assert mod["model_neg_pixel_fraction"]["value"] == pytest.approx(0.25)
        assert mod["model_sum_pos_jy"]["value"] == pytest.approx(0.165)
        assert mod["model_sum_neg_jy"]["value"] == pytest.approx(-0.015)
        assert mod["model_neg_to_pos_flux_ratio"]["value"] == pytest.approx(0.015 / 0.165, abs=1e-4)
        assert mod["model_neg_to_pos_peak_ratio"]["value"] == pytest.approx(0.15)
        assert mod["model_outer_pb_flux_frac"]["value"] == pytest.approx(0.015 / 0.18, abs=1e-4)
        assert mod_q["model_neg_to_pos_flux_ratio"]["flag"] == "UNAVAILABLE"

    def test_in_model_residual_ratio_computed_when_mask_absent(self, tmp_path):
        """When .mask is absent (or full-PB usemask='pb'), residual_in_model_rms_ratio
        and residual_in_to_out_rms_ratio fallback expose elevated on-source residuals."""
        import numpy as np

        from ms_inspect.tools import image_stats

        pbcor = tmp_path / "pbpass.image.tt0.pbcor"
        res_dir = tmp_path / "pbpass.residual.tt0"
        pb_dir = tmp_path / "pbpass.pb.tt0"
        mod_dir = tmp_path / "pbpass.model.tt0"
        for d in (pbcor, res_dir, pb_dir, mod_dir):
            d.mkdir()
        # Intentionally no .mask directory on disk.

        rng = np.random.default_rng(7)
        pb = np.zeros((64, 64, 1, 1), dtype=float)
        pb[8:56, 8:56, 0, 0] = 0.8

        res_arr = rng.normal(0.0, 0.0002, (64, 64, 1, 1))
        mod_arr = np.zeros((64, 64, 1, 1), dtype=float)
        # Put a small modeled region with 3x elevated uncleaned residuals.
        mod_arr[28:36, 28:36, 0, 0] = 0.05
        res_arr[28:36, 28:36, 0, 0] = 0.0006

        img_arr = mod_arr + res_arr
        arrays = {
            "pbpass.image.tt0.pbcor": img_arr,
            "pbpass.residual.tt0": res_arr,
            "pbpass.pb.tt0": pb,
            "pbpass.model.tt0": mod_arr,
        }

        def fake_open(path):
            name = Path(path).name
            arr = arrays[name]
            ia = MagicMock()
            ia.getchunk.return_value = arr
            ia.shape.return_value = list(arr.shape)
            ia.statistics.side_effect = lambda robust=False, **kw: (
                {"medabsdevmed": [0.000135]}
                if robust
                else {"max": [float(np.max(arr))], "min": [float(np.min(arr))], "rms": [0.0002]}
            )
            csys = MagicMock()
            csys.stokes.return_value = ["I"]
            ia.coordsys.return_value = csys
            ia.restoringbeam.return_value = {
                "major": {"value": 10.0, "unit": "arcsec"},
                "minor": {"value": 8.0, "unit": "arcsec"},
                "positionangle": {"value": 15.0, "unit": "deg"},
            }
            cm = MagicMock()
            cm.__enter__.return_value = ia
            return cm

        with patch.object(image_stats, "open_image", side_effect=fake_open):
            out = image_stats.run(str(pbcor), pb_level=0.1)["data"]

        assert out["residual_out_mask_rms_jy"]["value"] is None
        assert out["residual_in_model_rms_ratio"]["value"] > 2.5
        assert out["residual_in_to_out_rms_ratio"]["value"] == pytest.approx(
            out["residual_in_model_rms_ratio"]["value"]
        )
        assert (
            "fallback to residual_in_model_rms_ratio" in out["residual_in_to_out_rms_ratio"]["note"]
        )
