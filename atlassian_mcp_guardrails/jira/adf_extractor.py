"""Atlassian Document Format (ADF) extractor.

Walks the full ADF node tree and extracts:
- Plain text (without truncation)
- Media/image references (mediaSingle, media, mediaGroup nodes)
- Inline smart cards (inlineCard, blockCard) with URLs
- External URLs from text marks (link marks)
- Confluence page references (inlineCard/blockCard with /wiki/ URLs)
- Mention nodes (user references)
- Code block content

Every non-text node that carries semantic content is preserved as a structured
reference rather than silently dropped. Unresolvable visual media (images) is
flagged so downstream agents know visual context exists but cannot be read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CONFLUENCE_URL_RE = re.compile(r"/wiki/", re.IGNORECASE)
_URL_MARK_TYPE = "link"
_EXTERNAL_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class MediaRef:
    """A reference to an embedded media object (image, file, video)."""

    node_type: str
    media_id: str = ""
    media_type: str = ""
    collection: str = ""
    file_name: str = ""
    mime_type: str = ""
    alt_text: str = ""
    caption: str = ""
    width: int = 0
    height: int = 0
    url: str = ""
    resolvable: bool = False


@dataclass
class SmartCardRef:
    """An inlineCard or blockCard smart link reference."""

    node_type: str
    url: str
    is_confluence: bool = False
    confluence_page_id: str = ""
    title: str = ""


@dataclass
class DiscoveredUrl:
    """A URL found in a link mark on a text node."""

    url: str
    link_text: str = ""
    is_confluence: bool = False
    confluence_page_id: str = ""


@dataclass
class MentionRef:
    """A @mention of a user."""

    user_id: str
    display_name: str = ""


@dataclass
class AdfExtractionResult:
    """Full extraction result from a single ADF document."""

    plain_text: str = ""
    media_refs: list[MediaRef] = field(default_factory=list)
    smart_card_refs: list[SmartCardRef] = field(default_factory=list)
    discovered_urls: list[DiscoveredUrl] = field(default_factory=list)
    confluence_page_ids: list[str] = field(default_factory=list)
    mention_refs: list[MentionRef] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    has_unresolvable_media: bool = False
    node_type_counts: dict[str, int] = field(default_factory=dict)


def _extract_confluence_page_id(url: str) -> str:
    """Extract numeric Confluence page ID from a URL. Returns '' if not found."""
    if not url or "/wiki/" not in url.lower():
        return ""
    m = re.search(r"/pages/(\d+)", url) or re.search(r"[?&]pageId=(\d+)", url)
    return m.group(1) if m else ""


def extract_adf_nodes(adf: dict[str, Any] | None) -> AdfExtractionResult:
    """Walk an ADF document tree and extract all structured content.

    Args:
        adf: The ADF document dict (the value of the Jira ``description`` field
             when the instance uses ADF, i.e. ``{"type": "doc", "content": [...]}``)
             or ``None`` if the field is empty.

    Returns:
        AdfExtractionResult with plain text, media refs, URLs, and gap flags.
    """
    result = AdfExtractionResult()
    if not adf or not isinstance(adf, dict):
        return result

    text_parts: list[str] = []
    _walk(adf, result, text_parts, caption_context="")
    result.plain_text = "\n".join(p for p in text_parts if p).strip()

    # Deduplicate confluence_page_ids preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for pid in result.confluence_page_ids:
        if pid and pid not in seen:
            seen.add(pid)
            deduped.append(pid)
    result.confluence_page_ids = deduped

    result.has_unresolvable_media = any(not ref.resolvable for ref in result.media_refs)
    return result


def _walk(
    node: Any,
    result: AdfExtractionResult,
    text_parts: list[str],
    caption_context: str,
) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, result, text_parts, caption_context)
        return

    if not isinstance(node, dict):
        return

    node_type = node.get("type", "")
    result.node_type_counts[node_type] = result.node_type_counts.get(node_type, 0) + 1

    if node_type == "text":
        _handle_text_node(node, result, text_parts)
        return

    if node_type in ("media", "mediaSingle", "mediaGroup"):
        _handle_media_node(node, result, caption_context)
        return

    if node_type in ("inlineCard", "blockCard"):
        _handle_smart_card(node, result)
        return

    if node_type == "mention":
        _handle_mention(node, result)
        return

    if node_type == "codeBlock":
        _handle_code_block(node, result, text_parts)
        return

    if node_type == "caption":
        caption_parts: list[str] = []
        for child in node.get("content", []):
            _walk(child, result, caption_parts, caption_context="")
        caption_context = " ".join(caption_parts).strip()
        text_parts.extend(caption_parts)
        return

    if node_type == "hardBreak":
        text_parts.append("\n")
        return

    if node_type in ("paragraph", "heading", "bulletList", "orderedList",
                     "listItem", "blockquote", "panel", "expand",
                     "nestedExpand", "table", "tableRow", "tableHeader",
                     "tableCell", "doc", "rule"):
        if node_type in ("heading", "paragraph"):
            text_parts.append("")
        for child in node.get("content", []):
            _walk(child, result, text_parts, caption_context)
        if node_type in ("heading", "paragraph", "listItem"):
            text_parts.append("")
        return

    # Unknown node types — still walk content to not lose nested text
    for child in node.get("content", []):
        _walk(child, result, text_parts, caption_context)


def _handle_text_node(
    node: dict,
    result: AdfExtractionResult,
    text_parts: list[str],
) -> None:
    text = node.get("text", "")
    text_parts.append(text)

    for mark in node.get("marks", []):
        mark_type = mark.get("type", "")
        if mark_type == _URL_MARK_TYPE:
            attrs = mark.get("attrs", {})
            url = attrs.get("href", "")
            if url and _EXTERNAL_URL_RE.match(url):
                is_conf = bool(_CONFLUENCE_URL_RE.search(url))
                page_id = _extract_confluence_page_id(url) if is_conf else ""
                du = DiscoveredUrl(
                    url=url,
                    link_text=text,
                    is_confluence=is_conf,
                    confluence_page_id=page_id,
                )
                result.discovered_urls.append(du)
                if is_conf and page_id:
                    result.confluence_page_ids.append(page_id)


def _handle_media_node(
    node: dict,
    result: AdfExtractionResult,
    caption_context: str,
) -> None:
    """Handle media, mediaSingle, and mediaGroup nodes."""
    node_type = node.get("type", "")

    if node_type in ("mediaSingle", "mediaGroup"):
        for child in node.get("content", []):
            child_type = child.get("type", "")
            if child_type == "media":
                _handle_single_media(child, result, node_type, caption_context)
            elif child_type == "caption":
                pass  # caption handled separately in _walk
        return

    if node_type == "media":
        _handle_single_media(node, result, "media", caption_context)


def _handle_single_media(
    node: dict,
    result: AdfExtractionResult,
    container_type: str,
    caption_context: str,
) -> None:
    attrs = node.get("attrs", {})
    media_type = attrs.get("type", "")
    media_id = attrs.get("id", "")
    collection = attrs.get("collection", "")
    url = attrs.get("url", "")
    file_name = attrs.get("__fileName", attrs.get("fileName", ""))
    mime_type = attrs.get("__fileMimeType", attrs.get("mimeType", ""))
    width = int(attrs.get("width", 0) or 0)
    height = int(attrs.get("height", 0) or 0)
    alt = attrs.get("alt", "")

    resolvable = bool(url)

    ref = MediaRef(
        node_type=container_type,
        media_id=media_id,
        media_type=media_type,
        collection=collection,
        file_name=file_name,
        mime_type=mime_type,
        alt_text=alt,
        caption=caption_context,
        width=width,
        height=height,
        url=url,
        resolvable=resolvable,
    )
    result.media_refs.append(ref)


def _handle_smart_card(node: dict, result: AdfExtractionResult) -> None:
    attrs = node.get("attrs", {})
    url = attrs.get("url", "")
    if not url:
        return
    is_conf = bool(_CONFLUENCE_URL_RE.search(url))
    page_id = _extract_confluence_page_id(url) if is_conf else ""
    sc = SmartCardRef(
        node_type=node.get("type", ""),
        url=url,
        is_confluence=is_conf,
        confluence_page_id=page_id,
    )
    result.smart_card_refs.append(sc)
    if is_conf and page_id:
        result.confluence_page_ids.append(page_id)


def _handle_mention(node: dict, result: AdfExtractionResult) -> None:
    attrs = node.get("attrs", {})
    user_id = attrs.get("id", "")
    display_name = attrs.get("text", attrs.get("displayName", ""))
    if user_id:
        result.mention_refs.append(MentionRef(user_id=user_id, display_name=display_name))


def _handle_code_block(
    node: dict,
    result: AdfExtractionResult,
    text_parts: list[str],
) -> None:
    code_parts: list[str] = []
    for child in node.get("content", []):
        if isinstance(child, dict) and child.get("type") == "text":
            code_parts.append(child.get("text", ""))
    code_text = "".join(code_parts)
    if code_text:
        result.code_blocks.append(code_text)
        text_parts.append(f"\n```\n{code_text}\n```\n")
