"""Tests for guardrails enforcement and scope injection."""

from __future__ import annotations

import pytest

from atlassian_mcp_guardrails.guardrails import (
    ApiLimitExceededError,
    ScopeViolationError,
    enforce_project_scope,
    enforce_result_cap,
    enforce_space_scope,
    inject_default_project_scope,
    inject_default_space_scope,
)


class TestEnforceProjectScope:
    def test_empty_allowlist_is_noop(self):
        # Should not raise regardless of JQL content
        enforce_project_scope("issuetype = Story", [])
        enforce_project_scope("project = ANYTHING", [])

    def test_jql_with_allowed_project_passes(self):
        enforce_project_scope('project in ("PROJ1")', ["PROJ1", "PROJ2"])

    def test_jql_with_allowed_project_case_insensitive(self):
        enforce_project_scope('project in ("proj1")', ["PROJ1"])

    def test_jql_without_project_clause_raises(self):
        with pytest.raises(ScopeViolationError, match="no project filter"):
            enforce_project_scope("issuetype = Story", ["PROJ1"])

    def test_jql_with_disallowed_project_raises(self):
        with pytest.raises(ScopeViolationError, match="allowlist"):
            enforce_project_scope('project in ("OTHER")', ["PROJ1", "PROJ2"])

    def test_project_equals_syntax(self):
        enforce_project_scope('project = "PROJ1"', ["PROJ1"])

    def test_project_not_in_syntax_raises_when_no_allowed_match(self):
        with pytest.raises(ScopeViolationError):
            enforce_project_scope('project not in ("PROJ1")', ["PROJ2"])


class TestEnforceSpaceScope:
    def test_empty_allowlist_is_noop(self):
        enforce_space_scope("text ~ 'auth'", [])

    def test_cql_with_allowed_space_passes(self):
        enforce_space_scope('space = "SPACE1"', ["SPACE1", "DOCS"])

    def test_cql_without_space_clause_raises(self):
        with pytest.raises(ScopeViolationError, match="no space filter"):
            enforce_space_scope("text ~ 'auth'", ["SPACE1"])

    def test_cql_with_disallowed_space_raises(self):
        with pytest.raises(ScopeViolationError, match="allowlist"):
            enforce_space_scope('space = "OTHER"', ["SPACE1"])

    def test_space_in_syntax(self):
        enforce_space_scope('space in ("SPACE1", "DOCS")', ["SPACE1", "DOCS"])


class TestInjectDefaultProjectScope:
    def test_injects_when_no_project_clause(self):
        result = inject_default_project_scope("issuetype = Story", ["PROJ1", "PROJ2"])
        assert result.startswith('project in ("PROJ1", "PROJ2")')
        assert "issuetype = Story" in result

    def test_skips_when_project_clause_present(self):
        jql = 'project = "PROJ1" AND issuetype = Story'
        result = inject_default_project_scope(jql, ["PROJ2"])
        assert result == jql

    def test_skips_when_defaults_empty(self):
        jql = "issuetype = Story"
        result = inject_default_project_scope(jql, [])
        assert result == jql

    def test_project_in_syntax_not_injected(self):
        jql = 'project in ("PROJ1") AND status = Open'
        result = inject_default_project_scope(jql, ["PROJ2"])
        assert result == jql

    def test_single_default_project(self):
        result = inject_default_project_scope("status = Open", ["MYPROJ"])
        assert 'project in ("MYPROJ")' in result


class TestInjectDefaultSpaceScope:
    def test_injects_when_no_space_clause(self):
        result = inject_default_space_scope("text ~ 'auth'", ["SPACE1", "DOCS"])
        assert result.startswith('space in ("SPACE1", "DOCS")')
        assert "text ~ 'auth'" in result

    def test_skips_when_space_clause_present(self):
        cql = 'space = "SPACE1" AND text ~ "auth"'
        result = inject_default_space_scope(cql, ["DOCS"])
        assert result == cql

    def test_skips_when_defaults_empty(self):
        cql = "text ~ 'auth'"
        result = inject_default_space_scope(cql, [])
        assert result == cql

    def test_space_in_syntax_not_injected(self):
        cql = 'space in ("SPACE1") AND type = page'
        result = inject_default_space_scope(cql, ["DOCS"])
        assert result == cql


class TestEnforceResultCap:
    def test_within_cap_unchanged(self):
        assert enforce_result_cap(50, 200) == 50

    def test_at_cap_unchanged(self):
        assert enforce_result_cap(200, 200) == 200

    def test_exceeds_cap_returns_cap(self):
        assert enforce_result_cap(500, 200) == 200

    def test_zero_requested(self):
        assert enforce_result_cap(0, 200) == 0


class TestApiLimitExceededError:
    def test_is_exception(self):
        exc = ApiLimitExceededError("too many calls")
        assert isinstance(exc, Exception)
        assert "too many calls" in str(exc)
