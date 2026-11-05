"""
util/phase_cal_catalog.py — VLA phase calibrator reference catalog.

Parses PhaseCalList.txt (shipped as package data) into an in-memory
lookup table.  Provides:

    get_source(iau_name)             → PhaseCalEntry | None
    lookup_nearest(ra_deg, dec_deg,  → PhaseCalMatch | None
                   band_code,
                   array_config,
                   max_sep_deg)

Source: NRAO VLA Calibrator Manual (PhaseCalList.txt, bundled in this package).

Determinism guarantee: static data, no live web fetch, no CASA dependency.
"""

from __future__ import annotations

import importlib.resources
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

BAND_WAVELENGTH_TO_CODE: dict[str, str] = {
    "90cm": "P",
    "20cm": "L",
    "6cm": "C",
    "3.7cm": "X",
    "2cm": "U",
    "1.3cm": "K",
    "0.7cm": "Q",
}

# Nominal frequency of each callist band, from its wavelength label (c / lambda).
_C_CM_GHZ = 29.9792458
BAND_NOMINAL_GHZ: dict[str, float] = {
    code: _C_CM_GHZ / float(wl[:-2]) for wl, code in BAND_WAVELENGTH_TO_CODE.items()
}

# Quality codes in descending order of suitability
QUALITY_RANK: dict[str, int] = {"P": 4, "S": 3, "W": 2, "C": 1, "X": 0, "?": -1}


@dataclass
class BandEntry:
    band_code: str  # L, C, X, U, K, Q, P
    wavelength: str  # '20cm', '6cm', …
    quality_A: str  # P / S / W / C / X / ?
    quality_B: str
    quality_C: str
    quality_D: str
    flux_jy: float | None
    uvmin_kl: float | None
    uvmax_kl: float | None

    def quality_for_config(self, array_config: str) -> str:
        """Return quality code for the given VLA array config (A/B/C/D)."""
        return {
            "A": self.quality_A,
            "B": self.quality_B,
            "C": self.quality_C,
            "D": self.quality_D,
        }.get(array_config.upper(), "?")

    def is_usable(self, array_config: str, min_quality: str = "W") -> bool:
        q = self.quality_for_config(array_config)
        return QUALITY_RANK.get(q, -1) >= QUALITY_RANK.get(min_quality, -1)


@dataclass
class PhaseCalEntry:
    iau_name: str  # '0137+331'
    ra_deg: float  # J2000 RA in decimal degrees
    dec_deg: float  # J2000 Dec in decimal degrees
    pos_accuracy: str  # A / B / C / T
    pos_ref: str | None  # 'Aug01', 'May00', …
    alt_name: str | None  # '3C48', 'JVAS', 'CJ2', …
    bands: dict[str, BandEntry] = field(default_factory=dict)  # keyed by band_code

    def band(self, band_code: str) -> BandEntry | None:
        return self.bands.get(band_code.upper())


@dataclass
class PhaseCalMatch:
    entry: PhaseCalEntry
    separation_deg: float
    band: BandEntry | None  # None if no entry for requested band
    quality: str | None  # quality code at requested band/config; None if no band


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_RA_RE = re.compile(r"(\d+)h(\d+)m([\d.]+)s")
_DEC_RE = re.compile(r'(-?)(\d+)d(\d+)\'([\d."]+)')
_BAND_RE = re.compile(
    r"^\s*(\d+\.?\d*cm)\s+([A-Z])\s+"  # wavelength  band_code
    r"([A-Z?])\s+([A-Z?])\s+([A-Z?])\s+([A-Z?])\s+"  # q_A q_B q_C q_D
    r"([\d.]+)"  # flux
)
_NUMBER_RE = re.compile(r"\d+\.?\d*")

# Start column of "UVMAX" in the BAND header. A row may carry a UVMAX value
# with no UVMIN, so the two limits are told apart by column, not by order.
_DEFAULT_UVMAX_COL = 46


def _parse_ra(s: str) -> float:
    m = _RA_RE.search(s)
    if not m:
        raise ValueError(f"Cannot parse RA: {s!r}")
    h, mn, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return (h + mn / 60.0 + sec / 3600.0) * 15.0


def _parse_dec(s: str) -> float:
    m = _DEC_RE.search(s)
    if not m:
        raise ValueError(f"Cannot parse Dec: {s!r}")
    sign = -1.0 if m.group(1) == "-" else 1.0
    deg, mn = int(m.group(2)), int(m.group(3))
    sec_str = m.group(4).rstrip('"').rstrip("'")
    sec = float(sec_str)
    return sign * (deg + mn / 60.0 + sec / 3600.0)


def _parse_j2000_line(line: str) -> tuple[str, float, float, str, str | None, str | None]:
    """Parse a J2000 header line.  Returns (iau_name, ra_deg, dec_deg, pos_accuracy, pos_ref, alt_name)."""
    # e.g. '0137+331   J2000  B 01h37m41.299431s 33d09'35.132990'' Aug01 3C48'
    tokens = line.split()
    if len(tokens) < 4:
        raise ValueError(f"Malformed J2000 line: {line!r}")
    iau_name = tokens[0]
    pos_accuracy = tokens[2]
    ra_str = tokens[3]
    dec_str = tokens[4]
    ra_deg = _parse_ra(ra_str)
    dec_deg = _parse_dec(dec_str)

    # Remaining tokens are optional pos_ref and alt_name
    rest = tokens[5:]
    pos_ref: str | None = None
    alt_name: str | None = None
    # pos_ref looks like 'Aug01', 'May00', 'Nov96', 'Jan00' etc. — month+year
    _POSREF_RE = re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{2}$")
    for tok in rest:
        if _POSREF_RE.match(tok):
            pos_ref = tok
        else:
            alt_name = tok
    return iau_name, ra_deg, dec_deg, pos_accuracy, pos_ref, alt_name


def _parse_band_line(line: str, uvmax_col: int = _DEFAULT_UVMAX_COL) -> BandEntry | None:
    m = _BAND_RE.match(line)
    if not m:
        return None
    wavelength = m.group(1).strip()
    band_code = BAND_WAVELENGTH_TO_CODE.get(wavelength, m.group(2))

    # A number that starts left of the UVMAX column is UVMIN. Rows drift by a
    # column or two, so the boundary sits one column left of the header.
    uvmin_kl: float | None = None
    uvmax_kl: float | None = None
    for num in _NUMBER_RE.finditer(line, m.end(7)):
        if num.start() < uvmax_col - 1:
            uvmin_kl = float(num.group())
        else:
            uvmax_kl = float(num.group())

    return BandEntry(
        band_code=band_code,
        wavelength=wavelength,
        quality_A=m.group(3),
        quality_B=m.group(4),
        quality_C=m.group(5),
        quality_D=m.group(6),
        flux_jy=float(m.group(7)),
        uvmin_kl=uvmin_kl,
        uvmax_kl=uvmax_kl,
    )


# ---------------------------------------------------------------------------
# Catalog loader
# ---------------------------------------------------------------------------


def _load_catalog(text: str) -> dict[str, PhaseCalEntry]:
    catalog: dict[str, PhaseCalEntry] = {}
    current: PhaseCalEntry | None = None
    in_band_table = False
    uvmax_col = _DEFAULT_UVMAX_COL

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Global file header and per-entry separators
        if line.startswith("===") or line.startswith("---"):
            # "===" may appear as the global header underline or as the band-table
            # underline that immediately follows "BAND  A B C D ...".  In both cases
            # we just skip it; band-table state is set by the BAND header line itself.
            continue

        # Blank / whitespace-only lines end the current band table
        if not line.strip():
            in_band_table = False
            continue

        # Band table header — sequence: "---" then this line then "==="
        if "BAND" in line and "FLUX" in line:
            in_band_table = True
            if "UVMAX" in line:
                uvmax_col = line.index("UVMAX")
            continue

        # J2000 source header → start a new entry
        if "J2000" in line:
            in_band_table = False
            try:
                iau_name, ra_deg, dec_deg, pos_acc, pos_ref, alt_name = _parse_j2000_line(line)
            except ValueError:
                continue
            current = PhaseCalEntry(
                iau_name=iau_name,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                pos_accuracy=pos_acc,
                pos_ref=pos_ref,
                alt_name=alt_name,
            )
            catalog[iau_name] = current
            continue

        # Skip B1950 lines (duplicate position in old equinox)
        if "B1950" in line:
            continue

        # Band data rows
        if in_band_table and current is not None:
            band = _parse_band_line(line, uvmax_col)
            if band is not None:
                current.bands[band.band_code] = band

    return catalog


@lru_cache(maxsize=1)
def _get_catalog() -> dict[str, PhaseCalEntry]:
    pkg = importlib.resources.files("ms_inspect.util")
    data = (pkg / "PhaseCalList.txt").read_text(encoding="ascii", errors="replace")
    return _load_catalog(data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_source(iau_name: str) -> PhaseCalEntry | None:
    """Return a catalog entry by IAU name, or None if not found."""
    return _get_catalog().get(iau_name)


def _angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation in degrees (haversine formula)."""
    ra1_r = math.radians(ra1)
    ra2_r = math.radians(ra2)
    dec1_r = math.radians(dec1)
    dec2_r = math.radians(dec2)
    d_ra = ra2_r - ra1_r
    d_dec = dec2_r - dec1_r
    a = math.sin(d_dec / 2) ** 2 + math.cos(dec1_r) * math.cos(dec2_r) * math.sin(d_ra / 2) ** 2
    return math.degrees(2 * math.asin(math.sqrt(a)))


def flux_at_frequency(band_flux: dict[str, float | None], freq_ghz: float) -> dict | None:
    """Power-law flux at freq_ghz from the two callist bands that bracket it.

    band_flux maps band code to catalogued flux (Jy). Each band sits at its
    nominal frequency (BAND_NOMINAL_GHZ). The spectral index is fitted through
    the nearest band at or below and the nearest at or above freq_ghz; a band
    at exactly freq_ghz is returned as is. No extrapolation: None when
    freq_ghz is outside the catalogued bands or fewer than two have a flux.
    """
    pts = sorted(
        (BAND_NOMINAL_GHZ[c], c, f)
        for c, f in band_flux.items()
        if c in BAND_NOMINAL_GHZ and f is not None and f > 0
    )
    lo = [p for p in pts if p[0] <= freq_ghz]
    hi = [p for p in pts if p[0] >= freq_ghz]
    if not lo or not hi:
        return None
    (nu1, c1, s1), (nu2, c2, s2) = lo[-1], hi[0]
    used = [lo[-1]] if c1 == c2 else [lo[-1], hi[0]]
    inputs = [{"band": c, "nominal_ghz": round(nu, 4), "flux_jy": f} for nu, c, f in used]
    if c1 == c2:
        return {
            "flux_jy": s1,
            "freq_ghz": freq_ghz,
            "band": c1,
            "spectral_index": None,
            "inputs": inputs,
        }
    alpha = math.log(s2 / s1) / math.log(nu2 / nu1)
    return {
        "flux_jy": round(s1 * (freq_ghz / nu1) ** alpha, 4),
        "freq_ghz": freq_ghz,
        "band": None,
        "spectral_index": round(alpha, 4),
        "inputs": inputs,
    }


def vla_band_for_freq(freq_ghz: float) -> str | None:
    """Callist band code covering freq_ghz, from the VLA telescope profile's band edges."""
    from ms_inspect.util.telescope import profile_from_name

    vla = profile_from_name("EVLA")
    code = vla.band_code(freq_ghz * 1e9) if vla else None
    return {"Ku": "U"}.get(code, code)


def expected_flux(
    entry: PhaseCalEntry,
    freq_ghz: float | None,
    band_code: str | None = None,
    position_match: bool = True,
    identity_exact: bool = True,
) -> tuple[dict | None, str, str]:
    """Expected callist flux of entry: (value, flag, note).

    The row at the observed band if the list has one (COMPLETE); otherwise a
    power law through the bracketing bands (INFERRED). band_code is taken
    from freq_ghz via the VLA band edges when not given. COMPLETE drops to
    INFERRED when the position match is not exact (identity_exact=False).
    UNAVAILABLE when entry is not the source at the position, or nothing
    can be computed. The value always carries flux_jy, freq_ghz, band,
    spectral_index and inputs.
    """
    if not position_match:
        return (
            None,
            "UNAVAILABLE",
            f"{entry.iau_name} is a neighbour, not the source at this position.",
        )
    code = band_code.upper() if band_code else None
    if code is None and freq_ghz is not None:
        code = vla_band_for_freq(freq_ghz)
    row = entry.band(code) if code else None
    if row is not None and row.flux_jy is not None:
        value = {
            "flux_jy": row.flux_jy,
            "freq_ghz": freq_ghz,
            "band": row.band_code,
            "spectral_index": None,
            "inputs": [
                {
                    "band": row.band_code,
                    "nominal_ghz": round(BAND_NOMINAL_GHZ[row.band_code], 4),
                    "flux_jy": row.flux_jy,
                }
            ],
        }
        flag = "COMPLETE" if identity_exact else "INFERRED"
        note = f"Callist row for {entry.iau_name} at band {row.band_code}."
        if not identity_exact:
            note += " Position match is not exact."
        return value, flag, note
    if freq_ghz is None:
        return None, "UNAVAILABLE", f"No row at band {code or '?'} and no frequency to interpolate."
    est = flux_at_frequency({k: v.flux_jy for k, v in entry.bands.items()}, freq_ghz)
    if est is None:
        return (
            None,
            "UNAVAILABLE",
            f"No row at band {code or '?'} and {freq_ghz} GHz is not bracketed by two "
            "catalogued bands; no extrapolation.",
        )
    return (
        est,
        "INFERRED",
        f"No row for {entry.iau_name} at band {code or '?'}: power law through the bracketing "
        "bands at their nominal frequencies. Catalogue fluxes are old and phase calibrators vary.",
    )


def lookup_nearest(
    ra_deg: float,
    dec_deg: float,
    band_code: str | None = None,
    array_config: str | None = None,
    max_sep_deg: float = 0.5,
    min_quality: str = "W",
    identity_arcsec: float = 5.0,
) -> PhaseCalMatch | None:
    """Find the nearest catalog source within max_sep_deg.

    If band_code and array_config are given, the match must be usable at that
    band/config (quality >= min_quality).  Returns None if no match found.

    A source within identity_arcsec (and within max_sep_deg) is the source at
    that position and is always returned, with band=None if it has no row at
    band_code and its quality even if below min_quality. It is never replaced
    by a neighbour.

    Args:
        ra_deg:       Target RA in decimal degrees (J2000).
        dec_deg:      Target Dec in decimal degrees (J2000).
        band_code:    VLA band code ('L', 'C', 'X', …).  None = position-only match.
        array_config: Array configuration ('A', 'B', 'C', 'D').  None = ignore.
        max_sep_deg:  Search radius in degrees.
        min_quality:  Minimum acceptable quality code ('P', 'S', 'W', 'C').

    Returns:
        PhaseCalMatch with the nearest qualifying source, or None.
    """
    catalog = _get_catalog()
    best: PhaseCalMatch | None = None
    best_sep = max_sep_deg
    id_sep = min(identity_arcsec / 3600.0, max_sep_deg)
    identity: PhaseCalMatch | None = None

    def _match(entry: PhaseCalEntry, sep: float) -> PhaseCalMatch:
        band_entry = entry.band(band_code) if band_code else None
        quality = (
            band_entry.quality_for_config(array_config) if (band_entry and array_config) else None
        )
        return PhaseCalMatch(entry=entry, separation_deg=sep, band=band_entry, quality=quality)

    for entry in catalog.values():
        sep = _angular_separation_deg(ra_deg, dec_deg, entry.ra_deg, entry.dec_deg)
        if sep <= id_sep and (identity is None or sep < identity.separation_deg):
            identity = _match(entry, sep)
        if sep > best_sep:
            continue

        band_entry = entry.band(band_code) if band_code else None
        # If band/config filter requested, skip unusable sources
        if (
            band_code
            and array_config
            and (band_entry is None or not band_entry.is_usable(array_config, min_quality))
        ):
            continue

        best_sep = sep
        best = _match(entry, sep)

    return identity if identity is not None else best


def cone_search(ra_deg: float, dec_deg: float, radius_arcsec: float = 5.0) -> PhaseCalMatch | None:
    """Nearest catalog source within radius_arcsec, position only.

    The identity check used by ms_field_list and ms_set_intents: a field whose
    phase centre sits on a catalogued calibrator is that calibrator. Band and
    array-configuration quality are lookup_nearest's concern, not this one's.
    """
    return lookup_nearest(ra_deg, dec_deg, max_sep_deg=radius_arcsec / 3600.0)


def lookup_by_name(name: str) -> PhaseCalEntry | None:
    """Match by IAU name or alt_name (case-insensitive).  Returns first match."""
    name_upper = name.upper().replace(" ", "")
    catalog = _get_catalog()
    # exact IAU match first
    if name in catalog:
        return catalog[name]
    # alt_name match
    for entry in catalog.values():
        if entry.alt_name and entry.alt_name.upper().replace(" ", "") == name_upper:
            return entry
    return None
