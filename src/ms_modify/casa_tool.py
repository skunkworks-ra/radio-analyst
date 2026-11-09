"""
casa_tool.py — ms_casa_tool: call casatools methods directly, for debugging.

One call runs a short sequence on ONE casatools instance (v1: ``table``):
``open``, a few reads, ``close``. The instance is closed in a ``finally`` so a
failed call never leaves a table lock behind.

Read-only by default. The method tiers are in ms_inspect/util/casa_tool_policy.py.

  - Every ``open`` is forced to ``nomodify=True`` unless the caller passes
    ``nomodify=False`` AND ``allow_write=True`` AND the table is a copy.
  - A "copy" is a table this tool made (``copy``, ``create``, ``fromascii``,
    ``fromfits``) inside the workdir. Each one is recorded in
    ``<workdir>/.casa_tool_copies.json``. The source MS is never in that file, so
    no EDIT method can reach it.
  - ``copy`` is always a deep copy, so editing the copy cannot touch the source.
  - Whole sequence is checked BEFORE anything runs (``plan``, CASA-free): a call
    refused at position 5 does not leave positions 1 to 4 half done.

No gate on the science: the tool does not judge the values it reads or writes.

Return values: scalars, lists and dicts come back inline. A numpy array comes
back inline only if it has at most ``inline_max_elements`` elements (default 0:
none); otherwise it is written to ``<workdir>/casa_tool_<n>_call<i>.npy`` and
the response carries its path, shape and dtype.
"""

from __future__ import annotations

import contextlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ms_inspect.exceptions import ComputationError
from ms_inspect.util.casa_tool_policy import (
    COPY,
    COPY_DEST_PARAMS,
    COPY_INPUT_FILES,
    COPY_MAKES_TABLE,
    COPY_OPENS_TABLE,
    EDIT,
    NEVER,
    POLICIES,
    ToolPolicy,
)
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.stage_log import record_stage

TOOL_NAME = "ms_casa_tool"
MANIFEST_NAME = ".casa_tool_copies.json"


# ---------------------------------------------------------------------------
# Manifest of copies
# ---------------------------------------------------------------------------


def manifest_path(workdir: Path) -> Path:
    return workdir / MANIFEST_NAME


def load_manifest(workdir: Path) -> list[dict[str, Any]]:
    p = manifest_path(workdir)
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text()).get("copies", []))
    except (ValueError, OSError) as e:
        raise ComputationError(f"copy manifest {p} is unreadable: {e}", ms_path="") from e


def _save_manifest(workdir: Path, copies: list[dict[str, Any]]) -> None:
    p = manifest_path(workdir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"copies": copies}, indent=1))
    tmp.replace(p)


def _under(path: Path, roots: set[str]) -> bool:
    """True if path is one of roots or inside one (a subtable of a copy)."""
    return any(path == Path(r) or Path(r) in path.parents for r in roots)


# ---------------------------------------------------------------------------
# Plan: validate the whole call list before anything runs. CASA-free.
# ---------------------------------------------------------------------------


@dataclass
class PlannedCall:
    index: int
    method: str
    tier: str
    args: dict[str, Any]
    written: str = ""  # path this call writes or creates ("" for a read)
    makes_copy_of: str = ""  # source path, when this call creates a copy


@dataclass
class _Session:
    path: str = ""
    writable: bool = False


@dataclass
class Plan:
    calls: list[PlannedCall] = field(default_factory=list)
    new_copies: list[dict[str, Any]] = field(default_factory=list)


def _refuse(i: int, method: str, why: str) -> ComputationError:
    return ComputationError(f"ms_casa_tool call {i} ({method}): {why}", ms_path="")


def _abs(p: Any) -> Path:
    return Path(str(p)).expanduser().resolve()


def _str_arg(i: int, method: str, args: dict[str, Any], key: str) -> str:
    v = args.get(key)
    if not isinstance(v, str) or not v.strip():
        raise _refuse(i, method, f"'{key}' is required (a non-empty string).")
    return v


def _new_dest(i: int, method: str, p: Path, workdir: Path, taken: set[str]) -> None:
    if not p.is_relative_to(workdir):
        raise _refuse(i, method, f"{p} is outside the workdir {workdir}; copies live inside it.")
    if p.exists() or str(p) in taken:
        raise _refuse(i, method, f"{p} already exists; choose a new path.")


def plan(
    tool: str,
    calls: list[dict[str, Any]],
    workdir: Path,
    allow_write: bool,
    manifest: list[dict[str, Any]],
) -> Plan:
    """Check every call against the policy and the session state; return the calls to run.

    Raises ComputationError naming the first call that is refused.
    """
    pol: ToolPolicy | None = POLICIES.get(tool)
    if pol is None:
        raise ComputationError(
            f"ms_casa_tool serves {sorted(POLICIES)} in this version, not {tool!r}.", ms_path=""
        )
    if not calls:
        raise ComputationError("ms_casa_tool needs at least one call.", ms_path="")

    copies = {str(_abs(c["path"])) for c in manifest}
    made: set[str] = set()  # destinations created by this plan
    out = Plan()
    sess: _Session | None = None

    for i, raw in enumerate(calls):
        if not isinstance(raw, dict) or set(raw) - {"method", "args"} or "method" not in raw:
            raise _refuse(i, "?", "a call is an object with 'method' and optional 'args'.")
        method = raw["method"]
        args = dict(raw.get("args") or {})
        if not isinstance(method, str) or not isinstance(args, dict):
            raise _refuse(i, str(method), "method must be a string and args an object.")
        tier = pol.tier(method)
        if tier is None:
            raise _refuse(
                i,
                method,
                f"not in the {tool} policy (ms_casa_tool_spec lists the methods). "
                "casatools gained a method since the policy was written.",
            )
        if tier == NEVER:
            raise _refuse(i, method, f"refused in every mode ({tool} policy, tier 'never').")
        if tier in (COPY, EDIT) and not allow_write:
            raise _refuse(
                i, method, f"is a {tier}-tier method; it needs allow_write=True (default False)."
            )
        pc = PlannedCall(i, method, tier, args)

        if method == "open":
            if sess is not None:
                raise _refuse(i, method, f"{sess.path} is already open; close it first.")
            if "lockoptions" in args:
                raise _refuse(i, method, "lockoptions is not accepted.")
            p = _abs(_str_arg(i, method, args, "tablename"))
            nomodify = args.get("nomodify", True)
            if not isinstance(nomodify, bool):
                raise _refuse(i, method, "nomodify must be true or false.")
            if not nomodify:
                if not allow_write:
                    raise _refuse(i, method, "nomodify=False needs allow_write=True.")
                if not _under(p, copies | made):
                    raise _refuse(
                        i,
                        method,
                        f"{p} is not a copy made by ms_casa_tool (not in {manifest_path(workdir)}). "
                        "Only a copy can be opened for writing; make one with the copy method.",
                    )
            args["tablename"] = str(p)
            args["nomodify"] = nomodify
            sess = _Session(str(p), not nomodify)
        elif method in ("close", "done"):
            sess = None
        elif tier == COPY:
            _plan_copy(pc, i, method, args, sess, workdir, made, copies)
            if method in COPY_OPENS_TABLE:
                if sess is not None:
                    raise _refuse(i, method, f"{sess.path} is open; close it first.")
                dest = pc.written
                if method == "create":
                    sess = _Session(dest, True)
                else:
                    nomodify = args.get("nomodify", True)
                    sess = _Session(dest, not nomodify)
            if method in COPY_MAKES_TABLE:
                made.add(pc.written)
                out.new_copies.append(
                    {
                        "path": pc.written,
                        "source": pc.makes_copy_of,
                        "call": {
                            "method": method,
                            "args": {k: str(v)[:200] for k, v in args.items()},
                        },
                    }
                )
        elif tier == EDIT:
            _plan_edit(pc, i, method, args, sess, copies | made)
        out.calls.append(pc)
    return out


def _plan_copy(
    pc: PlannedCall,
    i: int,
    method: str,
    args: dict[str, Any],
    sess: _Session | None,
    workdir: Path,
    made: set[str],
    copies: set[str],
) -> None:
    for key in COPY_INPUT_FILES.get(method, ()):
        if key in args and args[key]:
            f = _abs(args[key])
            if not f.is_file():
                raise _refuse(i, method, f"{key}={f} is not an existing file.")
            args[key] = str(f)
    if method in ("copy", "toasciifmt") and sess is None:
        raise _refuse(i, method, "needs an open table (call open first).")
    if method in ("create", "fromascii", "fromfits") and "lockoptions" in args:
        raise _refuse(i, method, "lockoptions is not accepted.")
    taken = made | copies
    dests: list[Path] = []
    for key in COPY_DEST_PARAMS[method]:
        if key == "headerfile":  # the one optional destination; always last
            if args.get(key):
                dests.append(_abs(args[key]))
        else:
            dests.append(_abs(_str_arg(i, method, args, key)))
    for d in dests:
        _new_dest(i, method, d, workdir, taken)
        if sess is not None and (d == Path(sess.path) or Path(sess.path) in d.parents):
            raise _refuse(i, method, f"{d} is inside the open table {sess.path}.")
    if method == "copy":
        if args.get("deep") is False:
            raise _refuse(
                i,
                method,
                "deep=False is refused: only a deep copy is independent of the source.",
            )
        if args.get("returnobject"):
            raise _refuse(i, method, "returnobject is not accepted (not JSON, leaves a handle).")
        args["deep"] = True
        pc.makes_copy_of = sess.path if sess else ""
    elif method in COPY_MAKES_TABLE:
        pc.makes_copy_of = str(args.get("asciifile") or args.get("fitsfile") or "(created empty)")
    for key, d in zip(COPY_DEST_PARAMS[method], dests, strict=False):
        args[key] = str(d)
    pc.written = str(dests[0])


def _plan_edit(
    pc: PlannedCall,
    i: int,
    method: str,
    args: dict[str, Any],
    sess: _Session | None,
    copies: set[str],
) -> None:
    if sess is None:
        raise _refuse(i, method, "needs an open table (call open first).")
    if method == "copyrows":
        out_t = _abs(_str_arg(i, method, args, "outtable"))
        if not _under(out_t, copies):
            raise _refuse(
                i,
                method,
                f"outtable {out_t} is not a copy made by ms_casa_tool; it cannot be written.",
            )
        args["outtable"] = str(out_t)
        pc.written = str(out_t)
        return
    if not sess.writable:
        raise _refuse(
            i, method, f"{sess.path} is open with nomodify=True; reopen it with nomodify=False."
        )
    # Writable sessions exist only on copies (open checked it), but check again.
    if not _under(Path(sess.path), copies):
        raise _refuse(i, method, f"{sess.path} is not a copy made by ms_casa_tool.")
    pc.written = sess.path


# ---------------------------------------------------------------------------
# JSON-safe return values
# ---------------------------------------------------------------------------


def _json_safe(v: Any, spill, inline_max: int) -> Any:
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy ships with casatools
        np = None
    if np is not None and isinstance(v, np.ndarray):
        if v.size <= inline_max:
            return _json_safe(v.tolist(), spill, inline_max)
        return spill(v)
    if np is not None and isinstance(v, np.generic):
        return _json_safe(v.item(), spill, inline_max)
    if isinstance(v, complex):
        return {
            "real": _json_safe(v.real, spill, inline_max),
            "imag": _json_safe(v.imag, spill, inline_max),
        }
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    if isinstance(v, bytes):
        return v.decode(errors="replace")
    if isinstance(v, dict):
        return {str(k): _json_safe(x, spill, inline_max) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x, spill, inline_max) for x in v]
    return repr(v)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _new_instance(tool: str) -> Any:
    import importlib

    try:
        casatools = importlib.import_module("casatools")
    except ImportError:
        from ms_inspect.exceptions import CASANotAvailableError

        raise CASANotAvailableError(
            "casatools is not installed or cannot be imported.", ms_path=""
        ) from None
    return getattr(casatools, tool)()


def _next_index(workdir: Path) -> int:
    n = 1
    while (workdir / f"casa_tool_{n}.json").exists():
        n += 1
    return n


def run(
    tool: str,
    calls: list[dict[str, Any]],
    workdir: str,
    allow_write: bool = False,
    inline_max_elements: int = 0,
) -> dict:
    """
    Run a sequence of casatools method calls on one instance.

    Args:
        tool:                 casatools class; 'table' in this version.
        calls:                [{"method": "open", "args": {"tablename": ...}}, ...]
        workdir:              Existing directory for results, spilled arrays, copies.
        allow_write:          False (default): READ-tier methods only.
        inline_max_elements:  Largest numpy array returned inline (default 0: none).

    Returns:
        Envelope with the calls as run (paths made absolute, nomodify and deep
        set), one result per call, and the path of the saved record.
    """
    workdir_path = _abs(workdir)
    if not workdir_path.is_dir():
        raise ComputationError(f"workdir does not exist: {workdir_path}", ms_path="")
    if inline_max_elements < 0:
        raise ComputationError("inline_max_elements must be >= 0.", ms_path="")
    manifest = load_manifest(workdir_path)
    pl = plan(tool, calls, workdir_path, allow_write, manifest)

    n = _next_index(workdir_path)
    record_path = workdir_path / f"casa_tool_{n}.json"
    results: list[dict[str, Any]] = []
    casa_calls: list[str] = []
    warnings: list[str] = []
    spilled: list[str] = []
    failed: dict[str, Any] | None = None
    created: list[dict[str, Any]] = []

    inst = _new_instance(tool)
    try:
        for pc in pl.calls:

            def spill(arr, _i=pc.index):
                import numpy as np

                p = workdir_path / f"casa_tool_{n}_call{_i}.npy"
                np.save(p, arr)
                spilled.append(str(p))
                return {"npy": str(p), "shape": list(arr.shape), "dtype": str(arr.dtype)}

            casa_calls.append(f"{tool}.{pc.method}({', '.join(sorted(pc.args))})")
            try:
                value = getattr(inst, pc.method)(**pc.args)
            except Exception as e:
                failed = {
                    "index": pc.index,
                    "method": pc.method,
                    "error": f"{type(e).__name__}: {e}",
                }
                break
            results.append(
                {
                    "index": pc.index,
                    "method": pc.method,
                    "tier": pc.tier,
                    "args": pc.args,
                    "value": _json_safe(value, spill, inline_max_elements),
                }
            )
            if pc.method in COPY_MAKES_TABLE:
                created.extend(c for c in pl.new_copies if c["path"] == pc.written)
                _save_manifest(workdir_path, [*manifest, *created])
            if pc.tier in (COPY, EDIT):
                record_stage(str(workdir_path), f"ms_casa_tool:{pc.method}", pc.written, None)
    finally:
        for closer in ("close", "done"):
            with contextlib.suppress(Exception):  # best effort; the lock is what matters
                getattr(inst, closer)()

    record = {"tool": tool, "allow_write": allow_write, "results": results, "failed": failed}
    record_path.write_text(json.dumps(record, indent=1))
    ms_path = next((c.args["tablename"] for c in pl.calls if c.method == "open"), "")
    if failed:
        warnings.append(
            f"call {failed['index']} ({failed['method']}) failed: {failed['error']}. "
            "Earlier results are in the record; later calls did not run."
        )
    data: dict[str, Any] = {
        "tool": tool,
        "allow_write": allow_write,
        "n_calls_planned": len(pl.calls),
        "n_calls_run": len(results),
        "results": fmt_field(results, flag="PARTIAL" if failed else "COMPLETE"),
        "failed_call": failed,
        "record_path": str(record_path),
        "spilled_arrays": spilled,
        "tiers": fmt_field(
            {pc.index: pc.tier for pc in pl.calls},
            flag="INFERRED",
            note="Method tiers are written by hand (ms_inspect/util/casa_tool_policy.py).",
        ),
        "new_copies": created,
    }
    return response_envelope(
        tool_name=TOOL_NAME, ms_path=ms_path, data=data, warnings=warnings, casa_calls=casa_calls
    )
