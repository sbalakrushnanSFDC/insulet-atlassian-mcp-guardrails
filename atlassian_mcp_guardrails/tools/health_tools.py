"""Health check MCP tool: atlassian_health_check."""

from __future__ import annotations

import logging
import time

from atlassian_mcp_guardrails.server import mcp
from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.context import RequestContext
from atlassian_mcp_guardrails.jira.client import JiraClient
from atlassian_mcp_guardrails.confluence.client import ConfluenceClient

logger = logging.getLogger(__name__)


@mcp.tool()
def atlassian_health_check() -> dict:
    """Check connectivity to Jira and Confluence.

    Verifies:
    - Configuration is valid (required env vars present)
    - Jira API is reachable and credentials are accepted
    - Confluence API is reachable and credentials are accepted
    - Canonical URL resolution (shows configured vs resolved URLs)

    No database check is performed — this server has no database dependency.

    Returns:
        Dict with ``ok`` (bool), per-subsystem status, and canonical URLs.
    """
    ctx = RequestContext.new()
    result: dict = {
        "ok": False,
        "config": {"ok": False},
        "jira": {"ok": False},
        "confluence": {"ok": False},
        "meta": {},
    }

    # --- Config check ---
    try:
        config = AtlassianConfig.from_env()
        result["config"] = {
            "ok": True,
            "jira_base_url": config.jira_base_url,
            "confluence_base_url": config.confluence_base_url,
            "jira_default_projects": config.jira_default_projects,
            "confluence_default_spaces": config.confluence_default_spaces,
            "jira_allowed_projects": config.jira_allowed_projects,
            "confluence_allowed_spaces": config.confluence_allowed_spaces,
            "max_results_per_request": config.max_results_per_request,
            "max_results_hard_cap": config.max_results_hard_cap,
            "max_api_calls_per_request": config.max_api_calls_per_request,
        }
    except Exception as exc:
        result["config"] = {"ok": False, "error": str(exc)}
        result["meta"] = ctx.to_dict()
        return result

    # --- Jira check ---
    t0 = time.monotonic()
    try:
        jira_client = JiraClient.from_config(config, ctx)
        server_info = jira_client.server_info()
        latency_ms = int((time.monotonic() - t0) * 1000)
        result["jira"] = {
            "ok": True,
            "canonical_url": jira_client._base_url,
            "configured_url": config.jira_base_url,
            "url_resolved": jira_client._base_url != config.jira_base_url,
            "server_title": server_info.get("serverTitle", ""),
            "version": server_info.get("version", ""),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        result["jira"] = {
            "ok": False,
            "error": str(exc),
            "latency_ms": latency_ms,
        }
        logger.error("Jira health check failed: %s", exc)

    # --- Confluence check ---
    t0 = time.monotonic()
    try:
        conf_client = ConfluenceClient.from_config(config, ctx)
        user_info = conf_client.current_user()
        latency_ms = int((time.monotonic() - t0) * 1000)
        result["confluence"] = {
            "ok": True,
            "canonical_url": conf_client._base,
            "configured_url": config.confluence_wiki_url,
            "url_resolved": conf_client._base != config.confluence_wiki_url,
            "is_cloud": conf_client.is_cloud,
            "user": user_info.get("displayName", user_info.get("accountId", "")),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        result["confluence"] = {
            "ok": False,
            "error": str(exc),
            "latency_ms": latency_ms,
        }
        logger.error("Confluence health check failed: %s", exc)

    result["ok"] = result["jira"]["ok"] and result["confluence"]["ok"]
    result["meta"] = ctx.to_dict()
    return result
