# Tool Reference

All 6 tools are read-only. No tool creates, updates, or deletes data in Jira or Confluence.

---

## `jira_search`

Search Jira issues using JQL.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `jql` | string | required | JQL query string |
| `max_results` | integer | 50 | Results to return; capped at `MAX_RESULTS_HARD_CAP` |
| `expand_beyond_defaults` | boolean | false | Skip default project scope injection |

**Scope behavior:**
- If `JIRA_DEFAULT_PROJECTS` is set and the JQL has no `project` clause, the defaults are prepended automatically.
- If `JIRA_ALLOWED_PROJECTS` is set, the query must reference an allowed project or it is rejected.
- Pass `expand_beyond_defaults=true` to skip injection (allowlist still applies).

**Example calls:**

```
# Uses default project scope if configured
jira_search(jql="issuetype = Story AND status = 'In Progress'")

# Explicit project overrides default injection
jira_search(jql="project = MYPROJ AND issuetype = Bug AND priority = High")

# Search across all projects (requires empty allowlist)
jira_search(jql="issuetype = Story", expand_beyond_defaults=true)

# Filter by label
jira_search(jql="labels = 'my-label' AND status != Done")

# Filter by fix version
jira_search(jql="fixVersion = 'v2.0' AND issuetype in (Story, Feature)")
```

**Response shape:**

```json
{
  "issues": [
    {
      "key": "PROJ-123",
      "summary": "...",
      "status": "In Progress",
      "issue_type": "Story",
      "project_key": "PROJ",
      "assignee": "Jane Doe",
      "priority": "Medium",
      "labels": ["label1"],
      "fix_versions": ["v2.0"],
      "tshirt_size": "M",
      "description_plain": "... (truncated at 500 chars)",
      "url": "https://your-instance.atlassian.net/browse/PROJ-123",
      "created": "2026-01-01T00:00:00.000Z",
      "updated": "2026-01-02T00:00:00.000Z"
    }
  ],
  "count": 1,
  "jql_executed": "project in (\"PROJ\") AND issuetype = Story AND status = 'In Progress'",
  "meta": { "request_id": "...", "elapsed_ms": 342, "api_calls_made": 2 }
}
```

---

## `jira_get_issue`

Fetch a single Jira issue by key.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `issue_key` | string | required | Issue key (e.g. `PROJ-123`) |
| `include_raw` | boolean | false | Include raw API response |

**Example calls:**

```
jira_get_issue(issue_key="PROJ-123")
jira_get_issue(issue_key="PROJ-456", include_raw=true)
```

**Response shape:** Same fields as a single item in `jira_search` issues list, plus `meta`.

---

## `jira_discover_fields`

Discover custom field mappings for this Jira instance.

Calls `GET /rest/api/3/field` and matches known logical names to `customfield_XXXXX` IDs. Results are returned directly — no database write occurs.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `force_refresh` | boolean | false | Ignored (no cache); included for API compatibility |

**Example call:**

```
jira_discover_fields()
```

**Response shape:**

```json
{
  "field_map": {
    "tshirt_size": "customfield_10261",
    "start_date": "customfield_10015",
    "end_date": "customfield_10203",
    "acceptance_criteria": "customfield_10308",
    "epic_link": "customfield_10014",
    "sprint": "customfield_10020",
    "story_points": ""
  },
  "total_fields_on_instance": 87,
  "custom_fields_on_instance": 43,
  "meta": { ... }
}
```

Empty string means the field was not found on this instance.

---

## `confluence_get_page`

Fetch a single Confluence page by ID.

Tries the v2 API first (Atlassian Cloud), falls back to v1.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page_id` | string | required | Numeric Confluence page ID |
| `include_children` | boolean | false | Also fetch direct child pages (capped at 50) |
| `include_body` | boolean | true | Include truncated body text (2000 chars) |

**Example calls:**

```
confluence_get_page(page_id="12345678")
confluence_get_page(page_id="12345678", include_children=true)
confluence_get_page(page_id="12345678", include_body=false)
```

**Response shape:**

```json
{
  "page_id": "12345678",
  "title": "Architecture Overview",
  "space_key": "MYSPACE",
  "status": "current",
  "version": 5,
  "last_modified": "2026-01-01T00:00:00.000Z",
  "author": "Jane Doe",
  "labels": ["architecture"],
  "parent_id": "11111111",
  "url": "/wiki/spaces/MYSPACE/pages/12345678",
  "body_plain": "... (truncated at 2000 chars)",
  "meta": { ... }
}
```

---

## `confluence_search`

Search Confluence pages using CQL.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `cql` | string | required | CQL query string |
| `limit` | integer | 25 | Results to return; capped at `MAX_RESULTS_HARD_CAP` |
| `include_body` | boolean | false | Include truncated body text in results |
| `expand_beyond_defaults` | boolean | false | Skip default space scope injection |

**Scope behavior:**
- If `CONFLUENCE_DEFAULT_SPACES` is set and the CQL has no `space` clause, the defaults are prepended automatically.
- If `CONFLUENCE_ALLOWED_SPACES` is set, the query must reference an allowed space.

**Example calls:**

```
# Uses default space scope if configured
confluence_search(cql="text ~ 'authentication' AND type = page")

# Explicit space overrides injection
confluence_search(cql="space = MYSPACE AND text ~ 'onboarding'")

# Search with body content included
confluence_search(cql="label = 'release-notes'", include_body=true)

# Recent pages
confluence_search(cql="type = page ORDER BY lastModified DESC", limit=10)
```

**Response shape:**

```json
{
  "pages": [
    {
      "page_id": "12345678",
      "title": "Authentication Guide",
      "space_key": "MYSPACE",
      "status": "current",
      "version": 3,
      "last_modified": "2026-01-01T00:00:00.000Z",
      "author": "Jane Doe",
      "labels": ["auth"],
      "url": "/wiki/spaces/MYSPACE/pages/12345678"
    }
  ],
  "count": 1,
  "cql_executed": "space in (\"MYSPACE\") AND text ~ 'authentication' AND type = page",
  "meta": { ... }
}
```

---

## `atlassian_health_check`

Verify connectivity, credentials, and canonical URL resolution.

**Parameters:** None

**Example call:**

```
atlassian_health_check()
```

**Response shape:**

```json
{
  "ok": true,
  "config": {
    "ok": true,
    "jira_base_url": "https://company.atlassian.net",
    "confluence_base_url": "https://company.atlassian.net",
    "jira_default_projects": ["PROJ1", "PROJ2"],
    "confluence_default_spaces": ["SPACE1"],
    "jira_allowed_projects": ["PROJ1", "PROJ2"],
    "confluence_allowed_spaces": ["SPACE1"],
    "max_results_per_request": 50,
    "max_results_hard_cap": 200,
    "max_api_calls_per_request": 20
  },
  "jira": {
    "ok": true,
    "canonical_url": "https://company.atlassian.net",
    "configured_url": "https://jira.company.com",
    "url_resolved": true,
    "server_title": "Company Jira",
    "version": "9.12.0",
    "latency_ms": 234
  },
  "confluence": {
    "ok": true,
    "canonical_url": "https://company.atlassian.net/wiki",
    "configured_url": "https://confluence.company.com/wiki",
    "url_resolved": true,
    "is_cloud": true,
    "user": "Jane Doe",
    "latency_ms": 187
  },
  "meta": { "request_id": "...", "elapsed_ms": 450 }
}
```

If `url_resolved: true`, update `JIRA_BASE_URL` / `CONFLUENCE_BASE_URL` in your `.env` to the `canonical_url` value to avoid the resolution overhead on every request.
