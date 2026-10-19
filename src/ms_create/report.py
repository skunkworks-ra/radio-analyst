"""
report.py — ms_report

Build one HTML report of a reduction from what the workdir already holds:

  - the ledger (reduction_log.jsonl): one row per recorded step, with params,
    outputs, rationale, skill rule and the script that ran, and a keep box per
    step. The boxes compose the `keep_steps` list for
    ms_reduction_log(action='render', keep_steps=[...]), so the user can drop
    steps from the replay
  - the open items the reduce hook recorded at its last Stop (reduce_hooks.jsonl)
  - the replay script from the last ledger render (reduction_replay.py), linked and shown
  - links to the HTML plots already written (caltable dashboards)
  - an interactive view of one image plane, if `image_path` is given

The narrative sections (summary, decisions, caveats) are written by the model
and passed in as text; this tool lays them out and adds no judgement of its own.
Re-running it overwrites report.html, so it can be rebuilt after every step.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path

from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_report"
REPORT_NAME = "report.html"
MAX_IMAGE_PIX = 1024

_CSS = """
body { font-family: sans-serif; margin: 2em; max-width: 1200px; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 4px 6px; vertical-align: top; font-size: 13px; }
th { background: #eee; }
pre { margin: 0; white-space: pre-wrap; font-size: 12px; }
tr.dropped { opacity: 0.4; }
#keep { width: 100%; font-family: monospace; }
"""

_KEEP_JS = """
function updateKeep() {
  const boxes = document.querySelectorAll('input.keep');
  const kept = [];
  boxes.forEach(b => {
    b.closest('tr').classList.toggle('dropped', !b.checked);
    if (b.checked) kept.push(Number(b.dataset.step));
  });
  const all = kept.length === boxes.length;
  document.getElementById('keep').value = all
    ? 'all steps kept'
    : "ms_reduction_log(action='render', keep_steps=[" + kept.join(', ') + "])";
}
"""


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _paragraphs(text: str) -> str:
    return "".join(
        f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n") if p.strip()
    )


def _pre(obj) -> str:
    if not obj:
        return ""
    return f"<pre>{html.escape(json.dumps(obj, indent=1, default=str))}</pre>"


def _steps_table(records: list[dict], wd: Path) -> str:
    rows = []
    for r in records:
        step = r.get("step")
        script = r.get("script_path", "")
        if script:
            rel = Path(script).name if Path(script).parent == wd.resolve() else script
            script = f'<a href="{html.escape(rel)}">{html.escape(Path(script).name)}</a>'
        rows.append(
            "<tr>"
            f'<td><input type="checkbox" class="keep" data-step="{step}" checked '
            'onchange="updateKeep()"></td>'
            f"<td>{step}</td><td>{html.escape(str(r.get('tool', '')))}</td>"
            f"<td>{html.escape(str(r.get('rationale', '')))}"
            f"<br><i>{html.escape(str(r.get('skill_rule', '')))}</i></td>"
            f"<td>{_pre(r.get('params'))}</td><td>{_pre(r.get('outputs'))}</td><td>{script}</td>"
            "</tr>"
        )
    head = (
        "<tr><th>keep</th><th>step</th><th>tool</th><th>why</th>"
        "<th>params</th><th>outputs</th><th>script</th></tr>"
    )
    return f"<table>{head}{''.join(rows)}</table>"


def _open_items(wd: Path) -> list[str] | None:
    stops = [r for r in _read_jsonl(wd / "reduce_hooks.jsonl") if r.get("event") == "stop"]
    return stops[-1].get("open", []) if stops else None


def _plot_links(wd: Path) -> list[str]:
    found = sorted({*wd.glob("*.html"), *wd.glob("plots/*.html")} - {wd / REPORT_NAME})
    return [str(p.relative_to(wd)) for p in found]


def _image_panel(image_path: str) -> tuple[str, str, dict]:
    """(bokeh head, bokeh body, image field). Plane 0 of every axis past RA/Dec."""
    import numpy as np
    from bokeh.embed import components
    from bokeh.models import ColorBar, LinearColorMapper
    from bokeh.plotting import figure
    from bokeh.resources import CDN

    from ms_inspect.util.casa_context import open_image

    with open_image(image_path) as ia:
        shape = [int(n) for n in ia.shape()]
        blc = [0] * len(shape)
        trc = [shape[0] - 1, shape[1] - 1] + [0] * (len(shape) - 2)
        plane = np.asarray(ia.getchunk(blc=blc, trc=trc)).reshape(shape[0], shape[1])
    step = max(1, int(np.ceil(max(plane.shape) / MAX_IMAGE_PIX)))
    view = plane[::step, ::step].T  # CASA is (x, y); bokeh draws rows as y
    finite = view[np.isfinite(view)]
    lo, hi = (
        (float(np.percentile(finite, 1)), float(np.percentile(finite, 99.9)))
        if finite.size
        else (0, 1)
    )
    mapper = LinearColorMapper(palette="Viridis256", low=lo, high=hi)
    fig = figure(
        title=Path(image_path).name,
        width=640,
        height=640,
        match_aspect=True,
        x_range=(0, view.shape[1]),
        y_range=(0, view.shape[0]),
    )
    fig.image(
        image=[np.nan_to_num(view, nan=lo)],
        x=0,
        y=0,
        dw=view.shape[1],
        dh=view.shape[0],
        color_mapper=mapper,
    )
    fig.add_layout(ColorBar(color_mapper=mapper, title="Jy/beam"), "right")
    script, div = components(fig)
    note = (
        f"shape {shape}; plane 0 of axes past RA/Dec; every {step}th pixel; "
        f"colour range is the 1st to 99.9th percentile of the shown plane"
    )
    return CDN.render() + script, div, fmt_field(image_path, "COMPLETE", note)


def run(
    workdir: str,
    summary: str = "",
    decisions: str = "",
    caveats: str = "",
    image_path: str = "",
) -> dict:
    """
    Write <workdir>/report.html.

    Args:
        workdir:    Directory holding reduction_log.jsonl.
        summary:    Model-written overview (plain text, blank line between paragraphs).
        decisions:  Decisions taken and the numbers they rest on (e.g. selfcal yes/no).
        caveats:    What the result does not support, and checks that were skipped.
        image_path: CASA image to show (plane 0); omit for no image panel.

    Returns:
        Standard envelope with report_path, n_steps, n_open_items, plots,
        replay_script, image.
    """
    from ms_inspect.exceptions import ComputationError

    wd = Path(workdir)
    if not wd.is_dir():
        raise ComputationError(f"workdir does not exist: {workdir}", ms_path=workdir)

    records = _read_jsonl(wd / "reduction_log.jsonl")
    open_items = _open_items(wd)
    plots = _plot_links(wd)
    replay = wd / "reduction_replay.py"
    if replay.exists():
        replay_html = (
            f'<p><a href="{replay.name}">{replay.name}</a> (from the last '
            "ms_reduction_log render; render again after changing keep_steps)</p>"
            f"<details><summary>show</summary><pre>{html.escape(replay.read_text())}</pre></details>"
        )
    else:
        replay_html = "<p>Not rendered yet: ms_reduction_log(action='render').</p>"
    warnings: list[str] = []

    head, img_div = "", "<p>No image given.</p>"
    image = fmt_field(None, "UNAVAILABLE", "no image_path given")
    if image_path:
        try:
            head, img_div, image = _image_panel(image_path)
        except Exception as exc:  # the report still renders without the image
            img_div = f"<p>Image could not be shown: {html.escape(str(exc))}</p>"
            image = fmt_field(image_path, "UNAVAILABLE", f"{type(exc).__name__}: {exc}")
            warnings.append(f"image panel skipped: {exc}")

    sections = [
        ("Summary", _paragraphs(summary)),
        ("Decisions", _paragraphs(decisions)),
        ("Caveats", _paragraphs(caveats)),
    ]
    if open_items is None:
        items_html = "<p>No reduce-hook Stop record in this workdir.</p>"
    elif open_items:
        items_html = "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in open_items) + "</ul>"
    else:
        items_html = "<p>None at the last Stop.</p>"
    plots_html = (
        "<ul>"
        + "".join(f'<li><a href="{html.escape(p)}">{html.escape(p)}</a></li>' for p in plots)
        + "</ul>"
        if plots
        else "<p>No HTML plots in the workdir.</p>"
    )
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    body = [
        f"<h1>Reduction report</h1><p>{html.escape(str(wd.resolve()))}<br>built {now}, "
        f"{len(records)} recorded steps</p>",
        *(f"<h2>{t}</h2>{b}" for t, b in sections if b),
        "<h2>Image</h2>",
        img_div,
        "<h2>Steps</h2>",
        "<p>Untick a step to drop it from the replay, then give the line below to the model. "
        "A dropped step's products are not made, so later steps that use them will fail.</p>",
        '<input id="keep" readonly value="all steps kept">',
        _steps_table(records, wd),
        "<h2>Open items at the last Stop</h2>",
        items_html,
        "<h2>Replay script</h2>",
        replay_html,
        "<h2>Plots</h2>",
        plots_html,
    ]
    page = (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Reduction report</title>"
        f"<style>{_CSS}</style><script>{_KEEP_JS}</script>{head}</head>"
        f"<body>{''.join(body)}</body></html>"
    )
    out = wd / REPORT_NAME
    out.write_text(page)

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=workdir,
        data={
            "report_path": fmt_field(str(out)),
            "n_steps": fmt_field(len(records)),
            "n_open_items": fmt_field(len(open_items))
            if open_items is not None
            else fmt_field(None, "UNAVAILABLE", "no reduce_hooks.jsonl Stop record"),
            "plots": fmt_field(plots),
            "replay_script": fmt_field(str(replay))
            if replay.exists()
            else fmt_field(None, "UNAVAILABLE", "ledger not rendered yet"),
            "image": image,
        },
        warnings=warnings,
        casa_calls=[f"write → {out}"] + (["ia.getchunk(plane 0)"] if image_path else []),
    )
