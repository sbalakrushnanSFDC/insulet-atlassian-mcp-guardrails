# Setup Guide

For engineers setting up, maintaining, or extending the Atlassian MCP Guardrails server.

## Prerequisites

- Python 3.12 or later (`python3 --version`)
- Git
- An Atlassian Cloud account with API token access

## Installation

```bash
# Clone
git clone https://github.com/sbalakrushnanSFDC/insulet-atlassian-mcp-guardrails
cd insulet-atlassian-mcp-guardrails

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# Install the package (editable mode for development)
pip install -e ".[dev]"
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```
JIRA_BASE_URL=https://your-instance.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_TOKEN=your-atlassian-api-token
```

See [ADMIN.md](ADMIN.md) for the full variable reference.

## Running the Server

```bash
# Foreground (for testing)
python -m atlassian_mcp_guardrails.server

# The server uses stdio transport (JSON-RPC over stdin/stdout).
# It is designed to be launched by an MCP client, not run as a daemon.
```

## Running Tests

```bash
pytest tests/ -v
```

All 116 tests run without network access or a database. No Postgres, no Docker required.

## Architecture

```
atlassian_mcp_guardrails/
├── server.py          FastMCP entry point; registers tools via decorator imports
├── config.py          AtlassianConfig dataclass; from_env() is the only constructor
├── auth.py            Basic auth headers; canonical URL resolution
├── guardrails.py      Scope enforcement, injection, and result caps
├── context.py         RequestContext — per-invocation ID, API call counter
├── jira/
│   ├── client.py      HTTP-only Jira client; v3 cursor + v2 offset pagination
│   ├── models.py      JiraIssue dataclass
│   └── field_discovery.py  Custom field mapping via /rest/api/3/field
└── confluence/
    ├── client.py      HTTP-only Confluence client; v2/v1 fallback
    └── models.py      ConfluencePage dataclass
```

### Tool Registration Pattern

Tools are registered via the `@mcp.tool()` decorator at import time. The `server.py` module creates the `FastMCP` instance (`mcp`) and then imports each tool module. Each tool module imports `mcp` from `server` and decorates its functions. No explicit `mcp.add_tool()` calls are needed.

```python
# server.py
mcp = FastMCP(name="atlassian-mcp-guardrails")
from atlassian_mcp_guardrails.tools import jira_tools  # registers tools at import

# tools/jira_tools.py
from atlassian_mcp_guardrails.server import mcp

@mcp.tool()
def jira_search(jql: str, ...) -> dict:
    ...
```

### Adding a New Tool

1. Create or edit a file in `atlassian_mcp_guardrails/tools/`
2. Import `mcp` from `atlassian_mcp_guardrails.server`
3. Decorate your function with `@mcp.tool()`
4. Apply guardrails: call `enforce_result_cap`, `inject_default_*_scope`, `enforce_*_scope`
5. Import the module in `server.py`
6. Add tests in `tests/test_tools.py`

### Canonical URL Resolution

`JiraClient.from_config()` and `ConfluenceClient.from_config()` both call `resolve_canonical_url` unconditionally at construction time. This resolves proxy/vanity domains (e.g. `jira.company.com`) to the real Atlassian Cloud host (`company.atlassian.net`).

If the resolution call fails (network error, timeout), the configured URL is used as-is with a warning logged. The server does not fail to start on resolution failure.

## Releasing a New Version

1. Bump `version` in `pyproject.toml`
2. Commit: `git commit -m "chore: bump version to X.Y.Z"`
3. Tag: `git tag vX.Y.Z`
4. Push: `git push origin main --tags`
