"""
tools/smearing.py — ms_smearing_limits

Largest channel width and time bin whose smearing stays within a stated
peak-brightness loss at the 10%-power radius of the primary beam
(Bridle & Schwab 1999, Synthesis Imaging in Radio Astronomy II, ch. 18).

    x            = r10 / theta_syn
    r10          = AIRY_R10_LAMBDA_OVER_D * lambda(nu_min) / D_min
    theta_syn    = lambda(nu_max) / B_max

    time:       R_t  = 1 - C_t * x**2 * tau**2,   C_t = omega_e**2 * 8 ln2 / 24
    bandwidth:  R_bw = 1 / sqrt(1 + (2 ln2 / 3) * (beta * x)**2),  beta = dnu / nu

The PB radius is taken at the lowest frequency and the beam at the highest, so
the bound holds for every frequency in an image that spans the whole band.
theta_syn = lambda/B_max ignores weighting; the real beam is wider, so the
limits are conservative. The time formula is exact at dec = 90 deg and an
upper bound elsewhere.

For a fixed radius beta * x = dnu * r10 * B_max / c, so the bandwidth limit is
one width in Hz for all SPWs.

Read-only.
"""

from __future__ import annotations

import math

import numpy as np

from ms_inspect.util.casa_context import open_msmd, open_table, validate_ms_path
from ms_inspect.util.conversions import baselines_m
from ms_inspect.util.formatting import field as fmt_field
from ms_inspect.util.formatting import response_envelope

TOOL_NAME = "ms_smearing_limits"

C_M_S = 299_792_458.0
OMEGA_EARTH_RAD_S = 7.2921159e-5

#: r10 / (lambda / D) for a uniformly illuminated circular aperture:
#: (2 J1(u) / u)**2 = 0.1 at u = 2.7314, and r10 = u / pi.
AIRY_R10_LAMBDA_OVER_D = 0.86942

#: Time-smearing coefficient in s**-2: a Gaussian beam of FWHM theta smeared
#: along an arc of length r * omega_e * tau loses (r omega_e tau)**2 / (24 sigma**2).
TIME_COEFF_S2 = OMEGA_EARTH_RAD_S**2 * 8.0 * math.log(2.0) / 24.0

BANDWIDTH_COEFF = 2.0 * math.log(2.0) / 3.0


def largest_divisor_at_most(n: int, limit: int) -> int:
    """Largest divisor of n that is <= limit (at least 1)."""
    for d in range(min(n, max(limit, 1)), 0, -1):
        if n % d == 0:
            return d
    return 1


def time_loss(x: float, tau_s: float) -> float:
    """Fractional peak loss from averaging tau_s seconds at x = r / theta_syn."""
    return TIME_COEFF_S2 * x**2 * tau_s**2


def bandwidth_loss(beta_x: float) -> float:
    """Fractional peak loss for a Gaussian bandpass at the product beta * x."""
    return 1.0 - 1.0 / math.sqrt(1.0 + BANDWIDTH_COEFF * beta_x**2)


def compute_limits(
    *,
    nu_min_hz: float,
    nu_max_hz: float,
    max_baseline_m: float,
    dish_diameter_m: float,
    dump_time_s: float | None,
    spws: list[dict],
    max_time_loss: float,
    max_bandwidth_loss: float,
    max_timebin_s: float,
) -> dict:
    """
    Pure arithmetic behind ms_smearing_limits.

    spws: [{"spw_id", "nchan", "channel_width_hz"}, ...]
    """
    lam_min_freq = C_M_S / nu_min_hz
    lam_max_freq = C_M_S / nu_max_hz
    r10_rad = AIRY_R10_LAMBDA_OVER_D * lam_min_freq / dish_diameter_m
    theta_syn_rad = lam_max_freq / max_baseline_m
    x = r10_rad / theta_syn_rad

    tau_max_s = math.sqrt(max_time_loss / TIME_COEFF_S2) / x
    beta_x_max = math.sqrt((1.0 / (1.0 - max_bandwidth_loss) ** 2 - 1.0) / BANDWIDTH_COEFF)
    dnu_max_hz = beta_x_max * C_M_S / (r10_rad * max_baseline_m)

    tau_allowed = min(tau_max_s, max_timebin_s)
    if dump_time_s and dump_time_s > 0:
        n_dumps = math.floor(tau_allowed / dump_time_s + 1e-9)
        suggested_timebin_s = n_dumps * dump_time_s if n_dumps >= 1 else 0.0
    else:
        n_dumps = None
        suggested_timebin_s = None

    per_spw: list[dict] = []
    for s in spws:
        nchan = int(s["nchan"])
        cw = float(s["channel_width_hz"])
        max_chan = math.floor(dnu_max_hz / cw + 1e-9) if cw > 0 else 1
        width = largest_divisor_at_most(nchan, max_chan)
        out_width_hz = width * cw
        per_spw.append(
            {
                "spw_id": int(s["spw_id"]),
                "nchan": nchan,
                "channel_width_hz": cw,
                "max_width_channels": max_chan,
                "suggested_width_channels": width,
                "suggested_output_nchan": nchan // width,
                "output_channel_width_hz": out_width_hz,
                "bandwidth_loss_at_suggested": round(
                    bandwidth_loss(out_width_hz * r10_rad * max_baseline_m / C_M_S), 4
                ),
            }
        )

    return {
        "r10_arcmin": math.degrees(r10_rad) * 60.0,
        "theta_syn_arcsec": math.degrees(theta_syn_rad) * 3600.0,
        "x": x,
        "tau_max_s": tau_max_s,
        "dnu_max_hz": dnu_max_hz,
        "suggested_timebin_s": suggested_timebin_s,
        "suggested_timebin_n_dumps": n_dumps,
        "time_loss_at_suggested": (
            time_loss(x, suggested_timebin_s) if suggested_timebin_s is not None else None
        ),
        "per_spw": per_spw,
    }


def _read_inputs(ms_str: str, casa_calls: list[str]) -> dict:
    """Read frequencies, channelisation, antenna geometry and dump time."""
    with open_table(ms_str + "/ANTENNA") as tb:
        positions = tb.getcol("POSITION")
        diameters = np.asarray(tb.getcol("DISH_DIAMETER"), dtype=float)
    casa_calls.append("tb.getcol(ANTENNA: POSITION, DISH_DIAMETER)")
    _, _, lengths = baselines_m(positions)

    spws: list[dict] = []
    freqs_lo: list[float] = []
    freqs_hi: list[float] = []
    dump_time_s: float | None = None
    with open_msmd(ms_str) as msmd:
        for spw_id in range(msmd.nspw()):
            f = np.asarray(msmd.chanfreqs(spw_id), dtype=float)
            w = np.abs(np.asarray(msmd.chanwidths(spw_id), dtype=float))
            spws.append({"spw_id": spw_id, "nchan": int(f.size), "channel_width_hz": float(w[0])})
            freqs_lo.append(float((f - w / 2).min()))
            freqs_hi.append(float((f + w / 2).max()))
        casa_calls.append("msmd.chanfreqs(), msmd.chanwidths() per SpW")
        # msmd.exposuretime(scan=...) can segfault CASA 6.7.x; use the time steps.
        scan0 = sorted(msmd.scannumbers())[0]
        times = np.unique(np.asarray(msmd.timesforscans([scan0]), dtype=float))
        steps = np.diff(times)
        steps = steps[steps > 0]
        if steps.size:
            dump_time_s = float(np.median(steps))
        casa_calls.append(f"msmd.timesforscans([{scan0}])")

    return {
        "nu_min_hz": min(freqs_lo),
        "nu_max_hz": max(freqs_hi),
        "max_baseline_m": float(np.max(lengths)),
        "dish_diameter_m": float(diameters[diameters > 0].min()),
        "dump_time_s": dump_time_s,
        "spws": spws,
    }


def run(
    ms_path: str,
    max_time_loss: float = 0.10,
    max_bandwidth_loss: float = 0.05,
    max_timebin_s: float = 30.0,
) -> dict:
    """
    Smearing-limited channel width and time bin for averaging a calibrated MS.

    Args:
        ms_path:            Path to the MS.
        max_time_loss:      Allowed fractional peak loss from time averaging at r10.
        max_bandwidth_loss: Allowed fractional peak loss from channel averaging at r10.
        max_timebin_s:      Upper limit on the suggested time bin, in seconds.
    """
    p = validate_ms_path(ms_path)
    ms_str = str(p)
    casa_calls: list[str] = []
    warnings: list[str] = []

    inputs = _read_inputs(ms_str, casa_calls)
    lim = compute_limits(
        **inputs,
        max_time_loss=max_time_loss,
        max_bandwidth_loss=max_bandwidth_loss,
        max_timebin_s=max_timebin_s,
    )

    dump = inputs["dump_time_s"]
    if dump is None:
        warnings.append("Dump time unavailable (one timestamp in the first scan); no timebin.")
    elif lim["suggested_timebin_n_dumps"] == 0:
        warnings.append(
            f"The time limit ({min(lim['tau_max_s'], max_timebin_s):.1f} s) is shorter "
            f"than one dump ({dump:.3f} s); time averaging is not possible."
        )

    per_spw = [
        {
            **s,
            "suggested_width_channels": fmt_field(
                s["suggested_width_channels"],
                note="largest divisor of nchan within the bandwidth limit",
            ),
        }
        for s in lim["per_spw"]
    ]

    data = {
        "inputs": {
            "nu_min_hz": inputs["nu_min_hz"],
            "nu_max_hz": inputs["nu_max_hz"],
            "max_baseline_m": round(inputs["max_baseline_m"], 2),
            "dish_diameter_m": inputs["dish_diameter_m"],
            "dump_time_s": fmt_field(
                round(dump, 3) if dump else None,
                flag="COMPLETE" if dump else "UNAVAILABLE",
            ),
            "max_time_loss": max_time_loss,
            "max_bandwidth_loss": max_bandwidth_loss,
            "max_timebin_s": max_timebin_s,
        },
        "constants": {
            "airy_r10_lambda_over_d": AIRY_R10_LAMBDA_OVER_D,
            "time_coeff_s2": TIME_COEFF_S2,
            "bandwidth_coeff": BANDWIDTH_COEFF,
        },
        "r10_arcmin": fmt_field(
            round(lim["r10_arcmin"], 3),
            flag="INFERRED",
            note="10% point of an Airy pattern at nu_min for the smallest dish",
        ),
        "theta_syn_arcsec": fmt_field(
            round(lim["theta_syn_arcsec"], 3),
            flag="INFERRED",
            note="lambda(nu_max)/B_max; ignores weighting, so the limits are conservative",
        ),
        "x": fmt_field(round(lim["x"], 2), note="r10 / theta_syn"),
        "tau_max_s": fmt_field(
            round(lim["tau_max_s"], 2), note="time bin that gives max_time_loss at r10"
        ),
        "dnu_max_hz": fmt_field(
            round(lim["dnu_max_hz"], 1),
            note="output channel width that gives max_bandwidth_loss at r10",
        ),
        "suggested_timebin_s": fmt_field(
            lim["suggested_timebin_s"],
            flag="COMPLETE" if dump else "UNAVAILABLE",
            note="min(tau_max_s, max_timebin_s) rounded down to whole dumps",
        ),
        "time_loss_at_suggested": (
            round(lim["time_loss_at_suggested"], 4)
            if lim["time_loss_at_suggested"] is not None
            else None
        ),
        "per_spw": per_spw,
    }

    return response_envelope(
        tool_name=TOOL_NAME,
        ms_path=ms_path,
        data=data,
        warnings=warnings,
        casa_calls=casa_calls,
    )
