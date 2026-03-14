"""Jira REST API v3 client with retry, backoff, and cursor-based pagination.

This client is read-only: it only issues GET and POST (for JQL search bodies).
No PUT, PATCH, or DELETE methods are provided.

Key behaviors:
- Canonical URL resolution at init (fixes proxy/vanity domain mismatches)
- Cursor-based pagination (v3) with offset-based fallback (v2)
- Retry on 429 (rate limit) with Retry-After header; retry on 5xx with backoff
- Per-request delay to stay within safe API call rates
- API call counting via RequestContext; raises ApiLimitExceededError at limit
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests

from atlassian_mcp_guardrails.auth import create_session, resolve_canonical_url
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.jira.models import JiraIssue

logger = logging.getLogger(__name__)

_MAX_RETRY_429 = 3
_MAX_RETRY_5XX = 2
_DEFAULT_BACKOFF = [1, 2, 4]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    return _HTML_TAG_RE.sub("", html).strip()


class JiraClient:
    """Authenticated Jira REST API v3 client (read-only).

    Instantiate via the class method ``from_config`` to ensure canonical URL
    resolution is applied at construction time.
    """

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        config: AtlassianConfig,
        ctx: RequestContext | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._config = config
        self._ctx = ctx
        self._timeout = config.http_timeout
        self._custom_field_map: dict[str, str] = {}

    @classmethod
    def from_config(
        cls,
        config: AtlassianConfig,
        ctx: RequestContext | None = None,
    ) -> "JiraClient":
        """Create a JiraClient with canonical URL resolution applied.

        Calls ``resolve_canonical_url`` unconditionally so proxy/vanity domains
        are resolved to the real Atlassian Cloud host before any API calls.
        """
        session = create_session(config.jira_email, config.jira_token)
        canonical = resolve_canonical_url(config.jira_base_url, session, config.http_timeout)
        return cls(session=session, base_url=canonical, config=config, ctx=ctx)

    # ------------------------------------------------------------------
    # Low-level HTTP with retry and rate limiting
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> requests.Response:
        url = f"{self._base_url}{path}"
        delay_s = self._config.request_delay_ms / 1000.0

        max_attempts = _MAX_RETRY_429 + 1
        resp: requests.Response | None = None

        for attempt in range(max_attempts):
            # Enforce inter-request delay (skip on first attempt for speed)
            if attempt > 0 or delay_s > 0:
                time.sleep(delay_s)

            try:
                resp = self._session.request(
                    method, url,
                    params=params,
                    json=json_body,
                    timeout=self._timeout,
                )
                if self._ctx:
                    self._ctx.increment_api_calls(self._config.max_api_calls_per_request)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < _MAX_RETRY_5XX:
                    wait = _DEFAULT_BACKOFF[min(attempt, len(_DEFAULT_BACKOFF) - 1)]
                    logger.warning(
                        "Network error on %s (attempt %d/%d), retrying in %ds: %s",
                        url, attempt + 1, max_attempts, wait, exc,
                    )
                    time.sleep(wait)
                    continue
                raise

            if resp.status_code == 429:
                retry_after = int(
                    resp.headers.get("Retry-After", _DEFAULT_BACKOFF[min(attempt, len(_DEFAULT_BACKOFF) - 1)])
                )
                if attempt < _MAX_RETRY_429:
                    logger.warning(
                        "Rate limited on %s, retrying in %ds (attempt %d/%d)",
                        url, retry_after, attempt + 1, max_attempts,
                    )
                    time.sleep(retry_after)
                    continue

            if resp.status_code >= 500 and attempt < _MAX_RETRY_5XX:
                wait = _DEFAULT_BACKOFF[min(attempt, len(_DEFAULT_BACKOFF) - 1)]
                logger.warning(
                    "Server error %d on %s, retrying in %ds (attempt %d/%d)",
                    resp.status_code, url, wait, attempt + 1, max_attempts,
                )
                time.sleep(wait)
                continue

            return resp

        return resp  # type: ignore[return-value]

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return self._request("POST", path, **kwargs)

    # ------------------------------------------------------------------
    # Public API methods (read-only)
    # ------------------------------------------------------------------

    def server_info(self) -> dict:
        """GET /rest/api/3/serverInfo — returns instance metadata."""
        resp = self._get("/rest/api/3/serverInfo")
        resp.raise_for_status()
        return resp.json()

    def myself(self) -> dict:
        """GET /rest/api/3/myself — connectivity and auth test."""
        resp = self._get("/rest/api/3/myself")
        resp.raise_for_status()
        return resp.json()

    def get_issue(self, key: str) -> JiraIssue:
        """Fetch a single issue by key."""
        resp = self._get(f"/rest/api/3/issue/{key}")
        resp.raise_for_status()
        return self._parse_issue(resp.json())

    def search(
        self,
        jql: str,
        max_results: int | None = None,
        custom_field_map: dict[str, str] | None = None,
    ) -> list[JiraIssue]:
        """Paginated JQL search.

        Tries v3 cursor-based endpoint first (``POST /rest/api/3/search/jql``),
        falls back to v2 offset-based (``POST /rest/api/2/search``) if the v3
        endpoint returns 404.

        Args:
            jql: The JQL query string.
            max_results: Maximum issues to return; capped at ``config.max_results_hard_cap``.
            custom_field_map: Mapping of logical name → ``customfield_XXXXX`` ID.

        Returns:
            List of ``JiraIssue`` objects.
        """
        self._custom_field_map = custom_field_map or {}
        cap = max_results or self._config.max_results_per_request
        page_size = min(self._config.max_results_per_request, cap)
        all_fields = self._build_field_list()

        issues: list[JiraIssue] = []

        if self._try_search_v3(jql, all_fields, page_size, cap, issues):
            return issues

        logger.info("v3 search endpoint unavailable, falling back to v2 offset-based search")
        self._search_v2(jql, all_fields, page_size, cap, issues)
        return issues

    def get_fields(self) -> list[dict]:
        """GET /rest/api/3/field — returns all field definitions."""
        resp = self._get("/rest/api/3/field")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Pagination helpers
    # ------------------------------------------------------------------

    def _build_field_list(self) -> list[str]:
        """Standard fields plus any discovered custom fields."""
        base = [
            "summary", "status", "issuetype", "project", "description",
            "labels", "components", "priority", "assignee", "reporter",
            "created", "updated", "resolution", "fixVersions",
            "parent", "issuelinks", "resolutiondate", "duedate",
        ]
        for cf_id in self._custom_field_map.values():
            if cf_id and cf_id not in base:
                base.append(cf_id)
        return base

    def _try_search_v3(
        self,
        jql: str,
        fields: list[str],
        page_size: int,
        cap: int,
        issues: list[JiraIssue],
    ) -> bool:
        """Attempt v3 cursor-based search. Returns True if the endpoint is available."""
        next_token: str | None = None
        while len(issues) < cap:
            body: dict = {
                "jql": jql,
                "fields": fields,
                "maxResults": min(page_size, cap - len(issues)),
            }
            if next_token:
                body["nextPageToken"] = next_token

            resp = self._post("/rest/api/3/search/jql", json_body=body)

            if resp.status_code == 404:
                return False

            if resp.status_code != 200:
                logger.error(
                    "Jira search failed: HTTP %d — %s",
                    resp.status_code, resp.text[:300],
                )
                break

            data = resp.json()
            for raw_issue in data.get("issues", data.get("values", [])):
                issues.append(self._parse_issue(raw_issue))
                if self._ctx:
                    self._ctx.items_fetched += 1

            next_token = data.get("nextPageToken")
            if not next_token:
                break

        return True

    def _search_v2(
        self,
        jql: str,
        fields: list[str],
        page_size: int,
        cap: int,
        issues: list[JiraIssue],
    ) -> None:
        """Offset-based search via POST /rest/api/2/search."""
        start_at = 0
        while len(issues) < cap:
            body = {
                "jql": jql,
                "fields": fields,
                "startAt": start_at,
                "maxResults": min(page_size, cap - len(issues)),
            }
            resp = self._post("/rest/api/2/search", json_body=body)

            if resp.status_code != 200:
                logger.error(
                    "Jira v2 search failed: HTTP %d — %s",
                    resp.status_code, resp.text[:300],
                )
                break

            data = resp.json()
            batch = data.get("issues", [])
            if not batch:
                break

            for raw_issue in batch:
                issues.append(self._parse_issue(raw_issue))
                if self._ctx:
                    self._ctx.items_fetched += 1

            start_at += len(batch)
            if start_at >= data.get("total", 0):
                break

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_issue(self, data: dict) -> JiraIssue:
        fields = data.get("fields", {})
        desc_raw = fields.get("description") or ""

        if isinstance(desc_raw, dict):
            desc_html = json.dumps(desc_raw)
            desc_plain = self._adf_to_plain(desc_raw)
        else:
            desc_html = str(desc_raw)
            desc_plain = _strip_html(str(desc_raw)) if desc_raw else ""

        status_obj = fields.get("status") or {}
        type_obj = fields.get("issuetype") or {}
        project_obj = fields.get("project") or {}
        priority_obj = fields.get("priority") or {}
        assignee_obj = fields.get("assignee") or {}
        reporter_obj = fields.get("reporter") or {}
        resolution_obj = fields.get("resolution") or {}

        cfm = self._custom_field_map

        parent_obj = fields.get("parent") or {}
        parent_key = parent_obj.get("key", "")

        epic_link = ""
        if cfm.get("epic_link"):
            epic_raw = fields.get(cfm["epic_link"]) or ""
            epic_link = epic_raw if isinstance(epic_raw, str) else ""

        linked_issues: list[dict] = []
        for link in fields.get("issuelinks") or []:
            entry: dict = {"type": (link.get("type") or {}).get("name", "")}
            if "outwardIssue" in link:
                entry["direction"] = "outward"
                entry["description"] = (link.get("type") or {}).get("outward", "")
                entry["key"] = link["outwardIssue"].get("key", "")
            elif "inwardIssue" in link:
                entry["direction"] = "inward"
                entry["description"] = (link.get("type") or {}).get("inward", "")
                entry["key"] = link["inwardIssue"].get("key", "")
            linked_issues.append(entry)

        acceptance_criteria = ""
        if cfm.get("acceptance_criteria"):
            ac_raw = fields.get(cfm["acceptance_criteria"]) or ""
            if isinstance(ac_raw, dict):
                acceptance_criteria = self._adf_to_plain(ac_raw)
            else:
                acceptance_criteria = _strip_html(str(ac_raw)) if ac_raw else ""

        # Collect any remaining discovered custom fields as key-value pairs
        custom_fields: dict[str, str] = {}
        for logical_name, field_id in cfm.items():
            if field_id and logical_name not in (
                "tshirt_size", "start_date", "end_date",
                "acceptance_criteria", "epic_link",
            ):
                val = self._extract_custom_str(fields, field_id)
                if val:
                    custom_fields[logical_name] = val

        key = data.get("key", "")
        return JiraIssue(
            key=key,
            issue_id=data.get("id", ""),
            summary=fields.get("summary", ""),
            status=status_obj.get("name", ""),
            issue_type=type_obj.get("name", ""),
            project_key=project_obj.get("key", ""),
            description_html=desc_html,
            description_plain=desc_plain,
            labels=fields.get("labels", []),
            components=[c.get("name", "") for c in (fields.get("components") or [])],
            priority=priority_obj.get("name", ""),
            assignee=assignee_obj.get("displayName", ""),
            reporter=reporter_obj.get("displayName", ""),
            created=fields.get("created", ""),
            updated=fields.get("updated", ""),
            resolution=resolution_obj.get("name", "") if resolution_obj else "",
            fix_versions=[v.get("name", "") for v in (fields.get("fixVersions") or [])],
            url=f"{self._base_url}/browse/{key}",
            raw=data,
            acceptance_criteria=acceptance_criteria,
            tshirt_size=self._extract_custom_str(fields, cfm.get("tshirt_size", "")),
            start_date=self._extract_custom_str(fields, cfm.get("start_date", "")),
            due_date=fields.get("duedate") or "",
            end_date=self._extract_custom_str(fields, cfm.get("end_date", "")),
            resolved_date=fields.get("resolutiondate") or "",
            parent_key=parent_key,
            epic_link=epic_link,
            linked_issues=linked_issues,
            custom_fields=custom_fields,
        )

    @staticmethod
    def _extract_custom_str(fields: dict, field_id: str) -> str:
        """Safely pull a string value from a custom field, handling dict/list/None."""
        if not field_id:
            return ""
        raw = fields.get(field_id)
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return raw.get("value", raw.get("name", str(raw)))
        return str(raw)

    @staticmethod
    def _adf_to_plain(adf: dict) -> str:
        """Recursively extract plain text from Atlassian Document Format (ADF)."""
        parts: list[str] = []

        def _walk(node: dict | list | str) -> None:
            if isinstance(node, str):
                parts.append(node)
                return
            if isinstance(node, list):
                for item in node:
                    _walk(item)
                return
            if isinstance(node, dict):
                if node.get("type") == "text":
                    parts.append(node.get("text", ""))
                for child in node.get("content", []):
                    _walk(child)

        _walk(adf)
        return "\n".join(parts).strip()
