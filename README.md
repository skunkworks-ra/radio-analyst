# radio-analyst

A Claude Code plugin for reducing radio interferometric data with CASA. It
gives Claude 55 tools across three MCP servers, the reasoning of an
experienced interferometrist (skills), and step-by-step workflows (slash
commands) for VLA/JVLA/EVLA, MeerKAT, and uGMRT Measurement Sets, from a raw
ASDM to a first image.

```bash
claude plugin marketplace add https://github.com/skunkworks-ra/radio-analyst
claude plugin install radio-analyst@radio-analyst
```

Prerequisites, first-run behaviour and troubleshooting are under
[Install](#install).

---

## What you can do with it

Talk about your data in plain language, or run a workflow command. Claude
picks the tools, reads the numbers, and tells you what they mean.

### Ask about a dataset

With a Measurement Set path in the conversation, just ask:

| You say | What happens |
|---|---|
| *"What's in /data/3c391.ms?"* | Telescope, array configuration, band, fields with their intents, scans, spectral windows and correlations, summarised in a paragraph. |
| *"Which antenna should I use as the reference?"* | Antennas ranked by distance from the array centre and by unflagged data, with both quantities shown so you can overrule the ranking. |
| *"Is there RFI in this observation? Which spectral windows are worst?"* | Per-channel flag fractions and a per-SpW amplitude severity, separating a SpW to drop from one worth salvaging. |
| *"Will I get enough parallactic-angle coverage to solve for leakage?"* | Identifies the polarisation calibrators and measures the PA spread per field. You get the numbers and what they allow you to claim, not a yes/no. |
| *"Is the phase calibrator in this MS a good one for B-config at L-band?"* | Cross-matches its position against the NRAO VLA calibrator list and returns flux, UV limits and quality codes per configuration. |
| *"Plot the bandpass table in ./cal/bandpass.B"* | An interactive Bokeh HTML dashboard of the solutions, routed by table type. |
| *"What's in this ASDM before I convert it?"* | Continuum vs. line SpWs, HI coverage, sources and intents, scan balance, target elevation. Reads only the ASDM XML, so no CASA is needed. |
| *"What does `timecutoff` do in flagdata's tfcrop mode?"* | Fetches and quotes the casadocs page, or the casa6 source if the docs don't cover it, instead of answering from memory. |

### Run a reduction, stage by stage

Each command is a workflow that runs a checked sequence of steps and stops to
report when a check fails. The commands are namespaced by the plugin:

| Command | Takes you from → to |
|---|---|
| `/radio-analyst:inspect <ms>` | A new MS → a data-quality report with a go/no-go for calibration (orientation + instrument sanity, 12 tools, nothing written). |
| `/radio-analyst:precal <ms>` | Imported MS → pre-calibrated calibrators: online flags, deterministic preflag, prior caltables (gain curves, opacity, requantizer, antenna positions), flux models, reference antenna, initial bandpass, residual RFI flagging. |
| `/radio-analyst:calibrate <ms>` | Pre-calibrated MS → calibrated target: initial phase → delay → bandpass → gain → fluxscale → applycal, with solution statistics checked after every solve. |
| `/radio-analyst:polcal <ms>` | Calibrated MS → polarisation-calibrated: cross-hand delay → leakage (D-terms) → position angle → applycal with parallactic-angle correction. |
| `/radio-analyst:image <ms>` | Calibrated MS → first image, with tclean parameters derived from the data (cell, image size, gridder, deconvolver, threshold) and the result checked against the radiometer noise and expected beam. |
| `/radio-analyst:simulate <description>` | A sentence → a synthetic MS, e.g. *"VLA B-config, L-band, 2 hours on 3C286 with a 5 % gain drift"*. |

A typical first session on a new VLA dataset:

```text
> What's in /data/19A-123.sb1234.eb5678/ ?            # raw ASDM: look before importing
> Import it to /data/work/obs.ms                        # writes an import script, then runs it
> /radio-analyst:inspect /data/work/obs.ms              # go / no-go report
> /radio-analyst:precal /data/work/obs.ms
> /radio-analyst:calibrate /data/work/obs.ms
> /radio-analyst:image /data/work/obs.ms
> Give me the replay script for everything that worked.
```

### Keep a reproducible record

As a reduction proceeds, Claude records each call that actually worked, with
its exact parameters and the reason for it, in `reduction_log.jsonl` in the
working directory. Ask for it back at any point, as a step list or as a single
replay script. Dead ends stay out, so the log is the clean path through your
data, not the search for it.

---

## How it works

**Tools measure. The skill reasons.** Every tool answers one question with
numbers and a completeness flag on each field (`COMPLETE`, `INFERRED`,
`PARTIAL`, `SUSPECT`, `UNAVAILABLE`). No tool decides whether you may proceed.
Thresholds depend on your science goal, so that judgement lives in the
`radio-interferometry` skill, where Claude applies it and shows you the inputs.
For example, 24° of parallactic-angle coverage doesn't block a leakage solve.
It becomes "proceed, and limit fractional-polarisation claims to a few percent".

**Nothing is written without a script you can read.** Every tool that modifies
data or imports an ASDM (17 in total) defaults to `execute=False`. It returns a
preview or writes a plain CASA Python script into your working directory and
returns its path. The workflow then runs that script and checks the result with
the read-only tools.

**Three servers, by what they can touch:**

- **ms-inspect**: read-only inspection and diagnostics (35 tools).
- **ms-modify**: flagging, calibration, imaging (17 tools, script-first).
- **ms-create**: ASDM inspection and import, and the reduction log (3 tools).

---

## Install

```bash
# Register the marketplace (once per machine)
claude plugin marketplace add https://github.com/skunkworks-ra/radio-analyst

# Install the plugin
claude plugin install radio-analyst@radio-analyst
```

**Prerequisites**

- [pixi](https://pixi.sh) on `PATH`: `curl -fsSL https://pixi.sh/install.sh | bash`
- Linux x86_64 or macOS arm64 (the platforms `pixi.toml` targets). On macOS,
  casatools isn't in `pixi.lock`, so the environment build installs it with pip.
- Roughly 1 GB of free disk for the Python/CASA environment.

**First run.** Start Claude Code. A `SessionStart` hook starts building the
Python/CASA environment in the background, and you'll see a message saying so
with the path to its log. The first build downloads casatools and its
dependencies and takes several minutes. It is stored under
`~/.claude/plugins/data/` and is kept across plugin updates. Until it finishes,
the three servers report that the build is in progress. When `build.log` ends
with `build complete`, run `/mcp` and reconnect them. Later updates only re-sync
the plugin's sources and reuse the installed packages, unless `pixi.lock`
changed.

**Check it works:** `/mcp` lists `ms-inspect`, `ms-modify` and `ms-create` as
connected. Then ask *"What's in <path to an MS>?"*.

**Update / remove.** The plugin carries no version number, so Claude Code
versions it by commit: an update brings you to the latest commit on `main`.

```bash
claude plugin update radio-analyst@radio-analyst
claude plugin uninstall radio-analyst@radio-analyst   # also deletes the environment
```

Third-party marketplaces don't auto-update by default. To turn that on, open
`/plugin` → **Marketplaces** → `radio-analyst` → **Enable auto-update**.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Servers fail with *"pixi is not on PATH"* | Install pixi (above), then restart Claude Code. |
| *"this machine is …"* at session start | The environment builds only on Linux x86_64 and macOS arm64 (the platforms `pixi.toml` targets). On other platforms the skills load but no tool can run. |
| Servers fail with *"still being built"* | Expected on the first run and after some updates. Wait for `build complete` in `build.log`, then reconnect with `/mcp`. |
| Servers fail with *"build failed"* | Read `build.log` (the message gives its path; the build before it is in `build.log.prev`). Reconnecting with `/mcp` retries the build. |
| Tools return `CASA_NOT_AVAILABLE` | casatools didn't install or import. Look for `WARNING` lines in `build.log`. |
| `INSUFFICIENT_METADATA` on a tool | The MS lacks a telescope name or antenna table. The error includes the exact repair command. |

### Permissions

- **Inside the workflow commands**, the MCP tools each command lists are
  pre-approved, and so is `Bash`, which runs the generated scripts. Those
  commands include the ms-modify tools that write to your MS and working
  directory. They run without a prompt per step, but each step goes through a
  generated script, and the workflow stops when a check fails.
- **Outside the commands**, every tool call prompts as usual. Allow them
  permanently in `/permissions` if you prefer. For example,
  `mcp__plugin_radio-analyst_ms-inspect__*` covers the read-only tools.

---

## Reference

### Skills

Loaded automatically when relevant. No need to invoke them yourself.

| Skill | Purpose |
|---|---|
| `radio-interferometry` | Interferometrist reasoning across the reduction: band tables, intent vocabulary, elevation/PA/flag thresholds, calibrator science, failure modes and recovery, and the execution playbooks the commands follow. |
| `ms-simulator` | Turns a conversational description into a `casatools.simulator` script and a validated MS. |
| `casa-docs` | Answers CASA task and parameter questions from the fetched casadocs page or casa6 source, never from memory. |

### Tools

The per-tool inventory is in [`design_docs/DESIGN.md`](design_docs/DESIGN.md)
(§8 ms-inspect, §8b ms-modify, §8c ms-create). Summary:

- **ms-inspect (34)**:
  - Orientation (6): observation info, fields, scans, scan intents, SpWs, correlator setup.
  - Instrument sanity (7): antennas, baselines, elevation and parallactic angle vs. time, shadowing, flag preflight, per-antenna flag fraction.
  - Calibration inspection (6): caltable statistics and detail, single and batch caltable plots, gaincal SNR prediction, caltable checks.
  - Pre-calibration checks (5): import, model, prior caltables, online flag stats, flag summary.
  - Instrument and RFI (7): reference antenna ranking, RFI channel stats, SpW amplitude severity, pol-cal conditions, residual and corrected-data statistics, phase-calibrator lookup.
  - Imaging (1): image RMS, peak, dynamic range, beam.
  - Workflow state (1).
  - CASA docs lookup (1).
- **ms-modify (16)**: intents, preflag, prior caltables, setjy / pol setjy,
  initial bandpass, gaincal (incl. KCROSS), bandpass, polcal, fluxscale,
  applycal, residual and post-cal RFI flagging, caltable autoflag, tclean.
- **ms-create (3)**: ASDM summary, ASDM → MS import, reduction log.

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `RADIO_MCP_TRANSPORT` | `stdio` | `stdio` for Claude Code / Desktop; `http` for remote clients |
| `RADIO_MCP_HOST` | `127.0.0.1` | HTTP bind address. **The HTTP transport has no authentication. Don't bind beyond localhost on shared or untrusted networks** |
| `RADIO_MCP_PORT` | `8000` / `8001` / `8002` | HTTP port (inspect / modify / create) |
| `RADIO_MCP_WORKERS` | `4` | Parallel workers for FLAG column reads (cap 8) |
| `RADIO_MCP_ENV_WAIT` | `20` | Plugin only: seconds a server waits on an in-progress environment build before exiting with a pointer to `build.log` |

---

## Other clients

Clone the repo and build the environment:

```bash
git clone https://github.com/skunkworks-ra/radio-analyst.git
cd radio-analyst
pixi install && pixi run pip install casatools casatasks
```

**Claude Desktop** launches each server itself and talks to it over stdio.
Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ms-inspect": {
      "command": "pixi",
      "args": ["run", "--manifest-path", "/path/to/radio-analyst/pixi.toml", "serve"]
    },
    "ms-modify": {
      "command": "pixi",
      "args": ["run", "--manifest-path", "/path/to/radio-analyst/pixi.toml", "serve-modify"]
    },
    "ms-create": {
      "command": "pixi",
      "args": ["run", "--manifest-path", "/path/to/radio-analyst/pixi.toml", "serve-create"]
    }
  }
}
```

This gives Desktop the tools. The skills and workflow commands are Claude Code
plugin components.

**Any MCP client over HTTP**: start the servers, then connect to
`http://localhost:8000/mcp` (and `:8001`, `:8002`; streamable HTTP):

```bash
RADIO_MCP_TRANSPORT=http RADIO_MCP_PORT=8000 pixi run serve
RADIO_MCP_TRANSPORT=http RADIO_MCP_PORT=8001 pixi run serve-modify
RADIO_MCP_TRANSPORT=http RADIO_MCP_PORT=8002 pixi run serve-create
```

---

## Development

Working on the plugin itself: register the servers against your clone instead
of the plugin install.

```bash
git clone https://github.com/skunkworks-ra/radio-analyst.git
cd radio-analyst
pixi install
pixi run pip install casatools casatasks   # first time only
pixi run install-mcp                       # removes a plugin install first, if any
```

`install-mcp` (`scripts/dev/install-local.sh`) registers the three servers at
user scope, pointing at `.pixi/envs/default/bin/`. Re-run it after a
`pixi install` that rebuilds the environment. `pixi run uninstall-mcp` undoes
it. Opened in Claude Code, the clone also loads the skills and commands from
`.claude/` directly, un-namespaced (`/inspect`, `/precal`, …).

To try the plugin packaging itself from a clone:
`claude plugin marketplace add ./ && claude plugin install radio-analyst@radio-analyst`.

```bash
pixi run test-unit     # unit tests (casatools required; builds a small real MS)
pixi run test-int      # integration: RADIO_MCP_TEST_MS=/path/to.ms or RADIO_MCP_TEST_MS_TGZ=/path/to.ms.tgz
pixi run check         # ruff lint + format check (CI gate)
claude plugin validate .claude-plugin/plugin.json
```

[`CLAUDE.md`](CLAUDE.md) holds the contributor contract and conventions, and
[`design_docs/DESIGN.md`](design_docs/DESIGN.md) the architecture. Read both
before a non-trivial change.

---

## License

GPL-3.0
