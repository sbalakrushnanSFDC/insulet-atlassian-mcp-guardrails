# Admin and Config Owner Guide

For administrators setting up this server for a team, managing allowlists, and tuning rate limits.

---

## Full Environment Variable Reference

### Required

| Variable | Description |
|---|---|
| `JIRA_BASE_URL` | Atlassian Cloud base URL (e.g. `https://company.atlassian.net`) |
| `JIRA_EMAIL` | Email address for the Atlassian account |
| `JIRA_TOKEN` | Atlassian API token (not password) |

### Optional — URLs

| Variable | Default | Description |
|---|---|---|
| `CONFLUENCE_BASE_URL` | `JIRA_BASE_URL` | Confluence base URL; defaults to Jira URL for Cloud |

### Optional — Default Scope (Tier 3)

| Variable | Default | Description |
|---|---|---|
| `JIRA_DEFAULT_PROJECTS` | `""` | Comma-separated project keys; injected when `scope="default"` and query has no project clause |
| `CONFLUENCE_DEFAULT_SPACES` | `""` | Comma-separated space keys; injected when `scope="default"` and query has no space clause |

### Optional — Priority Scope (Tier 1 — Phase 1)

| Variable | Default | Description |
|---|---|---|
| `JIRA_PRIORITY_PROJECTS` | `""` | Comma-separated project keys for Phase 1 priority scope |
| `JIRA_PRIORITY_LABELS` | `""` | Comma-separated label values; combined with fix versions in Phase 1 JQL |
| `JIRA_PRIORITY_FIX_VERSIONS` | `""` | Comma-separated fix version names for Phase 1 JQL |

### Optional — Expanded Scope (Tier 2 — Phase 2)

| Variable | Default | Description |
|---|---|---|
| `JIRA_EXPANDED_LABELS` | `""` | Broader label set for Phase 2; uses same projects as `JIRA_PRIORITY_PROJECTS` |
| `JIRA_EXPANDED_FIX_VERSIONS` | `""` | Broader fix-version set for Phase 2 |

### Optional — Confluence Priority Scope

| Variable | Default | Description |
|---|---|---|
| `CONFLUENCE_PRIORITY_SPACES` | `""` | Comma-separated space keys; injected when `scope="priority"` (falls back to default if empty) |

### Optional — Allowlist (Hard Enforcement)

| Variable | Default | Description |
|---|---|---|
| `JIRA_ALLOWED_PROJECTS` | `""` | Comma-separated allowlist; queries outside this scope are rejected |
| `CONFLUENCE_ALLOWED_SPACES` | `""` | Comma-separated allowlist; queries outside this scope are rejected |

### Optional — Rate Limiting and Result Caps

| Variable | Default | Description |
|---|---|---|
| `MAX_RESULTS_PER_REQUEST` | `50` | Default result count per search call |
| `MAX_RESULTS_HARD_CAP` | `200` | Absolute maximum results; caller cannot exceed this |
| `MAX_API_CALLS_PER_REQUEST` | `20` | Max Atlassian API calls per single tool invocation |
| `REQUEST_DELAY_MS` | `100` | Minimum ms between API calls within one tool invocation |
| `HTTP_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `LOG_LEVEL` | `INFO` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Insulet-Specific Configuration

The `.env.example` is pre-populated with Insulet defaults. Key values:

```
JIRA_BASE_URL=https://insulet.atlassian.net
CONFLUENCE_BASE_URL=https://insulet.atlassian.net/wiki

# All 6 NextGen projects
JIRA_DEFAULT_PROJECTS=NGCRMI,NGONDL,NGASIM,NGPSTE,NGOMCT,NGMC

# Phase 1 priority — NextGen program work
JIRA_PRIORITY_PROJECTS=NGCRMI,NGONDL,NGASIM,NGPSTE,NGOMCT,NGMC
JIRA_PRIORITY_LABELS=2026Q2,NGPI4,NGPI3,NextGen,PRJ0717,PodderCentral,Team3
JIRA_PRIORITY_FIX_VERSIONS=Project Infinity SOW MVP,Project Infinity Persona Release 2

# Phase 2 expanded
JIRA_EXPANDED_LABELS=2026Q2,NGPI4,NGPI3,NGPI2,NextGen,PRJ0717,PodderCentral,Team3,OrgSync,PI2_OS_Sprint3
JIRA_EXPANDED_FIX_VERSIONS=Project Infinity SOW MVP,Project Infinity Persona Release 1,Project Infinity Persona Release 2
```

Confluence spaces are resolved from `https://confluence.prod.insulet.com/wiki/spaces` (Your spaces):

```
CONFLUENCE_DEFAULT_SPACES=AJST,AS,CCPROC,DGBG,ESG,MOON,Mule,NASFL,ensre
```

| Space key | Display name |
|---|---|
| AJST | iOS Platform ART |
| AS | Atlassian Support |
| CCPROC | CC_International_Change Enablement |
| DGBG | DGB Gibraltar |
| ESG | Electronic Systems |
| MOON | Moonshot |
| Mule | MuleSoft Integrations |
| NASFL | NextGen CRM (U.S.) |
| ensre | Enterprise-SRE |

---

## Scope Tier Behaviour

The `scope` parameter on `jira_search` and `confluence_search` controls which filter is prepended when the query has no explicit project/space clause:

| `scope` | Jira filter | Confluence filter |
|---|---|---|
| `"priority"` *(default)* | `project in (PRIORITY_PROJECTS) AND (labels OR fixVersion)` | `space in (PRIORITY_SPACES)` → falls back to default |
| `"expanded"` | `project in (PRIORITY_PROJECTS) AND (expanded labels OR fixVersion)` | same as priority |
| `"default"` | `project in (DEFAULT_PROJECTS)` | `space in (DEFAULT_SPACES)` |
| `"all"` | no injection | no injection |

The allowlist (`JIRA_ALLOWED_PROJECTS` / `CONFLUENCE_ALLOWED_SPACES`) is always enforced regardless of scope tier.

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

JIRA_PRIORITY_PROJECTS=PROJ1,PROJ2
JIRA_PRIORITY_LABELS=label1,label2
JIRA_PRIORITY_FIX_VERSIONS=v1.0,v2.0

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
| `DEBUG` | Scope injection details (tier applied, filter prepended), field discovery mappings, canonical URL resolution |
| `INFO` | Canonical URL changes, field discovery summary |
| `WARNING` | Rate limit retries, result cap enforcement, server errors, resolution failures |
| `ERROR` | Tool invocation failures, API errors |

To see scope injection in action, set `LOG_LEVEL=DEBUG` and run a search without a project clause. You will see:

```
DEBUG atlassian_mcp_guardrails.guardrails: Injecting priority (Phase 1) scope: project in ("NGCRMI",...) AND (labels in (...) OR fixVersion in (...))
```

---

## Identifying Auto-Scoped Queries

Every tool response includes `jql_executed` / `cql_executed` and `scope_applied` showing the exact query sent to the API and which tier was used:

```json
{
  "scope_applied": "priority",
  "jql_executed": "project in (\"NGCRMI\",\"NGASIM\") AND (labels in (\"NextGen\") OR fixVersion in (\"...\")) AND issuetype = Story",
  ...
}
```
