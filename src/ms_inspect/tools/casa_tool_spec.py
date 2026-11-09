"""
casa_tool_spec.py — ms_casa_tool_spec: the methods of an installed casatools class.

casatools ships no XML, so the signature and docstring come from introspection
of the installed class. The tier of each method is our hand-written policy
(util/casa_tool_policy.py), INFERRED. Read-only; no table is opened.
"""

from __future__ import annotations

import inspect

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.casa_context import _require_casatools
from ms_inspect.util.casa_tool_policy import POLICIES
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_casa_tool_spec"

_TIER_NOTE = "Method tiers are written by hand (ms_inspect/util/casa_tool_policy.py)."


def run(tool: str = "", method: str = "") -> dict:
    """
    Methods of casatools.<tool>, or one method's signature and docstring.

    Empty tool: the tools ms_casa_tool serves. Tool only: its public methods with
    the tier each has. Tool and method: signature, docstring and tier.
    """
    tool, method = tool.strip(), method.strip()
    if not tool:
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path="",
            data={"tools": sorted(POLICIES)},
            casa_calls=["POLICIES"],
        )
    pol = POLICIES.get(tool)
    if pol is None:
        raise ComputationError(f"ms_casa_tool serves {sorted(POLICIES)}, not {tool!r}.", ms_path="")
    casatools = _require_casatools()
    inst = getattr(casatools, tool)()
    public = sorted(m for m in dir(inst) if not m.startswith("_"))
    if not method:
        rows = [{"method": m, "tier": pol.tier(m) or "not_listed"} for m in public]
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path="",
            data={
                "tool": tool,
                "n_methods": len(rows),
                "methods": fmt_field(rows, flag="INFERRED", note=_TIER_NOTE),
            },
            casa_calls=[f"dir(casatools.{tool}())"],
        )
    if method not in public:
        raise ComputationError(f"casatools.{tool} has no method {method!r}.", ms_path="")
    fn = getattr(inst, method)
    try:
        sig = str(inspect.signature(fn))
    except (TypeError, ValueError):
        sig = ""
    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path="",
        data={
            "tool": tool,
            "method": method,
            "signature": fmt_field(sig or None, flag="COMPLETE" if sig else "UNAVAILABLE"),
            "docstring": inspect.getdoc(fn) or "",
            "tier": fmt_field(pol.tier(method) or "not_listed", flag="INFERRED", note=_TIER_NOTE),
        },
        casa_calls=[f"inspect.signature(casatools.{tool}().{method})"],
    )
