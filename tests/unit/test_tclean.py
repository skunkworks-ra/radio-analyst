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


class TestTcleanHygieneAndArchive:
    def test_next_script_path_versions_retries_without_clobber(self, tmp_path, real_ms_calibrated):
        from ms_modify.tclean import run

        wd = tmp_path / "work"
        wd.mkdir()
        r1 = run(real_ms_calibrated, str(wd / "mos"), field="0", workdir=str(wd), execute=False)
        r2 = run(real_ms_calibrated, str(wd / "mos"), field="0", workdir=str(wd), execute=False)
        p1 = Path(r1["data"]["script_path"]["value"])
        p2 = Path(r2["data"]["script_path"]["value"])
        assert p1.name == "tclean_mos.py"
        assert p2.name == "tclean_mos_2.py"
        assert p1.is_file() and p2.is_file()

    def test_spw_normalization_and_param_validation(self, tmp_path, real_ms_calibrated):
        from ms_inspect.exceptions import ComputationError
        from ms_modify.tclean import run

        wd = tmp_path / "work"
        wd.mkdir()

        res = run(
            real_ms_calibrated,
            str(wd / "spw_list"),
            field="0",
            spw="[0, 1]",
            savemodel="none",
            imsize=[256],
            workdir=str(wd),
            execute=False,
        )
        script = Path(res["data"]["script_path"]["value"]).read_text()
        assert "spw          = '0,1'," in script
        assert "savemodel    = 'none'," in script
        assert "imsize       = [256]," in script

        res_semi = run(
            real_ms_calibrated,
            str(wd / "spw_semi"),
            field="0",
            spw="0;1",
            workdir=str(wd),
            execute=False,
        )
        script_semi = Path(res_semi["data"]["script_path"]["value"]).read_text()
        assert "spw          = '0,1'," in script_semi
        assert "savemodel    = 'modelcolumn'," in script_semi

        with pytest.raises(ComputationError, match="Unsupported savemodel"):
            run(
                real_ms_calibrated,
                str(wd / "bad_sm"),
                field="0",
                savemodel="invalid",
                workdir=str(wd),
                execute=False,
            )

        for bad_imsize in ([], [0, 512], [-128, 128], [64, 64, 64], [True, 64]):
            with pytest.raises(ComputationError, match="imsize"):
                run(
                    real_ms_calibrated,
                    str(wd / "bad_im"),
                    field="0",
                    imsize=bad_imsize,
                    workdir=str(wd),
                    execute=False,
                )

    def test_atomic_archive_moves_products_preserves_mask_and_guards_ms(self, tmp_path):
        from ms_modify.tclean import _archive_tclean_products

        wd = tmp_path / "work"
        wd.mkdir()
        img = str(wd / "mos")
        (wd / "mos.image.tt0").mkdir()
        (wd / "mos.pb.tt0").mkdir()
        (wd / "mos.alpha").mkdir()
        (wd / "mos.beta").mkdir()
        (wd / "mos.alpha.error").mkdir()
        (wd / "mos.mask").mkdir()
        (wd / "mos.notes.txt").write_text("unrelated")

        moved1 = _archive_tclean_products(str(wd), img, input_mask=str(wd / "mos.mask"))
        assert (wd / "mos.mask").is_dir()  # input mask preserved
        assert (wd / "mos.notes.txt").is_file()  # non-product preserved
        for suf in (".image.tt0", ".pb.tt0", ".alpha", ".beta", ".alpha.error"):
            assert not (wd / f"mos{suf}").exists()
            dst = wd / "rejected" / f"mos.attempt1{suf}"
            assert dst.is_dir()
            assert moved1[str(wd / f"mos{suf}")] == str(dst)

        # Second archive increments attempt number cleanly.
        (wd / "mos.image.tt0").mkdir()
        moved2 = _archive_tclean_products(str(wd), img)
        assert moved2[str(wd / "mos.image.tt0")] == str(wd / "rejected" / "mos.attempt2.image.tt0")

        # MS table.info guard refuses to touch a Measurement Set.
        fake_ms_prod = wd / "mos.image"
        fake_ms_prod.mkdir()
        (fake_ms_prod / "table.info").write_text("Type = Measurement Set\n")
        with pytest.raises(RuntimeError, match="Measurement Set"):
            _archive_tclean_products(str(wd), img)
        assert fake_ms_prod.is_dir()

    def test_execute_prearchives_and_auto_quarantines_only_diverged_runs(
        self, tmp_path, real_ms_calibrated, monkeypatch
    ):
        import sys
        import types

        from ms_inspect.util.stage_log import completed_stages, read_stage_log
        from ms_modify.tclean import run

        # 1. stopcode=5 with niter>0: pre-archives prior attempt, then auto-quarantines
        #    diverged output into rejected/ and records original path (exists=False) in stage_log.
        wd_div = tmp_path / "work_div"
        wd_div.mkdir()
        (wd_div / "mos.image.tt0").mkdir()
        (wd_div / "mos.residual.tt0").mkdir()

        def fake_tclean_div(**kwargs):
            (Path(kwargs["imagename"] + ".image.tt0")).mkdir()
            (Path(kwargs["imagename"] + ".pb.tt0")).mkdir()
            (Path(kwargs["imagename"] + ".alpha")).mkdir()
            return {"stopcode": 5}

        monkeypatch.setitem(sys.modules, "casatasks", types.SimpleNamespace(tclean=fake_tclean_div))
        res_div = run(
            real_ms_calibrated,
            str(wd_div / "mos"),
            field="0",
            deconvolver="mtmfs",
            nterms=2,
            niter=1000,
            workdir=str(wd_div),
            execute=True,
        )
        assert res_div["status"] == "ok"
        assert res_div["data"]["converged"]["value"] is False
        assert res_div["data"]["stopcode"]["value"] == 5
        # Prior attempt archived as attempt1; diverged run quarantined as attempt2.
        assert (wd_div / "rejected" / "mos.attempt1.image.tt0").is_dir()
        q_img = wd_div / "rejected" / "mos.attempt2.image.tt0"
        assert q_img.is_dir()
        assert (wd_div / "rejected" / "mos.attempt2.alpha").is_dir()
        assert res_div["data"]["quarantined_to"]["value"] == str(q_img)
        # Top-level image no longer exists -> stage_log marks exists=False -> NOT completed!
        assert not (wd_div / "mos.image.tt0").exists()
        entries = read_stage_log(wd_div)
        assert len(entries) == 1
        assert entries[0]["product"] == str(wd_div / "mos.image.tt0")
        assert entries[0]["exists"] is False
        assert entries[0]["measurement"]["quarantined_to"] == str(q_img)
        assert entries[0]["measurement"]["stopcode"] == 5
        assert "tclean" not in completed_stages(entries)

        # 2. stopcode=1 (hit niter) is NOT quarantined.
        wd_niter = tmp_path / "work_niter"
        wd_niter.mkdir()

        def fake_tclean_stop1(**kwargs):
            (Path(kwargs["imagename"] + ".image")).mkdir()
            return {"stopcode": 1}

        monkeypatch.setitem(
            sys.modules, "casatasks", types.SimpleNamespace(tclean=fake_tclean_stop1)
        )
        res_s1 = run(
            real_ms_calibrated,
            str(wd_niter / "img"),
            field="0",
            niter=100,
            workdir=str(wd_niter),
            execute=True,
        )
        assert (wd_niter / "img.image").is_dir()
        assert not (wd_niter / "rejected").exists()
        assert "quarantined_to" not in res_s1["data"]

        # 3. niter=0 is NEVER quarantined (even if stopcode were 5/6).
        wd_dirty = tmp_path / "work_dirty"
        wd_dirty.mkdir()
        monkeypatch.setitem(
            sys.modules,
            "casatasks",
            types.SimpleNamespace(
                tclean=lambda **kw: (Path(kw["imagename"] + ".image").mkdir(), {"stopcode": 5})[1]
            ),
        )
        run(
            real_ms_calibrated,
            str(wd_dirty / "dirty"),
            field="0",
            niter=0,
            workdir=str(wd_dirty),
            execute=True,
        )
        assert (wd_dirty / "dirty.image").is_dir()
        assert not (wd_dirty / "rejected").exists()

    def test_generated_script_quarantines_diverged_stopcode6(
        self, tmp_path, real_ms_calibrated, monkeypatch
    ):
        import sys
        import types

        from ms_inspect.util.stage_log import completed_stages, read_stage_log
        from ms_modify.tclean import run

        wd = tmp_path / "work_script_div"
        wd.mkdir()
        res = run(
            real_ms_calibrated,
            str(wd / "img"),
            field="0",
            niter=500,
            workdir=str(wd),
            execute=False,
        )
        script_path = Path(res["data"]["script_path"]["value"])

        def fake_tclean(**kwargs):
            (Path(kwargs["imagename"] + ".image")).mkdir()
            (Path(kwargs["imagename"] + ".pb")).mkdir()
            return {"stopcode": 6}

        monkeypatch.setitem(sys.modules, "casatasks", types.SimpleNamespace(tclean=fake_tclean))
        ns: dict = {}
        exec(compile(script_path.read_text(), str(script_path), "exec"), ns)

        assert not (wd / "img.image").exists()
        q_img = wd / "rejected" / "img.attempt1.image"
        assert q_img.is_dir()
        assert (wd / "rejected" / "img.attempt1.pb").is_dir()
        entries = read_stage_log(wd)
        assert len(entries) == 1
        assert entries[0]["product"] == str(wd / "img.image")
        assert entries[0]["exists"] is False
        assert entries[0]["measurement"]["quarantined_to"] == str(q_img)
        assert "tclean" not in completed_stages(entries)


class TestTcleanGeometryAndProvenanceWarnings:
    def test_mosaic_wildcard_phasecenter_ra_wrap_and_fov_warnings(
        self, tmp_path, real_ms_calibrated_copy
    ):
        import math

        import numpy as np

        from ms_inspect.util.casa_context import open_table
        from ms_modify.tclean import run

        # Add 4 mosaic pointings PER_FIELD_1..4 wrapping across RA=0h (359.5 deg .. 0.5 deg)
        # and Dec=+30.0 deg .. +31.0 deg (1 deg x 1 deg span).
        with open_table(str(Path(real_ms_calibrated_copy) / "FIELD"), read_only=False) as tb:
            orig_n = tb.nrows()
            base_dir = tb.getcell("PHASE_DIR", 0)
            base_time = tb.getcell("TIME", 0)
            pointings = [
                ("PER_FIELD_1", 359.5, 30.0),
                ("PER_FIELD_2", 359.8, 30.3),
                ("PER_FIELD_3", 0.2, 30.7),
                ("PER_FIELD_4", 0.5, 31.0),
            ]
            tb.addrows(len(pointings))
            for k, (name, ra_deg, dec_deg) in enumerate(pointings):
                row = orig_n + k
                pdir = np.array(base_dir, copy=True)
                pdir[0, 0] = math.radians(ra_deg)
                pdir[1, 0] = math.radians(dec_deg)
                tb.putcell("NAME", row, name)
                tb.putcell("CODE", row, "")
                tb.putcell("TIME", row, base_time)
                tb.putcell("NUM_POLY", row, 0)
                tb.putcell("DELAY_DIR", row, pdir)
                tb.putcell("PHASE_DIR", row, pdir)
                tb.putcell("REFERENCE_DIR", row, pdir)
                tb.putcell("SOURCE_ID", row, 50)
                tb.putcell("FLAG_ROW", row, False)

        wd = tmp_path / "work"
        wd.mkdir()

        # 1. Wildcard PER_FIELD_* with gridder='standard' must trigger multi-field warning!
        res_std = run(
            real_ms_calibrated_copy,
            str(wd / "std_wild"),
            field="PER_FIELD_*",
            gridder="standard",
            workdir=str(wd),
            execute=False,
        )
        assert any("gridder='standard'" in w for w in res_std["warnings"])
        # gridder='standard' skips mosaic FOV check.
        assert not any("Mosaic/PB FOV check" in w for w in res_std["warnings"])

        # 2. gridder='mosaic' with phasecenter='' warns with exact circular-unwrapped bbox
        #    midpoint (RA=00h00m00.00s, Dec=+30d30m00.0s!) and first_field_offset_arcmin,
        #    AND flags undersized FOV.
        res_mos = run(
            real_ms_calibrated_copy,
            str(wd / "mos_bad"),
            field="PER_FIELD_*",
            gridder="mosaic",
            phasecenter="",
            cell="4.0arcsec",
            imsize=[1024, 1024],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert any(
            "J2000 00h00m00.00s +30d30m00.0s" in w and "arcmin" in w for w in res_mos["warnings"]
        )
        assert not any("np.str_" in w for w in res_mos["warnings"])
        assert any("Mosaic/PB FOV check" in w and "(centered)" in w for w in res_mos["warnings"])

        # 3. Centered phasecenter + full extent + 4 * PB_FWHM clears both warnings!
        #    At min_freq ~ 1.0 GHz (25m dish), PB_FWHM ~ 42.1'; extent 60' + 4 * 42.1' = 228.4'
        #    -> ~3426 px at 4" (so 3600x3600 clears 4 * PB_FWHM cleanly).
        res_good = run(
            real_ms_calibrated_copy,
            str(wd / "mos_good"),
            field="PER_FIELD_*",
            gridder="mosaic",
            phasecenter="J2000 00h00m00.00s +30d30m00.0s",
            cell="4.0arcsec",
            imsize=[3600, 3600],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("defaults phasecenter" in w for w in res_good["warnings"])
        assert not any("Mosaic/PB FOV check" in w for w in res_good["warnings"])

        # 4. Baby-peel cutout (max(imsize) <= 256) skips mosaic FOV check.
        res_peel = run(
            real_ms_calibrated_copy,
            str(wd / "mos_peel"),
            field="PER_FIELD_*",
            gridder="mosaic",
            phasecenter="J2000 00h00m00.00s +30d30m00.0s",
            cell="4.0arcsec",
            imsize=[256, 256],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("Mosaic/PB FOV check" in w for w in res_peel["warnings"])

        # 5. Off-axis outlier cutout (> 256 px, e.g. 512x512) centered outside the mosaic
        #    footprint (~2.1 deg east of bbox center) must NOT emit a mosaic FOV warning.
        res_offaxis = run(
            real_ms_calibrated_copy,
            str(wd / "mos_offaxis_512"),
            field="PER_FIELD_*",
            gridder="mosaic",
            phasecenter="J2000 00h10m00.00s +30d30m00.0s",
            cell="4.0arcsec",
            imsize=[512, 512],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("Mosaic/PB FOV check" in w for w in res_offaxis["warnings"])

    def test_nyquist_spw_provenance_and_live_pid_warnings(self, tmp_path, real_ms_calibrated):
        import os
        import signal
        import subprocess
        import sys
        import time

        from ms_inspect.util.stage_log import record_stage
        from ms_modify.tclean import run

        wd = tmp_path / "work"
        wd.mkdir()

        # 1. Nyquist advisory fires for grossly coarse cell, stays silent for fine cell.
        res_coarse = run(
            real_ms_calibrated,
            str(wd / "coarse"),
            field="0",
            cell="300arcsec",
            workdir=str(wd),
            execute=False,
        )
        assert any(
            "Nyquist cell advisory" in w and "foreshortening" in w for w in res_coarse["warnings"]
        )

        res_fine = run(
            real_ms_calibrated,
            str(wd / "fine"),
            field="0",
            cell="1.0arcsec",
            workdir=str(wd),
            execute=False,
        )
        assert not any("Nyquist cell advisory" in w for w in res_fine["warnings"])

        # 2. SPW provenance warning when stage_log spw_amp_severity verified a narrower spw.
        record_stage(
            str(wd),
            "spw_amp_severity",
            real_ms_calibrated,
            {"datacolumn": "CORRECTED_DATA", "spw": "0"},
        )
        res_wider = run(
            real_ms_calibrated,
            str(wd / "wider_spw"),
            field="0",
            spw="0,1",
            workdir=str(wd),
            execute=False,
        )
        assert any("SPW provenance mismatch" in w for w in res_wider["warnings"])

        res_all = run(
            real_ms_calibrated,
            str(wd / "all_spw"),
            field="0",
            spw="",
            workdir=str(wd),
            execute=False,
        )
        assert any("SPW provenance mismatch" in w for w in res_all["warnings"])

        res_sub = run(
            real_ms_calibrated,
            str(wd / "sub_spw"),
            field="0",
            spw="0",
            workdir=str(wd),
            execute=False,
        )
        assert not any("SPW provenance mismatch" in w for w in res_sub["warnings"])

        # 3. Live tclean_*.py.pid warning (alive without .rc warns; with .rc or dead PID silent).
        live_pid_file = wd / "tclean_other.py.pid"
        live_pid_file.write_text(f"{os.getpid()}\n")
        res_live = run(
            real_ms_calibrated,
            str(wd / "live_check"),
            field="0",
            spw="0",
            workdir=str(wd),
            execute=False,
        )
        assert any(
            "Live tclean job detected" in w and "tclean_other.py" in w for w in res_live["warnings"]
        )

        # Adding .rc clears the live-PID warning (completed unharvested job).
        (wd / "tclean_other.py.rc").write_text("0\n")
        res_done = run(
            real_ms_calibrated,
            str(wd / "done_check"),
            field="0",
            spw="0",
            workdir=str(wd),
            execute=False,
        )
        assert not any("Live tclean job detected" in w for w in res_done["warnings"])

        # Dead PID without .rc does NOT trigger live-PID warning.
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        victim.send_signal(signal.SIGKILL)
        victim.wait(timeout=5)
        time.sleep(0.05)
        (wd / "tclean_dead.py.pid").write_text(f"{victim.pid}\n")
        res_dead = run(
            real_ms_calibrated,
            str(wd / "dead_check"),
            field="0",
            spw="0",
            workdir=str(wd),
            execute=False,
        )
        assert not any("Live tclean job detected" in w for w in res_dead["warnings"])

    def test_heterogeneous_dish_diameter_uses_smallest_dish_and_tapered_pb(
        self, tmp_path, real_ms_calibrated_copy
    ):
        import math

        import numpy as np

        from ms_inspect.util.casa_context import open_table
        from ms_inspect.util.conversions import angular_resolution_arcsec
        from ms_modify.tclean import run

        with open_table(str(Path(real_ms_calibrated_copy) / "FIELD"), read_only=False) as tb:
            orig_n = tb.nrows()
            base_dir = tb.getcell("PHASE_DIR", 0)
            base_time = tb.getcell("TIME", 0)
            pointings = [
                ("HET_1", 150.0, 30.0),
                ("HET_2", 150.0, 30.5),
            ]
            tb.addrows(len(pointings))
            for k, (name, ra_deg, dec_deg) in enumerate(pointings):
                row = orig_n + k
                pdir = np.array(base_dir, copy=True)
                pdir[0, 0] = math.radians(ra_deg)
                pdir[1, 0] = math.radians(dec_deg)
                tb.putcell("NAME", row, name)
                tb.putcell("CODE", row, "")
                tb.putcell("TIME", row, base_time)
                tb.putcell("NUM_POLY", row, 0)
                tb.putcell("DELAY_DIR", row, pdir)
                tb.putcell("PHASE_DIR", row, pdir)
                tb.putcell("REFERENCE_DIR", row, pdir)
                tb.putcell("SOURCE_ID", row, 60)
                tb.putcell("FLAG_ROW", row, False)

        # Heterogeneous array: majority 12 m dishes plus one 7 m dish (median=12 m, min=7 m).
        with open_table(str(Path(real_ms_calibrated_copy) / "ANTENNA"), read_only=False) as tb:
            diams = [12.0] * tb.nrows()
            diams[-1] = 7.0
            tb.putcol("DISH_DIAMETER", np.asarray(diams, dtype=float))

        with open_table(str(Path(real_ms_calibrated_copy) / "SPECTRAL_WINDOW")) as tb:
            min_freq_hz = min(
                float(np.min(np.asarray(tb.getcell("CHAN_FREQ", sid), dtype=float)))
                for sid in range(tb.nrows())
            )

        pb_7m_arcmin = 1.15 * angular_resolution_arcsec(7.0, min_freq_hz) / 60.0
        pb_12m_arcmin = 1.15 * angular_resolution_arcsec(12.0, min_freq_hz) / 60.0

        wd = tmp_path / "work_het"
        wd.mkdir()

        # FOV = 450' clears 12 m (30' + 3.6 * pb_12m ~ 386') but is below 7 m (30' + 3.6 * pb_7m).
        res = run(
            real_ms_calibrated_copy,
            str(wd / "het_mos"),
            field="HET_*",
            gridder="mosaic",
            phasecenter="J2000 10h00m00.00s +30d15m00.0s",
            cell="60arcsec",
            imsize=[450, 450],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        fov_warns = [w for w in res["warnings"] if "Mosaic/PB FOV check" in w]
        assert fov_warns
        assert f"PB_FWHM={pb_7m_arcmin:.1f}'" in fov_warns[0]
        assert f"PB_FWHM={pb_12m_arcmin:.1f}'" not in fov_warns[0]

    def test_colocated_multi_eb_fields_do_not_trigger_mosaic_warnings(
        self, tmp_path, real_ms_calibrated_copy
    ):
        import math

        import numpy as np

        from ms_inspect.util.casa_context import open_table
        from ms_modify.tclean import run

        with open_table(str(Path(real_ms_calibrated_copy) / "FIELD"), read_only=False) as tb:
            orig_n = tb.nrows()
            base_dir = tb.getcell("PHASE_DIR", 0)
            base_time = tb.getcell("TIME", 0)
            tb.addrows(2)
            for k, name in enumerate(("MULTIEB_1", "MULTIEB_2")):
                row = orig_n + k
                pdir = np.array(base_dir, copy=True)
                pdir[0, 0] = math.radians(150.0)
                pdir[1, 0] = math.radians(30.0)
                tb.putcell("NAME", row, name)
                tb.putcell("CODE", row, "")
                tb.putcell("TIME", row, base_time)
                tb.putcell("NUM_POLY", row, 0)
                tb.putcell("DELAY_DIR", row, pdir)
                tb.putcell("PHASE_DIR", row, pdir)
                tb.putcell("REFERENCE_DIR", row, pdir)
                tb.putcell("SOURCE_ID", row, 61)
                tb.putcell("FLAG_ROW", row, False)

        wd = tmp_path / "work_coloc"
        wd.mkdir()

        res_std = run(
            real_ms_calibrated_copy,
            str(wd / "coloc_std"),
            field="MULTIEB_*",
            gridder="standard",
            phasecenter="",
            cell="4.0arcsec",
            imsize=[512, 512],
            workdir=str(wd),
            execute=False,
        )
        assert not any("gridder='standard'" in w for w in res_std["warnings"])

        res_mos = run(
            real_ms_calibrated_copy,
            str(wd / "coloc_mos"),
            field="MULTIEB_*",
            gridder="mosaic",
            phasecenter="",
            cell="4.0arcsec",
            imsize=[512, 512],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("defaults phasecenter" in w for w in res_mos["warnings"])
        assert not any("Mosaic/PB FOV check" in w for w in res_mos["warnings"])

    def test_sky_angle_cutout_replaces_256px_magic_number(self, tmp_path, real_ms_calibrated_copy):
        import math

        import numpy as np

        from ms_inspect.util.casa_context import open_table
        from ms_modify.tclean import run

        with open_table(str(Path(real_ms_calibrated_copy) / "FIELD"), read_only=False) as tb:
            orig_n = tb.nrows()
            base_dir = tb.getcell("PHASE_DIR", 0)
            base_time = tb.getcell("TIME", 0)
            pointings = [
                ("CMP_1", 150.0, 30.0),
                ("CMP_2", 150.0, 30.5),
            ]
            tb.addrows(len(pointings))
            for k, (name, ra_deg, dec_deg) in enumerate(pointings):
                row = orig_n + k
                pdir = np.array(base_dir, copy=True)
                pdir[0, 0] = math.radians(ra_deg)
                pdir[1, 0] = math.radians(dec_deg)
                tb.putcell("NAME", row, name)
                tb.putcell("CODE", row, "")
                tb.putcell("TIME", row, base_time)
                tb.putcell("NUM_POLY", row, 0)
                tb.putcell("DELAY_DIR", row, pdir)
                tb.putcell("PHASE_DIR", row, pdir)
                tb.putcell("REFERENCE_DIR", row, pdir)
                tb.putcell("SOURCE_ID", row, 62)
                tb.putcell("FLAG_ROW", row, False)

        wd = tmp_path / "work_cutout"
        wd.mkdir()
        center = "J2000 10h00m00.00s +30d15m00.0s"

        # 1. Compact-array mosaic (imsize=192 <= 256, but FOV = 192 * 40" = 128' >= 1.5 * PB ~ 71')
        #    MUST still get both gridder='standard' and Mosaic/PB FOV checks.
        res_cmp_std = run(
            real_ms_calibrated_copy,
            str(wd / "cmp_std"),
            field="CMP_*",
            gridder="standard",
            phasecenter=center,
            cell="40arcsec",
            imsize=[192, 192],
            workdir=str(wd),
            execute=False,
        )
        assert any("gridder='standard'" in w for w in res_cmp_std["warnings"])

        res_cmp_mos = run(
            real_ms_calibrated_copy,
            str(wd / "cmp_mos"),
            field="CMP_*",
            gridder="mosaic",
            phasecenter=center,
            cell="40arcsec",
            imsize=[192, 192],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert any("Mosaic/PB FOV check" in w for w in res_cmp_mos["warnings"])

        # 2. High-res small-angle cutout (512x512 > 256, but FOV = 512 * 2" = 17.1' < 1.5 * PB)
        #    MUST skip both gridder='standard' and Mosaic/PB FOV checks.
        res_cut_std = run(
            real_ms_calibrated_copy,
            str(wd / "cut_std"),
            field="CMP_*",
            gridder="standard",
            phasecenter=center,
            cell="2.0arcsec",
            imsize=[512, 512],
            workdir=str(wd),
            execute=False,
        )
        assert not any("gridder='standard'" in w for w in res_cut_std["warnings"])

        res_cut_mos = run(
            real_ms_calibrated_copy,
            str(wd / "cut_mos"),
            field="CMP_*",
            gridder="mosaic",
            phasecenter=center,
            cell="2.0arcsec",
            imsize=[512, 512],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("Mosaic/PB FOV check" in w for w in res_cut_mos["warnings"])

    def test_subband_cube_uses_cube_frequency_bounds_instead_of_full_spw(
        self, tmp_path, real_ms_calibrated_copy
    ):
        import math

        import numpy as np

        from ms_inspect.util.casa_context import open_table
        from ms_inspect.util.conversions import angular_resolution_arcsec
        from ms_modify.tclean import run

        # Wideband SPW 0 spanning 856-1712 MHz.
        with open_table(
            str(Path(real_ms_calibrated_copy) / "SPECTRAL_WINDOW"), read_only=False
        ) as tb:
            n_ch = len(tb.getcell("CHAN_FREQ", 0))
            tb.putcell("CHAN_FREQ", 0, np.linspace(856e6, 1712e6, n_ch))

        with open_table(str(Path(real_ms_calibrated_copy) / "FIELD"), read_only=False) as tb:
            orig_n = tb.nrows()
            base_dir = tb.getcell("PHASE_DIR", 0)
            base_time = tb.getcell("TIME", 0)
            pointings = [
                ("HI_1", 150.0, 30.0),
                ("HI_2", 150.0, 30.5),
            ]
            tb.addrows(len(pointings))
            for k, (name, ra_deg, dec_deg) in enumerate(pointings):
                row = orig_n + k
                pdir = np.array(base_dir, copy=True)
                pdir[0, 0] = math.radians(ra_deg)
                pdir[1, 0] = math.radians(dec_deg)
                tb.putcell("NAME", row, name)
                tb.putcell("CODE", row, "")
                tb.putcell("TIME", row, base_time)
                tb.putcell("NUM_POLY", row, 0)
                tb.putcell("DELAY_DIR", row, pdir)
                tb.putcell("PHASE_DIR", row, pdir)
                tb.putcell("REFERENCE_DIR", row, pdir)
                tb.putcell("SOURCE_ID", row, 63)
                tb.putcell("FLAG_ROW", row, False)

        wd = tmp_path / "work_cube_bounds"
        wd.mkdir()
        center = "J2000 10h00m00.00s +30d15m00.0s"
        pb_1418_arcmin = 1.15 * angular_resolution_arcsec(25.0, 1418e6) / 60.0

        # 1. Undersized mosaic sub-band cube reports min_freq=1.418 GHz (not 0.856 GHz).
        res_fov = run(
            real_ms_calibrated_copy,
            str(wd / "cube_fov_warn"),
            field="HI_*",
            spw="0",
            specmode="cube",
            start="1418MHz",
            width="0.1MHz",
            nchan=40,
            gridder="mosaic",
            phasecenter=center,
            cell="30arcsec",
            imsize=[200, 200],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        fov_warns = [w for w in res_fov["warnings"] if "Mosaic/PB FOV check" in w]
        assert fov_warns
        assert "min_freq=1.418 GHz" in fov_warns[0]
        assert f"PB_FWHM={pb_1418_arcmin:.1f}'" in fov_warns[0]
        assert "0.856 GHz" not in fov_warns[0]

        # 2. FOV = 160' clears 30' + 3.6 * PB(1418 MHz) (~150') even though it would fail at 856 MHz (~229').
        res_fov_ok = run(
            real_ms_calibrated_copy,
            str(wd / "cube_fov_ok"),
            field="HI_*",
            spw="0",
            specmode="cube",
            start="1418MHz",
            width="0.1MHz",
            nchan=40,
            gridder="mosaic",
            phasecenter=center,
            cell="30arcsec",
            imsize=[320, 320],
            pblimit=-0.01,
            pbmask=0.1,
            nsigma=5.0,
            workdir=str(wd),
            execute=False,
        )
        assert not any("Mosaic/PB FOV check" in w for w in res_fov_ok["warnings"])

        # 3. Nyquist check uses max_freq=1.422 GHz (not 1.712 GHz), including negative width.
        res_nyq = run(
            real_ms_calibrated_copy,
            str(wd / "cube_nyq"),
            field="0",
            spw="0",
            specmode="cube",
            start="1418MHz",
            width="0.1MHz",
            nchan=40,
            cell="300arcsec",
            workdir=str(wd),
            execute=False,
        )
        nyq_warns = [w for w in res_nyq["warnings"] if "Nyquist cell advisory" in w]
        assert nyq_warns
        assert "max_freq=1.422 GHz" in nyq_warns[0]
        assert "1.712 GHz" not in nyq_warns[0]

        res_nyq_neg = run(
            real_ms_calibrated_copy,
            str(wd / "cube_nyq_neg"),
            field="0",
            spw="0",
            specmode="cube",
            start="1422MHz",
            width="-0.1MHz",
            nchan=40,
            cell="300arcsec",
            workdir=str(wd),
            execute=False,
        )
        nyq_neg_warns = [w for w in res_nyq_neg["warnings"] if "Nyquist cell advisory" in w]
        assert nyq_neg_warns and "max_freq=1.422 GHz" in nyq_neg_warns[0]

        # 4. Non-frequency (velocity) cube falls back to full SPW [0.856, 1.712] GHz.
        res_vel = run(
            real_ms_calibrated_copy,
            str(wd / "cube_vel"),
            field="0",
            spw="0",
            specmode="cube",
            start="10km/s",
            width="1km/s",
            nchan=40,
            cell="300arcsec",
            workdir=str(wd),
            execute=False,
        )
        vel_warns = [w for w in res_vel["warnings"] if "Nyquist cell advisory" in w]
        assert vel_warns and "max_freq=1.712 GHz" in vel_warns[0]
