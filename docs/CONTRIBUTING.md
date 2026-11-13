# Contributing & Developer Reference (`radio-analyst`)

Developer internals, repository layout, environment setup, full 61-tool
inventory, wire contract, and CASA conventions for `radio-analyst`. Read
[`CLAUDE.md`](../CLAUDE.md) first for the non-negotiable scientific and tool
contract.

---

## Repository layout

```text
radio-analyst/
├── CLAUDE.md                      <- always-loaded contract (<= 4 KiB)
├── README.md                      <- user/install guide
├── docs/
│   └── CONTRIBUTING.md            <- developer reference & 61-tool inventory
├── design_docs/
│   ├── DESIGN.md                  <- architecture, failure modes, conventions
│   └── FLUX_STANDARD_DESIGN.md    <- per-field flux standard resolution
├── pixi.toml                      <- conda-forge + pinned casatools/casatasks
├── pyproject.toml                 <- build metadata and ruff/pytest config
├── .mcp.json                      <- project-scope MCP server config (clone)
├── opencode.json                  <- opencode MCP server config (600 s timeout)
├── .claude-plugin/
│   ├── plugin.json                <- plugin manifest (${CLAUDE_PLUGIN_ROOT})
│   └── marketplace.json           <- marketplace catalogue entry
├── .claude/
│   ├── skills/
│   │   ├── radio-interferometry/  <- SKILL.md + 00..13 + ledger.md + bundles/*.md
│   │   ├── orchestrate/           <- SKILL.md (read-only orchestrator + <stage_decision>)
│   │   ├── ms-simulator/          <- SKILL.md + 01..05
│   │   ├── casa-docs/             <- SKILL.md
│   │   └── report/                <- SKILL.md
│   └── commands/                  <- inspect, precal, calibrate, polcal, image, postcal, selfcal, simulate
├── agents/                        <- Claude Code stage subagents (*-stage.md)
├── .opencode/
│   ├── agents/                    <- OpenCode stage subagents with per-stage MCP whitelists
│   └── commands/                  <- radio-analyst-*.md copies of .claude/commands/*.md
├── hooks/
│   └── hooks.json                 <- SessionStart (ensure-env.sh) + Stop/SessionEnd (audit_hook.sh)
├── scripts/
│   ├── plugin/
│   │   ├── serve*.sh / launch.sh  <- MCP server entry points
│   │   ├── ensure-env.sh / env-lib.sh
│   │   ├── run-step.sh            <- detached CASA runner with bounded --wait (default 240 s)
│   │   └── audit_hook.sh          <- Stop/SessionEnd <stage_decision> extractor wrapper
│   ├── dev/                       <- install-local.sh / uninstall-local.sh / run-isolated.sh
│   └── ci/                        <- tool_manifest.json, smoke MS generator, MCP probes
├── src/
│   ├── casa_tasks/                <- gen_schemas.py + casa_task_schemas.json
│   ├── ms_create/                 <- FastMCP server (4 tools, port 8002) + audit_hook.py
│   ├── ms_modify/                 <- FastMCP server (19 tools, port 8001)
│   └── ms_inspect/                <- FastMCP server (38 tools, port 8000) + util/stage_bundles.py
└── tests/
    ├── unit/                      <- fast unit suite (runs without live external data)
    └── integration/               <- real-MS integration suite
```

---

## Environment setup

Requires [pixi](https://prefix.dev). `casatools` and `casatasks` are PyPI-only
wheels resolved into the pixi environment (`[target.linux-64.pypi-dependencies]`
in `pixi.toml`).

```bash
pixi install
pixi run gen-stage-bundles   # regenerate .claude/skills/radio-interferometry/bundles/*.md
pixi run gen-casa-schemas    # regenerate src/casa_tasks/casa_task_schemas.json after CASA bump
pixi run check               # ruff lint + format check
pixi run test-unit           # unit test suite
pixi run test-int            # integration tests (RADIO_MCP_TEST_MS or RADIO_MCP_TEST_MS_TGZ)
```

### Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `RADIO_MCP_TRANSPORT` | `stdio` | `stdio` for local MCP clients; `http` for streamable HTTP |
| `RADIO_MCP_HOST` | `127.0.0.1` | HTTP bind address (unauthenticated; keep on localhost on shared hosts) |
| `RADIO_MCP_PORT` | `8000` | HTTP port (`8000` inspect, `8001` modify, `8002` create) |
| `RADIO_MCP_WORKERS` | `4` | Parallel worker count for FLAG column reads (capped at 8) |
| `RADIO_MCP_DIR` | cwd | Directory for server logs (`logs/`, `events.jsonl`) |
| `RADIO_MCP_ENV_WAIT` | `20` | Seconds `launch.sh` waits on an active plugin env build |
| `RADIO_MCP_TEST_MS` | unset | Path to pre-extracted MS for `test-int` |
| `RADIO_MCP_TEST_MS_TGZ` | unset | Path to `.ms.tgz` tarball for `test-int` |
| `RADIO_MCP_TEST_CALTABLE` | unset | Path to G/B caltable for caltable integration tests |

---

## Full tool inventory (61 tools)

### 1. `ms-inspect` -- read-only inspection and diagnostics (38 tools, port 8000)

#### Layer 1: Orientation (6 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_observation_info` | `tools/observation.py` | Telescope, project, observer, array config, UTC range, duration |
| `ms_field_list` | `tools/fields.py` | Unique fields (mosaic-deduplicated), sky coordinates, intents, calibrator matches, `pointing_table_path` sidecar |
| `ms_scan_list` | `tools/scans.py` | Compact scan count, duration, integration-time range, intent summary, plus `scan_table_path` sidecar |
| `ms_scan_intent_summary` | `tools/scans.py` | Aggregated scan count and duration per intent |
| `ms_spectral_window_list` | `tools/spectral.py` | Per-SPW frequencies, channel widths, correlations, suggested channel ranges |
| `ms_correlator_config` | `tools/spectral.py` | Dump time, correlation basis, full-Stokes status |

#### Layer 2: Instrument sanity (7 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_antenna_list` | `tools/antennas.py` | Antenna count, `dish_diameter_m`, `recommended_minblperant`, array centre, sidecar `antennas` table |
| `ms_baseline_lengths` | `tools/antennas.py` | Physical baseline min/max/percentiles and resolution range, sidecar `per_spw_derived` |
| `ms_elevation_vs_time` | `tools/geometry.py` | Per-field elevation min/max/mean and low-elevation scan counts, sidecar per-scan series |
| `ms_parallactic_angle_vs_time` | `tools/geometry.py` | Per-field `pa_sky_deg` and `pa_feed_deg` ranges (`validation_status: PENDING`), sidecar per-scan series |
| `ms_shadowing_report` | `tools/shadowing.py` | Read-only geometric shadowing fraction overall and per antenna |
| `ms_flag_preflight` | `tools/flags.py` | Row count, FLAG shape, data volume, runtime estimate, recommended workers |
| `ms_antenna_flag_fraction` | `tools/flags.py` | Adaptive chunked parallel `FLAG` read per antenna |

#### Calibration inspection (6 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_calsol_stats` | `tools/calsol_stats.py` | Compact or full statistics over G/B/K/D caltables plus `.calsol_stats.npz` sidecar |
| `ms_calsol_stats_detail` | `tools/calsol_stats_detail.py` | Slice reader over `.calsol_stats.npz` (`low_snr`, `amp_outliers`, `antenna`) |
| `ms_calsol_plot` | `tools/calsol_plot.py` | Interactive Bokeh HTML dashboard for one caltable |
| `ms_plot_caltable_library` | `tools/calsol_plot_library.py` | Batch Bokeh HTML dashboards for a list of caltables |
| `ms_gaincal_snr_predict` | `tools/gaincal_snr_predict.py` | Predicted per-(antenna, SPW) gaincal SNR from SEFD and MS metadata |
| `ms_verify_caltables` | `tools/caltables.py` | Structural check on `init_gain.g` and `BP0.b` |

#### Pre-calibration & workflow state (6 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_verify_import` | `tools/verify_import.py` | Verify MS `table.info` and `.flagonline.txt` after ASDM import |
| `ms_workflow_status` | `tools/workflow_status.py` | Filesystem + MS column probe returning stage booleans and `next_recommended_step` |
| `ms_verify_model` | `tools/verify_model.py` | Check physical `MODEL_DATA` against 1 Jy default trap and Stokes-I clobber |
| `ms_online_flag_stats` | `tools/online_flags.py` | Parse `.flagonline.txt` command counts, reasons, antennas, time span |
| `ms_flag_summary` | `tools/flag_summary.py` | Per-field, per-SPW, and per-antenna flag fractions (`flagdata(mode='summary')`) |
| `ms_verify_priorcals` | `tools/priorcals_check.py` | Check `gain_curves.gc`, `opacities.opac`, `requantizer.rq`, `antpos.ap` |

#### Instrument, RFI & visibility diagnostics (8 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_refant` | `tools/refant.py` | Reference-antenna ranking by centrality and unflagged fraction |
| `ms_phase_cal_lookup` | `util/phase_cal_catalog.py` | Positional cross-match against bundled NRAO VLA phase-calibrator catalogue |
| `ms_rfi_channel_stats` | `tools/rfi.py` | Per-channel flag fractions for persistent narrowband RFI |
| `ms_spw_amp_severity` | `tools/spw_amp_severity.py` | Per-SPW robust amplitude floor/severity; per-channel arrays offloaded to sidecar |
| `ms_pol_cal_conditions` | `tools/pol_cal_conditions.py` | Polarisation calibrator roles, band properties, and PA spread ranking |
| `ms_residual_stats` | `tools/residual_stats.py` | `CORRECTED - MODEL` amplitude distribution per SPW; per-channel arrays offloaded |
| `ms_corrected_stats` | `tools/corrected_stats.py` | Vector-averaged parallel-hand amplitude and phase scatter per field |
| `ms_vis_amp_time_stats` | `tools/vis_amp_time_stats.py` | Per-integration visibility amplitude summary (`median_amp`, `median_npts`, `top_outliers`) |

#### Imaging & sensitivity inspection (2 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_radiometer_estimate` | `tools/radiometer_estimate.py` | VLA OSS Eq. 1 thermal RMS (`thermal_rms_jy`, `sefd_jy`, `eff_bw_hz`, `on_source_s`, `n_ant_unflagged`, `weighting_factor`) |
| `ms_image_stats` | `tools/image_stats.py` | MAD-based `rms_jy`, PB-masked `residual_rms_jy`, peak, dynamic range, beam, PNG render, per-plane cube stats |

#### CASA documentation & schemas (3 tools)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_casa_task_lookup` | `util/casa_task_index.py` | Resolve CASA task name to casadocs API and casa6 source URLs |
| `ms_casa_task_spec` | `tools/casa_task_spec.py` | Return checked-in parameter schema for any installed CASA task |
| `ms_casa_tool_spec` | `tools/casa_tool_spec.py` | Introspect `casatools` methods (`table`) and safety tiers |

---

### 2. `ms-modify` -- calibration, flagging, and imaging (19 tools, port 8001)

Every `ms-modify` tool records its action in `<workdir>/stage_log.jsonl`. Script
generators default to `execute=False`.

| Tool | Module | Summary |
|------|--------|---------|
| `ms_set_intents` | `ms_modify/intents.py` | Populate `STATE` subtable and `STATE_ID` from calibrator/pol-catalogue matching |
| `ms_apply_preflag` | `ms_modify/preflag.py` | Online flags + shadow + quack + zero clip + tfcrop + `calibrators.ms` split |
| `ms_generate_priorcals` | `ms_modify/priorcals.py` | Generate `gc`, `opac`, `rq`, `ap` prior caltables |
| `ms_setjy` | `ms_modify/setjy.py` | Per-field flux density models (`exclude_fields` protects overlapping pol-angle cal) |
| `ms_setjy_polcal` | `ms_modify/setjy_polcal.py` | Probe + polynomial fit + `usescratch=True` polarised calibrator model |
| `ms_initial_bandpass` | `ms_modify/initial_bandpass.py` | Bootstrap `init_gain.g` + `BP0.b` + `applycal` restricted to `applycal_field` |
| `ms_apply_initial_rflag` | `ms_modify/initial_rflag.py` | `rflag` + `tfcrop` on `CORRECTED - MODEL` residuals (`field` required) |
| `ms_postcal_flag` | `ms_modify/postcal_flag.py` | Post-cal residual clip (modelled fields only) + `tfcrop`/`rflag` + manual drops |
| `ms_flag_caltable` | `ms_modify/flag_caltable.py` | Autoflag caltable solutions (`B -> tfcrop`, `G/T/D -> rflag`, `K` refused) or `mode='manual'` |
| `ms_flag_data` | `ms_modify/flag_data.py` | Manual MS selection flag with required `reason` and empty-selection guard |
| `ms_apply_rflag` | `ms_modify/rflag.py` | Target/field `rflag` pass with `before_rflag` flagbackup |
| `ms_gaincal` | `ms_modify/gaincal.py` | `G`, `T`, `K`, and `KCROSS` gain calibration |
| `ms_polcal` | `ms_modify/polcal.py` | Polarisation leakage (`Df`, `Df+QU`) and position angle (`Xf`) solves |
| `ms_bandpass` | `ms_modify/bandpass.py` | Bandpass `B` calibration |
| `ms_fluxscale` | `ms_modify/fluxscale.py` | Flux-scale bootstrap from reference to transfer fields |
| `ms_applycal` | `ms_modify/applycal.py` | Apply calibration stack and populate `CORRECTED_DATA` |
| `ms_tclean` | `ms_modify/tclean.py` | Continuum (`mfs`/`mtmfs`) or frequency-cube (`cube`) `tclean` script generator |
| `ms_casa_task` | `ms_modify/casa_task.py` | Guarded wrapper for CASA tasks without a dedicated MCP tool |
| `ms_casa_tool` | `ms_modify/casa_tool.py` | Guarded `casatools` (`table`) debugging inspector (read-only by default) |

---

### 3. `ms-create` -- ingestion, ledger, and reporting (4 tools, port 8002)

| Tool | Module | Summary |
|------|--------|---------|
| `ms_sdm_summary` | `ms_create/sdm_summary.py` | Pure-XML pre-import ASDM inspection (no `casatools` needed) |
| `ms_import_asdm` | `ms_create/import_asdm.py` | `importasdm` (`ocorr_mode='co'`, `savecmds=True`, `applyflags=False`) |
| `ms_reduction_log` | `ms_create/reduction_log.py` | Auto-derives effective replay steps from `stage_log.jsonl` (`list`/`render`), plus `append` for `manual` overrides |
| `ms_report` | `ms_create/report.py` | Build `report.html` embedding summary, decisions, caveats, auto-derived replay script, plots, and PNGs |

---

## Symmetric wire envelope & error taxonomy

Tool implementations wrap leaf values with `util/formatting.field(val, flag=..., note=...)`
and call `response_envelope(...)`. On the wire (`util/formatting.py` + `util/dispatch.py`):

```json
{
  "tool": "ms_antenna_list",
  "ms_path": "/data/obs/target.ms",
  "status": "ok",
  "completeness_summary": "COMPLETE",
  "data": {
    "n_antennas": 27,
    "dish_diameter_m": 25.0
  },
  "warnings": []
}
```

- `data` carries bare JSON scalars, lists, and dicts (never `{"value": ..., "flag": ...}`).
- `field_flags` is included only when one or more fields carry a non-`COMPLETE`
  flag or a `note` (`{"antennas[*].x_m": {"flag": "SUSPECT", "note": "..."}}`;
  identical per-element list flags collapse to `[*]`).
- `completeness_summary` is computed **before** any `offload_detail()` call so
  offloaded `SUSPECT`/`UNAVAILABLE` flags still surface in `completeness_summary`
  and `field_flags`.
- `provenance` is stripped from the MCP wire response and written only to
  `<workdir_or_RADIO_MCP_DIR>/events.jsonl` by `util/dispatch.py`.
- All MCP tools suppress FastMCP `outputSchema` emission (`outputSchema is None`)
  because `dispatch_tool` returns compact JSON `TextContent`.
- Sidecar files (`resolve_sidecar_path` in `util/formatting.py`) write under
  `<workdir>/sidecars/` or `RADIO_MCP_DIR/sidecars/` -- never into `ms_path.parent`,
  which may be read-only (`0o555`).

### Error codes

| Code | When raised |
|------|-------------|
| `MS_NOT_FOUND` | Path does not exist |
| `NOT_A_MEASUREMENT_SET` | Missing `table.info` |
| `SUBTABLE_MISSING` | Required MS subtable absent |
| `INSUFFICIENT_METADATA` | Blank/unknown telescope or unusable antenna table (includes repair command) |
| `CASA_NOT_AVAILABLE` | `casatools` not installed |
| `CASA_OPEN_FAILED` | `casatools` exception opening table |
| `COMPUTATION_ERROR` | Internal calculation failure |
| `INTENTS_ALREADY_POPULATED` | `>= 50%` of fields already carry intents (`ms_set_intents`) |

---

## Critical CASA & scientific conventions

1. **CASA table locks (`util/casa_context.py`)**: Always open MS/caltable/image
   resources via `open_msmd()`, `open_table()`, `open_ms()`, or `open_image()`.
   Never call raw `tb.open()` / `tb.close()` directly in tool code.
2. **Parallactic angle (`VALIDATION PENDING`)**: `ms_parallactic_angle_vs_time`
   returns both `pa_sky_deg` and `pa_feed_deg` (`pa_sky - 90 deg` on ALT-AZ
   mounts) with `validation_status="PENDING"`.
3. **Physical vs projected baselines**: `ms_baseline_lengths` reports physical
   ECEF baseline lengths (upper limits), not HA/Dec-projected UV distances.
4. **Calibrator catalogue scope**: `util/calibrators.py` holds primary flux/BP
   standards only; phase calibrators are queried via `util/phase_cal_catalog.py`.

---

## Adding or changing a tool

1. Implement `run(...)` using `util/casa_context.py`, `field()`, and
   `response_envelope()`. Write sidecars only via `resolve_sidecar_path(...)`.
2. Register in `src/<pkg>/server.py` (`@mcp.tool(name="ms_<name>", structured_output=False)`).
3. Add unit tests under `tests/unit/` (using pytest `tmp_path`, never `/tmp`) and
   an integration stub in `tests/integration/test_tools.py`.
4. Update `scripts/ci/tool_manifest.json`, `docs/CONTRIBUTING.md`,
   `design_docs/DESIGN.md`, and tool counts in `CLAUDE.md` and `README.md`.
5. If a stage command grants the tool, update `.claude/commands/<stage>.md`,
   copy to `.opencode/commands/radio-analyst-<stage>.md`, sync `agents/<stage>-stage.md`
   and `.opencode/agents/<stage>-stage.md`, and run `pixi run gen-stage-bundles`.
6. Run `pixi run check` and `pixi run test-unit`.
