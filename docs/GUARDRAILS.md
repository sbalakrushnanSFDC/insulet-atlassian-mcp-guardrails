# Guardrails Reference

This document explains all safety mechanisms built into the Atlassian MCP Guardrails server.

---

## Read-Only Enforcement

This server **never writes to Jira or Confluence**. The HTTP clients only issue:
- `GET` requests (for single-resource fetches and connectivity checks)
- `POST` requests with a JSON body (for JQL/CQL search — Atlassian's search APIs require POST)

No `PUT`, `PATCH`, or `DELETE` methods are implemented. There is no sync, no write-back, no create/update/delete of any Atlassian resource.

---

## Three-Layer Scope Model

```
Layer 1 — Allowlist (hard block)
         JIRA_ALLOWED_PROJECTS, CONFLUENCE_ALLOWED_SPACES
         ↓ query rejected if out of scope

Layer 2 — Default scope (auto-injection)
         JIRA_DEFAULT_PROJECTS, CONFLUENCE_DEFAULT_SPACES
         ↓ project/space prepended if query has no filter

Layer 3 — Caller override
         explicit project/space in JQL/CQL, or expand_beyond_defaults=true
         ↓ injection skipped; allowlist still applies
```

### Layer 1 — Allowlist (Hard Enforcement)

Configure `JIRA_ALLOWED_PROJECTS` and/or `CONFLUENCE_ALLOWED_SPACES` in `.env`:

```
JIRA_ALLOWED_PROJECTS=PROJ1,PROJ2
CONFLUENCE_ALLOWED_SPACES=SPACE1,DOCS
```

When non-empty:
- Any JQL query that does not reference at least one allowed project raises `ScopeViolationError`
- Any CQL query that does not reference at least one allowed space raises `ScopeViolationError`
- The error message tells the caller which projects/spaces are allowed

When empty (default): advisory mode — no enforcement, any project/space is permitted.

### Layer 2 — Default Scope (Auto-Injection)

Configure `JIRA_DEFAULT_PROJECTS` and/or `CONFLUENCE_DEFAULT_SPACES`:

```
JIRA_DEFAULT_PROJECTS=PROJ1,PROJ2
CONFLUENCE_DEFAULT_SPACES=SPACE1,DOCS
```

When set and a query has no project/space clause, the server automatically prepends:
- Jira: `project in ("PROJ1","PROJ2") AND {your_jql}`
- Confluence: `space in ("SPACE1","DOCS") AND {your_cql}`

This is logged at DEBUG level: `Injecting default project scope: project in ("PROJ1","PROJ2")`

The executed query is always returned in the response (`jql_executed` / `cql_executed`) so callers can see what was sent to the API.

### Layer 3 — Caller Override

Two ways to skip injection:

1. **Include a project/space clause in your query** — injection is skipped automatically when the clause is detected:
   ```
   jira_search(jql="project = MYPROJ AND issuetype = Story")
   ```

2. **Pass `expand_beyond_defaults=true`** — injection is skipped; allowlist still applies:
   ```
   jira_search(jql="issuetype = Story", expand_beyond_defaults=true)
   ```

Note: if `JIRA_ALLOWED_PROJECTS` is set and you use `expand_beyond_defaults=true` without a project clause, the query will be rejected by the allowlist.

---

## Rate Limiting

### Retry Behavior

The server automatically retries failed requests:

| Condition | Retries | Backoff |
|---|---|---|
| HTTP 429 (rate limited) | Up to 3 | Uses `Retry-After` header; falls back to [1, 2, 4] seconds |
| HTTP 5xx (server error) | Up to 2 | [1, 2, 4] seconds |
| Network error / timeout | Up to 2 | [1, 2, 4] seconds |

### Inter-Request Delay

`REQUEST_DELAY_MS` (default: 100ms) adds a minimum delay between consecutive API calls within a single tool invocation. This prevents bursting against the Atlassian API rate limit.

### Per-Invocation API Call Limit

`MAX_API_CALLS_PER_REQUEST` (default: 20) limits the total number of Atlassian API calls a single tool invocation can make. If exceeded, `ApiLimitExceededError` is raised and returned as `{"error": "...", "error_type": "ApiLimitExceededError"}`.

This prevents a single `jira_search` with a large `max_results` from making dozens of paginated API calls.

---

## Result Caps

| Setting | Default | Description |
|---|---|---|
| `MAX_RESULTS_PER_REQUEST` | 50 | Default result count when caller doesn't specify |
| `MAX_RESULTS_HARD_CAP` | 200 | Absolute maximum; caller cannot exceed this |

Even if a caller passes `max_results=9999`, the server caps it at `MAX_RESULTS_HARD_CAP`. A warning is logged when capping occurs.

---

## URL Validation and Canonical Resolution

At startup, `AtlassianConfig.from_env()` validates:
- `JIRA_BASE_URL` must have an `http://` or `https://` scheme
- `CONFLUENCE_BASE_URL` (if set) must have an `http://` or `https://` scheme

At client construction time, `resolve_canonical_url` calls `GET /rest/api/3/serverInfo` to detect proxy/vanity domain mismatches. If the response contains a `*.atlassian.net` URL that differs from the configured URL, the canonical URL is used for all subsequent API calls.

This prevents the most common cause of `403 Forbidden` errors: using a corporate proxy URL (e.g. `confluence.company.com`) when the actual Atlassian Cloud host is `company.atlassian.net`.

If resolution fails (network error, timeout), the configured URL is used as-is with a warning logged. The server does not fail to start.

---

## Output Truncation

To prevent oversized responses:

| Field | Truncation |
|---|---|
| `description_plain` (Jira) | 500 characters |
| `acceptance_criteria` (Jira) | 1000 characters |
| `body_plain` (Confluence) | 2000 characters |
| Child pages per `confluence_get_page` | 50 pages |

---

## Error Handling

All tools catch exceptions at the top level and return a structured error dict:

```json
{
  "error": "human-readable error message",
  "error_type": "ScopeViolationError"
}
```

This means the MCP client always receives a valid JSON response, even on failure. The `error_type` field identifies the class of error for programmatic handling.
