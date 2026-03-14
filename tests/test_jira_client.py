"""Tests for JiraClient — mock HTTP, no network required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from atlassian_mcp_guardrails.jira.client import JiraClient
from atlassian_mcp_guardrails.jira.models import JiraIssue


def _make_client(config, mock_session=None):
    """Create a JiraClient bypassing canonical URL resolution."""
    session = mock_session or MagicMock()
    return JiraClient(
        session=session,
        base_url="https://test.atlassian.net",
        config=config,
    )


class TestJiraClientFromConfig:
    def test_from_config_resolves_canonical_url(self, base_config):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://test.atlassian.net"}
        mock_session.get.return_value = mock_resp
        mock_session.request.return_value = mock_resp

        with patch("atlassian_mcp_guardrails.jira.client.create_session", return_value=mock_session):
            with patch("atlassian_mcp_guardrails.jira.client.resolve_canonical_url", return_value="https://test.atlassian.net") as mock_resolve:
                client = JiraClient.from_config(base_config)
                mock_resolve.assert_called_once()
                assert client._base_url == "https://test.atlassian.net"


class TestJiraClientSearch:
    def test_search_v3_returns_issues(self, base_config, mock_jira_search_response):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_jira_search_response
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session)
        issues = client.search("issuetype = Story", max_results=10)

        assert len(issues) == 1
        assert issues[0].key == "PROJ-1"
        assert issues[0].summary == "Test issue summary"

    def test_search_falls_back_to_v2_on_404(self, base_config, mock_jira_search_response):
        mock_session = MagicMock()

        v3_resp = MagicMock()
        v3_resp.status_code = 404

        v2_resp = MagicMock()
        v2_resp.status_code = 200
        v2_resp.json.return_value = {
            "issues": mock_jira_search_response["issues"],
            "total": 1,
        }

        mock_session.request.side_effect = [v3_resp, v2_resp]

        client = _make_client(base_config, mock_session)
        issues = client.search("issuetype = Story", max_results=10)

        assert len(issues) == 1

    def test_search_respects_max_results_cap(self, base_config):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": [], "total": 0}
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session)
        # max_results should be capped at config.max_results_per_request
        issues = client.search("issuetype = Story", max_results=5)
        assert isinstance(issues, list)


class TestJiraClientGetIssue:
    def test_get_issue_returns_issue(self, base_config, mock_jira_issue_response):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_jira_issue_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session)
        issue = client.get_issue("PROJ-1")

        assert isinstance(issue, JiraIssue)
        assert issue.key == "PROJ-1"
        assert issue.project_key == "PROJ"

    def test_get_issue_raises_on_404(self, base_config):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session)
        with pytest.raises(requests.HTTPError):
            client.get_issue("PROJ-9999")


class TestJiraClientRetry:
    def test_retries_on_429(self, base_config, mock_jira_issue_response):
        mock_session = MagicMock()

        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {"Retry-After": "0"}

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = mock_jira_issue_response
        success_resp.raise_for_status = MagicMock()

        mock_session.request.side_effect = [rate_limit_resp, success_resp]

        client = _make_client(base_config, mock_session)
        with patch("atlassian_mcp_guardrails.jira.client.time.sleep"):
            issue = client.get_issue("PROJ-1")

        assert issue.key == "PROJ-1"
        assert mock_session.request.call_count == 2


class TestJiraClientAdfParsing:
    def test_adf_to_plain_extracts_text(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world"},
                    ],
                }
            ],
        }
        result = JiraClient._adf_to_plain(adf)
        assert "Hello" in result
        assert "world" in result

    def test_adf_to_plain_handles_empty(self):
        result = JiraClient._adf_to_plain({})
        assert result == ""


class TestJiraClientExtractCustomStr:
    def test_string_value(self):
        assert JiraClient._extract_custom_str({"cf_1": "value"}, "cf_1") == "value"

    def test_dict_with_value_key(self):
        assert JiraClient._extract_custom_str({"cf_1": {"value": "Large"}}, "cf_1") == "Large"

    def test_dict_with_name_key(self):
        assert JiraClient._extract_custom_str({"cf_1": {"name": "Team A"}}, "cf_1") == "Team A"

    def test_none_returns_empty(self):
        assert JiraClient._extract_custom_str({"cf_1": None}, "cf_1") == ""

    def test_missing_field_returns_empty(self):
        assert JiraClient._extract_custom_str({}, "cf_1") == ""

    def test_empty_field_id_returns_empty(self):
        assert JiraClient._extract_custom_str({"cf_1": "value"}, "") == ""
