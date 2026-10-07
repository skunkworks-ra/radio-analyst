"""
util/selection.py — field and correlation selection shared by tools.

match_field_names is CASA-free. parallel_corr_by_ddid opens two subtables.
"""

from __future__ import annotations

import fnmatch

# CASA Stokes codes for the parallel hands.
PARALLEL_CORR = {5: "RR", 8: "LL", 9: "XX", 12: "YY"}


def match_field_names(names: list[str], field_sel: str) -> list[int]:
    """Resolve a CASA-style field selection against FIELD names. CASA-free.

    Tokens (comma-separated): exact name, shell wildcard ('PER_FIELD_*'),
    integer id ('3') or inclusive id range ('3~7'). Every token must match at
    least one field — an unmatched token raises ValueError rather than silently
    widening the selection to every field.
    """
    ids: set[int] = set()
    for raw in field_sel.split(","):
        tok = raw.strip()
        if not tok:
            continue
        hit: set[int] = set()
        if tok.isdigit():
            if int(tok) < len(names):
                hit.add(int(tok))
        elif "~" in tok and all(p.strip().isdigit() for p in tok.split("~", 1)):
            lo, hi = (int(p) for p in tok.split("~", 1))
            hit.update(i for i in range(lo, hi + 1) if i < len(names))
        elif any(c in tok for c in "*?["):
            hit.update(i for i, nm in enumerate(names) if fnmatch.fnmatchcase(nm, tok))
        else:
            hit.update(i for i, nm in enumerate(names) if nm == tok)
        if not hit:
            raise ValueError(f"field token {tok!r} matches no field in the MS")
        ids |= hit
    if not ids:
        raise ValueError(f"field selection {field_sel!r} is empty")
    return sorted(ids)


def parallel_corr_from_codes(
    corr_by_pol: list[list[int]], pol_ids: list[int]
) -> list[list[tuple[int, str]]]:
    """Per DATA_DESC_ID, the (index, name) of its parallel-hand correlations,
    taken from the POLARIZATION row that DATA_DESC_ID points to. CASA-free."""
    return [
        [(i, PARALLEL_CORR[c]) for i, c in enumerate(corr_by_pol[pid]) if c in PARALLEL_CORR]
        for pid in pol_ids
    ]


def _corr_tables(ms_str: str) -> tuple[list[list[int]], list[int]]:
    """CORR_TYPE per POLARIZATION row, and POLARIZATION_ID per DATA_DESC_ID."""
    from ms_inspect.util.casa_context import open_table

    with open_table(ms_str + "/POLARIZATION") as tb:
        corr = [[int(c) for c in tb.getcell("CORR_TYPE", r)] for r in range(tb.nrows())]
    with open_table(ms_str + "/DATA_DESCRIPTION") as tb:
        pol_ids = [int(x) for x in tb.getcol("POLARIZATION_ID")]
    return corr, pol_ids


def corr_codes_by_ddid(ms_str: str) -> list[list[int]]:
    """For each DATA_DESC_ID, the CORR_TYPE codes of the POLARIZATION row it
    points to (not row 0)."""
    corr, pol_ids = _corr_tables(ms_str)
    return [corr[pid] for pid in pol_ids]


def parallel_corr_by_ddid(ms_str: str) -> list[list[tuple[int, str]]]:
    """For each DATA_DESC_ID, the (index, name) of its parallel-hand correlations,
    read from the POLARIZATION row that DATA_DESCRIPTION actually points to."""
    return parallel_corr_from_codes(*_corr_tables(ms_str))
