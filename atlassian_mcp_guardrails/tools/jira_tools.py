"""Jira MCP tools: jira_search, jira_get_issue, jira_discover_fields."""

from __future__ import annotations

import logging

from atlassian_mcp_guardrails.server import mcp
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.guardrails import (
    enforce_project_scope,
    enforce_result_cap,
    inject_default_project_scope,
)
from atlassian_mcp_guardrails.jira.client import JiraClient
from atlassian_mcp_guardrails.jira.field_discovery import discover_custom_fields
from atlassian_mcp_guardrails.jira.models import JiraIssue

logger = logging.getLogger(__name__)

_DESCRIPTION_MAX_CHARS = 500
_ACCEPTANCE_CRITERIA_MAX_CHARS = 1000


def _issue_to_dict(issue: JiraIssue) -> dict:
    """Serialize a JiraIssue to a tool-response dict with bounded text fields."""
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
        "acceptance_criteria": issue.acceptance_criteria[:_ACCEPTANCE_CRITERIA_MAX_CHARS],
        "description_plain": issue.description_plain[:_DESCRIPTION_MAX_CHARS],
        "url": issue.url,
        "created": issue.created,
        "updated": issue.updated,
        "custom_fields": issue.custom_fields,
    }


@mcp.tool()
def jira_search(
    jql: str,
    max_results: int = 50,
    expand_beyond_defaults: bool = False,
) -> dict:
    """Search Jira issues using JQL.

    If ``JIRA_DEFAULT_PROJECTS`` is configured and the JQL has no project
    clause, the default projects are automatically prepended. Pass
    ``expand_beyond_defaults=True`` to skip this injection.

    If ``JIRA_ALLOWED_PROJECTS`` is configured, the query must reference at
    least one allowed project or a ``ScopeViolationError`` is returned.

    Args:
        jql: JQL query string (e.g. ``issuetype = Story AND status = 'In Progress'``).
        max_results: Number of results to return (default 50; hard cap from config).
        expand_beyond_defaults: If True, skip default project scope injection.

    Returns:
        Dict with ``issues`` list and ``meta`` context.
    """
    try:
        config = AtlassianConfig.from_env()
        ctx = RequestContext.new()

        effective_max = enforce_result_cap(max_results, config.max_results_hard_cap)

        effective_jql = jql
        if not expand_beyond_defaults:
            effective_jql = inject_default_project_scope(jql, config.jira_default_projects)

        enforce_project_scope(effective_jql, config.jira_allowed_projects)

        client = JiraClient.from_config(config, ctx)
        issues = client.search(effective_jql, max_results=effective_max)

        return {
            "issues": [_issue_to_dict(i) for i in issues],
            "count": len(issues),
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

        result = _issue_to_dict(issue)
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
