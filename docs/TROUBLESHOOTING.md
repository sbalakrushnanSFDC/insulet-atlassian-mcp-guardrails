# Troubleshooting Guide

Diagnosis and fixes for common issues.

---

## 403 Forbidden on Confluence

**Symptom:** `confluence_get_page` or `confluence_search` returns `{"error": "403 Client Error: Forbidden"}`

**Most likely cause:** `CONFLUENCE_BASE_URL` is set to a corporate proxy URL (e.g. `https://confluence.company.com`) instead of the canonical Atlassian Cloud URL (`https://company.atlassian.net`).

**Diagnosis:** Run `atlassian_health_check` and check:

```json
{
  "confluence": {
    "canonical_url": "https://company.atlassian.net/wiki",
    "configured_url": "https://confluence.company.com/wiki",
    "url_resolved": true
  }
}
```

If `url_resolved: true`, the server is already correcting this at runtime. But if the resolution itself fails (e.g. the proxy blocks `/rest/api/3/serverInfo`), the proxy URL is used and 403s occur.

**Fix:** Set `CONFLUENCE_BASE_URL` to the canonical URL in `.env`:

```
CONFLUENCE_BASE_URL=https://company.atlassian.net
```

Or leave `CONFLUENCE_BASE_URL` unset — it defaults to `JIRA_BASE_URL`, which is usually already the canonical URL.

---

## 401 Unauthorized

**Symptom:** `atlassian_health_check` returns `{"jira": {"ok": false, "error": "401 Client Error: Unauthorized"}}`

**Cause:** API token is wrong, expired, or you used your Atlassian password instead of an API token.

**Diagnosis:** Test your credentials directly:

```bash
curl -u "your-email@company.com:your-api-token" \
  https://your-instance.atlassian.net/rest/api/3/myself
```

A successful response returns your user profile JSON. A 401 means the credentials are invalid.

**Fix:**
1. Go to [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Create a new API token
3. Update `JIRA_TOKEN` in `.env`
4. Restart the server

---

## ScopeViolationError

**Symptom:** Tool returns `{"error": "...", "error_type": "ScopeViolationError"}`

**Cause:** `JIRA_ALLOWED_PROJECTS` or `CONFLUENCE_ALLOWED_SPACES` is set, and the query references a project/space not in the allowlist, or has no project/space clause at all.

**Fix options:**

1. **Add the project/space to the allowlist** in `.env`:
   ```
   JIRA_ALLOWED_PROJECTS=PROJ1,PROJ2,NEWPROJ
   ```

2. **Include the project in your query** explicitly:
   ```
   jira_search(jql="project = PROJ1 AND issuetype = Story")
   ```

3. **Set default projects** so queries without a clause are auto-scoped:
   ```
   JIRA_DEFAULT_PROJECTS=PROJ1,PROJ2
   ```

The error message includes the allowed list, so you can see exactly what is configured.

---

## ApiLimitExceededError

**Symptom:** Tool returns `{"error": "API call limit exceeded: ...", "error_type": "ApiLimitExceededError"}`

**Cause:** The tool made more than `MAX_API_CALLS_PER_REQUEST` (default: 20) Atlassian API calls in a single invocation. This usually happens with a large `max_results` value that requires many paginated pages.

**Fix options:**

1. **Reduce `max_results`** in your call:
   ```
   jira_search(jql="...", max_results=20)
   ```

2. **Increase `MAX_API_CALLS_PER_REQUEST`** in `.env`:
   ```
   MAX_API_CALLS_PER_REQUEST=40
   ```

3. **Narrow your query** to return fewer results naturally (add more filters).

---

## 429 Too Many Requests

**Symptom:** Slow responses; WARNING logs showing "Rate limited, retrying in Xs"

**Cause:** Your Atlassian plan's API rate limit is being hit. The server retries automatically (up to 3 times with `Retry-After` backoff), but persistent 429s indicate the rate limit is too low for the query volume.

**Fix:**
1. Increase `REQUEST_DELAY_MS` in `.env` to slow down inter-request calls:
   ```
   REQUEST_DELAY_MS=300
   ```

2. Reduce `MAX_API_CALLS_PER_REQUEST` to limit how many calls a single tool invocation makes.

3. Reduce `max_results` in search calls to reduce pagination.

---

## ImportError on Startup

**Symptom:** `ModuleNotFoundError: No module named 'atlassian_mcp_guardrails'`

**Cause:** The package is not installed in the Python environment being used.

**Fix:**
```bash
cd insulet-atlassian-mcp-guardrails
source .venv/bin/activate
pip install -e .
```

Make sure the `command` in your Cursor MCP config points to the venv Python, not the system Python:

```json
"command": "/full/path/to/insulet-atlassian-mcp-guardrails/.venv/bin/python"
```

---

## Server Not Appearing in Cursor

**Symptom:** `@atlassian-guardrails` does not appear in Cursor chat

**Diagnosis steps:**

1. Check Cursor Settings → MCP — is the server listed? Is there a red error indicator?
2. Check the MCP server logs in Cursor (Settings → MCP → click the server name → view logs)
3. Test the command manually in your terminal:
   ```bash
   /full/path/to/.venv/bin/python -m atlassian_mcp_guardrails.server
   ```
   It should start without error (it waits for stdin input from the MCP client).

**Common causes:**
- Wrong Python path in the config (points to system Python, not venv)
- Wrong `cwd` path (server can't find `.env`)
- Missing required env vars (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`)
- Cursor needs a restart after config changes

---

## Empty Results from jira_search

**Symptom:** `jira_search` returns `{"issues": [], "count": 0}`

**Possible causes:**

1. **Default scope is too narrow** — the auto-injected project filter has no matching issues. Check `jql_executed` in the response to see what was sent.

2. **JQL syntax error** — Jira returns 400 for invalid JQL. Check for typos, unquoted values with spaces, or unsupported field names.

3. **No issues match** — the query is valid but there are genuinely no results.

**Diagnosis:**
- Check `jql_executed` in the response to see the exact query sent
- Test the JQL directly in Jira's issue search (Issues → Advanced search)
- Try `expand_beyond_defaults=true` to see if the default scope is filtering out results

---

## Confluence Returns 0 Results Despite Known Pages

**Symptom:** `confluence_search` returns empty results for a space you know has pages.

**Possible causes:**

1. **Wrong space key** — Confluence space keys are case-sensitive. Use the exact key from the Confluence URL (e.g. `MYSPACE`, not `myspace`).

2. **Proxy URL issue** — see "403 Forbidden on Confluence" above.

3. **Default space injection** — if `CONFLUENCE_DEFAULT_SPACES` is set to a different space, your query may be scoped to the wrong space. Check `cql_executed` in the response.

**Diagnosis:**
```
confluence_search(cql="type = page ORDER BY lastModified DESC", limit=5)
```

Check `cql_executed` — if it shows `space in ("WRONGSPACE") AND ...`, update `CONFLUENCE_DEFAULT_SPACES` in `.env`.
