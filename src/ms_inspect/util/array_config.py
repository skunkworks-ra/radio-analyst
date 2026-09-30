"""
util/array_config.py — VLA array configuration of a Measurement Set.

The MS schema has no column for the array configuration. Two sources, in
order of trust:

1. ASDM_EXECBLOCK.configName — NRAO's own record, copied verbatim from the
   ASDM when importasdm runs with asis='ExecBlock'. Flag COMPLETE.
2. The longest baseline with data, against the nominal maximum baseline of
   each configuration. Flag INFERRED. A hybrid or move-time array matches no
   configuration and gives UNAVAILABLE.

Used by ms_observation_info and ms_field_list.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ms_inspect.util.casa_context import open_msmd, open_table
from ms_inspect.util.conversions import baselines_m, spherical_to_ecef
from ms_inspect.util.formatting import field

# Nominal maximum baseline of each VLA configuration, in km.
NOMINAL_MAX_BASELINE_KM = {"A": 36.4, "B": 11.1, "C": 3.4, "D": 1.03}

# Relative tolerance on the longest-baseline match. Adjacent configurations
# differ by a factor of about 3.3, so the accepted ranges do not overlap.
LENGTH_TOLERANCE = 0.20

# A configName made of configuration letters, joined by 'n' for a hybrid
# (for example 'BnA': the north arm in A, the other arms in B).
_CONFIG_NAME_RE = re.compile(r"^[ABCD](n[ABCD])*$")


def config_letters(name: str | None) -> list[str] | None:
    """Configuration letters in a configName ('BnA' -> ['B', 'A']); None if not parseable."""
    if not name or not _CONFIG_NAME_RE.match(name.strip()):
        return None
    return name.strip().split("n")


def array_baselines(msmd) -> dict | None:
    """
    Cross baselines that have data in the MS: antenna names, pair indices,
    physical lengths and ITRF vectors (ant_j - ant_i) in metres. None when
    msmd gives no ITRF positions.
    """
    try:
        names = list(msmd.antennanames())
        if len(names) < 2:
            return None
        positions = []
        for ant in range(len(names)):
            pos = msmd.antennaposition(ant)
            if pos.get("refer") != "ITRF":
                return None
            positions.append(
                spherical_to_ecef(pos["m0"]["value"], pos["m1"]["value"], pos["m2"]["value"])
            )
        has_data = np.asarray(msmd.baselines(), dtype=bool)
    except Exception:
        return None
    xyz = np.array(positions)
    ant_i, ant_j, length_m = baselines_m(xyz.T)
    keep = has_data[ant_i, ant_j]
    return {
        "names": names,
        "ant_i": ant_i[keep],
        "ant_j": ant_j[keep],
        "length_m": length_m[keep],
        "vector_m": (xyz[ant_j] - xyz[ant_i])[keep],
    }


def config_from_execblock(ms_path: str | Path) -> dict | None:
    """The configuration from ASDM_EXECBLOCK.configName; None if the subtable is absent."""
    sub = Path(ms_path) / "ASDM_EXECBLOCK"
    if not sub.exists():
        return None
    try:
        with open_table(str(sub)) as tb:
            names = sorted({str(n).strip() for n in tb.getcol("configName")})
    except Exception:
        return field(None, flag="UNAVAILABLE", note="ASDM_EXECBLOCK is present but unreadable.")
    if len(names) != 1:
        return field(
            None,
            flag="UNAVAILABLE",
            note=f"ASDM_EXECBLOCK has several configurations: {names}.",
        )
    name = names[0]
    if config_letters(name) is None:
        return field(
            None,
            flag="UNAVAILABLE",
            note=f"ASDM_EXECBLOCK configName {name!r} is not a known configuration name.",
        )
    return field(name, flag="COMPLETE", note="From ASDM_EXECBLOCK.configName.")


def config_from_array(array: dict | None) -> dict:
    """The configuration whose nominal maximum baseline matches the longest baseline with data."""
    if array is None or array["length_m"].size == 0:
        return field(None, flag="UNAVAILABLE", note="No baselines with data.")
    longest_km = float(array["length_m"].max()) / 1000.0
    for letter, nominal_km in NOMINAL_MAX_BASELINE_KM.items():
        if abs(longest_km / nominal_km - 1.0) <= LENGTH_TOLERANCE:
            return field(
                letter,
                flag="INFERRED",
                note=(
                    f"Longest baseline with data {longest_km:.2f} km is within "
                    f"{LENGTH_TOLERANCE:.0%} of the {letter}-configuration maximum "
                    f"{nominal_km} km."
                ),
            )
    return field(
        None,
        flag="UNAVAILABLE",
        note=(
            f"Longest baseline with data {longest_km:.2f} km matches no configuration "
            f"within {LENGTH_TOLERANCE:.0%}: a hybrid or move-time array."
        ),
    )


def resolve_array_config(ms_path: str | Path) -> dict:
    """The configuration of the MS: ASDM_EXECBLOCK first, else the longest baseline."""
    from_execblock = config_from_execblock(ms_path)
    if from_execblock is not None:
        return from_execblock
    with open_msmd(str(ms_path)) as msmd:
        return config_from_array(array_baselines(msmd))
