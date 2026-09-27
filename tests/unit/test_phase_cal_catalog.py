"""
Unit tests for the PhaseCalList.txt parser in util/phase_cal_catalog.py.

UVMIN and UVMAX are told apart by column: a row may carry either limit alone.
The real 3C84 (0319+415) block has a UVMIN at L-band and a UVMAX at Q-band.

No CASA dependency.
"""

from __future__ import annotations

from ms_inspect.util.phase_cal_catalog import _get_catalog, _load_catalog

HEADER = "BAND        A B C D    FLUX(Jy)    UVMIN(kL)  UVMAX(kL)"

BLOCK_3C84 = f"""\
0319+415   J2000  B 03h19m48.160102s  41d30'42.103050"  Aug01  3C84
0316+413   B1950  B 03h16m29.567300s  41d19'51.916000"
-----------------------------------------------------
{HEADER}
=====================================================
 90cm    P  S X X X          8           13
 20cm    L  P P X X      23.9            12
  6cm    C  P P P P      23.3
3.7cm    X  P P P P      21.70                       visplot
0.7cm    Q  X S S S      9.00                 1800   visplot
"""


def _bands(text: str) -> dict:
    return _load_catalog(text)["0319+415"].bands


def test_uvmin_only_row():
    b = _bands(BLOCK_3C84)["L"]
    assert (b.uvmin_kl, b.uvmax_kl) == (12.0, None)


def test_uvmax_only_row():
    b = _bands(BLOCK_3C84)["Q"]
    assert (b.uvmin_kl, b.uvmax_kl) == (None, 1800.0)


def test_no_limits_and_trailing_text():
    for code in ("C", "X"):
        b = _bands(BLOCK_3C84)[code]
        assert (b.uvmin_kl, b.uvmax_kl) == (None, None)


def test_both_limits_row():
    text = BLOCK_3C84 + "3.7cm    X  S S X X       0.84          100         400\n"
    b = _bands(text)["X"]
    assert (b.uvmin_kl, b.uvmax_kl) == (100.0, 400.0)


def test_bundled_file_3c84():
    bands = _get_catalog()["0319+415"].bands
    assert (bands["L"].uvmin_kl, bands["L"].uvmax_kl) == (12.0, None)
    assert (bands["Q"].uvmin_kl, bands["Q"].uvmax_kl) == (None, 1800.0)
