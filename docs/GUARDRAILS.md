# Guardrails Reference

This document explains all safety mechanisms built into the Atlassian MCP Guardrails server.

---

## Read-Only Enforcement

This server **never writes to Jira or Confluence**. The HTTP clients only issue:
- `GET` requests (for single-resource fetches and connectivity checks)
- `POST` requests with a JSON body (for JQL/CQL search — Atlassian's search APIs require POST)

No `PUT`, `PATCH`, or `DELETE` methods are implemented. There is no sync, no write-back, no create/update/delete of any Atlassian resource.

---

## Four-Tier Scope Model

```
Tier 1 — Priority scope (scope="priority", default)
         JIRA_PRIORITY_PROJECTS + JIRA_PRIORITY_LABELS / JIRA_PRIORITY_FIX_VERSIONS
         ↓ project + (labels OR fix versions) prepended if query has no project clause

Tier 2 — Expanded scope (scope="expanded")
         JIRA_PRIORITY_PROJECTS + JIRA_EXPANDED_LABELS / JIRA_EXPANDED_FIX_VERSIONS
         ↓ same projects, broader label/fix-version set

Tier 3 — Default scope (scope="default")
         JIRA_DEFAULT_PROJECTS / CONFLUENCE_DEFAULT_SPACES
         ↓ project/space prepended if query has no filter

Tier 4 — No injection (scope="all")
         raw JQL/CQL passed through unchanged

Allowlist — hard enforcement (always applied regardless of scope tier)
         JIRA_ALLOWED_PROJECTS / CONFLUENCE_ALLOWED_SPACES
         ↓ query rejected if out of scope
```

### Tier 1 — Priority Scope (Phase 1)

Configure `JIRA_PRIORITY_PROJECTS`, `JIRA_PRIORITY_LABELS`, and `JIRA_PRIORITY_FIX_VERSIONS` in `.env`:

```
JIRA_PRIORITY_PROJECTS=NGCRMI,NGONDL,NGASIM,NGPSTE,NGOMCT,NGMC
JIRA_PRIORITY_LABELS=2026Q2,NGPI4,NGPI3,NextGen,PRJ0717,PodderCentral,Team3
JIRA_PRIORITY_FIX_VERSIONS=Project Infinity SOW MVP,Project Infinity Persona Release 2
```

When set and a JQL query has no `project` clause, the server prepends:
```
project in ("NGCRMI","NGONDL",...) AND (labels in ("2026Q2","NGPI4",...) OR fixVersion in ("Project Infinity SOW MVP",...)) AND {your_jql}
```

This is the **default scope** for `jira_search` — it narrows results to NextGen program work before the caller needs to specify anything.

### Tier 2 — Expanded Scope (Phase 2)

Configure `JIRA_EXPANDED_LABELS` and `JIRA_EXPANDED_FIX_VERSIONS`:

```
JIRA_EXPANDED_LABELS=2026Q2,NGPI4,NGPI3,NGPI2,NextGen,PRJ0717,PodderCentral,Team3,OrgSync,PI2_OS_Sprint3
JIRA_EXPANDED_FIX_VERSIONS=Project Infinity SOW MVP,Project Infinity Persona Release 1,Project Infinity Persona Release 2
```

Uses the same `JIRA_PRIORITY_PROJECTS` but with the broader Phase 2 label and fix-version sets. Call with `scope="expanded"`.

### Tier 3 — Default Scope

Configure `JIRA_DEFAULT_PROJECTS` and/or `CONFLUENCE_DEFAULT_SPACES`:

```
JIRA_DEFAULT_PROJECTS=NGCRMI,NGONDL,NGASIM,NGPSTE,NGOMCT,NGMC
CONFLUENCE_DEFAULT_SPACES=AJST,AS,CCPROC,DGBG,ESG,MOON,Mule,NASFL,ensre
```

When set and a query has no project/space clause, the server prepends:
- Jira: `project in ("NGCRMI",...) AND {your_jql}`
- Confluence: `space in ("AJST",...) AND {your_cql}`

Call with `scope="default"` to use this tier explicitly.

### Tier 4 — No Injection

Pass `scope="all"` to send the raw JQL/CQL without any prepended filters. The allowlist still applies.

`expand_beyond_defaults=true` is a deprecated alias for `scope="all"` and is kept for backward compatibility.

### Allowlist (Hard Enforcement)

Configure `JIRA_ALLOWED_PROJECTS` and/or `CONFLUENCE_ALLOWED_SPACES`:

```
JIRA_ALLOWED_PROJECTS=PROJ1,PROJ2
CONFLUENCE_ALLOWED_SPACES=SPACE1,DOCS
```

When non-empty, **regardless of scope tier**:
- Any JQL query that does not reference at least one allowed project raises `ScopeViolationError`
- Any CQL query that does not reference at least one allowed space raises `ScopeViolationError`
- The error message tells the caller which projects/spaces are allowed

When empty (default): advisory mode — no enforcement, any project/space is permitted.

### Caller Override

If the caller includes an explicit `project` or `space` clause in their JQL/CQL, no scope injection occurs regardless of the `scope` parameter. The allowlist still applies.

```
# Injection skipped — explicit project clause present
jira_search(jql="project = MYPROJ AND issuetype = Story")
```

---

## Scope Tier Summary

| `scope` | Jira filter applied | Confluence filter applied |
|---|---|---|
| `"priority"` *(default)* | `project in (PRIORITY_PROJECTS) AND (labels in (PRIORITY_LABELS) OR fixVersion in (PRIORITY_FIX_VERSIONS))` | `space in (CONFLUENCE_PRIORITY_SPACES)` — falls back to default if not set |
| `"expanded"` | `project in (PRIORITY_PROJECTS) AND (labels in (EXPANDED_LABELS) OR fixVersion in (EXPANDED_FIX_VERSIONS))` | same as priority |
| `"default"` | `project in (JIRA_DEFAULT_PROJECTS)` | `space in (CONFLUENCE_DEFAULT_SPACES)` |
| `"all"` | no injection | no injection |

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
