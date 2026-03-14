# Admin and Config Owner Guide

For administrators setting up this server for a team, managing allowlists, and tuning rate limits.

---

## Full Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `JIRA_BASE_URL` | Yes | — | Atlassian Cloud base URL (e.g. `https://company.atlassian.net`) |
| `JIRA_EMAIL` | Yes | — | Email address for the Atlassian account |
| `JIRA_TOKEN` | Yes | — | Atlassian API token (not password) |
| `CONFLUENCE_BASE_URL` | No | `JIRA_BASE_URL` | Confluence base URL; defaults to Jira URL for Cloud |
| `JIRA_DEFAULT_PROJECTS` | No | `""` | Comma-separated project keys; auto-injected when query has no project clause |
| `CONFLUENCE_DEFAULT_SPACES` | No | `""` | Comma-separated space keys; auto-injected when query has no space clause |
| `JIRA_ALLOWED_PROJECTS` | No | `""` | Comma-separated allowlist; queries outside this scope are rejected |
| `CONFLUENCE_ALLOWED_SPACES` | No | `""` | Comma-separated allowlist; queries outside this scope are rejected |
| `MAX_RESULTS_PER_REQUEST` | No | `50` | Default result count per search call |
| `MAX_RESULTS_HARD_CAP` | No | `200` | Absolute maximum results; caller cannot exceed this |
| `MAX_API_CALLS_PER_REQUEST` | No | `20` | Max Atlassian API calls per single tool invocation |
| `REQUEST_DELAY_MS` | No | `100` | Minimum ms between API calls within one tool invocation |
| `HTTP_TIMEOUT` | No | `30` | HTTP request timeout in seconds |
| `LOG_LEVEL` | No | `INFO` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Setting Up Allowlists for a Team

The recommended pattern is to set both `DEFAULT` and `ALLOWED` to the same values:

```
# .env for a program team
JIRA_DEFAULT_PROJECTS=MYPROJ,MYPROJ2
CONFLUENCE_DEFAULT_SPACES=MYSPACE,DOCS
JIRA_ALLOWED_PROJECTS=MYPROJ,MYPROJ2
CONFLUENCE_ALLOWED_SPACES=MYSPACE,DOCS
```

This means:
- Queries without a project/space clause are automatically scoped to the team's projects/spaces
- Queries that explicitly reference a different project/space are rejected

If you want to allow queries to any project/space (not recommended for shared team use), leave the `ALLOWED` vars empty:

```
JIRA_DEFAULT_PROJECTS=MYPROJ
CONFLUENCE_DEFAULT_SPACES=MYSPACE
JIRA_ALLOWED_PROJECTS=
CONFLUENCE_ALLOWED_SPACES=
```

---

## Sharing a Pre-Configured Template with Your Team

Create a `.env.team` file with the team-specific settings (no credentials):

```
# .env.team — commit this to your team's internal docs or wiki
# Copy to .env and add your personal credentials

JIRA_BASE_URL=https://company.atlassian.net
# JIRA_EMAIL=your-email@company.com    <- fill in your own
# JIRA_TOKEN=your-api-token            <- fill in your own

JIRA_DEFAULT_PROJECTS=PROJ1,PROJ2
CONFLUENCE_DEFAULT_SPACES=SPACE1,DOCS
JIRA_ALLOWED_PROJECTS=PROJ1,PROJ2
CONFLUENCE_ALLOWED_SPACES=SPACE1,DOCS

MAX_RESULTS_PER_REQUEST=50
MAX_RESULTS_HARD_CAP=200
LOG_LEVEL=INFO
```

**Never commit a `.env` file with real credentials.** The `.gitignore` already excludes `.env`.

---

## Tuning Rate Limits

Atlassian Cloud rate limits vary by plan:

| Plan | Approximate limit |
|---|---|
| Free | ~50 requests/minute |
| Standard | ~200 requests/minute |
| Premium | ~500 requests/minute |

Recommended settings for each plan:

```
# Free plan — conservative
MAX_API_CALLS_PER_REQUEST=10
REQUEST_DELAY_MS=200

# Standard plan — default settings are appropriate
MAX_API_CALLS_PER_REQUEST=20
REQUEST_DELAY_MS=100

# Premium plan — can be more aggressive
MAX_API_CALLS_PER_REQUEST=40
REQUEST_DELAY_MS=50
```

The server already handles `HTTP 429` automatically (retries with `Retry-After` header), so these settings are a first line of defense, not a hard guarantee.

---

## Verifying Canonical URL Resolution

Run `atlassian_health_check` and check the response:

```json
{
  "jira": {
    "canonical_url": "https://company.atlassian.net",
    "configured_url": "https://jira.company.com",
    "url_resolved": true
  }
}
```

If `url_resolved: true`, the server is resolving your proxy URL to the canonical URL on every startup. To avoid this overhead, update `JIRA_BASE_URL` in `.env` to the `canonical_url` value:

```
JIRA_BASE_URL=https://company.atlassian.net
```

---

## Rotating API Tokens

1. Create a new API token at [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Update `JIRA_TOKEN` in `.env`
3. Restart the server process (the server reads `.env` at startup)
4. Revoke the old token in the Atlassian portal

---

## Understanding Log Output

| Level | When it appears |
|---|---|
| `DEBUG` | Scope injection details, field discovery mappings, canonical URL resolution |
| `INFO` | Canonical URL changes, field discovery summary |
| `WARNING` | Rate limit retries, result cap enforcement, server errors, resolution failures |
| `ERROR` | Tool invocation failures, API errors |

To see scope injection in action, set `LOG_LEVEL=DEBUG` and run a search without a project clause. You will see:

```
DEBUG atlassian_mcp_guardrails.guardrails: Injecting default project scope: project in ("PROJ1","PROJ2")
```

---

## Identifying Auto-Scoped Queries

Every tool response includes `jql_executed` or `cql_executed` showing the exact query sent to the API:

```json
{
  "jql_executed": "project in (\"PROJ1\",\"PROJ2\") AND issuetype = Story",
  ...
}
```

If the executed query starts with `project in (...)` or `space in (...)` and the caller did not include that clause, the default scope was injected.
