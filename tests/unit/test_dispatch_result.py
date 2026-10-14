"""dispatch.envelope_result: one envelope, two views, and isError on failure."""

from __future__ import annotations

import json

from ms_inspect.exceptions import MSNotFoundError
from ms_inspect.util.dispatch import envelope_result
from ms_inspect.util.worker import run_tool_sync


def test_ok_envelope_is_structured_and_text_with_the_same_values():
    env = {"tool": "t", "status": "ok", "data": {"n": 1, "x": 0.5}, "warnings": []}
    res = envelope_result(env)
    assert res.isError is False
    assert res.structuredContent == env
    assert json.loads(res.content[0].text) == env


def test_error_envelope_sets_is_error():
    def boom(path):
        raise MSNotFoundError("gone", ms_path=path)

    res = envelope_result(json.loads(run_tool_sync(boom, "/data/missing.ms")))
    assert res.isError is True
    assert res.structuredContent["error_type"] == "MS_NOT_FOUND"


def test_non_json_values_match_in_both_views():
    """default=str runs once, before either view is built."""
    from pathlib import Path

    res = envelope_result({"status": "ok", "data": {"p": Path("/a/b")}})
    assert res.structuredContent["data"]["p"] == "/a/b"
    assert json.loads(res.content[0].text)["data"]["p"] == "/a/b"
