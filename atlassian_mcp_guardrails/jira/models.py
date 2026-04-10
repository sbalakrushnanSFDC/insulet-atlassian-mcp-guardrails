"""Jira data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JiraComment:
    """A single comment from the Jira issue activity log."""

    comment_id: str
    author: str
    author_account_id: str
    body_plain: str
    body_adf: dict = field(default_factory=dict)
    created: str = ""
    updated: str = ""


@dataclass
class JiraAttachment:
    """Metadata for a single Jira attachment."""

    attachment_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    author: str
    created: str
    content_url: str
    thumbnail_url: str = ""


@dataclass
class JiraRemoteLink:
    """A remote (web) link on a Jira issue."""

    remote_link_id: str
    url: str
    title: str
    relationship: str = ""
    is_confluence: bool = False
    confluence_page_id: str = ""


@dataclass(slots=True)
class JiraIssue:
    """Represents a single Jira issue as returned by the REST API."""

    key: str
    issue_id: str
    summary: str
    status: str
    issue_type: str
    project_key: str

    description_html: str = ""
    description_plain: str = ""
    description_adf: dict = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    priority: str = ""
    assignee: str = ""
    reporter: str = ""
    created: str = ""
    updated: str = ""
    resolution: str = ""
    fix_versions: list[str] = field(default_factory=list)
    url: str = ""
    raw: dict = field(default_factory=dict)

    acceptance_criteria: str = ""
    tshirt_size: str = ""
    start_date: str = ""
    due_date: str = ""
    end_date: str = ""
    resolved_date: str = ""
    parent_key: str = ""
    epic_link: str = ""
    linked_issues: list[dict] = field(default_factory=list)

    # Dynamically discovered custom fields (field_id -> value)
    custom_fields: dict[str, str] = field(default_factory=dict)

    # Deep retrieval fields — populated only by get_issue_deep() or explicit fetch calls
    subtasks_raw: list[dict] = field(default_factory=list)
    comments: list[JiraComment] = field(default_factory=list)
    attachments: list[JiraAttachment] = field(default_factory=list)
    remotelinks: list[JiraRemoteLink] = field(default_factory=list)
