"""Unit tests for atlassian_mcp_guardrails.jira.adf_extractor."""

import pytest
from atlassian_mcp_guardrails.jira.adf_extractor import (
    AdfExtractionResult,
    extract_adf_nodes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _doc(*content: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(content)}


def _para(*inline: dict) -> dict:
    return {"type": "paragraph", "content": list(inline)}


def _text(t: str, marks: list[dict] | None = None) -> dict:
    node: dict = {"type": "text", "text": t}
    if marks:
        node["marks"] = marks
    return node


def _link_mark(href: str) -> dict:
    return {"type": "link", "attrs": {"href": href}}


def _media_single(media_id: str, url: str = "", alt: str = "") -> dict:
    attrs: dict = {"id": media_id, "type": "file", "collection": "MediaServicesSample"}
    if url:
        attrs["url"] = url
    if alt:
        attrs["alt"] = alt
    return {
        "type": "mediaSingle",
        "content": [
            {"type": "media", "attrs": attrs}
        ],
    }


def _inline_card(url: str) -> dict:
    return {"type": "inlineCard", "attrs": {"url": url}}


def _mention(user_id: str, name: str) -> dict:
    return {"type": "mention", "attrs": {"id": user_id, "text": name}}


# ---------------------------------------------------------------------------
# Tests — plain text extraction
# ---------------------------------------------------------------------------

def test_empty_adf_returns_empty_result():
    result = extract_adf_nodes(None)
    assert result.plain_text == ""
    assert result.media_refs == []
    assert result.smart_card_refs == []


def test_simple_text_extracted():
    doc = _doc(_para(_text("Hello world")))
    result = extract_adf_nodes(doc)
    assert "Hello world" in result.plain_text


def test_multiple_paragraphs_joined():
    doc = _doc(
        _para(_text("First paragraph")),
        _para(_text("Second paragraph")),
    )
    result = extract_adf_nodes(doc)
    assert "First paragraph" in result.plain_text
    assert "Second paragraph" in result.plain_text


def test_link_mark_extracts_url():
    doc = _doc(_para(_text("click here", [_link_mark("https://example.com/page")])))
    result = extract_adf_nodes(doc)
    assert len(result.discovered_urls) == 1
    assert result.discovered_urls[0].url == "https://example.com/page"
    assert result.discovered_urls[0].link_text == "click here"
    assert not result.discovered_urls[0].is_confluence


def test_confluence_link_mark_detected():
    url = "https://insulet.atlassian.net/wiki/spaces/NG/pages/12345678"
    doc = _doc(_para(_text("design doc", [_link_mark(url)])))
    result = extract_adf_nodes(doc)
    assert len(result.discovered_urls) == 1
    assert result.discovered_urls[0].is_confluence
    assert result.discovered_urls[0].confluence_page_id == "12345678"
    assert "12345678" in result.confluence_page_ids


# ---------------------------------------------------------------------------
# Tests — media detection
# ---------------------------------------------------------------------------

def test_media_single_detected_as_unresolvable():
    doc = _doc(_media_single("abc-123", url=""))
    result = extract_adf_nodes(doc)
    assert len(result.media_refs) == 1
    assert result.media_refs[0].media_id == "abc-123"
    assert not result.media_refs[0].resolvable
    assert result.has_unresolvable_media


def test_media_with_url_is_resolvable():
    doc = _doc(_media_single("xyz-456", url="https://cdn.example.com/image.png"))
    result = extract_adf_nodes(doc)
    assert len(result.media_refs) == 1
    assert result.media_refs[0].resolvable
    assert not result.has_unresolvable_media


def test_multiple_media_refs_counted():
    doc = _doc(
        _media_single("m1"),
        _media_single("m2"),
        _media_single("m3"),
    )
    result = extract_adf_nodes(doc)
    assert len(result.media_refs) == 3


# ---------------------------------------------------------------------------
# Tests — smart card (inlineCard / blockCard)
# ---------------------------------------------------------------------------

def test_inline_card_with_confluence_url():
    url = "https://insulet.atlassian.net/wiki/spaces/NG/pages/999000"
    doc = _doc(_para(_inline_card(url)))
    result = extract_adf_nodes(doc)
    assert len(result.smart_card_refs) == 1
    assert result.smart_card_refs[0].is_confluence
    assert result.smart_card_refs[0].confluence_page_id == "999000"
    assert "999000" in result.confluence_page_ids


def test_inline_card_non_confluence_url():
    doc = _doc(_para(_inline_card("https://github.com/org/repo")))
    result = extract_adf_nodes(doc)
    assert len(result.smart_card_refs) == 1
    assert not result.smart_card_refs[0].is_confluence
    assert result.smart_card_refs[0].confluence_page_id == ""


# ---------------------------------------------------------------------------
# Tests — mention
# ---------------------------------------------------------------------------

def test_mention_extracted():
    doc = _doc(_para(_mention("user-42", "@alice")))
    result = extract_adf_nodes(doc)
    assert len(result.mention_refs) == 1
    assert result.mention_refs[0].user_id == "user-42"
    assert result.mention_refs[0].display_name == "@alice"


# ---------------------------------------------------------------------------
# Tests — code block
# ---------------------------------------------------------------------------

def test_code_block_extracted():
    doc = _doc({
        "type": "codeBlock",
        "attrs": {"language": "apex"},
        "content": [{"type": "text", "text": "System.debug('hello');"}],
    })
    result = extract_adf_nodes(doc)
    assert len(result.code_blocks) == 1
    assert "System.debug" in result.code_blocks[0]
    assert "```" in result.plain_text


# ---------------------------------------------------------------------------
# Tests — deduplication of confluence_page_ids
# ---------------------------------------------------------------------------

def test_duplicate_confluence_ids_deduplicated():
    url = "https://insulet.atlassian.net/wiki/spaces/NG/pages/11111"
    doc = _doc(
        _para(_text("see", [_link_mark(url)])),
        _para(_inline_card(url)),
    )
    result = extract_adf_nodes(doc)
    assert result.confluence_page_ids.count("11111") == 1


# ---------------------------------------------------------------------------
# Tests — node_type_counts
# ---------------------------------------------------------------------------

def test_node_type_counts_populated():
    doc = _doc(
        _para(_text("hello")),
        _para(_text("world")),
    )
    result = extract_adf_nodes(doc)
    assert result.node_type_counts.get("text", 0) == 2
    assert result.node_type_counts.get("paragraph", 0) == 2
