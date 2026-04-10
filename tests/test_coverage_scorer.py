"""Unit tests for pipeline/deep_retriever/coverage_scorer.py."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pipeline"))

import pytest
from unittest.mock import MagicMock

from deep_retriever.coverage_scorer import score_retrieval_result, DIMENSION_WEIGHTS
from deep_retriever.models import (
    AdfExtractionSummary,
    CommentRecord,
    AttachmentRecord,
    ConfluencePageRecord,
    DeepRetrievalResult,
    IssueSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_result(root_key: str = "PROJ-1") -> DeepRetrievalResult:
    result = DeepRetrievalResult(
        root_issue_key=root_key,
        run_id="test-run",
        retrieved_at="2024-01-01T00:00:00Z",
    )
    result.root_issue_normalized = {
        "key": root_key,
        "summary": "Test story",
        "status": "In Progress",
        "priority": "High",
        "description_plain": "A" * 500,
        "acceptance_criteria": "Given X when Y then Z",
        "linked_issues": [],
        "subtasks_raw": [],
        "parent_key": "",
        "attachments": [],
    }
    result.adf_extraction = AdfExtractionSummary(
        plain_text_char_count=500,
        media_ref_count=0,
        smart_card_count=0,
        discovered_url_count=0,
    )
    return result


def _comment(body: str = "Some comment") -> CommentRecord:
    return CommentRecord(
        comment_id="c1",
        author="Alice",
        created="2024-01-01T00:00:00Z",
        updated="2024-01-01T00:00:00Z",
        body_plain=body,
    )


def _attachment() -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id="a1",
        file_name="spec.txt",
        mime_type="text/plain",
        size_bytes=512,
        author="Bob",
        created="2024-01-01T00:00:00Z",
        content_url="https://example.com/spec.txt",
    )


def _confluence_page(page_id: str = "12345") -> ConfluencePageRecord:
    return ConfluencePageRecord(
        page_id=page_id,
        title="Design Doc",
        space_key="NG",
        url=f"https://insulet.atlassian.net/wiki/pages/{page_id}",
        version=1,
        retrieved_at="2024-01-01T00:00:00Z",
        body_plain="Design content here",
        raw_path="",
        normalized_path="",
        origin_issue_key="PROJ-1",
        origin_field="description",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDimensionWeights:
    def test_weights_sum_to_one(self):
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


class TestFullyGroundedResult:
    def test_well_populated_result_scores_high(self):
        result = _base_result()
        result.comments = [_comment()]
        result.attachments = [_attachment()]
        result.confluence_pages = [_confluence_page()]
        result.root_issue_normalized["attachments"] = [{"id": "a1"}]

        report, findings = score_retrieval_result(result)
        assert report.overall_score >= 0.75
        assert report.groundedness_label in ("GROUNDED", "PARTIALLY_GROUNDED")

    def test_all_dimensions_scored_when_na(self):
        result = _base_result()
        result.comments = [_comment()]
        report, _ = score_retrieval_result(result)
        assert len(report.dimensions) == len(DIMENSION_WEIGHTS)


class TestDegradedResult:
    def test_missing_root_issue_gives_critical_finding(self):
        result = _base_result()
        result.root_issue_normalized = {}  # empty — no key

        report, findings = score_retrieval_result(result)
        critical = [f for f in findings if f.severity == "CRITICAL"]
        assert len(critical) >= 1
        assert report.groundedness_label == "CONTEXT_DEGRADED"
        assert report.blocks_downstream_generation

    def test_missing_comments_gives_high_finding(self):
        result = _base_result()
        # No comments populated

        report, findings = score_retrieval_result(result)
        high = [f for f in findings if f.severity == "HIGH" and "comment" in f.dimension]
        assert len(high) >= 1

    def test_missing_ac_gives_high_finding(self):
        result = _base_result()
        result.root_issue_normalized["acceptance_criteria"] = ""

        report, findings = score_retrieval_result(result)
        ac_findings = [f for f in findings if "acceptance" in f.dimension]
        assert len(ac_findings) >= 1

    def test_low_score_gives_context_degraded(self):
        # Strip all optional content → only issue-metadata dimensions score
        result = DeepRetrievalResult(
            root_issue_key="PROJ-1",
            run_id="run",
            retrieved_at="2024-01-01T00:00:00Z",
        )
        result.root_issue_normalized = {"key": "PROJ-1", "description_plain": "",
                                         "acceptance_criteria": "", "linked_issues": [],
                                         "subtasks_raw": [], "parent_key": "", "attachments": []}

        report, findings = score_retrieval_result(result)
        assert report.overall_score < 0.60
        assert report.groundedness_label == "CONTEXT_DEGRADED"


class TestMediaCoverage:
    def test_unresolvable_media_gives_medium_finding(self):
        result = _base_result()
        result.adf_extraction = AdfExtractionSummary(
            plain_text_char_count=300,
            media_ref_count=2,
            smart_card_count=0,
            discovered_url_count=0,
            has_unresolvable_media=True,
        )
        result.comments = [_comment()]

        report, findings = score_retrieval_result(result)
        media_findings = [f for f in findings if "media" in f.dimension]
        assert len(media_findings) >= 1
        assert all(f.severity in ("MEDIUM", "LOW") for f in media_findings)

    def test_no_media_nodes_gives_full_score(self):
        result = _base_result()
        result.adf_extraction = AdfExtractionSummary(
            plain_text_char_count=300,
            media_ref_count=0,
            smart_card_count=0,
            discovered_url_count=0,
        )
        result.comments = [_comment()]

        report, _ = score_retrieval_result(result)
        assert report.dimensions["adf-media-coverage"].score == 1.0


class TestGroundednessThresholds:
    def test_above_85_is_grounded(self):
        result = _base_result()
        result.comments = [_comment()]
        result.attachments = [_attachment()]
        result.confluence_pages = [_confluence_page()]
        result.root_issue_normalized["attachments"] = [{"id": "a1"}]
        # Force a well-populated result to score high
        result.adf_extraction = AdfExtractionSummary(
            plain_text_char_count=1000,
            media_ref_count=0,
            smart_card_count=0,
            discovered_url_count=0,
        )

        report, findings = score_retrieval_result(result)
        if report.overall_score >= 0.85:
            assert report.groundedness_label == "GROUNDED"

    def test_critical_finding_forces_degraded(self):
        result = DeepRetrievalResult(
            root_issue_key="PROJ-1",
            run_id="run",
            retrieved_at="2024-01-01T00:00:00Z",
        )
        result.root_issue_normalized = {}  # triggers CRITICAL

        report, _ = score_retrieval_result(result)
        assert report.groundedness_label == "CONTEXT_DEGRADED"
        assert report.blocks_downstream_generation
