"""
Session-scoped real CASA fixtures for the unit suite.

Several ms_modify tools read real CASA metadata (msmetadata, table columns)
even under execute=False, at script-generation time — not just inside the
generated script. Building a real, CASA-openable Measurement Set here, once
per session, lets those reads succeed for real instead of silently falling
through a swallow-and-degrade except-Exception path against an invalid
`table.info`-only stub, which is what most per-file `_make_ms` helpers built
and is the root cause of several tests that passed without exercising the
behavior they claimed to test.

Everything here is real, not fabricated to look plausible: the antenna
positions are the real VLA D-configuration (shipped with CASA's own data),
relabeled from the config file's pad names to the post-upgrade EVLA antenna
names (`ea01` etc.) a real observed MS actually reports. The two spectral
windows are real L-band continuum subbands (128 MHz / 64 chan, contiguous).
The two fields are at the real J2000 positions of 3C147 and 3C286 (field
name J1331+3030), with real scan intents (CALIBRATE_BANDPASS / OBSERVE_TARGET)
written via the simulator, not injected after the fact.

Usage:
    Read-only tests take `real_ms_raw` / `real_ms_calibrated` / `real_caltable`
    directly — these are the session-wide cached originals, shared by every
    test in the session, and must never be written to.

    Any test that mutates the MS or caltable (flagging, calibration writes,
    etc.) must take the `*_copy` fixture instead, which hands back a fresh
    `shutil.copytree` under that test's own `tmp_path`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_ANTENNA_NAMES = ["ea01", "ea02", "ea03", "ea05", "ea09"]


_VLA_LAT_DEG = 34.0784
_VLA_LON_DEG = -107.6184
_VLA_HEIGHT_M = 2124.0
_REF_TIME_SLASH = "2026-01-01/12:00:00"  # casatools me.epoch format
_REF_TIME_ISO = "2026-01-01T12:00:00"  # astropy Time format


def _transit_offset_hours(ra: str, dec: str) -> float:
    """Hours from the fixture's reference time to this source's real
    transit at the real VLA site. usehourangle=True in the simulator ties
    every sm.observe() call's hour angle to the FIRST source observed, not
    to each field's own transit — for two fields ~8h apart in RA (3C147,
    J1331+3030) that left the second field observed nowhere near its own
    meridian, at negative elevation, and 100% flagged. Computing each
    field's own transit offset and using usehourangle=False instead is the
    real fix, not a workaround."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time

    vla = EarthLocation(
        lat=_VLA_LAT_DEG * u.deg, lon=_VLA_LON_DEG * u.deg, height=_VLA_HEIGHT_M * u.m
    )
    ref = Time(_REF_TIME_ISO, scale="utc", location=vla)
    target = SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg))
    ha_hours = (ref.sidereal_time("apparent") - target.ra).wrap_at(12 * u.hourangle).hour
    # Sidereal hours run slightly fast relative to solar (UTC) hours.
    return -ha_hours / 1.0027379


def _antenna_positions() -> tuple[list[float], list[float], list[float], list[float], list[str]]:
    """First five antennas of the real VLA D-configuration, relabeled to
    post-upgrade EVLA antenna names already used elsewhere in this suite.
    The shipped config file uses pad names (W01, W02, ...); the names here
    match what a real observed MS reports. Five, not three: with only three
    antennas a single flagged baseline leaves some antenna with no data at
    all in a solution interval, which is a fragility of the fixture, not a
    real property of any dataset — no real VLA observation runs on 3
    antennas.
    """
    import casatools

    cfg = Path(casatools.ctsys.resolve("alma/simmos")) / "vla.d.cfg"
    x: list[float] = []
    y: list[float] = []
    z: list[float] = []
    diam: list[float] = []
    with open(cfg) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            x.append(float(parts[0]))
            y.append(float(parts[1]))
            z.append(float(parts[2]))
            diam.append(float(parts[3]))
            if len(x) == len(_ANTENNA_NAMES):
                break
    return x, y, z, diam, list(_ANTENNA_NAMES)


def _build_ms(path: Path) -> None:
    """Build a minimal, real, CASA-openable MS: 5 antennas, 2 contiguous
    L-band SPWs (128 MHz / 64 chan each, a real VLA continuum setup), and 2
    fields at their real J2000 coordinates with real scan intents —
    3C147 (CALIBRATE_BANDPASS) and J1331+3030 / 3C286 (OBSERVE_TARGET).
    """
    from casatools import measures, simulator

    if path.exists():
        shutil.rmtree(path)

    sm = simulator()
    me = measures()

    x, y, z, diam, names = _antenna_positions()

    sm.open(ms=str(path))
    sm.setconfig(
        telescopename="VLA",
        x=x,
        y=y,
        z=z,
        dishdiameter=diam,
        mount=["ALT-AZ"] * len(x),
        antname=names,
        coordsystem="global",
        referencelocation=me.observatory("VLA"),
    )
    sm.setfeed(mode="perfect R L", pol=[""])
    # Full L-band span (1.0-2.0 GHz), not a narrow slice: a real VLA L-band
    # continuum setup, and wide enough that real pol-property catalogue
    # entries (e.g. 3C286's 2019 nodes at 1.02 and 1.47 GHz) actually have
    # >=2 in-band frequency points to fit against. A narrower band here
    # isn't just less realistic, it made a real fit correctly fail for
    # lack of in-band nodes.
    sm.setspwindow(
        spwname="spw0",
        freq="1.0GHz",
        deltafreq="8MHz",
        freqresolution="8MHz",
        nchannels=64,
        stokes="RR LL",
    )
    sm.setspwindow(
        spwname="spw1",
        freq="1.512GHz",
        deltafreq="8MHz",
        freqresolution="8MHz",
        nchannels=64,
        stokes="RR LL",
    )
    sm.setfield(
        sourcename="3C147",
        sourcedirection=me.direction("J2000", "05h42m36.1s", "+49d51m07s"),
    )
    sm.setfield(
        sourcename="J1331+3030",
        sourcedirection=me.direction("J2000", "13h31m08.3s", "+30d30m33s"),
    )
    sm.setlimits(shadowlimit=0.001, elevationlimit="8deg")
    sm.setauto(autocorrwt=0.0)
    sm.settimes(
        integrationtime="10s",
        usehourangle=False,
        referencetime=me.epoch("UTC", _REF_TIME_SLASH),
    )

    t_3c147 = _transit_offset_hours("05h42m36.1s", "+49d51m07s")
    t_j1331 = _transit_offset_hours("13h31m08.3s", "+30d30m33s")

    sm.observe(
        "3C147",
        "spw0",
        starttime=f"{t_3c147 - 0.02}h",
        stoptime=f"{t_3c147 - 0.01}h",
        state_obs_mode="CALIBRATE_BANDPASS#UNSPECIFIED",
    )
    sm.observe(
        "3C147",
        "spw1",
        starttime=f"{t_3c147 - 0.01}h",
        stoptime=f"{t_3c147}h",
        state_obs_mode="CALIBRATE_BANDPASS#UNSPECIFIED",
    )
    sm.observe(
        "J1331+3030",
        "spw0",
        starttime=f"{t_j1331 - 0.01}h",
        stoptime=f"{t_j1331}h",
        state_obs_mode="OBSERVE_TARGET#UNSPECIFIED",
    )
    sm.close()

    _predict_signal(path, me)
    _remove_corrected_data(path)


def _predict_signal(path: Path, me) -> None:
    """Predict a real (if simplified) point-source sky model into MODEL_DATA,
    then copy it into DATA — without this, DATA is all zeros and any later
    real solve (gaincal) correctly refuses it as data with no signal, rather
    than something a fake MS could ever have exercised anyway. Unit flux
    (1 Jy, flat spectrum, unpolarized) is used deliberately: clearcal always
    resets MODEL_DATA to unity later, so predicting at unity keeps the
    predicted signal and the eventual solve self-consistent.
    """
    from casatools import componentlist, simulator, table

    cl = componentlist()
    cl_path = str(path) + ".sky.cl"
    if Path(cl_path).exists():
        shutil.rmtree(cl_path)
    cl.addcomponent(
        flux=1.0,
        fluxunit="Jy",
        shape="point",
        dir=me.direction("J2000", "05h42m36.1s", "+49d51m07s"),
    )
    cl.addcomponent(
        flux=1.0,
        fluxunit="Jy",
        shape="point",
        dir=me.direction("J2000", "13h31m08.3s", "+30d30m33s"),
    )
    cl.rename(cl_path)
    cl.close()

    sm = simulator()
    sm.openfromms(str(path))
    sm.predict(complist=cl_path)
    sm.close()

    tb = table()
    tb.open(str(path), nomodify=False)
    tb.putcol("DATA", tb.getcol("MODEL_DATA"))
    tb.close()

    # Add real thermal noise (sigma=0.01 Jy against a 1 Jy source, SNR~100).
    # Without this, DATA matches the assumed unit model exactly and gaincal
    # refuses the solve outright ("CHI2 IS SPURIOUSLY ZERO") — a real safety
    # check against numerically degenerate data, not a bug to route around.
    # No real MS is ever perfectly noiseless, so this isn't cutting a corner;
    # it's the one piece of realism a zero-noise simulation can't have.
    sm = simulator()
    sm.openfromms(str(path))
    sm.setnoise(mode="simplenoise", simplenoise="0.01Jy")
    sm.corrupt()
    sm.close()


def _remove_corrected_data(path: Path) -> None:
    """Drop CORRECTED_DATA from the raw MS.

    CASA's simulator tool creates MODEL_DATA *and* CORRECTED_DATA
    unconditionally as part of building any simulated MS — that's an
    artifact of the simulator, not something a real, freshly-correlated,
    not-yet-calibrated MS ever has (CORRECTED_DATA is added only by
    calibration/clearcal). Left in place, real_ms_raw wouldn't be able to
    stand in for genuinely uncalibrated data — verified directly: a tclean
    CORRECTED_DATA-presence check against it did not raise, because the
    column really was there.
    """
    from casatools import table

    tb = table()
    tb.open(str(path), nomodify=False)
    tb.removecols(["CORRECTED_DATA"])
    tb.close()


def _add_calibrated_columns(raw_path: Path, calibrated_path: Path) -> None:
    """Copy the raw MS and add a real CORRECTED_DATA column via clearcal —
    the standard CASA way to materialize it. MODEL_DATA already exists on
    the raw MS (sm.predict() writes it); clearcal resets it to unity here,
    which is what makes the later gaincal solve numerically well-posed."""
    from casatasks import clearcal

    if calibrated_path.exists():
        shutil.rmtree(calibrated_path)
    shutil.copytree(raw_path, calibrated_path)
    clearcal(vis=str(calibrated_path), addmodel=True)


def _build_caltable(calibrated_ms: Path, caltable_path: Path) -> None:
    """A real caltable, produced by an actual gaincal() solve — the only
    reliable way to get casacore's caltable structure right, rather than
    hand-building the table format. Solves on both fields (field="") rather
    than just 3C147: fluxscale's own real use case needs solutions for both
    a reference and a transfer field in one caltable, and tools that resolve
    field names to caltable IDs (fluxscale._resolve_field_ids) need a
    caltable that genuinely has more than one field in it to test against."""
    from casatasks import gaincal

    if caltable_path.exists():
        shutil.rmtree(caltable_path)
    gaincal(
        vis=str(calibrated_ms),
        caltable=str(caltable_path),
        field="",
        solint="inf",
        refant="ea01",
        gaintype="G",
        calmode="ap",
    )


@pytest.fixture(scope="session")
def _real_casa_fixtures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real_casa_fixtures")
    raw = root / "raw.ms"
    calibrated = root / "calibrated.ms"
    caltable = root / "gain.G"

    _build_ms(raw)
    _add_calibrated_columns(raw, calibrated)
    _build_caltable(calibrated, caltable)

    yield {"raw": raw, "calibrated": calibrated, "caltable": caltable}

    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def real_ms_raw(_real_casa_fixtures) -> str:
    """Path to a real, CASA-openable MS with a predicted MODEL_DATA column
    but no CORRECTED_DATA. Session-wide and shared — READ-ONLY. Use
    `real_ms_raw_copy` to mutate."""
    return str(_real_casa_fixtures["raw"])


@pytest.fixture(scope="session")
def real_ms_calibrated(_real_casa_fixtures) -> str:
    """Path to the same MS with a real CORRECTED_DATA column added (and
    MODEL_DATA reset to unity by clearcal). Session-wide and shared —
    READ-ONLY. Use `real_ms_calibrated_copy` to mutate."""
    return str(_real_casa_fixtures["calibrated"])


@pytest.fixture(scope="session")
def real_caltable(_real_casa_fixtures) -> str:
    """Path to a real caltable, from an actual gaincal() solve against
    real_ms_calibrated on both fields (3C147 and J1331+3030). Session-wide
    and shared — READ-ONLY. Use `real_caltable_copy` to mutate."""
    return str(_real_casa_fixtures["caltable"])


@pytest.fixture
def real_ms_raw_copy(real_ms_raw, tmp_path) -> str:
    """A fresh per-test copy of real_ms_raw — safe to mutate."""
    dst = Path(tmp_path) / "raw.ms"
    shutil.copytree(real_ms_raw, dst)
    return str(dst)


@pytest.fixture
def real_ms_calibrated_copy(real_ms_calibrated, tmp_path) -> str:
    """A fresh per-test copy of real_ms_calibrated — safe to mutate."""
    dst = Path(tmp_path) / "calibrated.ms"
    shutil.copytree(real_ms_calibrated, dst)
    return str(dst)


@pytest.fixture
def real_caltable_copy(real_caltable, tmp_path) -> str:
    """A fresh per-test copy of real_caltable — safe to mutate."""
    dst = Path(tmp_path) / "gain.G"
    shutil.copytree(real_caltable, dst)
    return str(dst)
