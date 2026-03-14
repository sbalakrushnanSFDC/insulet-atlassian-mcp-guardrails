"""Tests for AtlassianConfig and build_scoped_jql."""

from __future__ import annotations

import os
import pytest

from atlassian_mcp_guardrails.config import (
    AtlassianConfig,
    ConfigError,
    build_scoped_jql,
    _parse_csv_list,
    _validate_url,
)


class TestValidateUrl:
    def test_valid_https(self):
        assert _validate_url("https://test.atlassian.net", "X") == "https://test.atlassian.net"

    def test_strips_trailing_slash(self):
        assert _validate_url("https://test.atlassian.net/", "X") == "https://test.atlassian.net"

    def test_strips_whitespace(self):
        assert _validate_url("  https://test.atlassian.net  ", "X") == "https://test.atlassian.net"

    def test_valid_http(self):
        assert _validate_url("http://on-prem.company.com", "X") == "http://on-prem.company.com"

    def test_invalid_scheme_raises(self):
        with pytest.raises(ConfigError, match="http"):
            _validate_url("ftp://test.atlassian.net", "X")

    def test_no_scheme_raises(self):
        with pytest.raises(ConfigError):
            _validate_url("test.atlassian.net", "X")


class TestParseCsvList:
    def test_empty_string(self):
        assert _parse_csv_list("") == []

    def test_single_value(self):
        assert _parse_csv_list("PROJ1") == ["PROJ1"]

    def test_multiple_values(self):
        assert _parse_csv_list("PROJ1,PROJ2,PROJ3") == ["PROJ1", "PROJ2", "PROJ3"]

    def test_strips_spaces(self):
        assert _parse_csv_list("PROJ1, PROJ2 , PROJ3") == ["PROJ1", "PROJ2", "PROJ3"]

    def test_filters_empty_entries(self):
        assert _parse_csv_list("PROJ1,,PROJ2") == ["PROJ1", "PROJ2"]


class TestAtlassianConfigFromEnv:
    def test_happy_path(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)

        config = AtlassianConfig.from_env()

        assert config.jira_base_url == "https://test.atlassian.net"
        assert config.jira_email == "user@example.com"
        assert config.jira_token == "mytoken"
        assert config.confluence_base_url == "https://test.atlassian.net"

    def test_missing_jira_base_url_raises(self, monkeypatch):
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        with pytest.raises(ConfigError, match="JIRA_BASE_URL"):
            AtlassianConfig.from_env()

    def test_missing_jira_email_raises(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        with pytest.raises(ConfigError, match="JIRA_EMAIL"):
            AtlassianConfig.from_env()

    def test_missing_jira_token_raises(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        with pytest.raises(ConfigError, match="JIRA_TOKEN"):
            AtlassianConfig.from_env()

    def test_explicit_confluence_url(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://other.atlassian.net")

        config = AtlassianConfig.from_env()
        assert config.confluence_base_url == "https://other.atlassian.net"

    def test_default_scope_parsed(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        monkeypatch.setenv("JIRA_DEFAULT_PROJECTS", "PROJ1,PROJ2")
        monkeypatch.setenv("CONFLUENCE_DEFAULT_SPACES", "SPACE1,DOCS")
        monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)

        config = AtlassianConfig.from_env()
        assert config.jira_default_projects == ["PROJ1", "PROJ2"]
        assert config.confluence_default_spaces == ["SPACE1", "DOCS"]

    def test_allowlists_parsed(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        monkeypatch.setenv("JIRA_ALLOWED_PROJECTS", "PROJ1")
        monkeypatch.setenv("CONFLUENCE_ALLOWED_SPACES", "SPACE1")
        monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)

        config = AtlassianConfig.from_env()
        assert config.jira_allowed_projects == ["PROJ1"]
        assert config.confluence_allowed_spaces == ["SPACE1"]

    def test_integer_overrides(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        monkeypatch.setenv("MAX_RESULTS_PER_REQUEST", "25")
        monkeypatch.setenv("MAX_RESULTS_HARD_CAP", "100")
        monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)

        config = AtlassianConfig.from_env()
        assert config.max_results_per_request == 25
        assert config.max_results_hard_cap == 100

    def test_safe_defaults_when_optional_vars_absent(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://test.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "mytoken")
        for var in [
            "CONFLUENCE_BASE_URL", "JIRA_DEFAULT_PROJECTS", "CONFLUENCE_DEFAULT_SPACES",
            "JIRA_ALLOWED_PROJECTS", "CONFLUENCE_ALLOWED_SPACES",
            "MAX_RESULTS_PER_REQUEST", "MAX_RESULTS_HARD_CAP",
            "MAX_API_CALLS_PER_REQUEST", "REQUEST_DELAY_MS", "HTTP_TIMEOUT",
        ]:
            monkeypatch.delenv(var, raising=False)

        config = AtlassianConfig.from_env()
        assert config.jira_default_projects == []
        assert config.jira_allowed_projects == []
        assert config.max_results_per_request == 50
        assert config.max_results_hard_cap == 200
        assert config.max_api_calls_per_request == 20


class TestConfluenceWikiUrl:
    def test_appends_wiki(self):
        config = AtlassianConfig(
            jira_base_url="https://test.atlassian.net",
            jira_email="x",
            jira_token="y",
            confluence_base_url="https://test.atlassian.net",
        )
        assert config.confluence_wiki_url == "https://test.atlassian.net/wiki"

    def test_does_not_double_append(self):
        config = AtlassianConfig(
            jira_base_url="https://test.atlassian.net",
            jira_email="x",
            jira_token="y",
            confluence_base_url="https://test.atlassian.net/wiki",
        )
        assert config.confluence_wiki_url == "https://test.atlassian.net/wiki"


class TestBuildScopedJql:
    def test_empty_returns_order_by(self):
        jql = build_scoped_jql()
        assert jql == "ORDER BY key ASC"

    def test_projects_only(self):
        jql = build_scoped_jql(projects=["PROJ1", "PROJ2"])
        assert 'project in ("PROJ1", "PROJ2")' in jql
        assert "ORDER BY key ASC" in jql

    def test_issue_types(self):
        jql = build_scoped_jql(issue_types=["Story", "Bug"])
        assert 'issuetype in ("Story", "Bug")' in jql

    def test_labels_and_fix_versions_combined(self):
        jql = build_scoped_jql(labels=["LBL1"], fix_versions=["v1.0"])
        assert "labels in" in jql
        assert "fixVersion in" in jql
        assert " OR " in jql

    def test_labels_only(self):
        jql = build_scoped_jql(labels=["LBL1"])
        assert "labels in" in jql
        assert "fixVersion" not in jql

    def test_custom_order_by(self):
        jql = build_scoped_jql(projects=["P"], order_by="updated DESC")
        assert "ORDER BY updated DESC" in jql

    def test_extra_clauses(self):
        jql = build_scoped_jql(extra_clauses=["status = 'In Progress'"])
        assert "status = 'In Progress'" in jql

    def test_all_params(self):
        jql = build_scoped_jql(
            projects=["PROJ"],
            issue_types=["Story"],
            labels=["LBL"],
            fix_versions=["v1"],
            extra_clauses=["assignee is not EMPTY"],
        )
        assert "project in" in jql
        assert "issuetype in" in jql
        assert "labels in" in jql
        assert "fixVersion in" in jql
        assert "assignee is not EMPTY" in jql
