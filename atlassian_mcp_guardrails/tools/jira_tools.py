"""Jira MCP tools: jira_search, jira_get_issue, jira_get_issue_deep, jira_get_comments, jira_get_attachments, jira_discover_fields."""

from __future__ import annotations

import logging

from atlassian_mcp_guardrails.server import mcp
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.guardrails import (
    enforce_project_scope,
    enforce_result_cap,
    inject_default_project_scope,
    inject_expanded_jql,
    inject_priority_jql,
)
from atlassian_mcp_guardrails.jira.adf_extractor import extract_adf_nodes
from atlassian_mcp_guardrails.jira.client import JiraClient
from atlassian_mcp_guardrails.jira.field_discovery import discover_custom_fields
from atlassian_mcp_guardrails.jira.models import JiraAttachment, JiraComment, JiraIssue, JiraRemoteLink

logger = logging.getLogger(__name__)

# Legacy defaults kept for backward compat; overridden by AtlassianConfig when available.
# Set DESCRIPTION_MAX_CHARS=0 or AC_MAX_CHARS=0 in .env for unlimited.
_DESCRIPTION_MAX_CHARS_DEFAULT = 500
_ACCEPTANCE_CRITERIA_MAX_CHARS_DEFAULT = 1000


def _apply_cap(text: str, cap: int) -> str:
    """Return text truncated to cap chars. cap=0 means unlimited."""
    if cap <= 0:
        return text
    return text[:cap]


def _issue_to_dict(issue: JiraIssue, desc_cap: int = _DESCRIPTION_MAX_CHARS_DEFAULT,
                   ac_cap: int = _ACCEPTANCE_CRITERIA_MAX_CHARS_DEFAULT) -> dict:
    """Serialize a JiraIssue to a tool-response dict with configurable text caps."""
    return {
        "key": issue.key,
        "issue_id": issue.issue_id,
        "summary": issue.summary,
        "status": issue.status,
        "issue_type": issue.issue_type,
        "project_key": issue.project_key,
        "assignee": issue.assignee,
        "reporter": issue.reporter,
        "priority": issue.priority,
        "labels": issue.labels,
        "components": issue.components,
        "fix_versions": issue.fix_versions,
        "resolution": issue.resolution,
        "tshirt_size": issue.tshirt_size,
        "start_date": issue.start_date,
        "due_date": issue.due_date,
        "end_date": issue.end_date,
        "resolved_date": issue.resolved_date,
        "parent_key": issue.parent_key,
        "epic_link": issue.epic_link,
        "linked_issues": issue.linked_issues,
        "acceptance_criteria": _apply_cap(issue.acceptance_criteria, ac_cap),
        "description_plain": _apply_cap(issue.description_plain, desc_cap),
        "url": issue.url,
        "created": issue.created,
        "updated": issue.updated,
        "custom_fields": issue.custom_fields,
    }


@mcp.tool()
def jira_search(
    jql: str,
    max_results: int = 50,
    scope: str = "priority",
    expand_beyond_defaults: bool = False,
) -> dict:
    """Search Jira issues using JQL.

    The ``scope`` parameter controls which filter is prepended when the JQL has
    no explicit project clause:

    - ``"priority"`` *(default)* — Phase 1: ``JIRA_PRIORITY_PROJECTS`` AND
      (``JIRA_PRIORITY_LABELS`` OR ``JIRA_PRIORITY_FIX_VERSIONS``). Narrows to
      NextGen program work first.
    - ``"expanded"`` — Phase 2: same projects with broader label/fix-version sets
      from ``JIRA_EXPANDED_LABELS`` / ``JIRA_EXPANDED_FIX_VERSIONS``.
    - ``"default"`` — project-only filter from ``JIRA_DEFAULT_PROJECTS``
      (original behaviour).
    - ``"all"`` — no injection; raw JQL is sent as-is.

    If ``JIRA_ALLOWED_PROJECTS`` is configured, the query must reference at
    least one allowed project or a ``ScopeViolationError`` is returned regardless
    of scope.

    ``expand_beyond_defaults=True`` is a deprecated alias for ``scope="all"``.

    Args:
        jql: JQL query string (e.g. ``issuetype = Story AND status = 'In Progress'``).
        max_results: Number of results to return (default 50; hard cap from config).
        scope: Scope tier to apply — ``"priority"``, ``"expanded"``, ``"default"``,
            or ``"all"``. Defaults to ``"priority"``.
        expand_beyond_defaults: Deprecated. If True, overrides scope to ``"all"``.

    Returns:
        Dict with ``issues`` list, ``scope_applied``, ``jql_executed``, and ``meta``.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        effective_max = enforce_result_cap(max_results, config.max_results_hard_cap)

        # Deprecated flag takes precedence for backward compatibility
        effective_scope = "all" if expand_beyond_defaults else scope

        effective_jql = jql
        if effective_scope == "priority":
            effective_jql = inject_priority_jql(
                jql,
                config.jira_priority_projects,
                config.jira_priority_labels,
                config.jira_priority_fix_versions,
            )
        elif effective_scope == "expanded":
            effective_jql = inject_expanded_jql(
                jql,
                config.jira_priority_projects,
                config.jira_expanded_labels,
                config.jira_expanded_fix_versions,
            )
        elif effective_scope == "default":
            effective_jql = inject_default_project_scope(jql, config.jira_default_projects)
        # scope="all" → no injection

        enforce_project_scope(effective_jql, config.jira_allowed_projects)

        client = JiraClient.from_config(config, ctx)
        issues = client.search(effective_jql, max_results=effective_max)

        return {
            "issues": [_issue_to_dict(i, config.description_max_chars, config.ac_max_chars) for i in issues],
            "count": len(issues),
            "scope_applied": effective_scope,
            "jql_executed": effective_jql,
            "meta": ctx.to_dict(),
        }
    except Exception as exc:
        logger.error("jira_search failed: %s", exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def jira_get_issue(issue_key: str, include_raw: bool = False) -> dict:
    """Fetch a single Jira issue by key.

    Args:
        issue_key: The Jira issue key (e.g. ``PROJ-123``).
        include_raw: If True, include the raw API response in the result.

    Returns:
        Dict with issue fields, or ``error`` on failure.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        client = JiraClient.from_config(config, ctx)
        issue = client.get_issue(issue_key.strip().upper())

        result = _issue_to_dict(issue, config.description_max_chars, config.ac_max_chars)
        if include_raw:
            result["raw"] = issue.raw
        result["meta"] = ctx.to_dict()
        return result
    except Exception as exc:
        logger.error("jira_get_issue(%s) failed: %s", issue_key, exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def jira_discover_fields(force_refresh: bool = False) -> dict:
    """Discover custom field mappings for this Jira instance.

    Calls ``GET /rest/api/3/field`` and matches known logical names
    (``tshirt_size``, ``start_date``, ``end_date``, ``acceptance_criteria``,
    ``epic_link``, ``sprint``, ``story_points``) to their ``customfield_XXXXX``
    IDs.

    Results are returned directly — no database write occurs.

    Args:
        force_refresh: Ignored (no cache exists in this server); included for
            API compatibility with the full platform server.

    Returns:
        Dict with ``field_map`` (logical_name -> field_id) and ``meta``.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        client = JiraClient.from_config(config, ctx)
        cfm = discover_custom_fields(client)

        return {
            "field_map": cfm.to_dict(),
            "total_fields_on_instance": len(cfm._all_fields),
            "custom_fields_on_instance": len([f for f in cfm._all_fields if f.get("custom")]),
            "meta": ctx.to_dict(),
        }
    except Exception as exc:
        logger.error("jira_discover_fields failed: %s", exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


# ---------------------------------------------------------------------------
# Deep retrieval tools (Phase 1+)
# ---------------------------------------------------------------------------

def _comment_to_dict(c: JiraComment) -> dict:
    return {
        "comment_id": c.comment_id,
        "author": c.author,
        "author_account_id": c.author_account_id,
        "body_plain": c.body_plain,
        "created": c.created,
        "updated": c.updated,
    }


def _attachment_to_dict(a: JiraAttachment) -> dict:
    return {
        "attachment_id": a.attachment_id,
        "file_name": a.file_name,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "author": a.author,
        "created": a.created,
        "content_url": a.content_url,
        "thumbnail_url": a.thumbnail_url,
    }


def _remotelink_to_dict(r: JiraRemoteLink) -> dict:
    return {
        "remote_link_id": r.remote_link_id,
        "url": r.url,
        "title": r.title,
        "relationship": r.relationship,
        "is_confluence": r.is_confluence,
        "confluence_page_id": r.confluence_page_id,
    }


@mcp.tool()
def jira_get_issue_deep(issue_key: str) -> dict:
    """Fetch a single Jira issue with full deep context.

    Returns the same fields as ``jira_get_issue`` plus:
    - ``description_plain``: full text without truncation (cap governed by env)
    - ``description_adf``: raw Atlassian Document Format JSON
    - ``adf_extraction``: structured extraction: media refs, discovered URLs,
      Confluence page IDs from smart cards and link marks, code blocks
    - ``comments``: full comment thread (author, timestamp, body)
    - ``attachments``: attachment metadata (file name, mime type, size, URL)
    - ``remotelinks``: web/remote links including Confluence page references
    - ``subtasks_raw``: subtask stubs from the issue fields

    Args:
        issue_key: The Jira issue key (e.g. ``PROJ-123``).

    Returns:
        Dict with all deep-retrieval fields, or ``error`` on failure.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        client = JiraClient.from_config(config, ctx)
        issue = client.get_issue_deep(issue_key.strip().upper())

        adf_result = extract_adf_nodes(issue.description_adf)

        result = _issue_to_dict(issue, config.description_max_chars, config.ac_max_chars)
        result["description_adf"] = issue.description_adf
        result["adf_extraction"] = {
            "plain_text_full": adf_result.plain_text,
            "media_refs": [
                {
                    "node_type": m.node_type,
                    "media_id": m.media_id,
                    "media_type": m.media_type,
                    "file_name": m.file_name,
                    "mime_type": m.mime_type,
                    "alt_text": m.alt_text,
                    "caption": m.caption,
                    "url": m.url,
                    "resolvable": m.resolvable,
                }
                for m in adf_result.media_refs
            ],
            "smart_card_refs": [
                {
                    "node_type": sc.node_type,
                    "url": sc.url,
                    "is_confluence": sc.is_confluence,
                    "confluence_page_id": sc.confluence_page_id,
                }
                for sc in adf_result.smart_card_refs
            ],
            "discovered_urls": [
                {
                    "url": u.url,
                    "link_text": u.link_text,
                    "is_confluence": u.is_confluence,
                    "confluence_page_id": u.confluence_page_id,
                }
                for u in adf_result.discovered_urls
            ],
            "confluence_page_ids": adf_result.confluence_page_ids,
            "mention_refs": [
                {"user_id": m.user_id, "display_name": m.display_name}
                for m in adf_result.mention_refs
            ],
            "code_blocks_count": len(adf_result.code_blocks),
            "has_unresolvable_media": adf_result.has_unresolvable_media,
            "node_type_counts": adf_result.node_type_counts,
        }
        result["comments"] = [_comment_to_dict(c) for c in issue.comments]
        result["comments_count"] = len(issue.comments)
        result["attachments"] = [_attachment_to_dict(a) for a in issue.attachments]
        result["attachments_count"] = len(issue.attachments)
        result["remotelinks"] = [_remotelink_to_dict(r) for r in issue.remotelinks]
        result["remotelinks_count"] = len(issue.remotelinks)
        result["subtasks_raw"] = issue.subtasks_raw
        result["subtasks_count"] = len(issue.subtasks_raw)
        result["meta"] = ctx.to_dict()
        return result
    except Exception as exc:
        logger.error("jira_get_issue_deep(%s) failed: %s", issue_key, exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def jira_get_comments(issue_key: str, max_comments: int = 100) -> dict:
    """Fetch all comments for a Jira issue, preserving author, timestamp, and full body.

    Args:
        issue_key: The Jira issue key (e.g. ``PROJ-123``).
        max_comments: Maximum number of comments to return (default 100, max 200).

    Returns:
        Dict with ``comments`` list and ``count``, or ``error`` on failure.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()
        effective_max = min(max_comments, config.max_results_hard_cap)

        client = JiraClient.from_config(config, ctx)
        comments = client.get_comments(issue_key.strip().upper(), max_comments=effective_max)

        return {
            "issue_key": issue_key.strip().upper(),
            "comments": [_comment_to_dict(c) for c in comments],
            "count": len(comments),
            "meta": ctx.to_dict(),
        }
    except Exception as exc:
        logger.error("jira_get_comments(%s) failed: %s", issue_key, exc)
        return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
def jira_get_attachments(issue_key: str) -> dict:
    """Fetch attachment metadata for a Jira issue.

    Returns file name, mime type, size, author, creation timestamp, and
    content URL for each attachment. Does not download binary content.

    Args:
        issue_key: The Jira issue key (e.g. ``PROJ-123``).

    Returns:
        Dict with ``attachments`` list and ``count``, or ``error`` on failure.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        client = JiraClient.from_config(config, ctx)
        attachments = client.get_attachments(issue_key.strip().upper())

        return {
            "issue_key": issue_key.strip().upper(),
            "attachments": [_attachment_to_dict(a) for a in attachments],
            "count": len(attachments),
            "meta": ctx.to_dict(),
        }
    except Exception as exc:
        logger.error("jira_get_attachments(%s) failed: %s", issue_key, exc)
        return {"error": str(exc), "error_type": type(exc).__name__}
