"""ms-modify — Radio interferometric Measurement Set modification utilities."""

__version__ = "0.1.0"

# Before anything imports casatools: keep CASA's log out of the cwd.
from ms_inspect.util.logs import configure_casa_log  # noqa: E402

configure_casa_log()
