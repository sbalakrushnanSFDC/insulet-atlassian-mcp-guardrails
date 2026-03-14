"""Shared test fixtures — no database, no network required."""

from __future__ import annotations

import pytest

from atlassian_mcp_guardrails.config import AtlassianConfig


@pytest.fixture
def base_config() -> AtlassianConfig:
    """Minimal valid AtlassianConfig for unit tests."""
    return AtlassianConfig(
        jira_base_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_token="test-token-abc123",
        confluence_base_url="https://test.atlassian.net",
    )


@pytest.fixture
def scoped_config() -> AtlassianConfig:
    """Config with default scope and allowlists set."""
    return AtlassianConfig(
        jira_base_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_token="test-token-abc123",
        confluence_base_url="https://test.atlassian.net",
        jira_default_projects=["PROJ1", "PROJ2"],
        confluence_default_spaces=["SPACE1", "DOCS"],
        jira_allowed_projects=["PROJ1", "PROJ2"],
        confluence_allowed_spaces=["SPACE1", "DOCS"],
    )


@pytest.fixture
def mock_jira_issue_response() -> dict:
    """Minimal Jira REST API issue response."""
    return {
        "id": "10001",
        "key": "PROJ-1",
        "fields": {
            "summary": "Test issue summary",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "project": {"key": "PROJ"},
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Test description"}]}]},
            "labels": ["label1"],
            "components": [{"name": "Backend"}],
            "priority": {"name": "Medium"},
            "assignee": {"displayName": "Jane Doe"},
            "reporter": {"displayName": "John Smith"},
            "created": "2026-01-01T00:00:00.000Z",
            "updated": "2026-01-02T00:00:00.000Z",
            "resolution": None,
            "fixVersions": [{"name": "v1.0"}],
            "parent": None,
            "issuelinks": [],
            "resolutiondate": None,
            "duedate": None,
        },
    }


@pytest.fixture
def mock_jira_search_response(mock_jira_issue_response) -> dict:
    """Minimal Jira v3 search response."""
    return {
        "issues": [mock_jira_issue_response],
        "total": 1,
    }


@pytest.fixture
def mock_confluence_page_response() -> dict:
    """Minimal Confluence v1 page response."""
    return {
        "id": "12345678",
        "title": "Test Page",
        "status": "current",
        "space": {"key": "SPACE1"},
        "version": {"number": 3, "when": "2026-01-01T00:00:00.000Z", "by": {"displayName": "Jane Doe"}},
        "body": {"storage": {"value": "<p>Test body content</p>"}},
        "metadata": {"labels": {"results": [{"name": "docs"}]}},
        "_links": {"webui": "/wiki/spaces/SPACE1/pages/12345678"},
    }


@pytest.fixture
def mock_confluence_search_response(mock_confluence_page_response) -> dict:
    """Minimal Confluence CQL search response."""
    return {
        "results": [mock_confluence_page_response],
        "totalSize": 1,
        "size": 1,
    }
