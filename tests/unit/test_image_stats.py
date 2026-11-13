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
