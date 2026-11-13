"""
Unit tests for Waves 2--5 token, latency, and schema optimizations:

- Wave 2: CR-8 completeness_summary preservation across offload_detail and
  calsol_stats compact mode; symmetric field_flags (bare values in data,
  [*]/[a..b] array index collapsing, COMPLETE+note retention); wire provenance
  stripping with events.jsonl retention; mosaic pointing deduplication in
  ms_field_list; read-only MS/caltable parent (chmod 0o555) sidecar safety.
- Wave 3: bounded-wait scripts/plugin/run-step.sh (fast rc=0, fast rc!=0,
  status=running + idempotent re-attach, status=crashed on dead PID without .rc);
  auto-ledger derivation from stage_log.jsonl (deduplication, ms_postcal_flag,
  ms_setjy_polcal, ms_report without reduction_log.jsonl).
- Wave 4: ms_radiometer_estimate (analytic formula, weighting factors, mosaic
  median on_source_s, real MS); ms_vis_amp_time_stats (pure summary, multi-DDID
  real MS with injected outlier, all-flagged UNAVAILABLE); audit_hook.py
  transcript correlation and idempotency.
- Wave 5: stage_bundles ungranted-tool leak detection.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from ms_create import audit_hook, reduction_log, report
from ms_inspect.tools import (
    antennas,
    calsol_stats,
    fields,
    geometry,
    radiometer_estimate,
    residual_stats,
    scans,
    spw_amp_severity,
    vis_amp_time_stats,
)
from ms_inspect.util import dispatch
from ms_inspect.util.casa_context import open_table
from ms_inspect.util.formatting import (
    field as fmt_field,
)
from ms_inspect.util.formatting import (
    offload_detail,
    resolve_sidecar_path,
    response_envelope,
    unwrap_fields,
    wire_envelope,
)
from ms_inspect.util.stage_bundles import verify_bundle_tool_grants
from ms_modify import postcal_flag, setjy_polcal

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_STEP_SH = REPO_ROOT / "scripts" / "plugin" / "run-step.sh"


# ---------------------------------------------------------------------------
# Wave 2: CR-8 completeness_summary, symmetric field_flags, provenance strip
# ---------------------------------------------------------------------------


def test_offload_detail_preserves_worst_flag_and_field_flags(tmp_path: Path):
    sidecar = resolve_sidecar_path("demo.detail.json", str(tmp_path))
    assert sidecar is not None
    assert Path(sidecar).parent == (tmp_path / "sidecars").resolve()

    raw_data = {
        "n_items": fmt_field(2),
        "heavy_rows": [
            {"id": 0, "metric": fmt_field(1.25, flag="SUSPECT", note="borderline SNR")},
            {"id": 1, "metric": fmt_field(None, flag="UNAVAILABLE", note="all flagged")},
        ],
    }
    slim = offload_detail(raw_data, ["heavy_rows"], sidecar)
    env = response_envelope(
        tool_name="ms_demo",
        ms_path="/fake/demo.ms",
        data=slim,
        casa_calls=["tb.open()"],
    )
    # CR-8: offloaded UNAVAILABLE flag must govern completeness_summary even after slimming.
    assert env["completeness_summary"] == "UNAVAILABLE"
    assert Path(sidecar).is_file()
    saved = json.loads(Path(sidecar).read_text())
    assert len(saved["heavy_rows"]) == 2

    wire = wire_envelope(env)
    assert "provenance" not in wire
    assert wire["completeness_summary"] == "UNAVAILABLE"
    assert wire["data"]["n_items"] == 2
    assert "heavy_rows" not in wire["data"]
    assert wire["data"]["detail_path"] == sidecar
    assert wire["field_flags"]["heavy_rows[0].metric"]["flag"] == "SUSPECT"
    assert wire["field_flags"]["heavy_rows[1].metric"]["flag"] == "UNAVAILABLE"


def test_symmetric_field_flags_wildcards_ranges_and_notes():
    payload = {
        "clean_val": fmt_field(42.0),
        "noted_complete": fmt_field("VLA", flag="COMPLETE", note="resolved from OBSERVATION"),
        "uniform_list": [
            {"flux": fmt_field(1.0, flag="INFERRED", note="catalogue prior")} for _ in range(4)
        ],
        "range_list": [fmt_field(i, flag="PARTIAL" if i < 3 else "COMPLETE") for i in range(5)],
    }
    unwrapped, ff = unwrap_fields(payload)
    assert unwrapped["clean_val"] == 42.0
    assert unwrapped["noted_complete"] == "VLA"
    assert unwrapped["uniform_list"] == [{"flux": 1.0}, {"flux": 1.0}, {"flux": 1.0}, {"flux": 1.0}]
    assert unwrapped["range_list"] == [0, 1, 2, 3, 4]

    assert "clean_val" not in ff
    assert ff["noted_complete"] == {"flag": "COMPLETE", "note": "resolved from OBSERVATION"}
    assert ff["uniform_list[*].flux"] == {"flag": "INFERRED", "note": "catalogue prior"}
    assert ff["range_list[0..2]"] == {"flag": "PARTIAL"}


def test_calsol_stats_compact_preserves_unavailable_completeness_summary(
    real_caltable_copy: str,
):
    with open_table(real_caltable_copy, read_only=False) as tb:
        flg = tb.getcol("FLAG")
        tb.putcol("FLAG", np.ones_like(flg, dtype=bool))

    env = calsol_stats.run(real_caltable_copy, verbosity="compact")
    assert env["completeness_summary"] == "UNAVAILABLE"
    wire = wire_envelope(env)
    assert wire["completeness_summary"] == "UNAVAILABLE"
    assert wire["data"]["amp_median"] is None
    assert wire["field_flags"]["amp_median"]["flag"] == "UNAVAILABLE"


def test_dispatch_strips_wire_provenance_and_logs_to_events_jsonl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    real_ms_raw: str,
):
    monkeypatch.setenv("RADIO_MCP_DIR", str(tmp_path))
    res = asyncio.run(dispatch.run_tool(antennas.run_antenna_list, real_ms_raw, str(tmp_path)))
    assert not res.isError
    wire = json.loads(res.content[0].text)
    assert wire["status"] == "ok"
    assert "provenance" not in wire
    assert "field_flags" in wire
    assert isinstance(wire["data"]["dish_diameter_m"], float)
    assert wire["data"]["dish_diameter_m"] > 0

    events_file = (
        (tmp_path / "logs" / "events.jsonl")
        if (tmp_path / "logs" / "events.jsonl").is_file()
        else (tmp_path / "events.jsonl")
    )
    assert events_file.is_file()
    events = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
    assert events
    last = events[-1]
    assert "provenance" in last
    assert last["provenance"]["casa_calls"]


# ---------------------------------------------------------------------------
# Wave 2: Mosaic pointing deduplication & read-only MS/caltable parent safety
# ---------------------------------------------------------------------------


def _synthetic_mosaic_field_record(fid: int, name: str, source_id: int, ra_deg: float) -> dict:
    return {
        "field_id": fid,
        "name": name,
        "source_id": source_id,
        "ra_j2000_deg": fmt_field(ra_deg),
        "dec_j2000_deg": fmt_field(30.5),
        "intents": fmt_field(["OBSERVE_TARGET#ON_SOURCE"]),
        "observing_frequency": fmt_field(
            {"min_ghz": 1.0, "max_ghz": 2.0, "centre_ghz": 1.5, "n_spw": 2}
        ),
        "calibrator_match": fmt_field(None, flag="UNAVAILABLE"),
        "field_role": fmt_field(["target"]),
        "catalogue_role": fmt_field(None, flag="UNAVAILABLE"),
        "flux_standard": fmt_field(None, flag="UNAVAILABLE"),
        "flux_standard_range_checked": False,
        "resolved_source": fmt_field(None, flag="UNAVAILABLE"),
        "vla_cal_match": fmt_field(None, flag="UNAVAILABLE"),
        "vla_cal_flux_estimate": fmt_field(None, flag="UNAVAILABLE"),
        "pol_calibrator": fmt_field(None, flag="UNAVAILABLE"),
        "nearest_phase_cal": "J1331+3030",
        "separation_deg": 2.1,
    }


def test_mosaic_field_detection_and_real_ms_dedup(tmp_path: Path, real_ms_raw_copy: str):
    # 1. Pure grouping check across shared source_id and stem-matched pointings.
    recs = [
        {
            **_synthetic_mosaic_field_record(0, "3C147", 0, 85.65),
            "calibrator_match": fmt_field("3C147"),
            "field_role": fmt_field(["flux", "bandpass"]),
        },
        *[_synthetic_mosaic_field_record(i, f"G55_{i}", 10, 290.0 + 0.05 * i) for i in range(1, 5)],
        *[
            _synthetic_mosaic_field_record(4 + j, f"M31 P{j}", 20 + j, 10.68 + 0.04 * j)
            for j in range(1, 5)
        ],
    ]
    sids = [r["source_id"] for r in recs]
    scans_cnt = Counter({r["field_id"]: 2 for r in recs})
    groups = fields._detect_mosaic_groups(recs, sids, scans_cnt)
    assert [g["group_name"] for g in groups] == ["G55", "M31"]
    assert [g["n_pointings"] for g in groups] == [4, 4]

    # 2. End-to-end fields.run() on a real MS with 4 mosaic target pointings added to FIELD.
    field_tb_path = str(Path(real_ms_raw_copy) / "FIELD")
    with open_table(field_tb_path, read_only=False) as tb:
        orig_n = tb.nrows()
        base_dir = tb.getcell("PHASE_DIR", orig_n - 1)
        base_delay = tb.getcell("DELAY_DIR", orig_n - 1)
        base_ref = tb.getcell("REFERENCE_DIR", orig_n - 1)
        base_time = tb.getcell("TIME", orig_n - 1)
        tb.addrows(4)
        for k in range(4):
            row = orig_n + k
            shift = np.array(base_dir, copy=True)
            shift[0, 0] += math.radians(0.05 * (k + 1))
            tb.putcell("NAME", row, f"MOS_TGT_{k + 1}")
            tb.putcell("CODE", row, "")
            tb.putcell("TIME", row, base_time)
            tb.putcell("NUM_POLY", row, 0)
            tb.putcell("DELAY_DIR", row, base_delay if k == 0 else shift)
            tb.putcell("PHASE_DIR", row, shift)
            tb.putcell("REFERENCE_DIR", row, base_ref if k == 0 else shift)
            tb.putcell("SOURCE_ID", row, 99)
            tb.putcell("FLAG_ROW", row, False)

    wd = tmp_path / "work"
    wd.mkdir()
    env = fields.run(real_ms_raw_copy, workdir=str(wd))
    wire = wire_envelope(env)
    mgroups = wire["data"]["mosaic_groups"]
    assert len(mgroups) == 1
    assert mgroups[0]["group_name"] == "MOS_TGT"
    assert mgroups[0]["n_pointings"] == 4
    slimmed = [f for f in wire["data"]["fields"] if f.get("mosaic_group") == "MOS_TGT"]
    assert len(slimmed) == 4
    for rec in slimmed:
        assert "vla_cal_match" not in rec
        assert "catalogue_role" not in rec
    sidecar = wire["data"]["detail_path"]
    assert sidecar is not None and Path(sidecar).is_file()
    full_saved = json.loads(Path(sidecar).read_text())
    assert "vla_cal_match" in full_saved["fields"][-1]


def test_readonly_ms_and_caltable_parent_sidecar_safety(
    tmp_path: Path,
    real_ms_calibrated: str,
    real_caltable: str,
    monkeypatch: pytest.MonkeyPatch,
):
    ro_dir = tmp_path / "readonly_archive"
    ro_dir.mkdir()
    ro_ms = ro_dir / "archive.ms"
    ro_cal = ro_dir / "archive.G"
    shutil.copytree(real_ms_calibrated, ro_ms)
    shutil.copytree(real_caltable, ro_cal)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.delenv("RADIO_MCP_DIR", raising=False)
    assert resolve_sidecar_path("x.json", None) is None

    before_entries = sorted(p.name for p in ro_dir.iterdir())
    ro_dir.chmod(0o555)
    try:
        # 1. Without workdir or RADIO_MCP_DIR: must succeed and write nothing into ro_dir.
        assert antennas.run_antenna_list(str(ro_ms))["status"] == "ok"
        assert antennas.run_baseline_lengths(str(ro_ms))["status"] == "ok"
        assert geometry.run_elevation_vs_time(str(ro_ms))["status"] == "ok"
        assert geometry.run_parallactic_angle_vs_time(str(ro_ms))["status"] == "ok"
        assert fields.run(str(ro_ms))["status"] == "ok"
        assert scans.run_scan_list(str(ro_ms))["status"] == "ok"
        assert spw_amp_severity.run(str(ro_ms), datacolumn="CORRECTED_DATA")["status"] == "ok"
        assert residual_stats.run(str(ro_ms), 0, max_per_chan_records=1)["status"] == "ok"
        assert calsol_stats.run(str(ro_cal))["status"] == "ok"
        assert sorted(p.name for p in ro_dir.iterdir()) == before_entries

        # 2. With explicit workdir: sidecars land inside work_dir/sidecars/, never ro_dir.
        wd = str(work_dir)
        ant_res = wire_envelope(antennas.run_antenna_list(str(ro_ms), workdir=wd))
        scn_res = wire_envelope(scans.run_scan_list(str(ro_ms), workdir=wd))
        res_res = wire_envelope(
            residual_stats.run(str(ro_ms), 0, max_per_chan_records=1, workdir=wd)
        )
        cal_res = wire_envelope(calsol_stats.run(str(ro_cal), workdir=wd))
        for r, key in (
            (ant_res, "detail_path"),
            (scn_res, "detail_path"),
            (res_res, "detail_path"),
            (cal_res, "npz_path"),
        ):
            p_str = r["data"][key]
            assert p_str is not None
            assert Path(p_str).is_file()
            assert Path(p_str).parent == (work_dir / "sidecars").resolve()
        assert sorted(p.name for p in ro_dir.iterdir()) == before_entries
    finally:
        ro_dir.chmod(0o755)


# ---------------------------------------------------------------------------
# Wave 3: Bounded-wait run-step.sh & stage_log.jsonl auto-ledger
# ---------------------------------------------------------------------------


def test_run_step_fast_zero_and_nonzero_rc(tmp_path: Path):
    ok_script = tmp_path / "ok_step.py"
    ok_script.write_text("print('step complete')\n")
    proc = subprocess.run(
        ["bash", str(RUN_STEP_SH), sys.executable, str(ok_script), "--wait", "10"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "status=done rc=0" in proc.stdout
    assert "step complete" in proc.stdout
    assert (tmp_path / "ok_step.py.rc").read_text().strip() == "0"
    assert not (tmp_path / "ok_step.py.pid").exists()

    fail_script = tmp_path / "fail_step.py"
    fail_script.write_text("import sys\nprint('bad solve')\nsys.exit(3)\n")
    proc_fail = subprocess.run(
        ["bash", str(RUN_STEP_SH), sys.executable, str(fail_script), "--wait", "10"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_fail.returncode == 3
    assert "status=done rc=3" in proc_fail.stdout
    assert "bad solve" in proc_fail.stdout


def test_run_step_bounded_wait_running_and_idempotent_reattach(tmp_path: Path):
    counter_file = tmp_path / "launches.txt"
    slow_script = tmp_path / "slow_step.py"
    slow_script.write_text(
        f"import time\n"
        f"from pathlib import Path\n"
        f"p = Path({str(counter_file)!r})\n"
        f"p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
        f"print('started slow step', flush=True)\n"
        f"time.sleep(2.4)\n"
        f"print('finished slow step', flush=True)\n"
    )

    first = subprocess.run(
        [
            "bash",
            str(RUN_STEP_SH),
            sys.executable,
            str(slow_script),
            "--wait",
            "1",
            "--interval",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    assert "status=running" in first.stdout
    assert "pid_alive=true" in first.stdout
    assert (tmp_path / "slow_step.py.pid").is_file()

    second = subprocess.run(
        [
            "bash",
            str(RUN_STEP_SH),
            sys.executable,
            str(slow_script),
            "--wait",
            "6",
            "--interval",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0
    assert "status=done rc=0" in second.stdout
    assert "finished slow step" in second.stdout
    # Must have attached to the existing process rather than launching a second copy.
    assert counter_file.read_text() == "x"


def test_run_step_crashed_dead_pid_without_rc(tmp_path: Path):
    crash_script = tmp_path / "crash_step.py"
    crash_script.write_text("import time\ntime.sleep(30)\n")
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    victim.send_signal(signal.SIGKILL)
    victim.wait(timeout=5)
    # Give OS a brief tick to reap dead PID.
    time.sleep(0.05)

    (tmp_path / "crash_step.py.pid").write_text(f"{victim.pid}\n")
    (tmp_path / "crash_step.py.log").write_text("killed by signal\n")
    res = subprocess.run(
        ["bash", str(RUN_STEP_SH), sys.executable, str(crash_script), "--wait", "2"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "status=crashed" in res.stdout
    assert "pid_alive=false" in res.stdout
    assert not (tmp_path / "crash_step.py.pid").exists()


def test_auto_ledger_derivation_deduplication_and_report(
    tmp_path: Path,
    real_ms_calibrated_copy: str,
):
    wd = tmp_path / "work"
    wd.mkdir()

    # Verify postcal_flag and setjy_polcal generated scripts embed record_stage calls.
    pf_env = postcal_flag.run(
        real_ms_calibrated_copy,
        str(wd),
        field="J1331+3030",
        keep_spw="0",
        execute=False,
    )
    assert pf_env["status"] == "ok"
    pf_script = (wd / "postcal_flag.py").read_text()
    assert "record_stage" in pf_script and '"postcal_flag"' in pf_script

    sp_env = setjy_polcal.run(
        real_ms_calibrated_copy,
        field="J1331+3030",
        workdir=str(wd),
        calibrator_name="3C286",
        execute=False,
    )
    assert sp_env["status"] == "ok"
    sp_script = (wd / "setjy_polcal.py").read_text()
    assert "record_stage" in sp_script and '"setjy_polcal"' in sp_script

    # Populate stage_log.jsonl directly (no reduction_log.jsonl) including a superseded gaincal.
    prior_py = wd / "priorcals.py"
    prior_py.write_text("# priorcals\n")
    prior_sha = hashlib.sha256(prior_py.read_bytes()).hexdigest()

    g_py = wd / "gaincal_G0.py"
    g_py.write_text("# gaincal v2\n")
    g_sha = hashlib.sha256(g_py.read_bytes()).hexdigest()

    pf_sha = hashlib.sha256((wd / "postcal_flag.py").read_bytes()).hexdigest()
    sp_sha = hashlib.sha256((wd / "setjy_polcal.py").read_bytes()).hexdigest()

    stage_entries = [
        {
            "at": "2026-11-12T10:00:00Z",
            "stage": "priorcals",
            "product": str(wd / "antpos.cal"),
            "exists": True,
            "script_path": str(prior_py),
            "script_sha256": prior_sha,
            "params": {"ms_path": real_ms_calibrated_copy, "workdir": str(wd)},
        },
        {
            "at": "2026-11-12T10:00:01Z",
            "stage": "priorcals",
            "product": str(wd / "gaincurve.cal"),
            "exists": True,
            "script_path": str(prior_py),
            "script_sha256": prior_sha,
            "params": {"ms_path": real_ms_calibrated_copy, "workdir": str(wd)},
        },
        # Superseded attempt on G0.G (must be dropped in favour of the later G0.G solve).
        {
            "at": "2026-11-12T10:01:00Z",
            "stage": "gaincal",
            "product": str(wd / "G0.G"),
            "exists": True,
            "script_path": str(g_py),
            "script_sha256": "0" * 64,
            "params": {"solint": "10s"},
        },
        {
            "at": "2026-11-12T10:02:00Z",
            "stage": "gaincal",
            "product": str(wd / "G0.G"),
            "exists": True,
            "script_path": str(g_py),
            "script_sha256": g_sha,
            "params": {"solint": "inf"},
        },
        {
            "at": "2026-11-12T10:03:00Z",
            "stage": "setjy_polcal",
            "product": real_ms_calibrated_copy,
            "exists": True,
            "script_path": str(wd / "setjy_polcal.py"),
            "script_sha256": sp_sha,
            "params": {"field": "J1331+3030", "calibrator": "3C286"},
        },
        {
            "at": "2026-11-12T10:04:00Z",
            "stage": "postcal_flag",
            "product": real_ms_calibrated_copy,
            "exists": True,
            "script_path": str(wd / "postcal_flag.py"),
            "script_sha256": pf_sha,
            "params": {"field": "J1331+3030", "keep_spw": "0"},
        },
    ]
    (wd / "stage_log.jsonl").write_text("\n".join(json.dumps(e) for e in stage_entries) + "\n")
    assert not (wd / "reduction_log.jsonl").exists()

    listed = wire_envelope(reduction_log.run("list", str(wd)))
    tools_in_order = [s["tool"] for s in listed["data"]["steps"]]
    assert tools_in_order == [
        "ms_generate_priorcals",
        "ms_gaincal",
        "ms_setjy_polcal",
        "ms_postcal_flag",
    ]

    rendered = wire_envelope(reduction_log.run("render", str(wd)))
    assert rendered["data"]["n_records"] == 4
    replay_path = Path(rendered["data"]["replay_script"])
    replay_src = replay_path.read_text()
    compile(replay_src, str(replay_path), "exec")
    assert "# ms_postcal_flag" in replay_src
    assert "# ms_setjy_polcal" in replay_src

    rep = wire_envelope(report.run(str(wd), summary="Auto-ledger test run."))
    assert rep["data"]["n_steps"] == 4
    assert Path(rep["data"]["report_path"]).is_file()


# ---------------------------------------------------------------------------
# Wave 4: ms_radiometer_estimate, ms_vis_amp_time_stats, audit_hook.py
# ---------------------------------------------------------------------------


def test_radiometer_estimate_formula_and_mosaic_on_source():
    sefd = 420.0
    n_ant = 27
    n_bl = n_ant * (n_ant - 1) // 2  # 351
    t_s = 600.0
    bw_hz = 1.0e9
    unfl = 0.85
    eta_c = 0.93
    expected_nat = sefd / (eta_c * math.sqrt(2.0 * 2 * n_bl * t_s * (bw_hz * unfl)))

    nat = radiometer_estimate.compute_radiometer_estimate(
        sefd_jy=sefd,
        sefd_note=None,
        n_ant_total=27,
        n_ant_unflagged=n_ant,
        on_source_s=t_s,
        on_source_total_s=t_s,
        n_fields_selected=1,
        total_bw_hz=bw_hz,
        unflagged_fraction=unfl,
        n_pol=2,
        eta_c=eta_c,
        weighting="natural",
        robust=0.5,
    )
    assert nat["sigma_natural_jy"]["value"] == pytest.approx(round(expected_nat, 9), abs=1e-9)
    assert nat["thermal_rms_jy"]["value"] == pytest.approx(round(expected_nat, 9), abs=1e-9)

    briggs = radiometer_estimate.compute_radiometer_estimate(
        sefd_jy=sefd,
        sefd_note=None,
        n_ant_total=27,
        n_ant_unflagged=n_ant,
        on_source_s=120.0,
        on_source_total_s=840.0,
        n_fields_selected=7,
        total_bw_hz=bw_hz,
        unflagged_fraction=unfl,
        n_pol=2,
        eta_c=eta_c,
        weighting="briggs",
        robust=0.5,
    )
    assert briggs["weighting_factor"]["value"] == pytest.approx(1.2)
    assert briggs["thermal_rms_jy"]["value"] == pytest.approx(
        1.2 * briggs["sigma_natural_jy"]["value"], rel=1e-5
    )
    assert "mosaic" in (briggs["on_source_s"].get("note") or "")

    unavail = radiometer_estimate.compute_radiometer_estimate(
        sefd_jy=None,
        sefd_note="unknown array",
        n_ant_total=10,
        n_ant_unflagged=10,
        on_source_s=60.0,
        on_source_total_s=60.0,
        n_fields_selected=1,
        total_bw_hz=1e8,
        unflagged_fraction=1.0,
        n_pol=2,
        eta_c=eta_c,
        weighting="briggs",
        robust=0.5,
    )
    assert unavail["thermal_rms_jy"]["flag"] == "UNAVAILABLE"
    assert unavail["thermal_rms_jy"]["value"] is None


def test_radiometer_estimate_on_real_ms(real_ms_raw: str):
    env = radiometer_estimate.run(real_ms_raw)
    assert env["status"] == "ok"
    wire = wire_envelope(env)
    d = wire["data"]
    assert d["telescope_name"] == "VLA"
    assert d["band_code"] == "L"
    assert d["selected_fields"] == ["J1331+3030"]
    assert d["n_ant_unflagged"] == 5
    assert d["n_baselines_eff"] == 10
    assert d["thermal_rms_jy"] > 0
    assert d["thermal_rms_jy"] == pytest.approx(
        d["weighting_factor"] * d["sigma_natural_jy"], rel=1e-5
    )


def test_vis_amp_time_stats_pure_summary_and_real_ms(real_ms_calibrated_copy: str):
    # 1. Pure summary math + empty/flagged handling.
    empty = vis_amp_time_stats.summarize_integration_amplitudes(
        [
            {
                "scan": 1,
                "time_mjd_s": 5.0e9,
                "field_id": 0,
                "field_name": "X",
                "sum_amp": 0.0,
                "npts": 0,
                "total_pts": 100,
            }
        ]
    )
    assert empty["n_integrations_unflagged"] == 0
    assert empty["median_amp"] is None

    # 2. Real MS across 2 DDIDs (3C147 is observed on spw0 and spw1) with an injected 12x outlier.
    with open_table(real_ms_calibrated_copy, read_only=False) as tb:
        fids = tb.getcol("FIELD_ID")
        times = tb.getcol("TIME")
        ant1 = tb.getcol("ANTENNA1")
        ant2 = tb.getcol("ANTENNA2")
        mask_3c147 = (fids == 0) & (ant1 != ant2)
        spike_t = float(np.min(times[mask_3c147]))
        spike_rows = np.where(mask_3c147 & (np.abs(times - spike_t) < 0.002))[0]
        for r in spike_rows:
            cell = tb.getcell("CORRECTED_DATA", int(r))
            tb.putcell("CORRECTED_DATA", int(r), cell * 12.0)

    env = vis_amp_time_stats.run(
        real_ms_calibrated_copy,
        field="3C147",
        datacolumn="CORRECTED_DATA",
        top_k=3,
    )
    wire = wire_envelope(env)
    assert wire["status"] == "ok"
    assert wire["data"]["selected_spws"] == [0, 1]
    assert wire["data"]["n_integrations_unflagged"] >= 2
    top = wire["data"]["top_outliers"][0]
    assert top["time_mjd_s"] == pytest.approx(spike_t, abs=0.01)
    assert top["ratio_to_median"] > 5.0

    # 3. All-flagged selection returns UNAVAILABLE cleanly.
    with open_table(real_ms_calibrated_copy, read_only=False) as tb:
        tb.putcol("FLAG_ROW", np.ones(tb.nrows(), dtype=bool))
    flagged_env = vis_amp_time_stats.run(
        real_ms_calibrated_copy,
        field="3C147",
        datacolumn="CORRECTED_DATA",
    )
    assert flagged_env["completeness_summary"] == "UNAVAILABLE"


def test_audit_hook_correlates_transcript_and_is_idempotent(tmp_path: Path):
    wd = tmp_path / "work"
    wd.mkdir()
    png_file = wd / "target.image.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    events = [
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_agent_1",
                        "name": "Agent",
                        "input": {
                            "subagent_type": "radio-analyst:precal-stage",
                            "prompt": f"ms=/data/obs.ms workdir={wd}\nSKILL EXCERPT FILE: /x/precal.md",
                        },
                    }
                ],
            },
        },
        {
            "type": "user",
            "toolUseResult": {"agentId": "ag_precal_01", "usage": {"total_tokens": 1234}},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_agent_1",
                        "content": "STAGE HANDOFF\nstage: precal\nproducts: antpos.cal",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "msg_2",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_chk_1",
                        "name": "mcp__plugin_radio-analyst_ms-inspect__ms_verify_priorcals",
                        "input": {"params": {"ms_path": "/data/obs.ms", "workdir": str(wd)}},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_chk_1",
                        "content": json.dumps({"status": "ok", "completeness_summary": "COMPLETE"}),
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "msg_3",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<stage_decision>"
                            + json.dumps(
                                {
                                    "seq": 1,
                                    "stage": "precal",
                                    "try": 1,
                                    "workdir": str(wd),
                                    "decision": "accept",
                                    "deciding_metric": "priorcals COMPLETE",
                                    "reason": "all tables verified",
                                }
                            )
                            + "</stage_decision>"
                        ),
                    },
                    {
                        "type": "tool_use",
                        "id": "tu_agent_2",
                        "name": "Agent",
                        "input": {
                            "subagent_type": "radio-analyst:image-stage",
                            "prompt": f"ms=/data/obs.ms workdir={wd} mode: iquv_cube",
                        },
                    },
                ],
            },
        },
        {
            "type": "user",
            "toolUseResult": {"agentId": "ag_img_02"},
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_agent_2",
                        "content": "STAGE HANDOFF\nstage: image\nproducts: target.image",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "msg_4",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_read_png",
                        "name": "Read",
                        "input": {"file_path": str(png_file)},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_read_png", "content": "[image]"}
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "id": "msg_5",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "<stage_decision>"
                            + json.dumps(
                                {
                                    "seq": 2,
                                    "stage": "image_iquv",
                                    "try": 1,
                                    "workdir": str(wd),
                                    "decision": "accept",
                                    "deciding_metric": "dynamic_range=140",
                                    "reason": "clean point source",
                                }
                            )
                            + "</stage_decision>"
                        ),
                    }
                ],
            },
        },
    ]

    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    written_1 = audit_hook.build_audit_records_from_transcript(transcript)
    assert [p.name for p in written_1] == ["01_precal_try1.json", "02_image_iquv_try1.json"]

    rec1 = json.loads(written_1[0].read_text())
    assert rec1["agent_id"] == "ag_precal_01"
    assert rec1["decision"] == "accept"
    assert len(rec1["checks"]) == 1
    assert rec1["checks"][0]["tool"] == "ms_verify_priorcals"

    rec2 = json.loads(written_1[1].read_text())
    assert rec2["stage"] == "image_iquv"
    assert rec2["png_reviewed"] == f"viewed: {png_file}"

    # Idempotency check: second invocation must not rewrite unchanged audit files.
    mtimes_before = [p.stat().st_mtime_ns for p in written_1]
    bytes_before = [p.read_bytes() for p in written_1]
    time.sleep(0.02)
    written_2 = audit_hook.build_audit_records_from_transcript(transcript)
    assert written_2 == written_1
    assert [p.read_bytes() for p in written_2] == bytes_before
    assert [p.stat().st_mtime_ns for p in written_2] == mtimes_before


# ---------------------------------------------------------------------------
# Wave 5: stage_bundles ungranted-tool leak detection
# ---------------------------------------------------------------------------


def test_stage_bundles_detects_ungranted_tool_cue():
    errors = verify_bundle_tool_grants(
        {"image": "## Bad section\nRun `ms_corrected_stats` before imaging.\n"},
        REPO_ROOT,
    )
    assert errors
    assert "ms_corrected_stats" in errors[0]


# ---------------------------------------------------------------------------
# Review MUST-FIX regression tests (#1--#7)
# ---------------------------------------------------------------------------


def test_run_step_finishes_between_polls_without_rerunning(tmp_path: Path):
    """MUST-FIX #1: if .rc appears while .pid is still on disk after --wait, do not re-launch."""
    launches = tmp_path / "launches_race.txt"
    script = tmp_path / "race_step.py"
    script.write_text(
        f"import time\n"
        f"from pathlib import Path\n"
        f"p = Path({str(launches)!r})\n"
        f"p.write_text(p.read_text() + '1' if p.exists() else '1')\n"
        f"time.sleep(1.6)\n"
        f"print('race done', flush=True)\n"
    )
    first = subprocess.run(
        ["bash", str(RUN_STEP_SH), sys.executable, str(script), "--wait", "1", "--interval", "1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    assert "status=running" in first.stdout
    # Wait until background job writes .rc while .pid is still sitting on disk.
    deadline = time.monotonic() + 5.0
    while not (tmp_path / "race_step.py.rc").is_file() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (tmp_path / "race_step.py.rc").is_file()
    assert (tmp_path / "race_step.py.pid").is_file()

    second = subprocess.run(
        ["bash", str(RUN_STEP_SH), sys.executable, str(script), "--wait", "5", "--interval", "1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0
    assert "status=done rc=0" in second.stdout
    assert launches.read_text() == "1"


def test_reduction_log_shared_script_path_replays_via_run(tmp_path: Path):
    """MUST-FIX #2: multiple steps sharing <workdir>/applycal.py must all replay via run(..., execute=True)."""
    wd = tmp_path / "work_shared"
    wd.mkdir()
    shared_py = wd / "applycal.py"
    shared_py.write_text("# final applycal\n")
    sha2 = hashlib.sha256(shared_py.read_bytes()).hexdigest()
    entries = [
        {
            "at": "2026-11-13T01:00:00Z",
            "stage": "applycal",
            "product": "/fake/cal.ms",
            "exists": True,
            "script_path": str(shared_py),
            "script_sha256": "a" * 64,
            "params": {"ms_path": "/fake/cal.ms", "workdir": str(wd), "field": "3C147"},
        },
        {
            "at": "2026-11-13T01:05:00Z",
            "stage": "applycal",
            "product": "/fake/cal.ms",
            "exists": True,
            "script_path": str(shared_py),
            "script_sha256": sha2,
            "params": {"ms_path": "/fake/cal.ms", "workdir": str(wd), "field": "J1331+3030"},
        },
    ]
    (wd / "stage_log.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    rendered = wire_envelope(reduction_log.run("render", str(wd)))
    replay_src = Path(rendered["data"]["replay_script"]).read_text()
    assert f"_run_script({str(shared_py)!r}" not in replay_src
    assert replay_src.count("importlib.import_module('ms_modify.applycal').run(") == 2


def test_radiometer_flag_row_counted_once(real_ms_raw_copy: str):
    """MUST-FIX #3: flagging half of target rows via FLAG_ROW scales thermal_rms_jy by sqrt(2), not 2."""
    from casatools import table

    base = wire_envelope(radiometer_estimate.run(real_ms_raw_copy))["data"]["thermal_rms_jy"]
    tb = table()
    tb.open(real_ms_raw_copy, nomodify=False)
    try:
        fids = tb.getcol("FIELD_ID")
        times = tb.getcol("TIME")
        frow = tb.getcol("FLAG_ROW")
        tgt_times = sorted(np.unique(np.round(times[fids == 1], 3)))
        half_cut = tgt_times[len(tgt_times) // 2 :]
        flag_mask = (fids == 1) & np.isin(np.round(times, 3), half_cut)
        frow[flag_mask] = True
        tb.putcol("FLAG_ROW", frow)
    finally:
        tb.close()
    half = wire_envelope(radiometer_estimate.run(real_ms_raw_copy))["data"]
    expected_ratio = 1.0 / math.sqrt(half["unflagged_fraction"])
    assert (half["thermal_rms_jy"] / base) == pytest.approx(expected_ratio, rel=1e-3)


def test_spw_amp_severity_truncation_preserves_unavailable_and_freq_ghz(
    real_ms_calibrated_copy: str,
):
    """MUST-FIX #4: truncating per_chan preserves UNAVAILABLE in completeness_summary and populates freq_ghz."""
    from casatools import table

    tb = table()
    tb.open(real_ms_calibrated_copy, nomodify=False)
    try:
        flg = tb.getcol("FLAG")
        vis = tb.getcol("CORRECTED_DATA")
        # Fully flag channel 0 across all rows -> UNAVAILABLE per-chan entry; spike channel 5 -> elevated chan.
        flg[:, 0, :] = True
        vis[:, 5, :] = vis[:, 5, :] * 25.0
        tb.putcol("FLAG", flg)
        tb.putcol("CORRECTED_DATA", vis)
    finally:
        tb.close()

    env = spw_amp_severity.run(
        real_ms_calibrated_copy,
        datacolumn="CORRECTED_DATA",
        max_per_chan_records=4,
    )
    wire = wire_envelope(env)
    assert wire["completeness_summary"] == "UNAVAILABLE"
    elevated = [
        ch for spw_rec in wire["data"]["per_spw"] for ch in spw_rec.get("top_elevated_chans", [])
    ]
    assert elevated
    assert elevated[0]["freq_ghz"] is not None and elevated[0]["freq_ghz"] > 0.5


def test_calsol_stats_respects_radio_mcp_dir_and_readonly_completeness(
    tmp_path: Path,
    real_caltable: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """MUST-FIX #5: RADIO_MCP_DIR/sidecars wins over caltable.parent, and read-only parent keeps npz_path COMPLETE."""
    ro_dir = tmp_path / "ro_cal"
    ro_dir.mkdir()
    ro_cal = ro_dir / "gain.G"
    shutil.copytree(real_caltable, ro_cal)

    monkeypatch.delenv("RADIO_MCP_DIR", raising=False)
    ro_dir.chmod(0o555)
    try:
        env_no_wd = wire_envelope(calsol_stats.run(str(ro_cal)))
        assert env_no_wd["data"]["npz_path"] is None
        assert env_no_wd["field_flags"]["npz_path"]["flag"] == "COMPLETE"

        mcp_dir = tmp_path / "mcp_wd"
        mcp_dir.mkdir()
        monkeypatch.setenv("RADIO_MCP_DIR", str(mcp_dir))
        env_mcp = wire_envelope(calsol_stats.run(str(ro_cal)))
        assert Path(env_mcp["data"]["npz_path"]).parent == (mcp_dir / "sidecars").resolve()
    finally:
        ro_dir.chmod(0o755)


def test_phase_cal_lookup_and_plot_library_wire_and_lock(
    tmp_path: Path,
    real_caltable: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """MUST-FIX #6 & #7: ms_phase_cal_lookup uses symmetric wire envelope; ms_plot_caltable_library locks paths."""
    import ms_inspect.server as inspect_srv

    monkeypatch.setenv("RADIO_MCP_DIR", str(tmp_path))
    # #7: ms_phase_cal_lookup
    res_lookup = asyncio.run(
        inspect_srv.ms_phase_cal_lookup(
            inspect_srv.PhaseCalLookupInput(ra_deg=202.7845, dec_deg=30.5092, band_code="L")
        )
    )
    wire_lookup = json.loads(res_lookup.content[0].text)
    assert wire_lookup["status"] == "ok"
    assert "completeness_summary" in wire_lookup
    assert "field_flags" in wire_lookup
    assert "provenance" not in wire_lookup
    fe = wire_lookup["data"]["flux_estimate"]
    assert not (isinstance(fe, dict) and "value" in fe and "flag" in fe)

    # #6: ms_plot_caltable_library with list[str] caltable_paths
    out_dir = tmp_path / "plots"
    out_dir.mkdir()
    res_lib = asyncio.run(
        inspect_srv.ms_plot_caltable_library(
            inspect_srv.CalsolPlotLibraryInput(
                caltable_paths=[real_caltable],
                output_dir=str(out_dir),
            )
        )
    )
    wire_lib = json.loads(res_lib.content[0].text)
    assert wire_lib["status"] == "ok"
