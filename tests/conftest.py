"""
Keep pytest out of the repo root.

casatools writes ``casa-*.log`` into the cwd of any process that imports it,
and tests write logs/ under the workdir. Run the whole session from a scratch
directory so neither lands in the checkout, and silence CASA before any test
module imports it.
"""

from __future__ import annotations

import os

import pytest

from ms_inspect.util.logs import WORKDIR_ENV, configure_casa_log

configure_casa_log()


@pytest.fixture(scope="session", autouse=True)
def _scratch_cwd(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("pytest_cwd")
    previous = os.getcwd()
    os.chdir(scratch)
    os.environ[WORKDIR_ENV] = str(scratch)
    yield scratch
    os.chdir(previous)
    os.environ.pop(WORKDIR_ENV, None)
