"""
Unit tests for tools/geometry.py elevation and parallactic angle with no
network: astropy must answer from its bundled IERS tables for recent dates.

No CASA dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from astropy.utils import iers

from ms_inspect.tools.geometry import _compute_el_pa

_VLA = (34.0784, -107.6184, 2124.0)  # lat deg, lon deg, height m


@pytest.mark.filterwarnings("ignore")
@pytest.mark.parametrize("year", [2017, 2026, 2040])
def test_el_pa_without_network(year):
    t_unix = datetime(year, 6, 15, 10, tzinfo=UTC).timestamp()
    with iers.conf.set_temp("auto_download", False):
        el, pa = _compute_el_pa(0.87, 0.72, t_unix, *_VLA)
    assert -90.0 <= el <= 90.0
    assert -180.0 <= pa <= 180.0


def test_astropy_config_is_left_as_it_was():
    before = (iers.conf.auto_download, iers.conf.auto_max_age, iers.conf.iers_degraded_accuracy)
    _compute_el_pa(0.87, 0.72, datetime(2017, 3, 15, tzinfo=UTC).timestamp(), *_VLA)
    after = (iers.conf.auto_download, iers.conf.auto_max_age, iers.conf.iers_degraded_accuracy)
    assert before == after
