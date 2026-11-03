"""ms-inspect — Radio interferometric Measurement Set inspector (MCP server)."""

__version__ = "0.1.1"

# Before anything imports casatools: keep CASA's log out of the cwd.
from ms_inspect.util.logs import configure_casa_log  # noqa: E402

configure_casa_log()
