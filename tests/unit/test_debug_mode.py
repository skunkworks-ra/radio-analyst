"""
Unit tests for task_spec (the CASA task schemas) and debug_mode (the debug
pass-through on the ms_modify write tools).

No CASA required: the XML is a small file written by the test, put through the
schema translator, and task_spec is replaced by that where debug_mode looks it up.
"""

from __future__ import annotations

import inspect

import pytest

from casa_tasks.gen_schemas import _task_schema
from ms_inspect.exceptions import ComputationError
from ms_inspect.util.task_spec import spec_from_entry
from ms_modify import debug_mode


def parse_task_xml(path, signature=None):
    """TaskSpec for a test XML file, through the real translator (gen_schemas)."""
    return spec_from_entry(path.stem, _task_schema(path, signature or inspect.Signature()))


_XML = """<?xml version="1.0" encoding="UTF-8"?>
<casaxml xmlns="http://casa.nrao.edu/schema/psetTypes.html">
<task category="calibration" name="{name}" type="function">
<shortdescription>Test task</shortdescription>
<input>
  <param mustexist="true" name="vis" type="path"><shortdescription>input MS</shortdescription><value/></param>
  <param name="caltable" type="string"><shortdescription>output</shortdescription><value/></param>
  <param name="antenna" type="string"><shortdescription>antennas</shortdescription><value/></param>
  <param name="mode" type="string"><shortdescription>mode</shortdescription><value>manual</value></param>
  <param name="minsnr" type="double"><shortdescription>min SNR</shortdescription><value>3.0</value></param>
  <param name="minblperant" type="int"><shortdescription>min bl</shortdescription><value>4</value></param>
  <param name="solnorm" type="bool"><shortdescription>norm</shortdescription><value>False</value></param>
  <param subparam="true" name="interp" type="stringVec"><shortdescription>interp</shortdescription><value/></param>
  <param name="smodel" type="doubleVec"><shortdescription>model</shortdescription><value><value>1.0</value><value>0.0</value></value></param>
</input>
</task>
</casaxml>
"""


def _signature(
    vis="",
    caltable="",
    antenna="",
    mode="manual",
    minsnr=3.0,
    minblperant=4,
    solnorm=False,
    interp=[],  # noqa: B006 - a CASA-style signature default
    smodel=[1.0, 0.0],  # noqa: B006
):
    """The Python signature the test task's defaults come from."""


@pytest.fixture
def fake_specs(tmp_path, monkeypatch):
    """task_spec(name) translates the test XML, with the task named `name`."""

    def _spec(name):
        p = tmp_path / f"{name}.xml"
        p.write_text(_XML.format(name=name))
        return parse_task_xml(p, inspect.signature(_signature))

    import ms_inspect.util.task_spec as ts

    monkeypatch.setattr(ts, "task_spec", _spec)
    return _spec


class TestTaskSpecFromSchema:
    def test_params_types_defaults(self, fake_specs):
        spec = fake_specs("gaincal")
        assert spec.name == "gaincal"
        assert list(spec.params)[:3] == ["vis", "caltable", "antenna"]
        assert spec.params["minsnr"].default == 3.0
        assert spec.params["minblperant"].default == 4
        assert spec.params["solnorm"].default is False
        assert spec.params["mode"].default == "manual"
        assert spec.params["smodel"].default == [1.0, 0.0]
        assert spec.params["interp"].subparam is True
        assert spec.params["vis"].type == "path"


class TestValidate:
    def test_no_params_is_empty(self):
        assert debug_mode.validate(False, None, ("gaincal",)) == {}
        assert debug_mode.validate(True, {}, ("gaincal",)) == {}

    def test_params_without_debug_refused(self, fake_specs):
        with pytest.raises(ComputationError, match="without debug=True"):
            debug_mode.validate(False, {"gaincal": {"minsnr": 2.0}}, ("gaincal",))

    def test_valid_override_returned(self, fake_specs):
        out = debug_mode.validate(True, {"gaincal": {"minsnr": 2.0}}, ("gaincal",))
        assert out == {"gaincal": {"minsnr": 2.0}}

    def test_task_not_called_by_tool_refused(self, fake_specs):
        with pytest.raises(ComputationError, match="not a CASA task this tool calls"):
            debug_mode.validate(True, {"bandpass": {"minsnr": 2.0}}, ("gaincal",))

    def test_unknown_param_refused(self, fake_specs):
        with pytest.raises(ComputationError, match="no parameter"):
            debug_mode.validate(True, {"gaincal": {"nosuch": 1}}, ("gaincal",))

    @pytest.mark.parametrize("param", ["vis", "caltable"])
    def test_paths_protected(self, fake_specs, param):
        with pytest.raises(ComputationError, match="may not override"):
            debug_mode.validate(True, {"gaincal": {param: "x"}}, ("gaincal",))

    def test_flagdata_mode_protected(self, fake_specs):
        with pytest.raises(ComputationError, match="may not override"):
            debug_mode.validate(True, {"flagdata": {"mode": "clip"}}, ("flagdata",))

    @pytest.mark.parametrize("value", ["", " ", "*", [], None])
    def test_flagdata_selection_protected_whatever_the_value(self, fake_specs, value):
        # A widened selection ("*", [], None) flags as much as an empty one.
        with pytest.raises(ComputationError, match="may not override"):
            debug_mode.validate(True, {"flagdata": {"antenna": value}}, ("flagdata",))

    @pytest.mark.parametrize("param", ["savemodel", "interactive"])
    def test_tclean_model_and_interactive_protected(self, param):
        assert param in debug_mode.protected("tclean")

    def test_tclean_pbcor_protected(self):
        assert "pbcor" in debug_mode.protected("tclean")

    def test_gencal_caltype_protected(self):
        assert {"caltype", "parameter", "spw"} <= debug_mode.protected("gencal")

    def test_setjy_per_field_params_protected(self):
        assert {"field", "standard", "model", "fluxdensity"} <= debug_mode.protected("setjy")


class TestWrapAndInject:
    def test_wrap_merges_and_overrides(self):
        calls = []

        def task(**kw):
            calls.append(kw)

        debug_mode.wrap("gaincal", task, {"gaincal": {"minsnr": 2.0}})(minsnr=3.0, refant="ea04")
        assert calls == [{"minsnr": 2.0, "refant": "ea04"}]

    def test_wrap_leaves_summary_calls_alone(self):
        calls = []

        def task(**kw):
            calls.append(kw)

        wrapped = debug_mode.wrap("flagdata", task, {"flagdata": {"timecutoff": 3.0}})
        wrapped(vis="a.ms", mode="summary")
        wrapped(vis="a.ms", mode="tfcrop")
        assert calls == [
            {"vis": "a.ms", "mode": "summary"},
            {"vis": "a.ms", "mode": "tfcrop", "timecutoff": 3.0},
        ]

    def test_wrap_without_overrides_is_identity(self):
        def task(**kw):
            return kw

        assert debug_mode.wrap("gaincal", task, {}) is task
        assert debug_mode.wrap("gaincal", task, {"bandpass": {"x": 1}}) is task

    def test_inject_unchanged_without_overrides(self):
        script = "from casatasks import gaincal\ngaincal(vis='a')\n"
        assert debug_mode.inject(script, {}) == script

    def test_injected_script_runs_with_override(self):
        script = "from casatasks import gaincal\ngaincal(vis='a.ms', minsnr=3.0)\n"
        out = debug_mode.inject(script, {"gaincal": {"minsnr": 2.0}})
        assert out.index("_DEBUG_PARAMS") > out.index("from casatasks import gaincal")
        calls = []

        class _Casatasks:
            @staticmethod
            def gaincal(**kw):
                calls.append(kw)

        import sys
        import types

        mod = types.ModuleType("casatasks")
        mod.gaincal = _Casatasks.gaincal
        sys.modules["casatasks"] = mod
        try:
            exec(compile(out, "<script>", "exec"), {})  # noqa: S102 - test-built script
        finally:
            del sys.modules["casatasks"]
        assert calls == [{"vis": "a.ms", "minsnr": 2.0}]

    def test_inject_needs_casatasks_import(self):
        with pytest.raises(ComputationError, match="no top-level"):
            debug_mode.inject("import os\n", {"gaincal": {"minsnr": 2.0}})


_WRAPPERS = [
    "applycal",
    "bandpass",
    "flag_caltable",
    "flag_data",
    "fluxscale",
    "gaincal",
    "initial_bandpass",
    "initial_rflag",
    "polcal",
    "postcal_flag",
    "preflag",
    "priorcals",
    "rflag",
    "setjy",
    "tclean",
]


@pytest.mark.parametrize("name", _WRAPPERS)
def test_every_wrapper_takes_debug_and_names_its_tasks(name):
    import importlib
    import re

    mod = importlib.import_module(f"ms_modify.{name}")
    params = inspect.signature(mod.run).parameters
    assert "debug" in params and "debug_params" in params
    assert mod.DEBUG_TASKS, f"{name}: DEBUG_TASKS is empty"
    # DEBUG_TASKS must be exactly the CASA tasks on the template's import line
    # (less the two the wrappers use only for bookkeeping), where inject() puts
    # the rebinding.
    src = inspect.getsource(mod)
    line = re.search(r"^from casatasks import (.+)$", src, re.M).group(1)
    imported = {n.strip() for n in line.split(",")} - {"flagmanager", "plotweather"}
    assert set(mod.DEBUG_TASKS) == imported


def test_server_declares_debug_fields_last():
    from pydantic import BaseModel

    import ms_modify.server as srv

    models = [
        m
        for m in vars(srv).values()
        if isinstance(m, type) and issubclass(m, BaseModel) and "debug" in m.model_fields
    ]
    assert len(models) == len(_WRAPPERS)
    for m in models:
        assert list(m.model_fields)[-2:] == ["debug", "debug_params"], m.__name__


def test_gaincal_real_template_injects_and_compiles(fake_specs):
    from ms_modify.gaincal import _build_script

    script = _build_script(
        ms_str="a.ms",
        caltable="w/g.G",
        workdir="w",
        field="f",
        spw="",
        gaintype="G",
        calmode="p",
        solint="int",
        combine="",
        refant="ea04",
        minsnr=3.0,
        minblperant=4,
        solnorm=False,
        gaintable=[],
        interp=[],
        parang=True,
    )
    out = debug_mode.inject(script, {"gaincal": {"minsnr": 2.0}})
    compile(out, "<gaincal>", "exec")
    assert out.index("gaincal = _debug_wrap") < out.index("\ngaincal(")


def test_flag_data_script_carries_debug_override(tmp_path, monkeypatch, fake_specs):
    import ms_modify.flag_data as mod

    monkeypatch.setattr(mod, "validate_ms_path", lambda p: tmp_path / "t.ms")
    work = tmp_path / "work"
    work.mkdir()
    result = mod.run(
        "t.ms",
        str(work),
        reason="ea05 amp 40% low",
        antenna="ea05",
        debug=True,
        debug_params={"flagdata": {"minsnr": 2.0}},  # fake XML param
    )
    assert result["status"] == "ok"
    text = (work / "flag_data.py").read_text()
    assert "_DEBUG_PARAMS = {'flagdata': {'minsnr': 2.0}}" in text
    assert "flagdata = _debug_wrap('flagdata', flagdata)" in text
    assert any("debug mode" in w for w in result["warnings"])
