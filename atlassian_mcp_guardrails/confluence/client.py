"""Confluence REST API client with v2/v1 fallback, retry, and pagination.

This client is read-only: it only issues GET requests.
No PUT, PATCH, or DELETE methods are provided.

Key behaviors:
- Canonical URL resolution at init (fixes proxy/vanity domain mismatches)
- Cloud (*.atlassian.net): v2 API first, v1 fallback for page fetch
- Server/Data Center: v1 API only
- Retry on 429 (rate limit) with Retry-After header; retry on 5xx with backoff
- Per-request delay to stay within safe API call rates
- API call counting via RequestContext; raises ApiLimitExceededError at limit
"""

from __future__ import annotations

import logging
import re
import time

import requests

from atlassian_mcp_guardrails.auth import create_session, resolve_canonical_wiki_url
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.confluence.models import ConfluencePage

logger = logging.getLogger(__name__)

_MAX_RETRY_429 = 3
_MAX_RETRY_5XX = 2
_DEFAULT_BACKOFF = [1, 2, 4]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    return _HTML_TAG_RE.sub("", html).strip()


def is_cloud_instance(base_url: str) -> bool:
    """Return True if the URL points to an Atlassian Cloud instance."""
    return ".atlassian.net" in base_url.lower()


class ConfluenceClient:
    """Authenticated Confluence REST API client (v2 primary, v1 fallback).

    Automatically detects Cloud vs Server/Data Center instances:
    - Cloud (``*.atlassian.net``): uses v2 API first, v1 fallback
    - Server/DC (on-prem): uses v1 API only (``/rest/api/content``)

    Instantiate via ``from_config`` to ensure canonical URL resolution.
    """

    def __init__(
        self,
        session: requests.Session,
        wiki_base_url: str,
        config: AtlassianConfig,
        ctx: RequestContext | None = None,
    ) -> None:
        self._session = session
        self._base = wiki_base_url.rstrip("/")
        self._config = config
        self._ctx = ctx
        self._timeout = config.http_timeout
        self._is_cloud = is_cloud_instance(self._base)

    @classmethod
    def from_config(
        cls,
        config: AtlassianConfig,
        ctx: RequestContext | None = None,
    ) -> "ConfluenceClient":
        """Create a ConfluenceClient with canonical URL resolution applied.

        Calls ``resolve_canonical_wiki_url`` unconditionally so proxy/vanity
        domains are resolved to the real Atlassian Cloud host before any API
        calls. This prevents 403 Forbidden errors from proxy URL mismatches.
        """
        session = create_session(config.jira_email, config.jira_token)
        canonical_wiki = resolve_canonical_wiki_url(
            config.confluence_wiki_url, session, config.http_timeout
        )
        return cls(session=session, wiki_base_url=canonical_wiki, config=config, ctx=ctx)

    @property
    def is_cloud(self) -> bool:
        """True if connected to an Atlassian Cloud instance."""
        return self._is_cloud

    # ------------------------------------------------------------------
    # Low-level HTTP with retry and rate limiting
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        delay_s = self._config.request_delay_ms / 1000.0
        max_attempts = _MAX_RETRY_429 + 1
        resp: requests.Response | None = None

        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(delay_s)

            try:
                resp = self._session.request(method, url, **kwargs)
                if self._ctx:
                    self._ctx.increment_api_calls(self._config.max_api_calls_per_request)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < _MAX_RETRY_5XX:
                    wait = _DEFAULT_BACKOFF[min(attempt, len(_DEFAULT_BACKOFF) - 1)]
                    logger.warning(
                        "Network error (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, max_attempts, wait, exc,
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
                        "Rate limited, retrying in %ds (attempt %d/%d)",
                        retry_after, attempt + 1, max_attempts,
                    )
                    time.sleep(retry_after)
                    continue

            if resp.status_code >= 500 and attempt < _MAX_RETRY_5XX:
                wait = _DEFAULT_BACKOFF[min(attempt, len(_DEFAULT_BACKOFF) - 1)]
                logger.warning(
                    "Server error %d, retrying in %ds (attempt %d/%d)",
                    resp.status_code, wait, attempt + 1, max_attempts,
                )
                time.sleep(wait)
                continue

            return resp

        return resp  # type: ignore[return-value]

    def _get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    # ------------------------------------------------------------------
    # Public API methods (read-only)
    # ------------------------------------------------------------------

    def current_user(self) -> dict:
        """GET /wiki/rest/api/user/current — auth test."""
        resp = self._get(f"{self._base}/rest/api/user/current")
        resp.raise_for_status()
        return resp.json()

    def get_page(self, page_id: str, body_format: str = "storage") -> ConfluencePage:
        """Fetch a page by ID.

        Tries v2 API first (Cloud only), falls back to v1.
        """
        if self._is_cloud:
            page = self._get_page_v2(page_id, body_format)
            if page is not None:
                return page
        return self._get_page_v1(page_id)

    def get_children(self, page_id: str, limit: int = 50) -> list[ConfluencePage]:
        """Fetch child pages of a given page (capped at ``limit``)."""
        pages: list[ConfluencePage] = []
        if self._is_cloud:
            url = f"{self._base}/api/v2/pages/{page_id}/children?limit={limit}"
        else:
            url = (
                f"{self._base}/rest/api/content/{page_id}/child/page"
                f"?limit={limit}&expand=body.storage,version,space,metadata.labels"
            )

        while url and len(pages) < limit:
            resp = self._get(url)
            if resp.status_code != 200:
                logger.warning("get_children(%s) returned HTTP %d", page_id, resp.status_code)
                break
            data = resp.json()
            for child in data.get("results", []):
                if self._is_cloud:
                    pages.append(self._parse_v2_page(child))
                else:
                    pages.append(self._parse_v1_page(child))
                if len(pages) >= limit:
                    break

            next_link = data.get("_links", {}).get("next")
            if next_link and len(pages) < limit:
                url = next_link if next_link.startswith("http") else self._base + next_link
            else:
                url = None

        return pages

    def search_cql(self, cql: str, limit: int = 50) -> list[ConfluencePage]:
        """CQL search for pages (always uses v1 search endpoint).

        Args:
            cql: The CQL query string.
            limit: Maximum number of pages to return.

        Returns:
            List of ``ConfluencePage`` objects.
        """
        pages: list[ConfluencePage] = []
        start = 0

        while len(pages) < limit:
            resp = self._get(
                f"{self._base}/rest/api/content/search",
                params={
                    "cql": cql,
                    "start": start,
                    "limit": min(limit - len(pages), 50),
                    "expand": "body.storage,version,space,metadata.labels",
                },
            )
            if resp.status_code != 200:
                logger.warning("CQL search returned HTTP %d for: %s", resp.status_code, cql[:100])
                break

            data = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for item in results:
                pages.append(self._parse_v1_page(item))
                if self._ctx:
                    self._ctx.items_fetched += 1

            start += len(results)
            total = data.get("totalSize", data.get("size", 0))
            if start >= total:
                break

        return pages

    # ------------------------------------------------------------------
    # v2 / v1 page fetch
    # ------------------------------------------------------------------

    def _get_page_v2(self, page_id: str, body_format: str) -> ConfluencePage | None:
        url = f"{self._base}/api/v2/pages/{page_id}?body-format={body_format}"
        resp = self._get(url)
        if resp.status_code != 200:
            logger.debug("v2 page fetch returned HTTP %d, trying v1 fallback", resp.status_code)
            return None
        return self._parse_v2_page(resp.json())

    def _get_page_v1(self, page_id: str) -> ConfluencePage:
        url = (
            f"{self._base}/rest/api/content/{page_id}"
            f"?expand=body.storage,version,space,ancestors,metadata.labels"
        )
        resp = self._get(url)
        resp.raise_for_status()
        return self._parse_v1_page(resp.json())

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_v2_page(self, data: dict) -> ConfluencePage:
        version = data.get("version", {})
        body = data.get("body", {}).get("storage", {})
        body_html = body.get("value", "") if isinstance(body, dict) else ""

        return ConfluencePage(
            page_id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_key=str(data.get("spaceId", "")),
            status=data.get("status", ""),
            body_html=body_html,
            body_plain=_strip_html(body_html) if body_html else "",
            version=version.get("number", 0) if isinstance(version, dict) else 0,
            last_modified=version.get("createdAt", "") if isinstance(version, dict) else "",
            author=version.get("authorId", "") if isinstance(version, dict) else "",
            labels=[],
            parent_id=str(data.get("parentId", "")),
            url=data.get("_links", {}).get("webui", ""),
            raw=data,
        )

    def _parse_v1_page(self, data: dict) -> ConfluencePage:
        version = data.get("version", {})
        body = data.get("body", {}).get("storage", {})
        body_html = body.get("value", "")
        space = data.get("space", {})

        labels_raw = data.get("metadata", {}).get("labels", {}).get("results", [])
        labels = [lb.get("name", "") for lb in labels_raw] if labels_raw else []

        return ConfluencePage(
            page_id=str(data.get("id", "")),
            title=data.get("title", ""),
            space_key=space.get("key", ""),
            status=data.get("status", ""),
            body_html=body_html,
            body_plain=_strip_html(body_html) if body_html else "",
            version=version.get("number", 0),
            last_modified=version.get("when", ""),
            author=version.get("by", {}).get("displayName", ""),
            labels=labels,
            parent_id="",
            url=data.get("_links", {}).get("webui", ""),
            raw=data,
        )
