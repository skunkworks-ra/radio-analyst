"""
Unit tests for ms_create/report.py — ms_report HTML builder. No CASA required
(the image panel is exercised only for its failure path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ms_create import reduction_log, report


@pytest.fixture
def workdir(tmp_path):
    for name in ("preflag.py", "gaincal_G0.py"):
        (tmp_path / name).write_text("print(1)\n")
    reduction_log.run("append", str(tmp_path), tool="ms_apply_preflag", script_path="preflag.py")
    reduction_log.run(
        "append",
        str(tmp_path),
        tool="ms_gaincal",
        params={"calmode": "p", "execute": False},
        outputs={"phase_rms_deg": 3.1},
        rationale="G0 <before> bandpass",
        script_path="gaincal_G0.py",
    )
    (tmp_path / "plots").mkdir()
    (tmp_path / "plots" / "caltables_overview.html").write_text("<html></html>")
    hook = {"event": "stop", "session_id": "s", "open": ["[image] m2 ms_tclean: not called"]}
    (tmp_path / "reduce_hooks.jsonl").write_text(json.dumps(hook) + "\n")
    return tmp_path


def test_report_lays_out_ledger_items_plots_and_sections(workdir):
    env = report.run(
        str(workdir), summary="Para one.\n\nPara <two>.", decisions="No selfcal: DR 25."
    )
    page = (workdir / "report.html").read_text()
    assert env["data"]["n_steps"]["value"] == 2
    assert env["data"]["n_open_items"]["value"] == 1
    assert page.count('class="keep"') == 2
    assert "G0 &lt;before&gt; bandpass" in page and "<before>" not in page
    assert "<p>Para one.</p><p>Para &lt;two&gt;.</p>" in page
    assert "No selfcal: DR 25." in page
    assert "[image] m2 ms_tclean: not called" in page
    assert 'href="plots/caltables_overview.html"' in page
    assert 'href="gaincal_G0.py"' in page
    assert "keep_steps=[" in page  # the composer the boxes drive


def test_replay_script_is_linked_once_rendered(workdir):
    env = report.run(str(workdir))
    assert env["data"]["replay_script"]["flag"] == "UNAVAILABLE"
    reduction_log.run("render", str(workdir))
    env = report.run(str(workdir))
    page = (workdir / "report.html").read_text()
    assert env["data"]["replay_script"]["value"].endswith("reduction_replay.py")
    assert 'href="reduction_replay.py"' in page and "_run_script(" in page


def test_no_hook_log_is_unavailable_not_zero(tmp_path):
    env = report.run(str(tmp_path))
    assert env["data"]["n_open_items"]["flag"] == "UNAVAILABLE"
    assert env["data"]["n_steps"]["value"] == 0


def test_missing_image_still_writes_report(workdir):
    env = report.run(str(workdir), image_path=str(workdir / "nope.image"))
    assert (workdir / "report.html").exists()
    assert env["data"]["image"]["flag"] == "UNAVAILABLE"
    assert env["warnings"]


def test_missing_workdir_raises(tmp_path):
    from ms_inspect.exceptions import ComputationError

    with pytest.raises(ComputationError):
        report.run(str(tmp_path / "nope"))


def test_sections_render_headings_lists_code_and_step_links(workdir):
    text = (
        "## Calibrate\n"
        "- refant `refant = ea21` [step 2, model choice]\n"
        "- solint per skill 07 [step 2, skill 07]\n"
        "Plain line."
    )
    report.run(str(workdir), decisions=text)
    page = (workdir / "report.html").read_text()
    assert "<h3>Calibrate</h3>" in page
    assert "<ul><li>refant <code>refant = ea21</code>" in page
    assert '<a href="#step-2" class="choice">[step 2, model choice]</a>' in page
    assert '<a href="#step-2">[step 2, skill 07]</a>' in page
    assert "<p>Plain line.</p>" in page
    assert 'id="step-2"' in page


def test_params_differing_from_tool_default_are_highlighted(workdir):
    (workdir / "gaincal_G0.py").write_text("x = 1\n    calmode      = 'p',\n")
    report.run(str(workdir))
    page = (workdir / "report.html").read_text()
    # calmode 'p' differs from ms_gaincal's default; its script line is given
    assert '<div class="set">calmode = &quot;p&quot; <i>(default' in page
    assert "script line 2)" in page
    # execute=False is the default: not highlighted
    assert "<div>execute = false</div>" in page


def test_dead_script_path_is_plain_text(tmp_path):
    script = tmp_path / "applycal.py"
    script.write_text("print(1)\n")
    reduction_log.run(
        "append",
        str(tmp_path),
        tool="ms_applycal",
        params={"execute": False},
        script_path=str(script),
    )
    script.unlink()  # e.g. a container path that does not exist where the report is read
    report.run(str(tmp_path))
    steps = (tmp_path / "report.html").read_text().split("<h2>Steps")[1].split("<h2>Open")[0]
    assert "applycal.py" in steps
    assert 'href="applycal.py"' not in steps


def test_workdir_pngs_are_embedded_in_order(workdir):
    from ms_create.report import run

    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
    )
    (Path(workdir) / "img_hogbom.png").write_bytes(png)
    (Path(workdir) / "plots").mkdir(exist_ok=True)
    (Path(workdir) / "plots" / "gain.png").write_bytes(png)
    out = run(workdir)
    page = (Path(workdir) / "report.html").read_text()
    assert page.count("data:image/png;base64,") == 2
    assert "<figcaption>img_hogbom.png</figcaption>" in page
    assert "<figcaption>plots/gain.png</figcaption>" in page
    assert out["data"]["images_embedded"]["value"] == ["img_hogbom.png", "plots/gain.png"]


def test_long_backtick_span_is_plain_text(workdir):
    from ms_create.report import MAX_CODE_SPAN, run

    long = "x " * MAX_CODE_SPAN
    run(workdir, summary=f"- `refant = ea21` and `{long}`")
    page = (Path(workdir) / "report.html").read_text()
    assert "<code>refant = ea21</code>" in page
    assert f"<code>{long}</code>" not in page and long in page


def test_accounting_table_and_rebuild_without_inputs(workdir):
    from ms_create.report import run

    run(workdir, summary="- first pass")
    acct = {
        "total_cost_usd": 1.7,
        "model_cost_usd": {"m-sonnet": 1.45, "m-haiku": 0.25},
        "num_turns": 41,
        "duration_s": 2730,
        "permission_denials": [],
        "note": "measured and estimated",
        "sessions": [
            {
                "session": "main (orchestrator)",
                "model": "m-sonnet",
                "tool_calls": 40,
                "output_tokens": 57204,
                "tokens_exact": True,
                "cost_usd_estimate": 1.45,
            },
            {
                "session": "radio-analyst:precal-stage",
                "model": "m-haiku",
                "tool_calls": 34,
                "output_tokens": 336,
                "tokens_exact": False,
                "cost_usd_estimate": 0.05,
            },
        ],
    }
    (Path(workdir) / "accounting.json").write_text(json.dumps(acct))
    run(workdir, reuse_saved=True)  # rebuild with the saved narrative
    page = (Path(workdir) / "report.html").read_text()
    assert "first pass" in page
    assert "Cost and sessions" in page and "radio-analyst:precal-stage" in page
    assert "≥ 336" in page and "0.0500 (est.)" in page and "1.4500<" in page


def test_empty_call_does_not_replay_saved_narrative(workdir):
    from ms_create.report import run

    run(workdir, summary="- old narrative")
    out = run(workdir)
    page = (Path(workdir) / "report.html").read_text()
    assert "old narrative" not in page
    assert out["data"]["narrative_source"]["value"] == "this call"
