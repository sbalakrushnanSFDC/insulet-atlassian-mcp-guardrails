"""Jira data models."""

from __future__ import annotations

from dataclasses import dataclass, field


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
