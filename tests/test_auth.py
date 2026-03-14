"""Tests for auth helpers."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from atlassian_mcp_guardrails.auth import (
    build_auth_header,
    create_session,
    resolve_canonical_url,
    resolve_canonical_wiki_url,
)


class TestBuildAuthHeader:
    def test_returns_authorization_and_accept(self):
        headers = build_auth_header("user@example.com", "mytoken")
        assert "Authorization" in headers
        assert "Accept" in headers
        assert headers["Accept"] == "application/json"

    def test_authorization_is_basic(self):
        headers = build_auth_header("user@example.com", "mytoken")
        assert headers["Authorization"].startswith("Basic ")

    def test_credentials_encoded_correctly(self):
        headers = build_auth_header("user@example.com", "mytoken")
        encoded = headers["Authorization"].replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user@example.com:mytoken"

    def test_token_not_in_plain_text(self):
        headers = build_auth_header("user@example.com", "supersecrettoken")
        assert "supersecrettoken" not in headers["Authorization"]


class TestCreateSession:
    def test_returns_session(self):
        session = create_session("user@example.com", "token")
        assert isinstance(session, requests.Session)

    def test_session_has_auth_header(self):
        session = create_session("user@example.com", "token")
        assert "Authorization" in session.headers
        assert session.headers["Authorization"].startswith("Basic ")


class TestResolveCanonicalUrl:
    def test_returns_canonical_when_different(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://company.atlassian.net"}
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_url("https://jira.company.com", mock_session)
        assert result == "https://company.atlassian.net"

    def test_returns_original_when_same(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://company.atlassian.net"}
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_url("https://company.atlassian.net", mock_session)
        assert result == "https://company.atlassian.net"

    def test_returns_original_on_non_200(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_url("https://jira.company.com", mock_session)
        assert result == "https://jira.company.com"

    def test_returns_original_on_network_error(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("unreachable")

        result = resolve_canonical_url("https://jira.company.com", mock_session)
        assert result == "https://jira.company.com"

    def test_strips_wiki_suffix_before_calling(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://company.atlassian.net"}
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_url("https://jira.company.com/wiki", mock_session)
        assert result == "https://company.atlassian.net"

    def test_ignores_non_atlassian_net_canonical(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://other.company.com"}
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_url("https://jira.company.com", mock_session)
        assert result == "https://jira.company.com"


class TestResolveCanonicalWikiUrl:
    def test_appends_wiki_to_canonical(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"baseUrl": "https://company.atlassian.net"}
        mock_session.get.return_value = mock_resp

        result = resolve_canonical_wiki_url("https://confluence.company.com/wiki", mock_session)
        assert result == "https://company.atlassian.net/wiki"

    def test_returns_original_wiki_on_failure(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("unreachable")

        result = resolve_canonical_wiki_url("https://confluence.company.com/wiki", mock_session)
        assert result == "https://confluence.company.com/wiki"
