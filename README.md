# Atlassian MCP Guardrails

A **read-only, rate-limited, scope-guarded MCP server** for Jira and Confluence.

Designed for safe team distribution — no database, no write-back to Atlassian, no project-specific defaults baked in. Configure once with your Atlassian credentials and default project/space scopes, then use from any MCP client (Cursor AI, Claude, custom agents).

## Quickstart (5 steps)

```bash
# 1. Clone the repo
git clone https://github.com/sbalakrushnanSFDC/insulet-atlassian-mcp-guardrails
cd insulet-atlassian-mcp-guardrails

# 2. Create a virtual environment and install
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

# 3. Configure credentials
cp .env.example .env
# Edit .env — fill in JIRA_BASE_URL, JIRA_EMAIL, JIRA_TOKEN

# 4. Verify connectivity
atlassian-mcp-guardrails &
# Or: python -m atlassian_mcp_guardrails
# Then call atlassian_health_check from your MCP client

# 5. Add to Cursor AI (see docs/CURSOR_SETUP.md)
```

## Tools

| Tool | Description |
|---|---|
| `jira_search` | JQL search with default-scope injection and result caps |
| `jira_get_issue` | Fetch a single issue by key (e.g. `PROJ-123`) |
| `jira_discover_fields` | Map custom field IDs for this Jira instance |
| `confluence_get_page` | Fetch a page by ID; optional children (capped at 50) |
| `confluence_search` | CQL search with default-space injection and result caps |
| `atlassian_health_check` | Verify connectivity, credentials, and canonical URLs |

## Guardrails

- **Read-only**: only GET and POST-for-search calls to Atlassian APIs — no create, update, or delete
- **Result caps**: default 50 results per call; hard cap of 200 (configurable)
- **API call limit**: max 20 Atlassian API calls per tool invocation (configurable)
- **Scope injection**: queries without a project/space filter are automatically scoped to your configured defaults
- **Allowlist enforcement**: optionally restrict queries to specific projects/spaces
- **Canonical URL resolution**: proxy/vanity domains resolved to `*.atlassian.net` at startup

See [docs/GUARDRAILS.md](docs/GUARDRAILS.md) for the full three-layer scope model.

## Configuration

Copy `.env.example` to `.env` and fill in your values. Minimum required:

```
JIRA_BASE_URL=https://your-instance.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_TOKEN=your-atlassian-api-token
```

Recommended for team use:

```
JIRA_DEFAULT_PROJECTS=PROJ1,PROJ2
CONFLUENCE_DEFAULT_SPACES=SPACE1,DOCS
JIRA_ALLOWED_PROJECTS=PROJ1,PROJ2
CONFLUENCE_ALLOWED_SPACES=SPACE1,DOCS
```

See [docs/ADMIN.md](docs/ADMIN.md) for the full environment variable reference.

## Documentation

| Document | Audience |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Engineers setting up or maintaining the server |
| [docs/TOOLS.md](docs/TOOLS.md) | Integration teams using the tools |
| [docs/GUARDRAILS.md](docs/GUARDRAILS.md) | Anyone needing to understand scope and rate limits |
| [docs/CURSOR_SETUP.md](docs/CURSOR_SETUP.md) | End users configuring Cursor AI |
| [docs/ADMIN.md](docs/ADMIN.md) | Config owners and support teams |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Diagnosing connectivity and config issues |

## Requirements

- Python 3.12+
- Atlassian Cloud account with API token ([create one here](https://id.atlassian.com/manage-profile/security/api-tokens))
- No database required

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All 116 tests run without network access or a database.
