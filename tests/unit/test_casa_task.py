"""
Unit tests for casa_task (generic guard for CASA tasks with no dedicated tool)
and casa_task_spec. No CASA required: the task XML is written by the test and
put through the schema translator.
"""

from __future__ import annotations

import inspect
import os

import pytest

from casa_tasks.gen_schemas import _task_schema
from ms_inspect.exceptions import ComputationError
from ms_inspect.util.task_spec import spec_from_entry


def parse_task_xml(path, signature=None):
    """TaskSpec for a test XML file, through the real translator (gen_schemas)."""
    return spec_from_entry(path.stem, _task_schema(path, signature or inspect.Signature()))


_XML = """<?xml version="1.0" encoding="UTF-8"?>
<casaxml xmlns="http://casa.nrao.edu/schema/psetTypes.html">
<task category="manipulation" name="{name}" type="function">
<shortdescription>Test task</shortdescription>
<input>
  <param mustexist="true" name="vis" type="path"><shortdescription>input MS</shortdescription><value/></param>
  <param name="caltable" type="string"><shortdescription>output caltable</shortdescription><value/></param>
  <param name="outputvis" type="string"><shortdescription>output MS</shortdescription><value/></param>
  <param name="fitorder" type="int"><shortdescription>order</shortdescription><value>1</value></param>
</input>
</task>
</casaxml>
"""


@pytest.fixture
def fake_spec(tmp_path, monkeypatch):
    def _spec(name):
        p = tmp_path / f"{name}.xml"
        p.write_text(_XML.format(name=name))
        return parse_task_xml(p)

    import ms_modify.casa_task as ct

    monkeypatch.setattr(ct, "task_spec", _spec)
    return _spec


@pytest.fixture
def work(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    return w


def _ms(path):
    path.mkdir()
    (path / "table.info").write_text("Type = Measurement Set\n")
    return path


def test_dedicated_task_refused(work):
    from ms_modify.casa_task import run

    with pytest.raises(ComputationError, match="ms_gaincal wraps it"):
        run("gaincal", {}, str(work))


def test_every_dedicated_module_has_a_tool_name():
    from ms_modify.casa_task import DEDICATED, wrapped_tasks

    assert set(wrapped_tasks()) == set(DEDICATED)


def test_unknown_param_refused(fake_spec, work):
    from ms_modify.casa_task import run

    with pytest.raises(ComputationError, match="no parameter"):
        run("statwt", {"nosuch": 1}, str(work))


def test_missing_workdir_refused(fake_spec, tmp_path):
    from ms_modify.casa_task import run

    with pytest.raises(ComputationError, match="workdir does not exist"):
        run("statwt", {}, str(tmp_path / "nope"))


def test_output_outside_workdir_refused(fake_spec, work, tmp_path):
    from ms_modify.casa_task import run

    with pytest.raises(ComputationError, match="not inside workdir"):
        run("split", {"vis": "a.ms", "outputvis": str(tmp_path / "b.ms")}, str(work))


def test_new_vis_without_mustexist_is_an_output(work, monkeypatch):
    import ms_modify.casa_task as ct

    monkeypatch.setattr(
        ct,
        "task_spec",
        lambda name: parse_task_xml(
            _write_xml(work.parent, name, 'mustexist="true" name="fitsfile" type="path"')
        ),
    )
    outputs, _ = ct._classify("importuvfits", {"fitsfile": "x.uvfits", "vis": str(work / "x.ms")})
    assert outputs == {"vis": str(work / "x.ms")}


def test_output_equal_to_input_ms_refused(fake_spec, work):
    from ms_modify.casa_task import run

    ms = _ms(work / "a.ms")
    with pytest.raises(ComputationError):
        run("split", {"vis": str(ms), "outputvis": str(ms)}, str(work))


def test_existing_non_caltable_output_refused(fake_spec, work):
    from ms_modify.casa_task import run

    (work / "b.out").mkdir()
    with pytest.raises(ComputationError, match="already exists"):
        run("split", {"vis": "a.ms", "outputvis": str(work / "b.out")}, str(work))


def test_script_written_with_params_and_caltable_archive(fake_spec, work):
    from ms_modify.casa_task import run

    ct = str(work / "ant.cal")
    result = run("gencal", {"vis": "a.ms", "caltable": ct, "fitorder": 2}, str(work))
    assert result["status"] == "ok"
    script = work / "casa_task_gencal.py"
    text = script.read_text()
    assert "from casatasks import gencal" in text
    assert f"_safe_rm_table({ct!r})" in text
    assert f"'caltable': {ct!r}" in text and "'fitorder': 2" in text
    assert "casa_task_gencal.py.result.json" in text
    assert result["data"]["outputs"] == {"caltable": ct}
    compile(text, str(script), "exec")


def test_in_place_task_records_input_ms_as_product(fake_spec, work):
    from ms_modify.casa_task import run

    ms = _ms(work.parent / "a.ms")
    result = run("statwt", {"vis": str(ms), "fitorder": 1}, str(work))
    text = (work / "casa_task_statwt.py").read_text()
    assert f"_product = {str(ms)!r}" in text
    assert "{'modifies_in_place': [" in text
    assert result["data"]["modifies_in_place"]["value"] == [str(ms)]
    # nothing to archive: no top-level _safe_rm_table call
    assert not any(line.startswith("_safe_rm_table(") for line in text.splitlines())


def test_casa_task_spec_lists_params(tmp_path, monkeypatch):
    import ms_inspect.tools.casa_task_spec as cts

    def _spec(name):
        p = tmp_path / f"{name}.xml"
        p.write_text(_XML.format(name=name))
        return parse_task_xml(p)

    monkeypatch.setattr(cts, "task_spec", _spec)
    out = cts.run("statwt")
    assert out["data"]["task"] == "statwt"
    names = [p["name"] for p in out["data"]["params"]]
    assert names == ["vis", "caltable", "outputvis", "fitorder"]
    assert out["data"]["params"][0]["mustexist"] is True
    assert "docs_path" in out["data"]


def test_docs_path_uses_env_root(tmp_path, monkeypatch):
    import ms_inspect.tools.casa_task_spec as cts

    page = tmp_path / ".claude" / "skills" / "casa-docs" / "tasks" / "statwt.rst"
    page.parent.mkdir(parents=True)
    page.write_text("statwt page\n")
    monkeypatch.setenv("RADIO_ANALYST_ROOT", str(tmp_path))
    assert cts.docs_path("statwt") == str(page)
    assert cts.docs_path("nosuch") is None


def test_servers_register_the_two_tools():
    import asyncio

    import ms_inspect.server as ins
    import ms_modify.server as mod

    inspect_names = {t.name for t in asyncio.run(ins.mcp.list_tools())}
    modify_names = {t.name for t in asyncio.run(mod.mcp.list_tools())}
    assert "ms_casa_task_spec" in inspect_names
    assert "ms_casa_task" in modify_names


def test_rmtables_refused(work):
    from ms_modify.casa_task import run

    with pytest.raises(ComputationError, match="deletes any table"):
        run("rmtables", {"tablenames": ["/data/x.ms"]}, str(work))


def test_lock_paths_cover_inputs_outputs_and_list_entries(tmp_path, monkeypatch):
    from ms_modify.casa_task import lock_paths

    monkeypatch.chdir(tmp_path)
    paths = lock_paths(
        {
            "vis": ["a.ms", "b.ms"],
            "concatvis": "c.ms",
            "caltable": "~/x.G",
            "gaintable": ["g1", "g2"],
            "fitorder": 1,
            "outputvis": "",
        },
        "W",
    )
    assert sorted(paths) == sorted(
        [
            str(tmp_path / "a.ms"),
            str(tmp_path / "b.ms"),
            str(tmp_path / "c.ms"),
            os.path.expanduser("~/x.G"),
            str(tmp_path / "g1"),
            str(tmp_path / "g2"),
        ]
    )


def test_lock_paths_without_a_path_lock_the_workdir():
    from ms_modify.casa_task import lock_paths

    assert lock_paths({"fitorder": 1}, "W") == ["W"]


def test_two_calls_writing_one_output_share_a_lock(tmp_path):
    """Different input MSs, same output MS: their lock sets overlap.

    outputvis is an output only (not in INPUT_PARAMS), so this fails if outputs
    are left out of the lock set.
    """
    from ms_modify.casa_task import INPUT_PARAMS, lock_paths

    assert "outputvis" not in INPUT_PARAMS
    out = str(tmp_path / "out.ms")
    first = lock_paths({"vis": str(tmp_path / "a.ms"), "outputvis": out}, "W")
    second = lock_paths({"vis": str(tmp_path / "b.ms"), "outputvis": out}, "W")
    assert set(first) & set(second) == {out}


def test_existing_imagename_prefix_is_an_input(fake_spec, work, monkeypatch):
    import ms_modify.casa_task as ct

    (work / "img.image").mkdir()
    monkeypatch.setattr(
        ct,
        "task_spec",
        lambda name: parse_task_xml(
            _write_xml(work.parent, name, 'name="imagename" type="string"')
        ),
    )
    outputs, inputs = ct._classify("deconvolve", {"imagename": str(work / "img")})
    assert outputs == {} and inputs == [str(work / "img")]


def _write_xml(d, name, param_attrs):
    p = d / f"{name}.xml"
    p.write_text(
        '<?xml version="1.0"?><casaxml xmlns="http://casa.nrao.edu/schema/psetTypes.html">'
        f'<task name="{name}"><input><param {param_attrs}><value/></param>'
        '<param name="vis" type="path"><value/></param>'
        '<param name="mode" type="string"><value/></param>'
        "</input></task></casaxml>"
    )
    return p


def test_flagcmd_script_saves_flag_version_first(work, monkeypatch):
    import ms_modify.casa_task as ct

    monkeypatch.setattr(
        ct,
        "task_spec",
        lambda name: parse_task_xml(_write_xml(work.parent, name, 'name="inpmode" type="string"')),
    )
    ms = _ms(work.parent / "a.ms")
    result = ct.run("flagcmd", {"vis": str(ms), "inpmode": "list"}, str(work))
    text = (work / "casa_task_flagcmd.py").read_text()
    assert text.index("_flagmanager(vis=") < text.index("_result = flagcmd(")
    assert any("FLAG only" in w for w in result["warnings"])
    assert result["data"]["modifies_in_place"]["value"] == [str(ms)]


def test_script_json_encoder_handles_numpy_and_complex():
    import numpy as np

    from ms_modify.casa_task import _JSON_DEFAULT_SNIPPET

    ns: dict = {}
    exec(_JSON_DEFAULT_SNIPPET, ns)  # noqa: S102 - our own snippet
    import json

    out = json.loads(
        json.dumps(
            ns["_json_safe"]({("a", 1): np.arange(3), "c": 1 + 2j, "n": np.int64(5)}),
            default=ns["_json_default"],
        )
    )
    assert out == {"('a', 1)": [0, 1, 2], "c": [1.0, 2.0], "n": 5}


def test_import_task_refuses_an_existing_vis(work, monkeypatch):
    import ms_modify.casa_task as ct

    monkeypatch.setattr(
        ct,
        "task_spec",
        lambda name: parse_task_xml(
            _write_xml(work.parent, name, 'mustexist="true" name="fitsfile" type="path"')
        ),
    )
    ms = _ms(work / "x.ms")
    with pytest.raises(ComputationError):
        ct.run("importuvfits", {"fitsfile": "x.uvfits", "vis": str(ms)}, str(work))
