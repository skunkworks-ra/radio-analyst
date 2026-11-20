"""
CASA-free unit tests for root orchestrator tool-schema scoping and inline payload cuts:
1. Root orchestrator tool-schema budget (61 tools -> 16 granted MCP tools) across
   Claude Code and OpenCode agent definitions.
2. ms_calsol_stats compact-mode per-antenna phase_mean_deg and table-wide
   phase_mean_abs_max_deg (including cross-field/SpW sign-cancellation and +/-180 deg
   wrap protection), plus removal of verbosity='full' in selfcal command/bundle.
3. ms_residual_stats compact default (_DEFAULT_MAX_PER_CHAN_RECORDS == 0) offloading
   chan_* arrays to <workdir>/sidecars/ while keeping all per-SpW aggregates and
   CompletionFlags intact.
4. ms_casa_task_spec optional param_names filter (XML schema order, n_params_total,
   wire payload size < 1.5 KB on tclean/flagdata, and unknown/empty validation).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import ms_create.server as create_srv
import ms_inspect.server as inspect_srv
import ms_modify.server as modify_srv
from ms_inspect.exceptions import ComputationError
from ms_inspect.tools import calsol_stats, casa_task_spec, residual_stats
from ms_inspect.util.formatting import wire_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Root orchestrator tool-schema budget
# ---------------------------------------------------------------------------


def test_orchestrator_mcp_schema_diet_under_quarter_of_full_surface():
    """The 16 MCP tools granted to orchestrate weigh < 25% of the full 63-tool surface."""

    async def _list_all():
        return (
            await inspect_srv.mcp.list_tools(),
            await modify_srv.mcp.list_tools(),
            await create_srv.mcp.list_tools(),
        )

    ins_tools, mod_tools, crt_tools = asyncio.run(_list_all())
    by_key: dict[str, str] = {}
    for srv_name, tools in (
        ("ms-inspect", ins_tools),
        ("ms-modify", mod_tools),
        ("ms-create", crt_tools),
    ):
        for tool in tools:
            by_key[f"{srv_name}_{tool.name}"] = json.dumps(
                tool.model_dump(exclude_none=True), separators=(",", ":")
            )

    assert len(by_key) == 63
    total_bytes = sum(len(s.encode("utf-8")) for s in by_key.values())

    import yaml

    oc_text = (REPO_ROOT / ".opencode" / "agents" / "orchestrate.md").read_text()
    oc_fm = yaml.safe_load(oc_text.split("---\n", 2)[1])
    granted_keys = [
        k
        for k, v in oc_fm["tools"].items()
        if k.startswith(("ms-inspect_", "ms-modify_", "ms-create_"))
        and not k.endswith("_*")
        and v is True
    ]
    assert len(granted_keys) == 16
    assert all(not k.startswith("ms-modify_") for k in granted_keys)

    orch_bytes = sum(len(by_key[k].encode("utf-8")) for k in granted_keys)
    assert orch_bytes < 25_000
    assert total_bytes > 90_000
    assert orch_bytes / total_bytes < 0.25


# ---------------------------------------------------------------------------
# 2. ms_calsol_stats compact phase_mean_deg & selfcal verbosity='full' removal
# ---------------------------------------------------------------------------


def _mock_complex_caltable(
    tbl_path: Path,
    *,
    ant_names: list[str],
    field_names: list[str],
    spw_field_phases_deg: dict[tuple[int, int], list[float | None]],
    viscal: str = "G Jones",
):
    """Build an open_table side_effect for a multi-(spw, field) complex caltable."""
    n_ant = len(ant_names)
    spws = sorted({s for s, _ in spw_field_phases_deg})
    fields = sorted({f for _, f in spw_field_phases_deg})

    def _tb(keywords=None, cols=None, nrows=0):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        m.nrows.return_value = nrows
        if keywords is not None:
            m.getkeywords.return_value = keywords
        if cols is not None:
            m.getcol.side_effect = lambda c: cols[c]
        return m

    ant_tb = _tb(cols={"NAME": np.array(ant_names)})
    field_tb = _tb(cols={"NAME": np.array(field_names)})
    kw_tb = _tb(keywords={"VisCal": viscal})
    axis_spw = np.array([s for s in spws for _ in fields], dtype=int)
    axis_fld = np.array([f for _ in spws for f in fields], dtype=int)
    axis_tb = _tb(cols={"SPECTRAL_WINDOW_ID": axis_spw, "FIELD_ID": axis_fld})

    subs: dict[tuple[int, int], MagicMock] = {}
    for (spw, fid), ph_list in spw_field_phases_deg.items():
        # 2 correlations, 1 channel, 2 time samples per antenna
        n_rows = n_ant * 2
        ant1 = np.repeat(np.arange(n_ant), 2)
        cparam = np.ones((2, 1, n_rows), dtype=complex)
        flag = np.zeros((2, 1, n_rows), dtype=bool)
        snr = np.full((2, 1, n_rows), 25.0, dtype=float)
        for ai, ph_deg in enumerate(ph_list):
            mask = ant1 == ai
            if ph_deg is None:
                flag[:, :, mask] = True
            else:
                cparam[:, :, mask] = np.exp(1j * np.deg2rad(ph_deg))
        sub = MagicMock()
        sub.nrows.return_value = n_rows
        sub.close = MagicMock()
        cols = {"ANTENNA1": ant1, "CPARAM": cparam, "FLAG": flag, "SNR": snr}
        sub.getcol.side_effect = lambda c, _cols=cols: _cols[c]
        subs[(spw, fid)] = sub

    calls: list[str] = []

    def _open_table(path, **kwargs):
        p = str(path)
        calls.append(p)
        if p.endswith("ANTENNA"):
            return ant_tb
        if p.endswith("FIELD"):
            return field_tb
        n = sum(1 for c in calls if c == str(tbl_path))
        if n == 1:
            return kw_tb
        if n == 2:
            return axis_tb
        tb = _tb(nrows=len(subs) * n_ant * 2)

        def _query(expr: str):
            for (spw, fid), sub in subs.items():
                if f"SPECTRAL_WINDOW_ID == {spw} AND FIELD_ID == {fid}" in expr:
                    return sub
            raise AssertionError(f"Unexpected query: {expr}")

        tb.query.side_effect = _query
        return tb

    return _open_table


def test_calsol_stats_compact_includes_signed_max_abs_phase_mean_deg_without_cancellation(
    tmp_path: Path,
):
    tbl = tmp_path / "pcal1.g"
    tbl.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()

    # Mosaic with 2 pointings and 2 SpWs:
    # - ea01: +18 deg on field 0, -18 deg on field 1 -> arithmetic mean would cancel to 0!
    # - ea02: +179 deg on SpW 0, -179.5 deg on SpW 1 -> must report -179.5, never ~0!
    # - ea03: completely flagged -> None, PARTIAL on phase_mean_deg, antennas_lost=['ea03']
    # - ea04: near-zero (+0.3 deg, -0.4 deg) -> signed max-abs is -0.4 deg
    ot = _mock_complex_caltable(
        tbl,
        ant_names=["ea01", "ea02", "ea03", "ea04"],
        field_names=["3C391_C1", "3C391_C2"],
        spw_field_phases_deg={
            (0, 0): [18.0, 179.0, None, 0.3],
            (0, 1): [-18.0, 179.0, None, -0.4],
            (1, 0): [12.0, -179.5, None, 0.2],
            (1, 1): [-22.5, -179.5, None, 0.1],
        },
    )
    with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot):
        env = calsol_stats.run(str(tbl), verbosity="compact", workdir=str(workdir))

    wire = wire_envelope(env)
    assert wire["status"] == "ok"
    d = wire["data"]
    assert d["ant_names"] == ["ea01", "ea02", "ea03", "ea04"]
    assert d["antennas_lost"] == ["ea03"]
    assert d["phase_mean_deg"] == pytest.approx([-22.5, -179.5, None, -0.4], abs=1e-3)
    assert d["phase_mean_abs_max_deg"] == pytest.approx(179.5, abs=1e-3)
    assert wire["field_flags"]["phase_mean_deg"]["flag"] == "PARTIAL"

    # Compact wire JSON on 1-field 27a/16s (< 4 KB vs > 35 KB full) and 5-pointing mosaic (< 6 KB vs > 150 KB full).
    ants_27 = [f"ea{i:02d}" for i in range(1, 28)]
    grid_1f = {(s, 0): [float((i % 7) - 3) * 4.5 for i in range(27)] for s in range(16)}
    tbl_1f = tmp_path / "single_pcal1.g"
    tbl_1f.mkdir()
    with patch(
        "ms_inspect.tools.calsol_stats.open_table",
        side_effect=_mock_complex_caltable(
            tbl_1f, ant_names=ants_27, field_names=["target"], spw_field_phases_deg=grid_1f
        ),
    ):
        wire_1f = wire_envelope(
            calsol_stats.run(str(tbl_1f), verbosity="compact", workdir=str(workdir))
        )
    with patch(
        "ms_inspect.tools.calsol_stats.open_table",
        side_effect=_mock_complex_caltable(
            tbl_1f, ant_names=ants_27, field_names=["target"], spw_field_phases_deg=grid_1f
        ),
    ):
        wire_1f_full = wire_envelope(
            calsol_stats.run(str(tbl_1f), verbosity="full", workdir=str(workdir))
        )
    assert len(json.dumps(wire_1f, separators=(",", ":")).encode("utf-8")) < 4_000
    assert len(json.dumps(wire_1f_full, separators=(",", ":")).encode("utf-8")) > 35_000

    flds_5 = [f"ptg_{j}" for j in range(5)]
    grid = {
        (s, f): [float((i % 7) - 3) * 4.5 for i in range(27)] for s in range(16) for f in range(5)
    }
    tbl_mos = tmp_path / "mosaic_pcal1.g"
    tbl_mos.mkdir()
    ot_mos = _mock_complex_caltable(
        tbl_mos, ant_names=ants_27, field_names=flds_5, spw_field_phases_deg=grid
    )
    with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot_mos):
        wire_mos = wire_envelope(
            calsol_stats.run(str(tbl_mos), verbosity="compact", workdir=str(workdir))
        )
    ot_mos_full = _mock_complex_caltable(
        tbl_mos, ant_names=ants_27, field_names=flds_5, spw_field_phases_deg=grid
    )
    with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=ot_mos_full):
        wire_mos_full = wire_envelope(
            calsol_stats.run(str(tbl_mos), verbosity="full", workdir=str(workdir))
        )

    compact_bytes = len(json.dumps(wire_mos, separators=(",", ":")).encode("utf-8"))
    full_bytes = len(json.dumps(wire_mos_full, separators=(",", ":")).encode("utf-8"))
    assert compact_bytes < 6_000
    assert full_bytes > 150_000


def test_selfcal_commands_and_bundle_drop_verbosity_full():
    import re

    for rel in (
        ".claude/commands/selfcal.md",
        ".opencode/commands/radio-analyst-selfcal.md",
        ".claude/skills/radio-interferometry/12-selfcal.md",
        ".claude/skills/radio-interferometry/bundles/selfcal.md",
        ".claude/commands/calibrate.md",
        ".opencode/commands/radio-analyst-calibrate.md",
        ".claude/skills/radio-interferometry/07-calibration-execution.md",
        ".claude/skills/radio-interferometry/bundles/calibrate.md",
    ):
        txt = (REPO_ROOT / rel).read_text()
        assert not re.search(r"verbosity\s*=\s*['\"]full['\"]", txt), rel
    for rel in (
        ".claude/commands/inspect.md",
        ".opencode/commands/radio-analyst-inspect.md",
    ):
        insp_txt = (REPO_ROOT / rel).read_text()
        assert "n_fields_with_intents > 0" in insp_txt, rel


def test_calsol_stats_multi_corr_opposite_phase_no_cancellation_or_180_flip(tmp_path: Path):
    """Opposite-sign RR/LL phases (+25/-25 deg, +95/-95 deg) must not cancel to 0 or flip to 180."""
    tbl = tmp_path / "pcal_corr.g"
    tbl.mkdir()
    workdir = tmp_path / "work_corr"
    workdir.mkdir()

    # 3 antennas, 2 correlations (RR, LL), 1 channel, 3 rows per antenna:
    # - ea01: RR=+25 deg, LL=-25 deg -> |phase_mean_deg| == 25.0 (not 0.0!)
    # - ea02: RR=+95 deg, LL=-95 deg -> |phase_mean_deg| == 95.0 (not 180.0!)
    # - ea03: RR=+10 deg, LL=-35 deg -> signed max-abs == -35.0
    ant1 = np.repeat(np.arange(3), 3)
    cparam = np.ones((2, 1, 9), dtype=complex)
    flag = np.zeros((2, 1, 9), dtype=bool)
    snr = np.full((2, 1, 9), 30.0, dtype=float)
    corr_phases = [(25.0, -25.0), (95.0, -95.0), (10.0, -35.0)]
    for ai, (ph0, ph1) in enumerate(corr_phases):
        mask = ant1 == ai
        cparam[0, 0, mask] = np.exp(1j * np.deg2rad(ph0))
        cparam[1, 0, mask] = np.exp(1j * np.deg2rad(ph1))

    def _tb(keywords=None, cols=None, nrows=0, sub=None):
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        m.nrows.return_value = nrows
        if keywords is not None:
            m.getkeywords.return_value = keywords
        if cols is not None:
            m.getcol.side_effect = lambda c: cols[c]
        if sub is not None:
            m.query.return_value = sub
        return m

    sub = MagicMock()
    sub.nrows.return_value = 9
    sub.close = MagicMock()
    sub_cols = {"ANTENNA1": ant1, "CPARAM": cparam, "FLAG": flag, "SNR": snr}
    sub.getcol.side_effect = lambda c: sub_cols[c]

    ant_tb = _tb(cols={"NAME": np.array(["ea01", "ea02", "ea03"])})
    fld_tb = _tb(cols={"NAME": np.array(["target"])})
    kw_tb = _tb(keywords={"VisCal": "G Jones"})
    ax_tb = _tb(cols={"SPECTRAL_WINDOW_ID": np.array([0]), "FIELD_ID": np.array([0])})
    sl_tb = _tb(nrows=9, sub=sub)
    calls: list[str] = []

    def _open(path, **kwargs):
        p = str(path)
        calls.append(p)
        if p.endswith("ANTENNA"):
            return ant_tb
        if p.endswith("FIELD"):
            return fld_tb
        n = sum(1 for x in calls if x == str(tbl))
        return kw_tb if n == 1 else ax_tb if n == 2 else sl_tb

    with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=_open):
        wire = wire_envelope(calsol_stats.run(str(tbl), verbosity="compact", workdir=str(workdir)))

    pm = wire["data"]["phase_mean_deg"]
    assert abs(pm[0]) == pytest.approx(25.0, abs=1e-3)
    assert abs(pm[1]) == pytest.approx(95.0, abs=1e-3)
    assert pm[2] == pytest.approx(-35.0, abs=1e-3)
    assert wire["data"]["phase_mean_abs_max_deg"] == pytest.approx(95.0, abs=1e-3)


def test_calsol_stats_delay_flag_symmetry_and_kcross_flagged_corr1(tmp_path: Path):
    """delay_rms_ns and delay_ns flags match across full/compact on all-flagged, 1-lost, and KCROSS."""
    workdir = tmp_path / "work_delay"
    workdir.mkdir()

    def _run_delay(name: str, viscal: str, fparam: np.ndarray, flag: np.ndarray, verbosity: str):
        tbl = tmp_path / name
        tbl.mkdir(exist_ok=True)
        ant1 = np.arange(3)
        snr = np.zeros_like(fparam)

        def _tb(keywords=None, cols=None, nrows=0, sub=None):
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=m)
            m.__exit__ = MagicMock(return_value=False)
            m.nrows.return_value = nrows
            if keywords is not None:
                m.getkeywords.return_value = keywords
            if cols is not None:
                m.getcol.side_effect = lambda c: cols[c]
            if sub is not None:
                m.query.return_value = sub
            return m

        sub = MagicMock()
        sub.nrows.return_value = 3
        sub.close = MagicMock()
        sc = {"ANTENNA1": ant1, "FPARAM": fparam, "FLAG": flag, "SNR": snr}
        sub.getcol.side_effect = lambda c: sc[c]

        ant_tb = _tb(cols={"NAME": np.array(["ea01", "ea02", "ea03"])})
        fld_tb = _tb(cols={"NAME": np.array(["3C286"])})
        kw_tb = _tb(keywords={"VisCal": viscal})
        ax_tb = _tb(cols={"SPECTRAL_WINDOW_ID": np.array([0]), "FIELD_ID": np.array([0])})
        sl_tb = _tb(nrows=3, sub=sub)
        calls: list[str] = []

        def _open(path, **kwargs):
            p = str(path)
            calls.append(p)
            if p.endswith("ANTENNA"):
                return ant_tb
            if p.endswith("FIELD"):
                return fld_tb
            n = sum(1 for x in calls if x == str(tbl))
            return kw_tb if n == 1 else ax_tb if n == 2 else sl_tb

        with patch("ms_inspect.tools.calsol_stats.open_table", side_effect=_open):
            return calsol_stats.run(str(tbl), verbosity=verbosity, workdir=str(workdir))

    # 1. All-flagged delay table -> UNAVAILABLE on delay_rms_ns in both full and compact
    fp_all = np.ones((2, 1, 3), dtype=float)
    flg_all = np.ones((2, 1, 3), dtype=bool)
    for verb in ("full", "compact"):
        res = _run_delay(f"all_flg_{verb}.K", "K Jones", fp_all, flg_all, verb)
        assert res["data"]["delay_ns"]["flag"] == "UNAVAILABLE"
        assert res["data"]["delay_rms_ns"]["flag"] == "UNAVAILABLE"
        assert res["data"]["delay_rms_ns"]["value"] == [[None]]

    # 2. 1 antenna flagged, 2 unflagged -> delay_ns PARTIAL, delay_rms_ns COMPLETE in both
    flg_one = np.zeros((2, 1, 3), dtype=bool)
    flg_one[:, :, 0] = True
    for verb in ("full", "compact"):
        res = _run_delay(f"one_flg_{verb}.K", "K Jones", fp_all * 2.0, flg_one, verb)
        assert res["data"]["delay_ns"]["flag"] == "PARTIAL"
        assert res["data"]["delay_rms_ns"]["flag"] == "COMPLETE"

    # 3. KCROSS with structural corr 1 flagged -> delay_ns & delay_rms_ns COMPLETE in both
    fp_kc = np.array([[[5.5, 5.5, 5.5]], [[0.0, 0.0, 0.0]]], dtype=float)
    flg_kc = np.zeros((2, 1, 3), dtype=bool)
    flg_kc[1, :, :] = True
    for verb in ("full", "compact"):
        res = _run_delay(f"kc_{verb}.K", "Kcross Jones", fp_kc, flg_kc, verb)
        assert res["data"]["delay_ns"]["flag"] == "COMPLETE"
        assert res["data"]["delay_rms_ns"]["flag"] == "COMPLETE"


# ---------------------------------------------------------------------------
# 3. ms_residual_stats compact default & sidecar/flag preservation
# ---------------------------------------------------------------------------


def test_residual_stats_default_offloads_channels_and_preserves_spw_flags(tmp_path: Path):
    assert residual_stats._DEFAULT_MAX_PER_CHAN_RECORDS == 0
    assert inspect_srv.ResidualStatsInput.model_fields["max_per_chan_records"].default == 0

    # Build 16 SpWs x 64 channels (1,024 channels), with SpW 15 completely flagged (UNAVAILABLE).
    rng = np.random.default_rng(42)
    per_spw = []
    for spw_id in range(16):
        amp = np.abs(rng.normal(0.0, 0.05, (2, 64, 50)))
        flag = np.ones_like(amp, dtype=bool) if spw_id == 15 else np.zeros_like(amp, dtype=bool)
        stats = residual_stats._spw_stats(amp, flag)
        per_spw.append(
            {
                "data_desc_id": spw_id,
                "spw_id": spw_id,
                "correlations_used": ["RR", "LL"],
                **stats,
            }
        )

    data = {
        "field_id": 2,
        "n_rows_read": {"value": 800, "flag": "COMPLETE"},
        "n_data_desc_ids": {"value": 16, "flag": "COMPLETE"},
        "note": "test",
        "per_spw": per_spw,
    }
    sidecar = tmp_path / "sidecars" / "obs.ms.residual_stats.field2.json"
    sidecar.parent.mkdir(parents=True)
    warnings: list[str] = []

    bounded = residual_stats._bound_chan_payload(
        data,
        max_per_chan_records=residual_stats._DEFAULT_MAX_PER_CHAN_RECORDS,
        sidecar_path=str(sidecar),
        warnings=warnings,
    )
    from ms_inspect.util.formatting import response_envelope

    wire = wire_envelope(
        response_envelope(
            tool_name="ms_residual_stats",
            ms_path="/data/obs.ms",
            data=bounded,
            warnings=warnings,
            casa_calls=[],
        )
    )
    wire_bytes = len(json.dumps(wire, separators=(",", ":")).encode("utf-8"))
    assert wire_bytes < 4_500  # down from ~37 KB!
    assert wire["completeness_summary"] == "UNAVAILABLE"  # SpW 15 all-flagged preserved!
    assert wire["data"]["per_chan_truncated"] is True
    assert wire["data"]["detail_path"] == str(sidecar)
    assert len(wire["data"]["per_spw"]) == 16
    assert wire["data"]["per_spw"][0]["median_amp"] is not None
    assert wire["data"]["per_spw"][15]["median_amp"] is None
    assert "chan_median_amp" not in wire["data"]["per_spw"][0]

    saved = json.loads(sidecar.read_text())
    assert len(saved["per_spw"][0]["chan_median_amp"]) == 64


# ---------------------------------------------------------------------------
# 4. ms_casa_task_spec optional param_names filter
# ---------------------------------------------------------------------------


def test_casa_task_spec_param_names_filter_and_validation():
    # Unfiltered tclean is > 15 KB; filtered to 2 params is < 1 KB and preserves XML order.
    full_wire = wire_envelope(casa_task_spec.run("tclean"))
    full_bytes = len(json.dumps(full_wire, separators=(",", ":")).encode("utf-8"))
    assert full_bytes > 15_000
    n_total = full_wire["data"]["n_params_total"]
    assert full_wire["data"]["n_params"] == n_total
    assert n_total >= 80

    # Pass reversed order + whitespace + duplicate to verify XML schema ordering and dedup.
    filt_wire = wire_envelope(
        casa_task_spec.run("tclean", param_names=[" scales ", "deconvolver", "scales"])
    )
    filt_bytes = len(json.dumps(filt_wire, separators=(",", ":")).encode("utf-8"))
    assert filt_bytes < 1_200
    assert filt_wire["data"]["n_params"] == 2
    assert filt_wire["data"]["n_params_total"] == n_total
    assert [p["name"] for p in filt_wire["data"]["params"]] == ["deconvolver", "scales"]
    assert filt_wire["data"]["docs_path"] is not None
    assert filt_wire["data"]["docs_path"].endswith("tclean.rst")

    # Empty list behaves identically to None (returns all parameters).
    all_again = wire_envelope(casa_task_spec.run("flagdata", param_names=[]))
    assert all_again["data"]["n_params"] == all_again["data"]["n_params_total"]

    # Unknown parameter raises ComputationError naming the invalid entry and valid parameters.
    with pytest.raises(ComputationError, match="no_such_param"):
        casa_task_spec.run("tclean", param_names=["deconvolver", "no_such_param"])

    # Blank or mixed-blank param_names raises ComputationError.
    with pytest.raises(ComputationError, match="non-empty parameter name"):
        casa_task_spec.run("tclean", param_names=["   "])
    with pytest.raises(ComputationError, match="non-empty parameter name"):
        casa_task_spec.run("tclean", param_names=["scales", "   "])

    # Empty task with non-empty param_names raises ComputationError.
    with pytest.raises(ComputationError, match="requires a non-empty task name"):
        casa_task_spec.run("", param_names=["vis"])
