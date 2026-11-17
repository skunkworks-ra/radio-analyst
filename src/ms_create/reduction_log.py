"""
reduction_log.py — ms_reduction_log

A place to shuttle KNOWN-GOOD calls as a reduction proceeds. After a tool call
succeeds, append it here with the exact parameters that worked, the salient
output, and why it was done. The accumulated log is the replayable "working
path" through the data — the canonical recipe for this dataset, and the
artifact a cheaper model (or a future run) can replay step by step.

Only validated calls should be shuttled in: failed attempts and dead ends stay
out, so the ledger is the clean path, not the search for it.

Storage is a JSON-lines file `reduction_log.jsonl` in the workdir — one record
per line, append-only, trivially diffable and greppable.

Actions:
  append  — record one working call (tool, params, outputs, rationale, rule,
            script_path). `tool` is the write tool's own name, or 'manual' for
            work done off the tools; anything else is refused, so render can
            map every entry. A call not run with execute=True must name the
            script that was actually run; its sha256 is stored with it.
  render  — emit the ordered recipe and a replay Python script: each entry with
            a script re-runs that script (hash checked first), the rest call run()
  list    — compact summary (step, tool, rationale) of the recorded path
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope
from ms_inspect.util.logs import write_script
from ms_inspect.util.stage_log import read_stage_log

TOOL_NAME = "ms_reduction_log"

_LOG_NAME = "reduction_log.jsonl"


def _log_path(workdir: str) -> Path:
    return Path(workdir) / _LOG_NAME


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# Maps the recorded tool name to the package module whose run() implements it.
# Steps whose tool name is not in this registry are emitted as MANUAL markers
# (e.g. ad-hoc casatasks bypasses), so the script is honest about what it can
# and cannot replay automatically.
_RUN_REGISTRY: dict[str, str] = {
    "ms_sdm_summary": "ms_create.sdm_summary",
    "ms_import_asdm": "ms_create.import_asdm",
    # Replay on an MS that already carries intents is refused by the tool itself.
    "ms_set_intents": "ms_modify.intents",
    "ms_apply_preflag": "ms_modify.preflag",
    "ms_generate_priorcals": "ms_modify.priorcals",
    "ms_initial_bandpass": "ms_modify.initial_bandpass",
    "ms_apply_initial_rflag": "ms_modify.initial_rflag",
    "ms_setjy": "ms_modify.setjy",
    "ms_setjy_polcal": "ms_modify.setjy_polcal",
    "ms_gaincal": "ms_modify.gaincal",
    "ms_bandpass": "ms_modify.bandpass",
    "ms_fluxscale": "ms_modify.fluxscale",
    "ms_polcal": "ms_modify.polcal",
    "ms_applycal": "ms_modify.applycal",
    "ms_apply_rflag": "ms_modify.rflag",
    "ms_postcal_flag": "ms_modify.postcal_flag",
    "ms_flag_caltable": "ms_modify.flag_caltable",
    "ms_flag_data": "ms_modify.flag_data",
    "ms_tclean": "ms_modify.tclean",
    "ms_casa_task": "ms_modify.casa_task",
    "ms_casa_tool": "ms_modify.casa_tool",
}

_STAGE_TO_TOOL: dict[str, str] = {
    "import_asdm": "ms_import_asdm",
    "set_intents": "ms_set_intents",
    "intents": "ms_set_intents",
    "preflag": "ms_apply_preflag",
    "priorcals": "ms_generate_priorcals",
    "initial_bandpass": "ms_initial_bandpass",
    "initial_rflag": "ms_apply_initial_rflag",
    "setjy": "ms_setjy",
    "setjy_polcal": "ms_setjy_polcal",
    "gaincal": "ms_gaincal",
    "bandpass": "ms_bandpass",
    "fluxscale": "ms_fluxscale",
    "polcal": "ms_polcal",
    "applycal": "ms_applycal",
    "rflag": "ms_apply_rflag",
    "postcal_flag": "ms_postcal_flag",
    "flag_caltable": "ms_flag_caltable",
    "flag_data": "ms_flag_data",
    "tclean": "ms_tclean",
}

_MULTI_PRODUCT_STAGES = frozenset({"import_asdm", "preflag", "priorcals", "initial_bandpass"})
_PRODUCT_SOLVE_STAGES = frozenset(
    {
        "import_asdm",
        "set_intents",
        "preflag",
        "priorcals",
        "initial_bandpass",
        "gaincal",
        "bandpass",
        "fluxscale",
        "polcal",
    }
)
_MODEL_STAGES = frozenset({"setjy", "setjy_polcal"})
_MODEL_CONSUMER_STAGES = frozenset(
    {"initial_bandpass", "initial_rflag", "gaincal", "bandpass", "polcal", "postcal_flag"}
)
_INPLACE_MS_MUTATOR_STAGES = frozenset(
    {
        "initial_rflag",
        "rflag",
        "postcal_flag",
        "flag_data",
        "setjy",
        "setjy_polcal",
        "applycal",
    }
)
_SCRIPTLESS_TOOLS = frozenset({"ms_casa_tool", "ms_sdm_summary"})
_CASA_TASK_CORRECTED_CONSUMERS = frozenset(
    {
        "statwt",
        "split",
        "mstransform",
        "uvsub",
        "uvcontsub",
        "uvcontsub_old",
        "cvel",
        "cvel2",
        "phaseshift",
        "fixvis",
        "hanningsmooth",
        "flagcmd",
        "concat",
        "virtualconcat",
        "exportuvfits",
        "exportasdm",
    }
)


# What append accepts: the replayable write tools, and 'manual' for off-tool work
# (a hand-edited or hand-written script).
_APPENDABLE = frozenset(_RUN_REGISTRY) | {"manual"}


@functools.cache
def _run_supports_execute(tool: str) -> bool:
    mod_name = _RUN_REGISTRY.get(tool)
    if not mod_name:
        return False
    try:
        mod = importlib.import_module(mod_name)
        sig = inspect.signature(mod.run)
    except Exception:
        return tool not in _SCRIPTLESS_TOOLS
    return "execute" in sig.parameters


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canon_path(raw: str, wd: Path) -> str:
    if not raw or not str(raw).strip():
        return ""
    p = Path(str(raw)).expanduser()
    if p.is_absolute():
        return str(p.resolve())
    wd_abs = wd.expanduser().resolve()
    in_wd = wd_abs / p
    if in_wd.exists():
        return str(in_wd.resolve())
    in_cwd = p.resolve()
    if in_cwd.exists():
        return str(in_cwd)
    if (wd_abs.parent / p).exists():
        return str((wd_abs.parent / p).resolve())
    return str(in_wd.resolve())


def _add_ms_target(raw: str, wd: Path, out: set[str]) -> None:
    cp = _canon_path(raw, wd)
    if not cp:
        return
    out.add(cp)
    if ".ms/" in cp:
        for anc in Path(cp).parents:
            if anc.name.endswith(".ms"):
                out.add(str(anc))


def _stage_to_tool(stage: str) -> str:
    if stage.startswith("ms_casa_task:"):
        return "ms_casa_task"
    if stage == "ms_casa_tool" or stage.startswith("ms_casa_tool:"):
        return "ms_casa_tool"
    return _STAGE_TO_TOOL.get(stage, stage)


def _casa_tool_inputs_and_outputs(params: dict, wd: Path) -> tuple[set[str], set[str]]:
    """Return canonical (external_inputs, created_outputs) for an ms_casa_tool call list."""
    ext_in: set[str] = set()
    created: set[str] = set()
    calls = params.get("calls")
    if not isinstance(calls, list):
        return ext_in, created

    for call in calls:
        if not isinstance(call, dict):
            continue
        method = str(call.get("method") or "")
        raw_args = call.get("args")
        raw_kw = call.get("kwargs") if isinstance(call.get("kwargs"), dict) else {}
        if method in ("copy", "create", "fromascii", "fromfits"):
            dest: object = ""
            if isinstance(raw_args, dict):
                dest = (
                    raw_args.get("newtablename")
                    or raw_args.get("tablename")
                    or raw_kw.get("newtablename")
                    or raw_kw.get("tablename")
                    or ""
                )
            elif isinstance(raw_args, (list, tuple)):
                dest = (
                    raw_kw.get("newtablename")
                    or raw_kw.get("tablename")
                    or (raw_args[0] if raw_args else "")
                )
            else:
                dest = raw_kw.get("newtablename") or raw_kw.get("tablename") or ""
            if isinstance(dest, str) and dest:
                dc = _canon_path(dest, wd)
                if dc:
                    created.add(dc)
        elif method == "open":
            tbl: object = ""
            open_keys = ("tablename", "thems", "filename", "infile", "msfile")
            if isinstance(raw_args, dict):
                tbl = next(
                    (raw_args[k] for k in open_keys if raw_args.get(k)),
                    "",
                ) or next((raw_kw[k] for k in open_keys if raw_kw.get(k)), "")
            elif isinstance(raw_args, (list, tuple)):
                tbl = next((raw_kw[k] for k in open_keys if raw_kw.get(k)), "") or (
                    raw_args[0] if raw_args else ""
                )
            else:
                tbl = next((raw_kw[k] for k in open_keys if raw_kw.get(k)), "")
            if isinstance(tbl, str) and tbl:
                tc = _canon_path(tbl, wd)
                if (
                    tc
                    and tc not in created
                    and not any(str(anc) in created for anc in Path(tc).parents)
                ):
                    ext_in.add(tc)
    return ext_in, created


def _group_input_caltables(grp: list[dict], prods_canon: tuple[str, ...], wd: Path) -> set[str]:
    """Return canonical caltable paths consumed as inputs by ``grp``."""
    stg = str(grp[0].get("stage", ""))
    params = grp[-1].get("params") if isinstance(grp[-1].get("params"), dict) else {}
    inner = params.get("params") if isinstance(params.get("params"), dict) else {}
    prods_set = set(prods_canon)
    out: set[str] = set()

    for pdict in (params, inner):
        for key in ("gaintable", "priorcals"):
            val = pdict.get(key)
            items = (
                val
                if isinstance(val, (list, tuple))
                else ([val] if isinstance(val, str) and val else [])
            )
            for item in items:
                if isinstance(item, str) and item:
                    ct_c = _canon_path(item, wd)
                    if ct_c and ct_c not in prods_set:
                        out.add(ct_c)
        if stg == "fluxscale" or stg.startswith("ms_casa_task:"):
            for key in ("caltable", "tablein"):
                val = pdict.get(key)
                if isinstance(val, str) and val:
                    ct_c = _canon_path(val, wd)
                    if ct_c and ct_c not in prods_set:
                        out.add(ct_c)

    if stg == "ms_casa_tool" or stg.startswith("ms_casa_tool:"):
        ext_in, _ = _casa_tool_inputs_and_outputs(params, wd)
        for tc in ext_in:
            if not tc.endswith(".ms") and ".ms/" not in tc and tc not in prods_set:
                out.add(tc)
    return out


def _group_ms_targets(grp: list[dict], wd: Path) -> set[str]:
    """Return canonical Measurement Set paths touched or read as input by ``grp``."""
    head = grp[0]
    tail = grp[-1]
    stg = str(head.get("stage", ""))
    params = tail.get("params") if isinstance(tail.get("params"), dict) else {}
    inner_params = params.get("params") if isinstance(params.get("params"), dict) else {}
    out: set[str] = set()

    for pdict in (params, inner_params):
        for key in ("ms_path", "vis"):
            val = pdict.get(key)
            if isinstance(val, str) and val:
                _add_ms_target(val, wd, out)
            elif isinstance(val, (list, tuple)):
                for item in val:
                    if isinstance(item, str) and item:
                        _add_ms_target(item, wd, out)

    if stg == "ms_casa_tool" or stg.startswith("ms_casa_tool:"):
        ext_in, _ = _casa_tool_inputs_and_outputs(params, wd)
        for tc in ext_in:
            _add_ms_target(tc, wd, out)

    for g in grp:
        meas = g.get("measurement")
        if isinstance(meas, dict):
            mip = meas.get("modifies_in_place")
            if isinstance(mip, (list, tuple)):
                for item in mip:
                    if isinstance(item, str) and (
                        item.rstrip("/").endswith(".ms") or ".ms/" in item
                    ):
                        _add_ms_target(item, wd, out)
        prod = g.get("product")
        if (
            isinstance(prod, str)
            and prod
            and (
                stg in _INPLACE_MS_MUTATOR_STAGES
                or (
                    not stg.startswith(("ms_casa_task:", "ms_casa_tool"))
                    and (prod.rstrip("/").endswith(".ms") or ".ms/" in prod)
                )
            )
        ):
            _add_ms_target(prod, wd, out)
    out.discard("")
    return out


def _group_recreated_ms(grp: list[dict], prods_canon: tuple[str, ...], wd: Path) -> set[str]:
    """Return canonical MS paths freshly created/split from scratch by ``grp``."""
    stg = str(grp[0].get("stage", ""))
    params = grp[-1].get("params") if isinstance(grp[-1].get("params"), dict) else {}
    if stg == "import_asdm":
        return {p for p in prods_canon if p.endswith(".ms")}
    if stg == "preflag":
        src_ms = _canon_path(str(params.get("ms_path", "")), wd)
        if src_ms:
            return {p for p in prods_canon if p != src_ms}
        if len(prods_canon) >= 2:
            return {prods_canon[-1]}
    return set()


def _is_corrected_consumer(stg: str, params: dict, meas: dict | None = None) -> bool:
    """True when ``stg`` consumes ``CORRECTED_DATA`` to mutate visibilities or model."""
    meas_d = meas if isinstance(meas, dict) else {}
    if stg == "initial_rflag":
        return True
    if stg in ("rflag", "postcal_flag"):
        return str(params.get("datacolumn", "corrected")).lower() != "data"
    if stg == "tclean":
        return str(params.get("savemodel", "none")).lower() != "none"
    if stg == "ms_casa_tool" or stg.startswith("ms_casa_tool:"):
        return params.get("allow_write") is not False or bool(meas_d.get("written_paths"))
    if stg.startswith("ms_casa_task:"):
        task_name = stg.split(":", 1)[1]
        if task_name not in _CASA_TASK_CORRECTED_CONSUMERS:
            return False
        inner = params.get("params") if isinstance(params.get("params"), dict) else params
        return str(inner.get("datacolumn", "")).lower() != "data"
    return False


def _is_model_consumer(stg: str, params: dict | None = None) -> bool:
    if stg in _MODEL_CONSUMER_STAGES:
        return True
    if stg == "rflag":
        dc = str((params or {}).get("datacolumn", "corrected")).lower()
        return dc in ("residual", "residual_data", "model", "model_data")
    if stg == "ms_casa_tool" or stg.startswith("ms_casa_tool:"):
        return True
    if stg.startswith("ms_casa_task:"):
        task_name = stg.split(":", 1)[1]
        return task_name in _CASA_TASK_CORRECTED_CONSUMERS or task_name == "blcal"
    return False


def _has_idx_between(indices: list[int], lo: int, hi: int) -> bool:
    return any(lo < x < hi for x in indices)


def _strip_unsupported_execute(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rec in records:
        r_copy = dict(rec)
        t_name = str(r_copy.get("tool") or "")
        if (
            t_name in _RUN_REGISTRY
            and not _run_supports_execute(t_name)
            and isinstance(r_copy.get("params"), dict)
            and "execute" in r_copy["params"]
        ):
            p_copy = dict(r_copy["params"])
            p_copy.pop("execute", None)
            r_copy["params"] = p_copy
        out.append(r_copy)
    return out


def load_effective_records(wd: Path) -> list[dict]:
    """Derive ordered, deduplicated replay records from stage_log.jsonl + reduction_log.jsonl."""
    from ms_inspect.util.formatting import normalize_field_sel

    manual_records = _strip_unsupported_execute(_read_records(wd / _LOG_NAME))
    stage_entries = [e for e in read_stage_log(wd) if e.get("exists") is True and e.get("stage")]
    if not stage_entries:
        return manual_records

    # 1. Group consecutive multi-product lines emitted by the same script/call.
    groups: list[list[dict]] = []
    for entry in stage_entries:
        if groups:
            prev = groups[-1][-1]
            prev_products = {
                _canon_path(str(g.get("product", "")), wd) for g in groups[-1] if g.get("product")
            }
            entry_prod_c = _canon_path(str(entry.get("product", "")), wd)
            same_script = (
                bool(entry.get("script_path"))
                and entry.get("script_path") == prev.get("script_path")
                and entry.get("script_sha256") == prev.get("script_sha256")
                and entry.get("stage") == prev.get("stage")
                and entry_prod_c not in prev_products
            )
            same_inproc_multi = (
                not entry.get("script_path")
                and not prev.get("script_path")
                and entry.get("stage") in _MULTI_PRODUCT_STAGES
                and entry.get("stage") == prev.get("stage")
                and entry.get("params") == prev.get("params")
                and entry_prod_c not in prev_products
            )
            if same_script or same_inproc_multi:
                groups[-1].append(entry)
                continue
        groups.append([entry])

    group_prods_canon: list[tuple[str, ...]] = []
    group_input_cts: list[set[str]] = []
    last_recreate_idx: dict[str, int] = {}
    for idx, grp in enumerate(groups):
        prods_c = tuple(
            p_c
            for g in grp
            if g.get("product")
            for p_c in (_canon_path(str(g.get("product", "")), wd),)
            if p_c
        )
        group_prods_canon.append(prods_c)
        group_input_cts.append(_group_input_caltables(grp, prods_c, wd))
        for new_ms in _group_recreated_ms(grp, prods_c, wd):
            last_recreate_idx[new_ms] = idx

    # Forward invalidity pre-pass: any step whose input MS is recreated from scratch
    # later (import_asdm / preflag retry), or whose input table/caltable was produced
    # by such a wiped step and not yet re-created, cannot run before the recreation.
    wiped_indices: set[int] = set()
    if last_recreate_idx:
        invalid_paths: set[str] = set()

        def _path_is_invalid(p_c: str) -> bool:
            if not p_c:
                return False
            if p_c in invalid_paths:
                return True
            return any(str(anc) in invalid_paths for anc in Path(p_c).parents)

        for idx, grp in enumerate(groups):
            stg = str(grp[0].get("stage", ""))
            params = grp[-1].get("params") if isinstance(grp[-1].get("params"), dict) else {}
            meas = (
                grp[-1].get("measurement") if isinstance(grp[-1].get("measurement"), dict) else {}
            )
            prods_c = group_prods_canon[idx]

            if stg == "import_asdm":
                recreated = _group_recreated_ms(grp, prods_c, wd)
                if any(last_recreate_idx.get(m, -1) > idx for m in recreated):
                    wiped_indices.add(idx)
                    invalid_paths.update(recreated)
                else:
                    for m in recreated:
                        invalid_paths.discard(m)
                continue

            if stg == "preflag":
                src_ms = _canon_path(str(params.get("ms_path", "")), wd)
                if not src_ms and len(prods_c) >= 2:
                    src_ms = prods_c[0]
                recreated = _group_recreated_ms(grp, prods_c, wd)
                if _path_is_invalid(src_ms) or any(
                    last_recreate_idx.get(m, -1) > idx for m in recreated
                ):
                    wiped_indices.add(idx)
                    invalid_paths.update(recreated)
                else:
                    for m in recreated:
                        invalid_paths.discard(m)
                continue

            req_inputs: set[str] = set(group_input_cts[idx])
            created_outs: set[str] = set()

            if stg == "ms_casa_tool" or stg.startswith("ms_casa_tool:"):
                ext_in, tool_created = _casa_tool_inputs_and_outputs(params, wd)
                req_inputs.update(ext_in)
                if tool_created:
                    created_outs.update(tool_created)
                else:
                    req_inputs.update(prods_c)
            elif stg == "flag_caltable":
                ct_c = (
                    prods_c[0] if prods_c else _canon_path(str(params.get("caltable_path", "")), wd)
                )
                if ct_c:
                    req_inputs.add(ct_c)
            elif (
                stg in _INPLACE_MS_MUTATOR_STAGES
                or stg in ("set_intents", "intents")
                or (stg.startswith("ms_casa_task:") and bool(meas.get("modifies_in_place")))
            ):
                req_inputs.update(_group_ms_targets(grp, wd))
            elif stg == "initial_bandpass":
                ms_c = _canon_path(str(params.get("ms_path", "")), wd) or (
                    prods_c[-1] if prods_c and prods_c[-1].endswith(".ms") else ""
                )
                if ms_c:
                    req_inputs.add(ms_c)
                created_outs.update(p for p in prods_c if p != ms_c)
            else:
                req_inputs.update(_group_ms_targets(grp, wd) - set(prods_c))
                created_outs.update(prods_c)

            input_recreated_later = any(
                last_recreate_idx.get(p, -1) > idx
                or any(
                    anc.name.endswith(".ms") and last_recreate_idx.get(str(anc), -1) > idx
                    for anc in Path(p).parents
                )
                for p in req_inputs
            )
            if input_recreated_later or any(_path_is_invalid(p) for p in req_inputs):
                wiped_indices.add(idx)
                invalid_paths.update(created_outs)
            else:
                for co in created_outs:
                    invalid_paths.discard(co)

    # 2. Walk newest -> oldest, dropping superseded solves, orphaned caltable flags,
    #    superseded applycals, and mutations on MSs that a later step recreated from scratch.
    #    kept_applied_ms_for_ct records ONLY kept applycal / initial_bandpass steps so a
    #    dropped applycal never keeps dead upstream solves or flags alive.
    kept_groups_rev: list[list[dict]] = []
    kept_applied_ms_for_ct: dict[str, list[tuple[int, str]]] = {}
    kept_products_by_stage: dict[str, set[str]] = {}
    next_kept_solve_for_prod: dict[str, int] = {}
    kept_caltable_consumers_by_ct: dict[str, list[int]] = {}
    kept_tclean_at: dict[str, int] = {}
    kept_tclean_products: set[str] = set()
    kept_auto_flag_caltables: set[str] = set()
    kept_setjy_at: dict[tuple[str, str, str], int] = {}
    kept_applycal_at: dict[tuple[str, str], tuple[int, set[str], tuple[str, ...]]] = {}
    kept_corrected_consumers_by_ms: dict[str, list[int]] = {}
    kept_model_consumers_by_ms: dict[str, list[int]] = {}
    kept_ms_activity_by_ms: dict[str, list[int]] = {}

    def _ct_consumed_before_resolve(
        ct_c: str, step_idx: int, resolve_idx: int, *, allow_self_apply: bool = True
    ) -> bool:
        if _has_idx_between(kept_caltable_consumers_by_ct.get(ct_c, []), step_idx, resolve_idx):
            return True
        min_apply_idx = step_idx if allow_self_apply else step_idx + 1
        for a_idx, ms_c in kept_applied_ms_for_ct.get(ct_c, ()):
            if min_apply_idx <= a_idx < resolve_idx and _has_idx_between(
                kept_corrected_consumers_by_ms.get(ms_c, []), a_idx, resolve_idx
            ):
                return True
        return False

    for idx in range(len(groups) - 1, -1, -1):
        if idx in wiped_indices:
            continue
        grp = groups[idx]
        stg = str(grp[0].get("stage", ""))
        params = grp[-1].get("params") if isinstance(grp[-1].get("params"), dict) else {}
        meas = grp[-1].get("measurement") if isinstance(grp[-1].get("measurement"), dict) else {}
        prods_c = group_prods_canon[idx]
        ms_targets = _group_ms_targets(grp, wd)
        is_casa_task_solve = (
            stg.startswith("ms_casa_task:")
            and bool(prods_c)
            and not any(p.endswith(".ms") for p in prods_c)
            and not meas.get("modifies_in_place")
        )

        # (b) set_intents / intents: deduplicate by canonical MS path so replay never
        #     triggers IntentsAlreadyPopulatedError on a second call.
        if stg in ("set_intents", "intents"):
            ms_c = prods_c[0] if prods_c else _canon_path(str(params.get("ms_path", "")), wd)
            if ms_c:
                already_si = kept_products_by_stage.setdefault("set_intents", set())
                if ms_c in already_si:
                    continue
                already_si.add(ms_c)

        # (c) tclean: deduplicate by canonical imagename (handles hogbom -> mtmfs suffix change).
        elif stg == "tclean":
            img_raw = str(params.get("imagename") or "")
            img_c = _canon_path(img_raw, wd) if img_raw else ""
            if not img_c and prods_c:
                p0 = prods_c[0]
                if p0.endswith(".image.tt0"):
                    img_c = p0[: -len(".image.tt0")]
                elif p0.endswith(".image"):
                    img_c = p0[: -len(".image")]
            if img_c:
                later_img_idx = kept_tclean_at.get(img_c, -1)
                if later_img_idx > idx:
                    ms_c = _canon_path(str(params.get("ms_path", "")), wd)
                    saves_model = str(params.get("savemodel", "none")).lower() != "none"
                    if not (
                        saves_model
                        and ms_c
                        and _has_idx_between(
                            kept_model_consumers_by_ms.get(ms_c, []), idx, later_img_idx
                        )
                    ):
                        continue
            elif prods_c and set(prods_c) <= kept_tclean_products:
                continue
            if img_c:
                kept_tclean_at[img_c] = idx
            kept_tclean_products.update(prods_c)

        # (d) Product-producing solve/setup stages and caltable-producing ms_casa_task:*
        #     (including subset partial crashes).
        elif (stg in _PRODUCT_SOLVE_STAGES or is_casa_task_solve) and prods_c:
            already = kept_products_by_stage.get(stg, set())
            if set(prods_c) <= already:
                if stg in ("import_asdm", "preflag", "set_intents"):
                    continue
                consumed = any(
                    _ct_consumed_before_resolve(p_c, idx, next_kept_solve_for_prod.get(p_c, idx))
                    for p_c in prods_c
                    if not p_c.endswith(".ms")
                )
                if not consumed and stg == "initial_bandpass":
                    ms_c_self = _canon_path(str(params.get("ms_path", "")), wd) or (
                        prods_c[-1] if prods_c[-1].endswith(".ms") else ""
                    )
                    if ms_c_self and ms_c_self in prods_c:
                        consumed = any(
                            _has_idx_between(
                                kept_corrected_consumers_by_ms.get(ms_c_self, []),
                                idx,
                                next_kept_solve_for_prod.get(p_c, idx),
                            )
                            for p_c in prods_c
                            if p_c != ms_c_self
                        )
                if not consumed:
                    continue
            kept_products_by_stage.setdefault(stg, set()).update(prods_c)
            for p_c in prods_c:
                if not p_c.endswith(".ms"):
                    next_kept_solve_for_prod[p_c] = idx

        # (e) flag_caltable: drop flags before a re-solve unless that earlier solve was
        #     itself consumed before the re-solve; deduplicate repeated auto-flags after a solve.
        elif stg == "flag_caltable":
            ct_c = prods_c[0] if prods_c else _canon_path(str(params.get("caltable_path", "")), wd)
            if ct_c:
                next_s = next_kept_solve_for_prod.get(ct_c, -1)
                if next_s > idx and not _ct_consumed_before_resolve(
                    ct_c, idx, next_s, allow_self_apply=False
                ):
                    continue
                mode_val = str(meas.get("mode") or params.get("mode") or "auto").lower()
                if mode_val != "manual":
                    if ct_c in kept_auto_flag_caltables:
                        continue
                    kept_auto_flag_caltables.add(ct_c)

        # (f) setjy / setjy_polcal: deduplicate repeated model writes when no MODEL_DATA
        #     consumer ran on that MS in between.
        elif stg in _MODEL_STAGES:
            ms_c = prods_c[0] if prods_c else _canon_path(str(params.get("ms_path", "")), wd)
            mkey: tuple[str, str, str] | None = None
            if stg == "setjy_polcal" and ("field" in params or "field" in meas):
                raw_f = params["field"] if "field" in params else meas["field"]
                mkey = ("setjy_polcal", ms_c, normalize_field_sel(str(raw_f)))
            elif stg == "setjy" and params:
                raw_ex = params.get("exclude_fields")
                if raw_ex is None:
                    ex_str = ""
                elif isinstance(raw_ex, (list, tuple)):
                    ex_str = ",".join(str(x) for x in raw_ex if x is not None and str(x).strip())
                else:
                    ex_str = str(raw_ex)
                mkey = ("setjy", ms_c, normalize_field_sel(ex_str))
            if ms_c and mkey is not None:
                later_m = kept_setjy_at.get(mkey, -1)
                if later_m > idx and not _has_idx_between(
                    kept_model_consumers_by_ms.get(ms_c, []), idx, later_m
                ):
                    continue
                kept_setjy_at[mkey] = idx

        # (g) applycal: drop when (i) any input caltable was re-solved later with no kept
        #     CORRECTED_DATA consumer on this MS in between, or (ii) a later kept applycal
        #     overwrote the same (ms, field) with no intervening kept MS consumer/modifier
        #     and no newly solved caltables applied in the later applycal (e.g. Stokes IQUV 7c -> polcal -> 5b).
        elif stg == "applycal":
            ms_c = prods_c[0] if prods_c else _canon_path(str(params.get("ms_path", "")), wd)
            raw_gts = params.get("gaintable")
            gts = (
                raw_gts
                if isinstance(raw_gts, (list, tuple))
                else ([raw_gts] if isinstance(raw_gts, str) and raw_gts else [])
            )
            cur_gts_c: set[str] = set()
            if ms_c and gts:
                stale_table = False
                for gt in gts:
                    if not isinstance(gt, str) or not gt:
                        continue
                    gt_c = _canon_path(gt, wd)
                    if gt_c:
                        cur_gts_c.add(gt_c)
                    next_s = next_kept_solve_for_prod.get(gt_c, -1)
                    if next_s > idx and not _has_idx_between(
                        kept_corrected_consumers_by_ms.get(ms_c, []), idx, next_s
                    ):
                        stale_table = True
                        break
                if stale_table:
                    continue

            cur_pol_types = tuple(str(x) for x in (meas.get("pol_types") or ()))
            raw_field = params.get("field") if "field" in params else meas.get("field")
            if ms_c and raw_field is not None:
                akey = (ms_c, normalize_field_sel(str(raw_field)))
                later_info = kept_applycal_at.get(akey)
                if later_info is not None:
                    later_a, later_gts_c, later_pol_types = later_info
                    if later_a > idx:
                        has_intervening = (
                            _has_idx_between(kept_ms_activity_by_ms.get(ms_c, []), idx, later_a)
                            or any(
                                idx < next_kept_solve_for_prod.get(l_gt, -1) < later_a
                                for l_gt in later_gts_c
                            )
                            or (
                                not cur_gts_c
                                and not later_gts_c
                                and cur_pol_types != later_pol_types
                            )
                        )
                        if not has_intervening:
                            continue
                kept_applycal_at[akey] = (idx, cur_gts_c, cur_pol_types)

        # Group is kept: update state for earlier indices.
        kept_groups_rev.append(grp)

        if stg == "applycal":
            ms_c_ap = prods_c[0] if prods_c else _canon_path(str(params.get("ms_path", "")), wd)
            if ms_c_ap:
                for gt_c in cur_gts_c:
                    kept_applied_ms_for_ct.setdefault(gt_c, []).append((idx, ms_c_ap))
        elif stg == "initial_bandpass" and len(prods_c) >= 2:
            ms_c_ib = _canon_path(str(params.get("ms_path", "")), wd) or (
                prods_c[-1] if prods_c[-1].endswith(".ms") else ""
            )
            if ms_c_ib:
                for ct_c in prods_c:
                    if ct_c != ms_c_ib:
                        kept_applied_ms_for_ct.setdefault(ct_c, []).append((idx, ms_c_ib))

        if stg not in ("flag_caltable", "applycal"):
            for in_ct in group_input_cts[idx]:
                kept_caltable_consumers_by_ct.setdefault(in_ct, []).append(idx)

        # When a kept solve of ct_c is crossed going backwards, an earlier kept solve
        # has its own auto-flag slot separate from the later solve's auto-flag.
        if stg in _PRODUCT_SOLVE_STAGES or is_casa_task_solve:
            for p_c in prods_c:
                kept_auto_flag_caltables.discard(p_c)

        is_corr_cons = _is_corrected_consumer(stg, params, meas)
        is_mod_cons = _is_model_consumer(stg, params)
        for m_c in ms_targets:
            if stg != "applycal":
                kept_ms_activity_by_ms.setdefault(m_c, []).append(idx)
            if is_corr_cons:
                kept_corrected_consumers_by_ms.setdefault(m_c, []).append(idx)
            if is_mod_cons:
                kept_model_consumers_by_ms.setdefault(m_c, []).append(idx)

    kept_groups = list(reversed(kept_groups_rev))

    # Track latest sha256 and kept-group count per script_path so shared/overwritten
    # script files fall back to run(**params, execute=True) across all sharing groups.
    latest_sha_for_script: dict[str, str | None] = {}
    sp_counts: dict[str, int] = {}
    for grp in kept_groups:
        sp = grp[-1].get("script_path")
        if isinstance(sp, str) and sp:
            latest_sha_for_script[sp] = grp[-1].get("script_sha256")
            sp_counts[sp] = sp_counts.get(sp, 0) + 1

    derived: list[dict] = []
    for grp in kept_groups:
        head = grp[0]
        tail = grp[-1]
        stage = str(head.get("stage", ""))
        tool = str(head.get("tool") or _stage_to_tool(stage))
        supports_exec = _run_supports_execute(tool)
        params = dict(tail.get("params") or {})
        if tool in _RUN_REGISTRY and not supports_exec:
            params.pop("execute", None)
        prods = [str(g.get("product")) for g in grp if g.get("product")]
        outputs: dict = {"product": prods[0]} if len(prods) == 1 else {"products": prods}
        for g in grp:
            meas = g.get("measurement")
            if isinstance(meas, dict):
                outputs.update(meas)

        sp = tail.get("script_path")
        sha = tail.get("script_sha256")
        script_fields: dict = {}
        if isinstance(sp, str) and sp:
            p_obj = Path(sp)
            disk_sha = _sha256(p_obj) if p_obj.is_file() else None
            overwritten_later = (
                sha is not None and latest_sha_for_script.get(sp) not in (None, sha)
            ) or (sha is not None and disk_sha is not None and disk_sha != sha)
            if (sp_counts.get(sp, 0) > 1 or overwritten_later) and params:
                if supports_exec:
                    params = {**params, "execute": True}
            else:
                script_fields["script_path"] = sp
                script_fields["script_sha256"] = sha or disk_sha
        elif not params:
            candidate = wd / f"{stage}.py"
            if candidate.is_file():
                resolved = str(candidate.resolve())
                script_fields["script_path"] = resolved
                script_fields["script_sha256"] = _sha256(candidate)
        elif supports_exec and "execute" not in params:
            params = {**params, "execute": True}

        label = Path(prods[0]).name if prods else stage
        rec: dict = {
            "step": 0,
            "ts": str(tail.get("at") or ""),
            "tool": tool,
            "params": params,
            "outputs": outputs,
            "rationale": f"{stage} -> {label}",
            "skill_rule": "",
            "status": "ok",
            **script_fields,
        }
        derived.append(rec)

    # 3. Merge manual reduction_log.jsonl records without duplicating matching steps.
    for m in manual_records:
        m_sp = m.get("script_path")
        matched = None
        for d in derived:
            if m_sp and d.get("script_path") == m_sp:
                matched = d
                break
            if (
                not m_sp
                and not d.get("script_path")
                and m.get("tool") == d.get("tool")
                and (not d.get("params") or m.get("params") == d.get("params"))
            ):
                matched = d
                break
        if matched is not None:
            if m.get("rationale"):
                matched["rationale"] = m["rationale"]
            if m.get("skill_rule"):
                matched["skill_rule"] = m["skill_rule"]
            if m.get("params") and not matched.get("params"):
                m_params = dict(m["params"])
                m_tool = str(matched.get("tool") or "")
                if m_tool in _RUN_REGISTRY and not _run_supports_execute(m_tool):
                    m_params.pop("execute", None)
                matched["params"] = m_params
            if isinstance(m.get("outputs"), dict) and m["outputs"]:
                matched["outputs"] = {**matched.get("outputs", {}), **m["outputs"]}
        else:
            derived.append(dict(m))

    for idx, rec in enumerate(derived, start=1):
        rec["step"] = idx
    return derived


def _validate_append(tool: str, params: dict, script_path: str, workdir: str) -> dict:
    """Refuse an entry render could not replay; return the script fields to store."""
    from ms_inspect.exceptions import ComputationError

    if tool not in _APPENDABLE:
        raise ComputationError(
            f"tool {tool!r} is not a replayable step. Use the write tool's own name "
            f"({', '.join(sorted(_APPENDABLE))}), one entry per call; 'manual' for work "
            "off the tools. Record checks in the outputs of the step they verify.",
            ms_path=workdir,
        )
    execute = params.get("execute", False)
    if not isinstance(execute, bool):
        raise ComputationError(
            f"params.execute must be the literal true/false passed to the tool, got {execute!r}.",
            ms_path=workdir,
        )
    if not script_path:
        if tool in _SCRIPTLESS_TOOLS:
            return {}
        # manual has no run() to replay, so it always needs the script
        if tool not in _RUN_REGISTRY or not execute:
            raise ComputationError(
                f"script_path is required for {tool!r}"
                + ("" if tool not in _RUN_REGISTRY else " unless it ran with execute=true")
                + ": name the script that was actually run (generated, edited, or your own).",
                ms_path=workdir,
            )
        return {}
    path = Path(script_path)
    if not path.is_absolute():
        path = Path(workdir) / path
    if not path.is_file():
        raise ComputationError(f"script_path does not exist: {path}", ms_path=workdir)
    return {"script_path": str(path.resolve()), "script_sha256": _sha256(path)}


_RUN_SCRIPT_HELPER = [
    "import hashlib",
    "import subprocess",
    "import sys",
    "",
    "",
    "def _run_script(path, sha256):",
    "    with open(path, 'rb') as fh:",
    "        if hashlib.sha256(fh.read()).hexdigest() != sha256:",
    "            sys.exit(f'{path} changed since it was recorded; not replaying')",
    "    subprocess.run([sys.executable, path], check=True)",
    "",
]


def _replay_script(records: list[dict], keep_steps: list[int] | None = None) -> str:
    """
    Render an EXECUTABLE replay of the recorded working calls.

    Each recognised step becomes ``importlib.import_module(mod).run(**params)``.
    Faithful replay requires the appended params to be the literal working
    kwargs (absolute paths, full gaintable lists) — abbreviated/placeholder
    params will not run as-is.
    """
    lines = [
        "#!/usr/bin/env python",
        '"""',
        "Auto-generated by ms_reduction_log render — executable replay of the",
        "working path. Run inside the project environment (pixi run python ...).",
        "Review before running: paths and selections are dataset-specific.",
        '"""',
        "import importlib",
        *_RUN_SCRIPT_HELPER,
        "",
    ]
    for r in records:
        if keep_steps is not None and r.get("step") not in keep_steps:
            lines.append(f"# step {r.get('step')}: dropped (not in keep_steps) — {r.get('tool')}")
            lines.append("")
            continue
        tool = r.get("tool", "?")
        params = r.get("params", {})
        rationale = r.get("rationale")
        if rationale:
            lines.append(f"# step {r.get('step')}: {rationale}")
        mod = _RUN_REGISTRY.get(tool)
        if r.get("script_path"):
            lines.append(f"_run_script({r['script_path']!r}, {r.get('script_sha256')!r})  # {tool}")
        elif mod is None:
            lines.append(f"# MANUAL STEP — no run() mapping for {tool!r}:")
            lines.append(f"#   params = {params!r}")
        else:
            call_params = dict(params) if isinstance(params, dict) else {}
            if not _run_supports_execute(str(tool)):
                call_params.pop("execute", None)
            lines.append(f"importlib.import_module({mod!r}).run(")
            for k, v in call_params.items():
                lines.append(f"    {k}={v!r},")
            lines.append(")")
        lines.append("")
    return "\n".join(lines)


def run(
    action: str,
    workdir: str,
    tool: str = "",
    params: dict | None = None,
    outputs: dict | None = None,
    rationale: str = "",
    skill_rule: str = "",
    status: str = "ok",
    script_path: str = "",
    keep_steps: list[int] | None = None,
) -> dict:
    """
    Append to / render / list the reduction working-calls ledger.

    Args:
        action:     'append', 'render', or 'list'.
        workdir:    Directory holding (or to hold) reduction_log.jsonl.
        tool:       (append) name of the tool/call that worked, e.g. 'ms_gaincal'.
        params:     (append) exact parameters that worked.
        outputs:    (append) salient outputs worth recording (paths, key numbers).
        rationale:  (append) why this step was done.
        skill_rule: (append) skill file / threshold cited, e.g. '07 Step 3'.
        status:     (append) outcome tag; default 'ok'. Only shuttle working calls.
        script_path: (append) the script that was run; required unless the call
                    ran with execute=True. Its sha256 is stored for replay.
        keep_steps: (render) step numbers to replay; the rest are emitted as
                    'dropped' comments. None replays every step.

    Returns:
        Standard envelope. append → n_records; render → recipe + replay_script;
        list → compact step/tool/rationale summary.
    """
    wd = Path(workdir)
    if not wd.is_dir():
        from ms_inspect.exceptions import ComputationError

        raise ComputationError(f"workdir does not exist: {workdir}", ms_path=workdir)

    path = _log_path(workdir)

    if action == "append":
        script = _validate_append(tool, params or {}, script_path, workdir)
        records = _read_records(path)
        record = {
            "step": len(records) + 1,
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": tool,
            "params": params or {},
            "outputs": outputs or {},
            "rationale": rationale,
            "skill_rule": skill_rule,
            "status": status,
            **script,
        }
        with path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={
                "action": "append",
                "log_path": fmt_field(str(path)),
                "step_recorded": fmt_field(record["step"]),
                "n_records": fmt_field(len(records) + 1),
            },
            casa_calls=[f"append → {path}"],
        )

    records = load_effective_records(wd)

    if action == "list":
        summary = [
            {
                "step": r.get("step"),
                "tool": r.get("tool"),
                "rationale": r.get("rationale"),
                "skill_rule": r.get("skill_rule"),
            }
            for r in records
        ]
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={"action": "list", "n_records": fmt_field(len(records)), "steps": summary},
            casa_calls=[f"read → {path}"],
        )

    if action == "render":
        script = _replay_script(records, keep_steps)
        script_path = wd / "reduction_replay.py"
        write_script(script_path, script)
        return response_envelope(
            tool_name=TOOL_NAME,
            ms_path=workdir,
            data={
                "action": "render",
                "n_records": fmt_field(len(records)),
                "recipe": fmt_field(records),
                "replay_script": fmt_field(str(script_path)),
                "dropped_steps": fmt_field(
                    [
                        r.get("step")
                        for r in records
                        if keep_steps is not None and r.get("step") not in keep_steps
                    ]
                ),
            },
            casa_calls=[f"read → {path}", f"write → {script_path}"],
        )

    from ms_inspect.exceptions import ComputationError

    raise ComputationError(
        f"Unknown action '{action}'; use 'append', 'render', or 'list'.",
        ms_path=workdir,
    )
