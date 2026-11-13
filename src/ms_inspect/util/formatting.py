"""
util/formatting.py — Response envelope construction and output formatting.

Defines the completeness flag schema and the standard JSON response envelope
described in design_docs/DESIGN.md §4 and §7.1.

No CASA dependency.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Completeness flag literals
# ---------------------------------------------------------------------------
CompletionFlag = Literal["COMPLETE", "INFERRED", "PARTIAL", "SUSPECT", "UNAVAILABLE"]

_FLAG_SEVERITY: dict[str, int] = {
    "COMPLETE": 0,
    "INFERRED": 1,
    "PARTIAL": 2,
    "SUSPECT": 3,
    "UNAVAILABLE": 4,
}


def field(
    value: Any,
    flag: CompletionFlag = "COMPLETE",
    note: str | None = None,
) -> dict:
    """
    Wrap a value with its completeness flag.

    Used to construct every data field in a tool response per design_docs/DESIGN.md §4.

    Example:
        field(1.4e9, "COMPLETE")
        → {"value": 1400000000.0, "flag": "COMPLETE"}

        field(None, "UNAVAILABLE", note="Telescope name unknown")
        → {"value": None, "flag": "UNAVAILABLE", "note": "..."}
    """
    result: dict[str, Any] = {"value": value, "flag": flag}
    if note is not None:
        result["note"] = note
    return result


def worst_flag(flags: list[CompletionFlag]) -> CompletionFlag:
    """Return the worst-case completeness flag from a list."""
    if not flags:
        return "COMPLETE"
    return max(flags, key=lambda f: _FLAG_SEVERITY.get(f, 0))  # type: ignore[return-value]


def _casa_version() -> str:
    """Return casatools version string, or 'unavailable' if not installed."""
    try:
        return importlib.metadata.version("casatools")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def response_envelope(
    tool_name: str,
    ms_path: str,
    data: dict,
    warnings: list[str] | None = None,
    casa_calls: list[str] | None = None,
    extra_flags: list[CompletionFlag] | None = None,
) -> dict:
    """
    Wrap tool output in the standard response envelope (design_docs/DESIGN.md §7.1).

    Computes completeness_summary as the worst flag found anywhere in `data`
    (recursively) combined with any flags in `extra_flags`.

    Args:
        tool_name:    Name of the calling tool (e.g. 'ms_observation_info').
        ms_path:      Absolute path to the Measurement Set.
        data:         The tool's result dictionary.
        warnings:     Non-fatal warning strings.
        casa_calls:   List of CASA API calls made (for provenance).
        extra_flags:  Additional flags to fold into completeness_summary.

    Returns:
        Standard envelope dict.
    """
    offloaded_flags = data.pop("_offloaded_flags", None)
    offloaded_field_flags = data.pop("_offloaded_field_flags", None)

    found_flags = _collect_flags(data)
    if offloaded_flags:
        found_flags.extend(offloaded_flags)
    if extra_flags:
        found_flags.extend(extra_flags)

    env: dict[str, Any] = {
        "tool": tool_name,
        "ms_path": ms_path,
        "status": "ok",
        "completeness_summary": worst_flag(found_flags) if found_flags else "COMPLETE",
        "data": data,
        "warnings": warnings or [],
        "provenance": {
            "casa_calls": casa_calls or [],
            "casatools_version": _casa_version(),
        },
    }
    if offloaded_field_flags:
        env["_offloaded_field_flags"] = offloaded_field_flags
    return env


def error_envelope(
    tool_name: str,
    ms_path: str | None,
    error_type: str,
    message: str,
) -> dict:
    """
    Construct a standard error response envelope (design_docs/DESIGN.md §7.1).
    """
    return {
        "tool": tool_name,
        "ms_path": ms_path,
        "status": "error",
        "error_type": error_type,
        "message": message,
        "data": None,
    }


def _is_field_wrapper(obj: Any) -> bool:
    """Return True when obj is a field() wrapper dict."""
    if not isinstance(obj, dict):
        return False
    keys = set(obj.keys())
    return (
        "value" in keys
        and "flag" in keys
        and keys <= {"value", "flag", "note"}
        and obj.get("flag") in _FLAG_SEVERITY
    )


def _format_index_group(indices: list[int], total_len: int) -> str:
    """Format sorted list indices concisely using [*] or contiguous a..b ranges."""
    if len(indices) == 1:
        return f"[{indices[0]}]"
    if total_len >= 2 and len(indices) == total_len:
        return "[*]"
    parts: list[str] = []
    start = end = indices[0]
    for idx in indices[1:]:
        if idx == end + 1:
            end = idx
        else:
            parts.append(
                f"{start}..{end}"
                if end - start >= 2
                else (f"{start},{end}" if end > start else str(start))
            )
            start = end = idx
    parts.append(
        f"{start}..{end}" if end - start >= 2 else (f"{start},{end}" if end > start else str(start))
    )
    return f"[{','.join(parts)}]"


def _join_rel_path(prefix: str, rel: str) -> str:
    if not rel:
        return prefix
    if rel.startswith("["):
        return f"{prefix}{rel}"
    return f"{prefix}.{rel}"


def unwrap_fields(obj: Any) -> tuple[Any, dict[str, dict[str, str]]]:
    """
    Recursively unwrap all field() dicts to bare values and collect field_flags.

    Every field() wrapper {"value": v, "flag": f, ...} is replaced by its
    recursively unwrapped `v`. Wrappers where `flag != "COMPLETE"` or `note`
    is non-empty are recorded in the returned `field_flags` dict, collapsing
    identical (flag, note) entries across array elements into wildcard (`[*]`)
    or range (`[a..b]`) paths.
    """
    if _is_field_wrapper(obj):
        inner_val, inner_flags = unwrap_fields(obj["value"])
        out_flags: dict[str, dict[str, str]] = {}
        flag_val: str = obj["flag"]
        note_val: str | None = obj.get("note")
        if flag_val != "COMPLETE" or note_val:
            entry: dict[str, str] = {"flag": flag_val}
            if note_val:
                entry["note"] = note_val
            out_flags[""] = entry
        for rel, info in inner_flags.items():
            if rel:
                out_flags[rel] = info
        return inner_val, out_flags

    if isinstance(obj, dict):
        out_dict: dict[str, Any] = {}
        out_flags = {}
        for k, v in obj.items():
            uv, sub_flags = unwrap_fields(v)
            out_dict[k] = uv
            for rel, info in sub_flags.items():
                out_flags[_join_rel_path(str(k), rel)] = info
        return out_dict, out_flags

    if isinstance(obj, list):
        n = len(obj)
        out_list: list[Any] = []
        grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for idx, item in enumerate(obj):
            uitem, sub_flags = unwrap_fields(item)
            out_list.append(uitem)
            for rel, info in sub_flags.items():
                grouped[(rel, info["flag"], info.get("note", ""))].append(idx)

        out_flags = {}
        for (rel, flag_val, note_val), indices in grouped.items():
            idx_expr = _format_index_group(indices, n)
            entry = {"flag": flag_val}
            if note_val:
                entry["note"] = note_val
            out_flags[_join_rel_path(idx_expr, rel)] = entry
        return out_list, out_flags

    return obj, {}


def wire_envelope(obj: Any) -> Any:
    """
    Convert an internal response_envelope() into the symmetric MCP wire envelope.

    On `"status": "ok"` envelopes:
      - Unwraps every field() wrapper inside `data` to its bare value so field
        types are invariant regardless of flag or note.
      - Populates top-level `field_flags` with all non-COMPLETE or noted fields
        (including offloaded non-COMPLETE/noted fields), deduplicating array paths.
      - Strips `provenance` from the wire payload (logged to events.jsonl instead).

    Error envelopes and raw dicts pass through unchanged.
    """
    if not (isinstance(obj, dict) and obj.get("status") == "ok" and "data" in obj):
        return obj

    out = {k: v for k, v in obj.items() if k not in ("provenance", "_offloaded_field_flags")}
    offloaded_ff: dict[str, dict[str, str]] = obj.get("_offloaded_field_flags") or {}
    unwrapped_data, inline_ff = unwrap_fields(obj["data"])
    merged_ff: dict[str, dict[str, str]] = {}
    merged_ff.update(offloaded_ff)
    merged_ff.update(inline_ff)

    out["data"] = unwrapped_data
    out["field_flags"] = merged_ff
    return out


def resolve_sidecar_path(filename: str, workdir: str | None = None) -> str | None:
    """
    Resolve an offloaded sidecar file path inside `<workdir>/sidecars/`.

    Uses explicit `workdir` when non-empty, else `os.environ.get(WORKDIR_ENV)`.
    Returns `None` when neither is configured -- sidecar writers must NEVER
    write next to `ms_path` because archival MS directories may be read-only.
    """
    from ms_inspect.util.logs import WORKDIR_ENV

    wd = (workdir or "").strip() or (os.environ.get(WORKDIR_ENV) or "").strip()
    if not wd:
        return None
    sidecars_dir = Path(wd).expanduser().resolve() / "sidecars"
    with contextlib.suppress(OSError):
        sidecars_dir.mkdir(parents=True, exist_ok=True)
    return str(sidecars_dir / Path(filename).name)


def offload_detail(
    data: dict,
    heavy_keys: list[str],
    sidecar_path: str | None,
) -> dict:
    """
    Offload large per-element tables to a JSON sidecar, returning a slimmed dict.

    Before removing `heavy_keys`, collects all CompletionFlags and non-COMPLETE
    / noted field entries from the offloaded subtrees so `response_envelope()`
    and `wire_envelope()` preserve true worst-case `completeness_summary` and
    `field_flags` (CR-8).

    When `sidecar_path` is provided, writes the complete `data` dict as compact
    JSON to `sidecar_path`. When `sidecar_path` is `None` (no workdir configured)
    or unwritable, skips disk write cleanly while keeping the wire payload slim.
    """
    import json as _json

    offloaded_sub = {k: data[k] for k in heavy_keys if k in data}
    offloaded_flags = _collect_flags(offloaded_sub)
    _, offloaded_field_flags = unwrap_fields(offloaded_sub)

    slim = {k: v for k, v in data.items() if k not in heavy_keys}
    slim["detail_keys"] = list(heavy_keys)

    if sidecar_path:
        try:
            with open(sidecar_path, "w") as fh:
                _json.dump(data, fh, separators=(",", ":"), default=str)
            slim["detail_path"] = field(sidecar_path)
            slim["detail_note"] = (
                "Full per-element detail for detail_keys written to detail_path (compact JSON). "
                "Read it directly from the filesystem when a specific element is needed."
            )
        except OSError as exc:
            slim["detail_path"] = field(
                None,
                "UNAVAILABLE",
                note=f"Could not write sidecar to {sidecar_path}: {exc}",
            )
            slim["detail_note"] = (
                "Sidecar write failed; pass a writable workdir to persist detail_keys."
            )
    else:
        slim["detail_path"] = field(
            None,
            "COMPLETE",
            note="No workdir provided; pass workdir or set RADIO_MCP_DIR to write detail sidecar.",
        )
        slim["detail_note"] = (
            "Per-element detail_keys omitted from wire output; pass workdir to write JSON sidecar."
        )

    if offloaded_flags:
        slim["_offloaded_flags"] = offloaded_flags
    if offloaded_field_flags:
        slim["_offloaded_field_flags"] = offloaded_field_flags
    return slim


def _collect_flags(obj: Any) -> list[CompletionFlag]:
    """
    Recursively collect all 'flag' values from a nested dict/list structure.
    """
    flags: list[CompletionFlag] = []
    if isinstance(obj, dict):
        if "flag" in obj and isinstance(obj["flag"], str):
            flags.append(obj["flag"])  # type: ignore[arg-type]
        for v in obj.values():
            flags.extend(_collect_flags(v))
    elif isinstance(obj, list):
        for item in obj:
            flags.extend(_collect_flags(item))
    return flags


# ---------------------------------------------------------------------------
# Numeric formatting helpers
# ---------------------------------------------------------------------------


def round_dict(d: dict, decimals: int = 4) -> dict:
    """
    Recursively round all float values in a nested dict to `decimals` places.
    Leaves non-float values untouched.
    """
    result = {}
    for k, v in d.items():
        if isinstance(v, float):
            result[k] = round(v, decimals)
        elif isinstance(v, dict):
            result[k] = round_dict(v, decimals)
        elif isinstance(v, list):
            result[k] = [round(i, decimals) if isinstance(i, float) else i for i in v]
        else:
            result[k] = v
    return result


def truncate_list(items: list, max_items: int = 50) -> tuple[list, bool]:
    """
    Truncate a list to `max_items` entries.
    Returns (truncated_list, was_truncated).
    """
    if len(items) <= max_items:
        return items, False
    return items[:max_items], True


# ---------------------------------------------------------------------------
# CASA input normalization helpers
# ---------------------------------------------------------------------------


def _normalize_casa_sel(value: str) -> str:
    """Convert Python list/tuple repr to CASA comma-separated selection string."""
    if not value:
        return value
    import ast

    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, (list, tuple)):
            return ",".join(str(x) for x in parsed)
    except (ValueError, SyntaxError):
        pass
    return value


def normalize_field_sel(value: str) -> str:
    """
    Normalize a CASA field selection string.

    LLMs sometimes pass Python list syntax ("[0, 1]" or "['J1331', 'J1822']")
    instead of CASA's comma-separated syntax ("0,1" or "J1331,J1822").
    Passes already-valid strings through unchanged.

    Examples:
        "[0, 1]"                       → "0,1"
        "['J1331+3030', 'J1822-0938']" → "J1331+3030,J1822-0938"
        "0,1"                          → "0,1"
        ""                             → ""
    """
    return _normalize_casa_sel(value)


def normalize_spw_sel(value: str) -> str:
    """
    Normalize a CASA SPW selection string.

    Two normalizations are applied in order:

    1. Python list/tuple repr → comma-separated string.
       "[0, 1]" or "['0:5~58', '1']" → "0,1" or "0:5~58,1"

    2. Bare semicolon-separated SPW list → comma-separated.
       "0;1;2" → "0,1,2"
       Only applied when no ":" precedes a ";" — colon indicates a channel-range
       spec ("0:5~10;20~30") where the semicolon must be preserved.

    Channel-range and channel-selection syntax is passed through unchanged:
        "0:5~58"        → "0:5~58"
        "0:5~10;20~30"  → "0:5~10;20~30"
        ""              → ""

    Examples:
        "[0]"          → "0"
        "[0, 1]"       → "0,1"
        "0;1;2"        → "0,1,2"
        "0:5~10;20~30" → "0:5~10;20~30"  (channel ranges preserved)
        "0:5~58,1"     → "0:5~58,1"
    """
    value = _normalize_casa_sel(value)
    # Normalize bare semicolons that are SPW separators (no preceding colon)
    if ";" in value and ":" not in value:
        value = ",".join(part.strip() for part in value.split(";"))
    return value
