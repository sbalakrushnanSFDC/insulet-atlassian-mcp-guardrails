"""Confluence MCP tools: confluence_get_page, confluence_search."""

from __future__ import annotations

import logging

from atlassian_mcp_guardrails.server import mcp
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.guardrails import (
    enforce_result_cap,
    enforce_space_scope,
    inject_default_space_scope,
    inject_priority_space_scope,
)
from atlassian_mcp_guardrails.confluence.client import ConfluenceClient
from atlassian_mcp_guardrails.confluence.models import ConfluencePage

logger = logging.getLogger(__name__)

_BODY_MAX_CHARS = 2000
_CHILDREN_HARD_CAP = 50


def _page_to_dict(page: ConfluencePage, include_body: bool = True) -> dict:
    """Serialize a ConfluencePage to a tool-response dict with bounded body."""
    result: dict = {
        "page_id": page.page_id,
        "title": page.title,
        "space_key": page.space_key,
        "status": page.status,
        "version": page.version,
        "last_modified": page.last_modified,
        "author": page.author,
        "labels": page.labels,
        "parent_id": page.parent_id,
        "url": page.url,
    }
    if include_body:
        result["body_plain"] = page.body_plain[:_BODY_MAX_CHARS]
    return result


@mcp.tool()
def confluence_get_page(
    page_id: str,
    include_children: bool = False,
    include_body: bool = True,
) -> dict:
    """Fetch a single Confluence page by ID.

    Tries the v2 API first (Atlassian Cloud), falls back to v1.

    Args:
        page_id: The numeric Confluence page ID.
        include_children: If True, also fetch direct child pages (capped at 50).
        include_body: If True (default), include truncated page body text.

    Returns:
        Dict with page fields, optional children list, and ``meta``.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        client = ConfluenceClient.from_config(config, ctx)
        page = client.get_page(page_id.strip())

        result = _page_to_dict(page, include_body=include_body)

        if include_children:
            children = client.get_children(page_id.strip(), limit=_CHILDREN_HARD_CAP)
            result["children"] = [_page_to_dict(c, include_body=False) for c in children]
            result["children_count"] = len(children)

        result["meta"] = ctx.to_dict()
        return result
    except Exception as exc:
        logger.error("confluence_get_page(%s) failed: %s", page_id, exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def confluence_search(
    cql: str,
    limit: int = 25,
    include_body: bool = False,
    scope: str = "priority",
    expand_beyond_defaults: bool = False,
) -> dict:
    """Search Confluence pages using CQL.

    The ``scope`` parameter controls which space filter is prepended when the
    CQL has no explicit space clause:

    - ``"priority"`` *(default)* — prepends ``CONFLUENCE_PRIORITY_SPACES``.
      Searches your most relevant spaces first.
    - ``"default"`` — prepends ``CONFLUENCE_DEFAULT_SPACES`` (original behaviour).
    - ``"all"`` — no injection; raw CQL is sent as-is.

    If ``CONFLUENCE_ALLOWED_SPACES`` is configured, the query must reference
    at least one allowed space or a ``ScopeViolationError`` is returned
    regardless of scope.

    ``expand_beyond_defaults=True`` is a deprecated alias for ``scope="all"``.

    Args:
        cql: CQL query string (e.g. ``text ~ 'authentication' AND type = page``).
        limit: Number of results to return (default 25; hard cap from config).
        include_body: If True, include truncated body text in results.
        scope: Scope tier to apply — ``"priority"``, ``"default"``, or ``"all"``.
            Defaults to ``"priority"``.
        expand_beyond_defaults: Deprecated. If True, overrides scope to ``"all"``.

    Returns:
        Dict with ``pages`` list, ``scope_applied``, ``cql_executed``, and ``meta``.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        effective_limit = enforce_result_cap(limit, config.max_results_hard_cap)

        # Deprecated flag takes precedence for backward compatibility
        effective_scope = "all" if expand_beyond_defaults else scope

        effective_cql = cql
        if effective_scope == "priority":
            effective_cql = inject_priority_space_scope(cql, config.confluence_priority_spaces)
            # Fall back to default spaces if no priority spaces configured
            if effective_cql == cql:
                effective_cql = inject_default_space_scope(cql, config.confluence_default_spaces)
        elif effective_scope == "default":
            effective_cql = inject_default_space_scope(cql, config.confluence_default_spaces)
        # scope="all" → no injection

        enforce_space_scope(effective_cql, config.confluence_allowed_spaces)

        client = ConfluenceClient.from_config(config, ctx)
        pages = client.search_cql(effective_cql, limit=effective_limit)

        return {
            "pages": [_page_to_dict(p, include_body=include_body) for p in pages],
            "count": len(pages),
            "scope_applied": effective_scope,
            "cql_executed": effective_cql,
            "meta": ctx.to_dict(),
        }
    except Exception as exc:
        logger.error("confluence_search failed: %s", exc)
        return {"error": str(exc), "error_type": type(exc).__name__}
