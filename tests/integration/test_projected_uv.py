"""
Integration test: projected baselines from geometry against the MS UVW column.

util.conversions.projected_uv_m computes sqrt(u^2 + v^2) from ITRF antenna
positions, the J2000 phase centre and the TIME column. The correlator's UVW
column is the reference. Requires casatools. Skipped when RADIO_MCP_TEST_MS is
not set.

    RADIO_MCP_TEST_MS=/path/to/your.ms pytest tests/integration/test_projected_uv.py -v
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ms_inspect.util.conversions import projected_uv_m

_TEST_MS = os.environ.get("RADIO_MCP_TEST_MS")

# J2000 coordinates without precession to date give up to about 1% in |uv|
# at low declination.
_TOLERANCE = 0.02


@pytest.mark.skipif(_TEST_MS is None, reason="RADIO_MCP_TEST_MS not set")
def test_projected_uv_matches_uvw_column():
    casatools = pytest.importorskip("casatools")
    tb = casatools.table()
    tb.open(_TEST_MS + "/ANTENNA")
    xyz = tb.getcol("POSITION").T
    tb.close()
    tb.open(_TEST_MS + "/FIELD")
    phase_dir = tb.getcol("PHASE_DIR")[:, 0, :]
    tb.close()

    tb.open(_TEST_MS)
    n_checked = 0
    worst = 0.0
    for fid in range(phase_dir.shape[1]):
        sub = tb.query(
            f"FIELD_ID=={fid} && ANTENNA1!=ANTENNA2", columns="TIME,ANTENNA1,ANTENNA2,UVW"
        )
        t, a1, a2, uvw = (sub.getcol(c) for c in ("TIME", "ANTENNA1", "ANTENNA2", "UVW"))
        sub.close()
        if t.size == 0:
            continue
        # One row per baseline at the first integration of the field.
        at_first = t == t.min()
        b = xyz[a2[at_first]] - xyz[a1[at_first]]
        ref = np.hypot(uvw[0, at_first], uvw[1, at_first])
        ra, dec = phase_dir[0, fid], phase_dir[1, fid]
        got = projected_uv_m(b, ra, dec, [t.min()])[0]
        ok = ref > 1.0
        rel = np.abs(got[ok] - ref[ok]) / ref[ok]
        worst = max(worst, float(rel.max()))
        n_checked += int(ok.sum())
    tb.close()

    assert n_checked > 0, "no cross-correlation rows checked"
    assert worst < _TOLERANCE, f"worst relative |uv| error {worst:.3e} over {n_checked} baselines"
