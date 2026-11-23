"""
Unit tests for ms_tclean script generation.

Uses real_ms_calibrated (tests/unit/conftest.py) — a real MS with a real
CORRECTED_DATA column — for every test that doesn't care about the
CORRECTED_DATA guardrail itself, so run() takes its real success branch
(column present, no raise, no warning) rather than accidentally falling
through open_table's except-Exception into "Could not verify" on a fake
`table.info`-only MS. TestCorrectedDataGuardrail below covers both real
outcomes of that check directly: present (real_ms_calibrated) and genuinely
absent (real_ms_raw).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _run(tmp_path, real_ms_calibrated, **kwargs):
    from ms_modify.tclean import run

    workdir = tmp_path / "work"
    workdir.mkdir()
    result = run(
        real_ms_calibrated,
        str(workdir / "img"),
        field="0",
        workdir=str(workdir),
        execute=False,
        **kwargs,
    )
    script = Path(result["data"]["script_path"]["value"]).read_text()
    warnings = result.get("warnings", [])
    return script, warnings


class TestCfcache:
    def test_cfcache_rendered_for_awproject(self, tmp_path, real_ms_calibrated):
        script, _ = _run(
            tmp_path,
            real_ms_calibrated,
            gridder="awproject",
            wprojplanes=32,
            cfcache="/data/cf.cache",
        )
        assert "cfcache      = '/data/cf.cache'" in script

    def test_cfcache_ignored_for_awp2_with_warning(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(
            tmp_path, real_ms_calibrated, gridder="awp2", wprojplanes=32, cfcache="/data/cf.cache"
        )
        assert "cfcache      =" not in script
        assert any("only used by gridder='awproject'" in w for w in warnings)

    def test_awproject_without_cfcache_warns(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, gridder="awproject", wprojplanes=32)
        assert any("without cfcache" in w for w in warnings)


class TestWprojplanesWarning:
    def test_awp2_without_wprojplanes_warns(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, gridder="awp2")
        assert any("wprojplanes=1" in w for w in warnings)

    def test_standard_gridder_no_warning(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, gridder="standard")
        assert not any("wprojplanes" in w for w in warnings)


class TestAwpFullPolGuardrails:
    def test_mvc_mtmfs_iquv_warns_shape_assert(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(
            tmp_path,
            real_ms_calibrated,
            gridder="awp2",
            wprojplanes=16,
            stokes="IQUV",
            deconvolver="mtmfs",
            nterms=2,
            specmode="mvc",
        )
        assert any("shapeIn.isEqual" in w for w in warnings)
        assert any("specmode='mfs'" in w for w in warnings)

    def test_mfs_mtmfs_iquv_no_shape_warning(self, tmp_path, real_ms_calibrated):
        # The steered-to combo must NOT emit the crash warning.
        _, warnings = _run(
            tmp_path,
            real_ms_calibrated,
            gridder="awp2",
            wprojplanes=16,
            stokes="IQUV",
            deconvolver="mtmfs",
            nterms=2,
            specmode="mfs",
        )
        assert not any("shapeIn.isEqual" in w for w in warnings)

    def test_awp_fullpol_warns_aterm_cost(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(
            tmp_path,
            real_ms_calibrated,
            gridder="awp2",
            wprojplanes=16,
            stokes="IQUV",
            specmode="mfs",
        )
        assert any("A-term" in w for w in warnings)

    def test_stokes_i_no_fullpol_warnings(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, gridder="awp2", wprojplanes=16, stokes="I")
        assert not any("A-term" in w for w in warnings)
        assert not any("shapeIn.isEqual" in w for w in warnings)

    def test_standard_gridder_no_fullpol_warnings(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, gridder="standard", stokes="IQUV")
        assert not any("A-term" in w for w in warnings)


class TestSpecmodeMvc:
    def test_mvc_rendered(self, tmp_path, real_ms_calibrated):
        script, _ = _run(
            tmp_path, real_ms_calibrated, gridder="awp2", wprojplanes=32, specmode="mvc"
        )
        assert "specmode     = 'mvc'" in script


class TestPbMask:
    def test_default_pblimit_and_pbmask(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated)
        assert "pblimit      = -0.1," in script
        assert "usemask      = 'pb'," in script
        assert "pbmask       = 0.1," in script

    def test_pbmask_follows_pblimit(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, pblimit=-0.2)
        assert "pbmask       = 0.2," in script

    def test_explicit_pbmask(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, pbmask=0.3)
        assert "pblimit      = -0.1," in script
        assert "pbmask       = 0.3," in script

    def test_positive_pblimit_and_nsigma(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, pblimit=0.1, nsigma=3.5)
        assert "pblimit      = 0.1," in script
        assert "pbmask       = 0.1," in script
        assert "nsigma       = 3.5," in script

    def test_user_mask_rendered(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(
            tmp_path,
            real_ms_calibrated,
            usemask="user",
            mask="/work/pybdsf.mask",
            pblimit=0.1,
        )
        assert "usemask      = 'user'," in script
        assert "mask         = '/work/pybdsf.mask'," in script
        assert "pbmask       =" not in script
        assert not any("ignored" in w for w in warnings)

    def test_user_mask_without_mask_raises(self, tmp_path, real_ms_calibrated):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="requires a non-empty mask"):
            _run(tmp_path, real_ms_calibrated, usemask="user")

    def test_user_mask_colliding_with_imagename_mask_warns(self, tmp_path, real_ms_calibrated):
        from ms_modify.tclean import run

        workdir = tmp_path / "work"
        workdir.mkdir()
        res = run(
            real_ms_calibrated,
            str(workdir / "img_r1"),
            field="0",
            usemask="user",
            mask=str(workdir / "img_r1.mask"),
            workdir=str(workdir),
            execute=False,
        )
        assert any("equals tclean's own output mask" in w for w in res["warnings"])

    def test_auto_multithresh_rejected(self, tmp_path, real_ms_calibrated):
        from ms_inspect.exceptions import ComputationError

        with pytest.raises(ComputationError, match="auto-multithresh"):
            _run(tmp_path, real_ms_calibrated, usemask="auto-multithresh")

    def test_mask_with_pb_warns_and_ignored(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(
            tmp_path, real_ms_calibrated, usemask="pb", mask="/work/pybdsf.mask"
        )
        assert "usemask      = 'pb'," in script
        assert "mask         =" not in script
        assert any("ignored when usemask='pb'" in w for w in warnings)

    def test_operational_guardrail_warnings(self, tmp_path, real_ms_calibrated):
        from ms_modify.tclean import run

        workdir = tmp_path / "work"
        workdir.mkdir()
        res = run(
            real_ms_calibrated,
            str(workdir / "mosaic_bad"),
            field="0,1",
            gridder="standard",
            usemask="pb",
            nsigma=None,
            workdir=str(workdir),
            execute=False,
        )
        warns = res["warnings"]
        assert any("gridder='standard'" in w for w in warns)
        assert any("usemask='pb' without nsigma" in w for w in warns)

        res2 = run(
            real_ms_calibrated,
            str(workdir / "mosaic_pospb"),
            field="0,1",
            gridder="mosaic",
            pblimit=0.1,
            nsigma=3.0,
            workdir=str(workdir),
            execute=False,
        )
        warns2 = res2["warnings"]
        assert any("positive pblimit" in w for w in warns2)
        assert not any("usemask='pb' without nsigma" in w for w in warns2)

        res3 = run(
            real_ms_calibrated,
            str(workdir / "mosaic_lowpbmask"),
            field="0,1",
            gridder="mosaic",
            pblimit=-0.01,
            pbmask=None,
            usemask="pb",
            nsigma=3.5,
            workdir=str(workdir),
            execute=False,
        )
        warns3 = res3["warnings"]
        assert any("pbmask=0.01" in w for w in warns3)

        res4 = run(
            real_ms_calibrated,
            str(workdir / "mosaic_good"),
            field="0,1",
            gridder="mosaic",
            pblimit=-0.01,
            pbmask=0.1,
            usemask="pb",
            nsigma=3.5,
            workdir=str(workdir),
            execute=False,
        )
        warns4 = res4["warnings"]
        assert not any("positive pblimit" in w for w in warns4)
        assert not any("pbmask=" in w for w in warns4)

        res5 = run(
            real_ms_calibrated,
            str(workdir / "mosaic_mtmfs_low_nsigma"),
            field="0,1",
            gridder="mosaic",
            deconvolver="mtmfs",
            nterms=2,
            specmode="mfs",
            pblimit=-0.01,
            pbmask=0.1,
            usemask="pb",
            nsigma=3.5,
            workdir=str(workdir),
            execute=False,
        )
        assert any("nsigma=5.0" in w for w in res5["warnings"])

        res6 = run(
            real_ms_calibrated,
            str(workdir / "mosaic_mtmfs_shallow"),
            field="0,1",
            gridder="mosaic",
            deconvolver="mtmfs",
            nterms=2,
            specmode="mfs",
            pblimit=-0.01,
            pbmask=0.1,
            usemask="pb",
            nsigma=5.0,
            workdir=str(workdir),
            execute=False,
        )
        assert not any("nsigma=5.0" in w for w in res6["warnings"])

    def test_execute_forwards_user_mask_pblimit_and_nsigma(
        self, tmp_path, real_ms_calibrated, monkeypatch
    ):
        import sys
        import types

        from ms_modify.tclean import run

        workdir = tmp_path / "work"
        workdir.mkdir()
        captured: dict = {}

        def fake_tclean(**kwargs):
            captured.update(kwargs)
            (Path(kwargs["imagename"] + ".image")).mkdir()
            return {"stopcode": 8}

        fake_mod = types.SimpleNamespace(tclean=fake_tclean)
        monkeypatch.setitem(sys.modules, "casatasks", fake_mod)

        res = run(
            real_ms_calibrated,
            str(workdir / "img"),
            field="0",
            workdir=str(workdir),
            pblimit=0.1,
            usemask="user",
            mask=str(workdir / "pybdsf.mask"),
            nsigma=3.5,
            execute=True,
        )
        assert res["status"] == "ok"
        assert captured["pblimit"] == 0.1
        assert captured["usemask"] == "user"
        assert captured["mask"] == str(workdir / "pybdsf.mask")
        assert "pbmask" not in captured
        assert captured["nsigma"] == 3.5


class TestCubeArgs:
    def test_cube_args_rendered_for_cube(self, tmp_path, real_ms_calibrated):
        script, _ = _run(
            tmp_path,
            real_ms_calibrated,
            specmode="cube",
            stokes="IQUV",
            nchan=16,
            start="1.0GHz",
            width="64MHz",
            outframe="LSRK",
        )
        assert "specmode     = 'cube'" in script
        assert "nchan        = 16" in script
        assert "start        = '1.0GHz'" in script
        assert "width        = '64MHz'" in script
        assert "outframe     = 'LSRK'" in script

    def test_cube_args_ignored_for_mfs_with_warning(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(
            tmp_path, real_ms_calibrated, specmode="mfs", nchan=16, outframe="LSRK"
        )
        assert "nchan" not in script
        assert "outframe" not in script
        assert any("cube args" in w for w in warnings)

    def test_no_cube_args_no_warning(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(tmp_path, real_ms_calibrated, specmode="mfs")
        assert not any("cube args" in w for w in warnings)
        assert "nchan" not in script

    def test_partial_cube_args_omits_unset(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, specmode="cube", nchan=8)
        assert "nchan        = 8" in script
        assert "start" not in script
        assert "width" not in script
        assert "outframe" not in script


class TestConvergence:
    def test_script_requests_compact_summary_and_checks_convergence(
        self, tmp_path, real_ms_calibrated
    ):
        script, _ = _run(tmp_path, real_ms_calibrated)
        assert "fullsummary  = False" in script
        assert "summary = tclean(" in script
        assert 'summary.get("stopcode")' in script
        assert "DID NOT CONVERGE" in script

    def test_convergence_classifier(self):
        from ms_modify.tclean import _convergence

        code, _desc, converged, warn = _convergence({"stopcode": 2})
        assert code == 2 and converged and warn is None

        code, _desc, converged, warn = _convergence({"stopcode": 1})
        assert code == 1 and not converged and "did NOT converge" in warn

        code, _desc, converged, warn = _convergence(None)
        assert code is None and not converged and "no summary dict" in warn


class TestCorrectedDataGuardrail:
    """Both real outcomes of the CORRECTED_DATA check, against real MSs."""

    def test_raises_when_corrected_data_is_genuinely_absent(self, tmp_path, real_ms_raw):
        from ms_inspect.exceptions import InsufficientMetadataError
        from ms_modify.tclean import run

        workdir = tmp_path / "work"
        workdir.mkdir()
        with pytest.raises(InsufficientMetadataError, match="CORRECTED_DATA column not found"):
            run(
                real_ms_raw,
                str(workdir / "img"),
                field="0",
                workdir=str(workdir),
                execute=False,
            )

    def test_no_warning_when_corrected_data_is_genuinely_present(
        self, tmp_path, real_ms_calibrated
    ):
        _, warnings = _run(tmp_path, real_ms_calibrated)
        assert not any("Could not verify" in w for w in warnings)


class TestScalesAndAsp:
    def test_multiscale_scales_rendered(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(
            tmp_path, real_ms_calibrated, deconvolver="multiscale", scales=[0, 5, 15]
        )
        assert "deconvolver  = 'multiscale'" in script
        assert "scales       = [0, 5, 15]" in script
        assert not any("no scales" in w or "ignored: deconvolver" in w for w in warnings)

    def test_scales_ignored_for_hogbom_with_warning(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(tmp_path, real_ms_calibrated, scales=[0, 5])
        assert "scales       =" not in script
        assert any("scales=[0, 5] ignored" in w for w in warnings)

    def test_multiscale_without_scales_warns(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated, deconvolver="multiscale")
        assert any("no scales" in w for w in warnings)

    def test_asp_warns_cost(self, tmp_path, real_ms_calibrated):
        script, warnings = _run(tmp_path, real_ms_calibrated, deconvolver="asp")
        assert "deconvolver  = 'asp'" in script
        assert any("'asp' is expensive" in w for w in warnings)

    def test_hogbom_no_scale_or_asp_warning(self, tmp_path, real_ms_calibrated):
        _, warnings = _run(tmp_path, real_ms_calibrated)
        assert not any(
            "no scales" in w or "ignored: deconvolver" in w or "is expensive" in w for w in warnings
        )


class TestMtmfsNtermsAndPathguard:
    """CR-4 & CR-11b: mtmfs default nterms=None -> .image.tt0, nterms=1 -> .image, and imagename pathguard."""

    def test_mtmfs_nterms_none_records_tt0(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, deconvolver="mtmfs", nterms=None)
        assert '_image = imagename + (".image.tt0" if True else ".image")' in script
        assert "nterms       =" not in script

    def test_mtmfs_nterms_two_records_tt0(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, deconvolver="mtmfs", nterms=2)
        assert '_image = imagename + (".image.tt0" if True else ".image")' in script
        assert "nterms       = 2," in script

    def test_mtmfs_nterms_one_records_plain_image(self, tmp_path, real_ms_calibrated):
        script, _ = _run(tmp_path, real_ms_calibrated, deconvolver="mtmfs", nterms=1)
        assert '_image = imagename + (".image.tt0" if False else ".image")' in script
        assert "nterms       = 1," in script

    def test_execute_mtmfs_nterms_none_checks_tt0(self, tmp_path, real_ms_calibrated, monkeypatch):
        import casatasks

        from ms_modify.tclean import run

        workdir = tmp_path / "work_exec"
        workdir.mkdir()
        img_prefix = workdir / "mtmfs_default"

        def fake_tclean(**kwargs):
            # CASA default nterms=2 writes .image.tt0, NOT .image
            (Path(kwargs["imagename"] + ".image.tt0")).mkdir()
            return {"stopcode": 2}

        monkeypatch.setattr(casatasks, "tclean", fake_tclean)
        res = run(
            real_ms_calibrated,
            str(img_prefix),
            field="0",
            deconvolver="mtmfs",
            nterms=None,
            workdir=str(workdir),
            execute=True,
        )
        assert res["status"] == "ok"
        assert res["data"]["completed"]["value"] is True

    def test_imagename_outside_or_equal_to_workdir_refused(self, tmp_path, real_ms_calibrated):
        from ms_inspect.exceptions import ComputationError
        from ms_modify.tclean import run

        workdir = tmp_path / "work_guard"
        workdir.mkdir()
        outside = tmp_path / "outside_img"

        with pytest.raises(ComputationError, match="not inside workdir"):
            run(
                real_ms_calibrated,
                str(outside),
                field="0",
                workdir=str(workdir),
                execute=False,
            )
        with pytest.raises(ComputationError, match="equals workdir"):
            run(
                real_ms_calibrated,
                str(workdir),
                field="0",
                workdir=str(workdir),
                execute=False,
            )
        # Ensure no script was written on refused calls
        assert list(workdir.glob("tclean_*.py")) == []

    def test_phasecenter_and_outlierfile_written_to_script(self, tmp_path, real_ms_calibrated):
        from ms_inspect.exceptions import ComputationError
        from ms_modify.tclean import run

        workdir = tmp_path / "work_peel"
        workdir.mkdir()
        outlier = workdir / "outliers.txt"
        outlier.write_text(
            "imagename=out1\nimsize=[128,128]\nphasecenter=J2000 03h30m26.21s +30d03m44.6s\n"
        )

        res = run(
            real_ms_calibrated,
            str(workdir / "peel_src"),
            field="0",
            deconvolver="mtmfs",
            nterms=2,
            gridder="standard",
            phasecenter="J2000 03h30m26.21s +30d03m44.6s",
            outlierfile=str(outlier),
            workdir=str(workdir),
            execute=False,
        )
        assert res["status"] == "ok"
        script = Path(res["data"]["script_path"]["value"]).read_text()
        assert "phasecenter  = 'J2000 03h30m26.21s +30d03m44.6s'" in script
        assert f"outlierfile  = {str(outlier.resolve())!r}" in script

        with pytest.raises(ComputationError, match="outlierfile does not exist"):
            run(
                real_ms_calibrated,
                str(workdir / "peel_missing"),
                field="0",
                outlierfile=str(workdir / "does_not_exist.txt"),
                workdir=str(workdir),
                execute=False,
            )

        # gridder='mosaic' + outlierfile missing gridder=standard warns against MosaicFTNew abort
        res_warn = run(
            real_ms_calibrated,
            str(workdir / "mosaic_out_warn"),
            field="0",
            gridder="mosaic",
            pblimit=-0.01,
            pbmask=0.1,
            outlierfile=str(outlier),
            workdir=str(workdir),
            execute=False,
        )
        assert any("MosaicFTNew" in w for w in res_warn["warnings"])

    def test_preflight_warning_when_applycal_target_lacks_spectrum_check(
        self, tmp_path, real_ms_calibrated
    ):
        from ms_inspect.util.stage_log import record_stage
        from ms_modify.tclean import run

        workdir = tmp_path / "work_postcal_warn"
        workdir.mkdir()

        # No stage_log yet (standalone imaging): no missing-spectrum warning.
        res_standalone = run(
            real_ms_calibrated,
            str(workdir / "standalone_img"),
            field="0",
            workdir=str(workdir),
            execute=False,
        )
        assert not any(
            "Pre-imaging target spectrum check missing" in w for w in res_standalone["warnings"]
        )

        # After applycal on target MS without subsequent spectrum check: warning fires.
        record_stage(str(workdir), "applycal", real_ms_calibrated, {"field": "0"})
        res_unverified = run(
            real_ms_calibrated,
            str(workdir / "unverified_img"),
            field="0",
            workdir=str(workdir),
            execute=False,
        )
        assert any(
            "Pre-imaging target spectrum check missing" in w for w in res_unverified["warnings"]
        )

        # Once ms_spw_amp_severity (CORRECTED_DATA) runs on target MS: warning clears.
        record_stage(
            str(workdir),
            "spw_amp_severity",
            real_ms_calibrated,
            {"datacolumn": "CORRECTED_DATA", "field": "0"},
        )
        res_verified = run(
            real_ms_calibrated,
            str(workdir / "verified_img"),
            field="0",
            workdir=str(workdir),
            execute=False,
        )
        assert not any(
            "Pre-imaging target spectrum check missing" in w for w in res_verified["warnings"]
        )
