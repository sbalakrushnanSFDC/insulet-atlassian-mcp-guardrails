"""Confluence data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConfluencePage:
    """Represents a single Confluence page."""

    page_id: str
    title: str
    space_key: str
    status: str

    body_html: str = ""
    body_plain: str = ""
    version: int = 0
    last_modified: str = ""
    author: str = ""
    labels: list[str] = field(default_factory=list)
    parent_id: str = ""
    url: str = ""
    raw: dict = field(default_factory=dict)
