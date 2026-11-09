"""
Unit tests for the CASA task schemas (casa_tasks/gen_schemas.py and the
checked-in casa_task_schemas.json) and the CASA version pin.

The translator tests need no CASA. The tests that compare against the installed
casatasks skip only when casatasks is not importable; CI installs the pinned
version on every platform, so there they always run.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import inspect
import os
import re
import tomllib
from pathlib import Path

import pytest

from casa_tasks.gen_schemas import _json_value, _task_schema, _type_schema
from ms_inspect.util.task_spec import load_schemas, task_names, task_spec

REPO = Path(__file__).resolve().parents[2]
PINNED = load_schemas()["casatasks_version"]

# ------------------------------------------------------------- installed CASA


def test_schemas_match_installed_casatasks():
    if importlib.util.find_spec("casatasks") is None:
        _skip_or_fail("casatasks is not installed")
    from casa_tasks.gen_schemas import build

    assert build()["tasks"] == load_schemas()["tasks"], (
        "casa_task_schemas.json is stale for the installed casatasks; "
        "run `pixi run gen-casa-schemas` and review the diff"
    )


@pytest.mark.parametrize("package", ["casatools", "casatasks"])
def test_installed_casa_is_the_pinned_version(package):
    try:
        installed = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        _skip_or_fail(f"{package} is not installed")
    assert installed == PINNED, (
        f"{package} {installed} is installed; the task schemas and the pin are for {PINNED}"
    )


# ------------------------------------------------------------------ the pin


def _pins(text: str) -> set[str]:
    """Every casatools/casatasks version pinned with == in a file."""
    return set(re.findall(r"casat(?:asks|ools)\s*=?\s*\"?==\s*([0-9][0-9.]*)", text))


def _ranges(text: str) -> list[str]:
    """casatools/casatasks requirements given as a range instead of a pin."""
    return re.findall(
        r"casat(?:asks|ools)\s*=?\s*(?:\{[^}]*version\s*=\s*)?\"?(?:>=|~=|<=|>|<)\s*[0-9]", text
    )


def _skip_or_fail(reason: str) -> None:
    """Skip on a machine without CASA; fail in CI, which installs the pin everywhere."""
    if os.environ.get("CI"):
        pytest.fail(f"{reason}; CI must install the pinned CASA")
    pytest.skip(reason)


@pytest.mark.parametrize(
    "path",
    [
        "pixi.toml",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        "README.md",
        "scripts/dev/install-local.sh",
    ],
)
def test_every_pin_is_the_schema_version(path):
    text = (REPO / path).read_text()
    pins = _pins(text)
    assert pins == {PINNED}, f"{path} pins {pins or 'nothing'}; the task schemas are for {PINNED}"
    assert not _ranges(text), f"{path} gives a version range: {_ranges(text)}"


def test_pixi_pins_both_packages_exactly():
    deps = tomllib.loads((REPO / "pixi.toml").read_text())["target"]["linux-64"][
        "pypi-dependencies"
    ]
    assert deps["casatools"] == deps["casatasks"] == f"=={PINNED}"


def test_plugin_scripts_pin_the_schema_version():
    lib = (REPO / "scripts/plugin/env-lib.sh").read_text()
    assert re.search(rf"^RA_CASA_VERSION={re.escape(PINNED)}$", lib, re.M), (
        f"scripts/plugin/env-lib.sh RA_CASA_VERSION is not {PINNED}"
    )
    for script in ("scripts/plugin/launch.sh", "scripts/plugin/ensure-env.sh"):
        text = (REPO / script).read_text()
        assert "pip install casatools casatasks" not in text, f"{script} installs unpinned CASA"
        assert "ra_casa_install" in text and "ra_casa_check" in text, script


# --------------------------------------------------------------- translator


def test_vec_type_accepts_scalar_or_list():
    prop = load_schemas()["tasks"]["applycal"]["params"]["gaintable"]
    assert {"type": "string"} in prop["anyOf"]
    assert {"type": "array", "items": {"type": "string"}} in prop["anyOf"]


@pytest.mark.parametrize(
    ("xml_type", "expected"),
    [
        ("path", {"type": "string"}),
        ("bool", {"type": "boolean"}),
        ("int", {"type": "integer"}),
        ("double", {"type": "number"}),
        ("record", {"type": "object"}),
        ("any", {}),
        ("variant", {}),
    ],
)
def test_type_mapping(xml_type, expected):
    assert _type_schema(xml_type, "t", "p") == expected


def test_unknown_xml_type_is_an_error():
    with pytest.raises(ValueError, match="t.p: XML type 'quaternion'"):
        _type_schema("quaternion", "t", "p")


_XML = """<?xml version="1.0" encoding="UTF-8"?>
<casaxml xmlns="http://casa.nrao.edu/schema/psetTypes.html">
<task name="demo"><shortdescription>Demo task</shortdescription>
<input>
  <param mustexist="true" name="vis" type="path"><shortdescription>input MS</shortdescription><value/></param>
  <param subparam="true" name="minsnr" type="double"><shortdescription>min SNR</shortdescription>
    <value>9.0</value></param>
  <param name="mode" type="string"><shortdescription>mode</shortdescription><value>a</value>
    <allowed kind="enum"><value>a</value><value>b</value></allowed></param>
</input></task></casaxml>
"""


def _demo_signature(vis="", minsnr=3.0, mode="a"):
    """Signature defaults; minsnr deliberately differs from the XML <value>."""


def test_translator_records_meta_with_signature_default(tmp_path):
    xml = tmp_path / "demo.xml"
    xml.write_text(_XML)
    entry = _task_schema(xml, inspect.signature(_demo_signature))
    assert entry["description"] == "Demo task"
    assert list(entry["params"]) == list(entry["meta"]) == ["vis", "minsnr", "mode"]
    assert entry["meta"]["vis"] == {
        "xml_type": "path",
        "default": "",
        "subparam": False,
        "mustexist": True,
    }
    assert entry["meta"]["minsnr"]["default"] == 3.0  # signature, not the XML's 9.0
    assert entry["meta"]["minsnr"]["subparam"] is True
    assert "Default: 3.0." in entry["params"]["minsnr"]["description"]
    assert "Documented values: 'a', 'b'." in entry["params"]["mode"]["description"]
    assert "enum" not in entry["params"]["mode"]
    for prop in entry["params"].values():  # meta never leaks into the MCP schema
        assert not {"xml_type", "default", "subparam", "mustexist"} & set(prop)


@pytest.mark.parametrize("value", ["", "inf", 4, 3.0, False, [1.0, 0.0], [], {"a": 1}])
def test_json_value_keeps_exact_values(value):
    assert _json_value(value, "t.p") == value


@pytest.mark.parametrize("value", [(1, 2), float("inf"), float("nan"), object(), [(1, 2)]])
def test_json_value_refuses_values_json_cannot_hold(value):
    with pytest.raises(ValueError, match="t.p: default"):
        _json_value(value, "t.p")


@pytest.mark.parametrize(
    "text",
    [
        'casatools = ">=6.6"',
        'casatasks = { version = ">=6.6" }',
        '"casatools>=6.7.0",',
        "pip install casatasks~=6.7",
    ],
)
def test_ranges_finds_every_range_form(text):
    assert _ranges(text)


# --------------------------------------------------------------- the file


def test_every_param_has_meta_and_every_meta_a_param():
    for name, entry in load_schemas()["tasks"].items():
        assert list(entry["params"]) == list(entry["meta"]), name


def test_task_spec_reads_the_schemas():
    spec = task_spec("gaincal")
    assert spec.params["vis"].mustexist is True
    assert spec.params["vis"].type == "path"
    assert spec.params["minsnr"].default == 3.0
    assert "gaincal" in task_names() and len(task_names()) == len(load_schemas()["tasks"])
    with pytest.raises(ValueError, match="no CASA task 'nosuch'"):
        task_spec("nosuch")
