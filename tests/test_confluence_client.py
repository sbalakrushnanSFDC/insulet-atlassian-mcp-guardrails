"""Tests for ConfluenceClient — mock HTTP, no network required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from atlassian_mcp_guardrails.confluence.client import ConfluenceClient, is_cloud_instance
from atlassian_mcp_guardrails.confluence.models import ConfluencePage


def _make_client(config, wiki_url="https://test.atlassian.net/wiki", mock_session=None):
    """Create a ConfluenceClient bypassing canonical URL resolution."""
    session = mock_session or MagicMock()
    return ConfluenceClient(
        session=session,
        wiki_base_url=wiki_url,
        config=config,
    )


class TestIsCloudInstance:
    def test_atlassian_net_is_cloud(self):
        assert is_cloud_instance("https://company.atlassian.net") is True

    def test_atlassian_net_wiki_is_cloud(self):
        assert is_cloud_instance("https://company.atlassian.net/wiki") is True

    def test_on_prem_is_not_cloud(self):
        assert is_cloud_instance("https://jira.company.com") is False

    def test_case_insensitive(self):
        assert is_cloud_instance("https://COMPANY.ATLASSIAN.NET") is True


class TestConfluenceClientFromConfig:
    def test_from_config_resolves_canonical_wiki_url(self, base_config):
        mock_session = MagicMock()

        with patch("atlassian_mcp_guardrails.confluence.client.create_session", return_value=mock_session):
            with patch(
                "atlassian_mcp_guardrails.confluence.client.resolve_canonical_wiki_url",
                return_value="https://test.atlassian.net/wiki",
            ) as mock_resolve:
                client = ConfluenceClient.from_config(base_config)
                mock_resolve.assert_called_once()
                assert client._base == "https://test.atlassian.net/wiki"


class TestConfluenceClientGetPage:
    def test_get_page_v1_returns_page(self, base_config, mock_confluence_page_response):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_confluence_page_response
        mock_resp.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_resp

        # Use a non-cloud URL to force v1 path
        client = _make_client(base_config, wiki_url="https://confluence.company.com/wiki", mock_session=mock_session)
        page = client.get_page("12345678")

        assert isinstance(page, ConfluencePage)
        assert page.page_id == "12345678"
        assert page.title == "Test Page"
        assert page.space_key == "SPACE1"

    def test_get_page_cloud_tries_v2_then_v1(self, base_config, mock_confluence_page_response):
        mock_session = MagicMock()

        v2_resp = MagicMock()
        v2_resp.status_code = 404  # v2 fails

        v1_resp = MagicMock()
        v1_resp.status_code = 200
        v1_resp.json.return_value = mock_confluence_page_response
        v1_resp.raise_for_status = MagicMock()

        mock_session.request.side_effect = [v2_resp, v1_resp]

        client = _make_client(base_config, wiki_url="https://test.atlassian.net/wiki", mock_session=mock_session)
        page = client.get_page("12345678")

        assert page.title == "Test Page"
        assert mock_session.request.call_count == 2

    def test_get_page_raises_on_404_v1(self, base_config):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, wiki_url="https://confluence.company.com/wiki", mock_session=mock_session)
        with pytest.raises(requests.HTTPError):
            client.get_page("99999999")


class TestConfluenceClientSearchCql:
    def test_search_returns_pages(self, base_config, mock_confluence_search_response):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_confluence_search_response
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session=mock_session)
        pages = client.search_cql("text ~ 'auth'", limit=10)

        assert len(pages) == 1
        assert pages[0].title == "Test Page"

    def test_search_returns_empty_on_non_200(self, base_config):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_session.request.return_value = mock_resp

        client = _make_client(base_config, mock_session=mock_session)
        pages = client.search_cql("text ~ 'auth'", limit=10)

        assert pages == []


class TestConfluenceClientRetry:
    def test_retries_on_429(self, base_config, mock_confluence_page_response):
        mock_session = MagicMock()

        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {"Retry-After": "0"}

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = mock_confluence_page_response
        success_resp.raise_for_status = MagicMock()

        mock_session.request.side_effect = [rate_limit_resp, success_resp]

        client = _make_client(base_config, wiki_url="https://confluence.company.com/wiki", mock_session=mock_session)
        with patch("atlassian_mcp_guardrails.confluence.client.time.sleep"):
            page = client.get_page("12345678")

        assert page.title == "Test Page"
        assert mock_session.request.call_count == 2


class TestConfluenceClientBodyParsing:
    def test_strip_html_removes_tags(self):
        from atlassian_mcp_guardrails.confluence.client import _strip_html
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_html_handles_empty(self):
        from atlassian_mcp_guardrails.confluence.client import _strip_html
        assert _strip_html("") == ""
