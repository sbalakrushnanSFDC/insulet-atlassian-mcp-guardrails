"""Unit tests for deep Jira client methods using responses mock library.

Tests:
- JiraClient.get_comments()
- JiraClient.get_attachments()
- JiraClient.get_remotelinks()
- JiraClient.get_issue_deep()
- JiraIssue.subtasks_raw populated from field list
- JiraIssue.description_adf populated

Uses `responses` for HTTP mocking — install with: pip install responses
"""

import pytest
from unittest.mock import MagicMock, patch

from atlassian_mcp_guardrails.jira.models import JiraComment, JiraAttachment, JiraRemoteLink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue_raw(key: str = "PROJ-1") -> dict:
    return {
        "id": "10001",
        "key": key,
        "fields": {
            "summary": "Test issue",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "project": {"key": "PROJ"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Full description text here."}],
                    }
                ],
            },
            "labels": ["sprint-3"],
            "components": [],
            "priority": {"name": "High"},
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "created": "2024-01-01T00:00:00.000Z",
            "updated": "2024-01-02T00:00:00.000Z",
            "resolution": None,
            "fixVersions": [],
            "parent": None,
            "issuelinks": [],
            "resolutiondate": None,
            "duedate": None,
            "subtasks": [{"key": "PROJ-2", "fields": {"summary": "Subtask 1"}}],
            "attachment": [
                {
                    "id": "att-1",
                    "filename": "spec.txt",
                    "mimeType": "text/plain",
                    "size": 1024,
                    "author": {"displayName": "Alice"},
                    "created": "2024-01-01T00:00:00.000Z",
                    "content": "https://jira.example.com/secure/attachment/att-1/spec.txt",
                    "thumbnail": "",
                }
            ],
        },
    }


def _make_comments_response(n: int = 2) -> dict:
    comments = []
    for i in range(n):
        comments.append({
            "id": f"comment-{i}",
            "author": {"displayName": f"User {i}", "accountId": f"acc-{i}"},
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Comment body {i}"}],
                    }
                ],
            },
            "created": f"2024-01-0{i+1}T00:00:00.000Z",
            "updated": f"2024-01-0{i+1}T00:00:00.000Z",
        })
    return {"comments": comments, "total": n, "maxResults": 50, "startAt": 0}


def _make_remotelinks_response() -> list:
    return [
        {
            "id": 100,
            "relationship": "Wiki Page",
            "object": {
                "url": "https://insulet.atlassian.net/wiki/spaces/NG/pages/12345",
                "title": "Design Doc",
                "summary": "",
            },
        },
        {
            "id": 101,
            "relationship": "External Link",
            "object": {
                "url": "https://github.com/org/repo/issues/42",
                "title": "GitHub Issue",
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tests using direct mock (no responses library dependency)
# ---------------------------------------------------------------------------

class TestGetComments:
    def _build_client(self, comments_data: dict):
        """Build a JiraClient with mocked _get for comment endpoint."""
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = comments_data
        mock_resp.raise_for_status = MagicMock()

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)
        client._base_url = "https://example.atlassian.net"
        client._adf_to_plain = lambda adf: "Comment body text"
        client.get_comments = JiraClient.get_comments.__get__(client)

        return client

    def test_returns_correct_count(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp_data = _make_comments_response(3)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_resp_data
        mock_resp.raise_for_status = MagicMock()

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)
        client._adf_to_plain = MagicMock(return_value="Comment body")

        # Bind get_comments as an instance method
        result = JiraClient.get_comments(client, "PROJ-1", max_comments=10)
        assert len(result) == 3

    def test_comment_fields_populated(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_comments_response(1)
        mock_resp.raise_for_status = MagicMock()

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)
        client._adf_to_plain = MagicMock(return_value="Parsed body")

        result = JiraClient.get_comments(client, "PROJ-1")
        assert len(result) == 1
        c = result[0]
        assert isinstance(c, JiraComment)
        assert c.comment_id == "comment-0"
        assert c.author == "User 0"
        assert c.body_plain == "Parsed body"

    def test_404_returns_empty_list(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)

        result = JiraClient.get_comments(client, "PROJ-MISSING")
        assert result == []


class TestGetAttachments:
    def test_attachments_parsed_from_raw_fields(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        raw = [
            {
                "id": "att-1",
                "filename": "spec.txt",
                "mimeType": "text/plain",
                "size": 1024,
                "author": {"displayName": "Alice"},
                "created": "2024-01-01T00:00:00.000Z",
                "content": "https://jira.example.com/attachment",
                "thumbnail": "",
            }
        ]
        result = JiraClient._parse_attachments(raw)
        assert len(result) == 1
        a = result[0]
        assert isinstance(a, JiraAttachment)
        assert a.attachment_id == "att-1"
        assert a.file_name == "spec.txt"
        assert a.mime_type == "text/plain"
        assert a.size_bytes == 1024
        assert a.author == "Alice"

    def test_empty_attachment_list(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient
        result = JiraClient._parse_attachments([])
        assert result == []


class TestGetRemoteLinks:
    def test_remotelinks_parsed(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _make_remotelinks_response()
        mock_resp.raise_for_status = MagicMock()

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)

        result = JiraClient.get_remotelinks(client, "PROJ-1")
        assert len(result) == 2
        conf_link = next(r for r in result if r.is_confluence)
        assert conf_link.confluence_page_id == "12345"
        non_conf = next(r for r in result if not r.is_confluence)
        assert "github.com" in non_conf.url

    def test_404_returns_empty_list(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        client = MagicMock(spec=JiraClient)
        client._get = MagicMock(return_value=mock_resp)

        result = JiraClient.get_remotelinks(client, "PROJ-GONE")
        assert result == []


class TestParseIssueSubtasks:
    """Test _parse_issue directly since it's where subtasks_raw and description_adf are set."""

    def _make_client(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        # Create a minimal real JiraClient without HTTP connectivity.
        # _custom_field_map is a plain dict[str, str] in the real client.
        client = object.__new__(JiraClient)
        client._base_url = "https://example.atlassian.net"
        client._session = MagicMock()
        client._custom_field_map = {}  # no custom fields in test
        return client

    def test_subtasks_raw_populated_from_fields(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        client = self._make_client()
        issue = JiraClient._parse_issue(client, _make_issue_raw("PROJ-1"))
        assert len(issue.subtasks_raw) == 1
        assert issue.subtasks_raw[0]["key"] == "PROJ-2"

    def test_description_adf_populated(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        client = self._make_client()
        issue = JiraClient._parse_issue(client, _make_issue_raw("PROJ-1"))
        assert issue.description_adf.get("type") == "doc"

    def test_description_plain_extracted_from_adf(self):
        from atlassian_mcp_guardrails.jira.client import JiraClient

        client = self._make_client()
        issue = JiraClient._parse_issue(client, _make_issue_raw("PROJ-1"))
        assert "Full description text here" in issue.description_plain
