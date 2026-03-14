"""Tests for MCP tools — mock HTTP, no network, no database."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from atlassian_mcp_guardrails.config import AtlassianConfig
from atlassian_mcp_guardrails.jira.models import JiraIssue
from atlassian_mcp_guardrails.confluence.models import ConfluencePage
from atlassian_mcp_guardrails.guardrails import ScopeViolationError


def _make_issue(**kwargs) -> JiraIssue:
    defaults = dict(
        key="PROJ-1",
        issue_id="10001",
        summary="Test issue",
        status="In Progress",
        issue_type="Story",
        project_key="PROJ",
        description_plain="A" * 600,  # longer than 500-char truncation limit
    )
    defaults.update(kwargs)
    return JiraIssue(**defaults)


def _make_page(**kwargs) -> ConfluencePage:
    defaults = dict(
        page_id="12345678",
        title="Test Page",
        space_key="SPACE1",
        status="current",
        body_plain="B" * 3000,  # longer than 2000-char truncation limit
    )
    defaults.update(kwargs)
    return ConfluencePage(**defaults)


class TestJiraSearchTool:
    def test_returns_issues_list(self, base_config):
        mock_client = MagicMock()
        mock_client.search.return_value = [_make_issue()]

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                result = jira_search("issuetype = Story")

        assert "issues" in result
        assert len(result["issues"]) == 1
        assert result["issues"][0]["key"] == "PROJ-1"

    def test_description_truncated_to_500(self, base_config):
        mock_client = MagicMock()
        mock_client.search.return_value = [_make_issue()]

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                result = jira_search("issuetype = Story")

        assert len(result["issues"][0]["description_plain"]) <= 500

    def test_default_scope_injected(self, scoped_config):
        mock_client = MagicMock()
        mock_client.search.return_value = []

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=scoped_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                result = jira_search("issuetype = Story", scope="default")

        # The executed JQL should have the default projects injected
        assert "PROJ1" in result["jql_executed"] or "PROJ2" in result["jql_executed"]

    def test_scope_violation_returns_error(self, scoped_config):
        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=scoped_config):
            from atlassian_mcp_guardrails.tools.jira_tools import jira_search
            # JQL already has a project clause that's not in the allowlist
            result = jira_search('project = "NOTALLOWED" AND issuetype = Story')

        assert "error" in result
        assert "ScopeViolationError" in result.get("error_type", "")

    def test_expand_beyond_defaults_skips_injection(self, scoped_config):
        mock_client = MagicMock()
        mock_client.search.return_value = []

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=scoped_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                # With expand_beyond_defaults, the injection is skipped
                # but the allowlist still applies — this JQL has no project clause
                # so it will be rejected by the allowlist
                result = jira_search("issuetype = Story", expand_beyond_defaults=True)

        # Should fail allowlist check since no project clause and allowlist is set
        assert "error" in result

    def test_result_capped_at_hard_cap(self, base_config):
        mock_client = MagicMock()
        mock_client.search.return_value = []

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                result = jira_search("issuetype = Story", max_results=9999)

        # Client should have been called with at most hard_cap
        call_kwargs = mock_client.search.call_args
        assert call_kwargs is not None
        effective_max = call_kwargs[1].get("max_results") or call_kwargs[0][1]
        assert effective_max <= base_config.max_results_hard_cap

    def test_returns_error_on_exception(self, base_config):
        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", side_effect=Exception("connection failed")):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_search
                result = jira_search("issuetype = Story")

        assert "error" in result
        assert "connection failed" in result["error"]


class TestJiraGetIssueTool:
    def test_returns_issue_fields(self, base_config):
        mock_client = MagicMock()
        mock_client.get_issue.return_value = _make_issue()

        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_get_issue
                result = jira_get_issue("PROJ-1")

        assert result["key"] == "PROJ-1"
        assert result["summary"] == "Test issue"
        assert "meta" in result

    def test_returns_error_on_exception(self, base_config):
        with patch("atlassian_mcp_guardrails.tools.jira_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.jira_tools.JiraClient.from_config", side_effect=Exception("not found")):
                from atlassian_mcp_guardrails.tools.jira_tools import jira_get_issue
                result = jira_get_issue("PROJ-9999")

        assert "error" in result


class TestConfluenceSearchTool:
    def test_returns_pages_list(self, base_config):
        mock_client = MagicMock()
        mock_client.search_cql.return_value = [_make_page()]

        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_search
                result = confluence_search("text ~ 'auth'")

        assert "pages" in result
        assert len(result["pages"]) == 1
        assert result["pages"][0]["page_id"] == "12345678"

    def test_body_not_included_by_default(self, base_config):
        mock_client = MagicMock()
        mock_client.search_cql.return_value = [_make_page()]

        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_search
                result = confluence_search("text ~ 'auth'", include_body=False)

        assert "body_plain" not in result["pages"][0]

    def test_default_space_injected(self, scoped_config):
        mock_client = MagicMock()
        mock_client.search_cql.return_value = []

        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=scoped_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_search
                result = confluence_search("text ~ 'auth'")

        assert "SPACE1" in result["cql_executed"] or "DOCS" in result["cql_executed"]


class TestConfluenceGetPageTool:
    def test_returns_page_fields(self, base_config):
        mock_client = MagicMock()
        mock_client.get_page.return_value = _make_page()

        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_get_page
                result = confluence_get_page("12345678")

        assert result["page_id"] == "12345678"
        assert result["title"] == "Test Page"
        assert "meta" in result

    def test_body_truncated_to_2000(self, base_config):
        mock_client = MagicMock()
        mock_client.get_page.return_value = _make_page()

        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", return_value=mock_client):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_get_page
                result = confluence_get_page("12345678")

        assert len(result["body_plain"]) <= 2000

    def test_returns_error_on_exception(self, base_config):
        with patch("atlassian_mcp_guardrails.tools.confluence_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.confluence_tools.ConfluenceClient.from_config", side_effect=Exception("forbidden")):
                from atlassian_mcp_guardrails.tools.confluence_tools import confluence_get_page
                result = confluence_get_page("12345678")

        assert "error" in result


class TestHealthCheckTool:
    def test_returns_ok_when_both_pass(self, base_config):
        mock_jira = MagicMock()
        mock_jira.server_info.return_value = {"serverTitle": "Test Jira", "version": "9.0"}
        mock_jira._base_url = "https://test.atlassian.net"

        mock_conf = MagicMock()
        mock_conf.current_user.return_value = {"displayName": "Test User"}
        mock_conf._base = "https://test.atlassian.net/wiki"
        mock_conf.is_cloud = True

        with patch("atlassian_mcp_guardrails.tools.health_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.health_tools.JiraClient.from_config", return_value=mock_jira):
                with patch("atlassian_mcp_guardrails.tools.health_tools.ConfluenceClient.from_config", return_value=mock_conf):
                    from atlassian_mcp_guardrails.tools.health_tools import atlassian_health_check
                    result = atlassian_health_check()

        assert result["ok"] is True
        assert result["jira"]["ok"] is True
        assert result["confluence"]["ok"] is True

    def test_returns_not_ok_when_jira_fails(self, base_config):
        with patch("atlassian_mcp_guardrails.tools.health_tools.AtlassianConfig.from_env", return_value=base_config):
            with patch("atlassian_mcp_guardrails.tools.health_tools.JiraClient.from_config", side_effect=Exception("unreachable")):
                with patch("atlassian_mcp_guardrails.tools.health_tools.ConfluenceClient.from_config", side_effect=Exception("unreachable")):
                    from atlassian_mcp_guardrails.tools.health_tools import atlassian_health_check
                    result = atlassian_health_check()

        assert result["ok"] is False
        assert result["jira"]["ok"] is False

    def test_config_error_returns_early(self, monkeypatch):
        from atlassian_mcp_guardrails.config import ConfigError
        with patch("atlassian_mcp_guardrails.tools.health_tools.AtlassianConfig.from_env", side_effect=ConfigError("missing vars")):
            from atlassian_mcp_guardrails.tools.health_tools import atlassian_health_check
            result = atlassian_health_check()

        assert result["ok"] is False
        assert result["config"]["ok"] is False
        assert "missing vars" in result["config"]["error"]
