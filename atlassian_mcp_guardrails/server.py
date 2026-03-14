"""FastMCP server for Atlassian MCP Guardrails.

Exposes read-only, rate-limited, scope-guarded tools for Jira and Confluence.
All tools are registered via the ``@mcp.tool()`` decorator at import time.

Tools provided:
- ``jira_search``        — JQL search with default-scope injection and caps
- ``jira_get_issue``     — Single issue fetch by key
- ``jira_discover_fields`` — Custom field mapping discovery
- ``confluence_get_page``  — Single page fetch by ID
- ``confluence_search``    — CQL search with default-space injection and caps
- ``atlassian_health_check`` — Connectivity and config validation

Run with:
    python -m atlassian_mcp_guardrails.server
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(name="atlassian-mcp-guardrails")

# Configure logging before importing tool modules so all loggers pick it up
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Import tool modules to register tools via @mcp.tool() decorators.
# Each module imports ``mcp`` from this module and decorates functions at
# import time — no explicit registration call is needed.
from atlassian_mcp_guardrails.tools import jira_tools  # noqa: F401, E402
from atlassian_mcp_guardrails.tools import confluence_tools  # noqa: F401, E402
from atlassian_mcp_guardrails.tools import health_tools  # noqa: F401, E402


def main() -> None:
    """Entry point for the MCP server (stdio transport)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
