"""Unit tests for pipeline/deep_retriever/traversal.py."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "pipeline"))

import pytest
from unittest.mock import MagicMock

from deep_retriever.traversal import JiraTraversalEngine
from deep_retriever.config import TraversalConfig


def _mock_issue(key: str, parent_key: str = "") -> MagicMock:
    issue = MagicMock()
    issue.key = key
    issue.parent_key = parent_key
    issue.summary = f"Summary of {key}"
    issue.status = "In Progress"
    issue.issue_type = "Story"
    issue.priority = "Medium"
    issue.url = f"https://jira.example.com/browse/{key}"
    issue.acceptance_criteria = ""
    return issue


class TestFetchSubtasks:
    def _engine(self, config=None):
        client = MagicMock()
        visited: set[str] = {"ROOT-1"}
        return JiraTraversalEngine(client, config or TraversalConfig(), visited), client

    def test_fetches_unvisited_subtask(self):
        engine, client = self._engine()
        client.get_issue.return_value = _mock_issue("ROOT-2")

        stubs = [{"key": "ROOT-2"}]
        result = engine.fetch_subtasks(stubs)

        assert len(result) == 1
        assert result[0].key == "ROOT-2"
        assert "ROOT-2" in engine._visited

    def test_skips_already_visited_subtask(self):
        engine, client = self._engine()
        engine._visited.add("ROOT-2")

        stubs = [{"key": "ROOT-2"}]
        result = engine.fetch_subtasks(stubs)

        assert result == []
        client.get_issue.assert_not_called()

    def test_skips_empty_key(self):
        engine, client = self._engine()
        result = engine.fetch_subtasks([{"key": ""}, {"key": None}])
        assert result == []
        client.get_issue.assert_not_called()

    def test_handles_fetch_exception(self):
        engine, client = self._engine()
        client.get_issue.side_effect = Exception("Jira 500")

        result = engine.fetch_subtasks([{"key": "ROOT-3"}])
        assert result == []


class TestFetchLinkedIssues:
    def _engine(self, config=None):
        client = MagicMock()
        visited: set[str] = {"ROOT-1"}
        return JiraTraversalEngine(client, config or TraversalConfig.default(), visited), client

    def test_fetches_linked_issue(self):
        engine, client = self._engine()
        client.get_issue.return_value = _mock_issue("LINKED-1")

        linked = [{"key": "LINKED-1", "type": "relates to"}]
        result = engine.fetch_linked_issues(linked)

        assert len(result) == 1
        issue, link_type = result[0]
        assert issue.key == "LINKED-1"
        assert link_type == "relates to"

    def test_respects_max_linked_per_issue_cap(self):
        config = TraversalConfig(max_linked_per_issue=2)
        engine, client = self._engine(config)
        client.get_issue.side_effect = [
            _mock_issue(f"LINKED-{i}") for i in range(10)
        ]

        linked = [{"key": f"LINKED-{i}", "type": "relates to"} for i in range(10)]
        result = engine.fetch_linked_issues(linked)

        assert len(result) == 2

    def test_excludes_excluded_link_types(self):
        engine, client = self._engine()

        linked = [{"key": "DUPE-1", "type": "duplicates"}]
        result = engine.fetch_linked_issues(linked)

        assert result == []
        client.get_issue.assert_not_called()

    def test_skips_zero_max_linked(self):
        config = TraversalConfig(max_linked_per_issue=0)
        engine, client = self._engine(config)

        linked = [{"key": "LINKED-1", "type": "relates to"}]
        result = engine.fetch_linked_issues(linked)

        assert result == []
        client.get_issue.assert_not_called()

    def test_cycle_detection_prevents_refetch(self):
        engine, client = self._engine()
        engine._visited.add("LINKED-1")

        linked = [{"key": "LINKED-1", "type": "relates to"}]
        result = engine.fetch_linked_issues(linked)

        assert result == []
        client.get_issue.assert_not_called()


class TestFetchHierarchy:
    def _engine(self, config=None):
        client = MagicMock()
        visited: set[str] = {"CHILD-1"}
        return JiraTraversalEngine(client, config or TraversalConfig.default(), visited), client

    def test_fetches_direct_parent(self):
        engine, client = self._engine()
        parent = _mock_issue("PARENT-1", parent_key="")
        client.get_issue.return_value = parent

        result = engine.fetch_hierarchy("PARENT-1")

        assert len(result) == 1
        issue, role = result[0]
        assert issue.key == "PARENT-1"
        assert role == "parent"

    def test_fetches_grandparent(self):
        config = TraversalConfig(max_hierarchy_depth=2)
        engine, client = self._engine(config)

        parent = _mock_issue("PARENT-1", parent_key="GRANDPARENT-1")
        grandparent = _mock_issue("GRANDPARENT-1", parent_key="")
        client.get_issue.side_effect = [parent, grandparent]

        result = engine.fetch_hierarchy("PARENT-1")

        assert len(result) == 2
        assert result[0][1] == "parent"
        assert result[1][1] == "grandparent"

    def test_empty_parent_key_returns_empty(self):
        engine, client = self._engine()
        result = engine.fetch_hierarchy("")
        assert result == []
        client.get_issue.assert_not_called()

    def test_zero_depth_returns_empty(self):
        config = TraversalConfig(max_hierarchy_depth=0)
        engine, client = self._engine(config)
        result = engine.fetch_hierarchy("PARENT-1")
        assert result == []

    def test_cycle_detection_in_hierarchy(self):
        engine, client = self._engine()
        engine._visited.add("PARENT-1")

        result = engine.fetch_hierarchy("PARENT-1")
        assert result == []
        client.get_issue.assert_not_called()
