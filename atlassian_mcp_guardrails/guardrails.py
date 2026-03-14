"""Guardrail enforcement for the Atlassian MCP Guardrails server.

This module provides:
- Custom exception types for guardrail violations
- Scope allowlist enforcement (hard block for out-of-scope queries)
- Priority, expanded, and default scope injection (auto-prepend project/space/label filters)
- Result cap enforcement (prevent unbounded result sets)

Four-tier scope model (controlled by the ``scope`` parameter on search tools)
------------------------------------------------------------------------------
Tier 1 — Priority scope (``scope="priority"``, default):
    ``JIRA_PRIORITY_PROJECTS`` + ``JIRA_PRIORITY_LABELS`` / ``JIRA_PRIORITY_FIX_VERSIONS``
    Narrows to NextGen program work: project filter AND (labels OR fix versions).

Tier 2 — Expanded scope (``scope="expanded"``):
    Same projects with broader label/fix-version sets from Phase 2.

Tier 3 — Default scope (``scope="default"``):
    ``JIRA_DEFAULT_PROJECTS`` / ``CONFLUENCE_DEFAULT_SPACES``
    Project-only filter; same as the original behaviour.

Tier 4 — No injection (``scope="all"``):
    Raw JQL/CQL passed through unchanged.

Layer — Allowlist (hard enforcement, always applied):
    ``JIRA_ALLOWED_PROJECTS`` / ``CONFLUENCE_ALLOWED_SPACES``
    If non-empty, any query that does not reference an allowed project/space
    raises ``ScopeViolationError``.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class ReadOnlyViolationError(Exception):
    """Raised when a write operation (PUT/PATCH/DELETE) is attempted."""


class ScopeViolationError(Exception):
    """Raised when a query references a project or space outside the allowlist."""


class ApiLimitExceededError(Exception):
    """Raised when a tool invocation exceeds MAX_API_CALLS_PER_REQUEST."""


# ---------------------------------------------------------------------------
# JQL / CQL clause detection helpers
# ---------------------------------------------------------------------------

# Matches "project" as a JQL field operator — not inside a text search value.
# Handles: project = X, project in (...), project != X, project not in (...)
_JQL_PROJECT_RE = re.compile(
    r"\bproject\s*(=|!=|in\b|not\s+in\b)",
    re.IGNORECASE,
)

# Matches "space" as a CQL field operator.
# Handles: space = X, space in (...), space != X, space not in (...)
_CQL_SPACE_RE = re.compile(
    r"\bspace\s*(=|!=|in\b|not\s+in\b)",
    re.IGNORECASE,
)


def _has_project_clause(jql: str) -> bool:
    """Return True if the JQL already contains a project filter clause."""
    return bool(_JQL_PROJECT_RE.search(jql))


def _has_space_clause(cql: str) -> bool:
    """Return True if the CQL already contains a space filter clause."""
    return bool(_CQL_SPACE_RE.search(cql))


def _extract_project_keys_from_jql(jql: str) -> set[str]:
    """Extract quoted project key values from a JQL string (best-effort)."""
    return {m.strip('"').strip("'") for m in re.findall(r'["\']([A-Z][A-Z0-9_]+)["\']', jql)}


def _extract_space_keys_from_cql(cql: str) -> set[str]:
    """Extract quoted space key values from a CQL string (best-effort)."""
    return {m.strip('"').strip("'") for m in re.findall(r'["\']([A-Z][A-Z0-9_]+)["\']', cql)}


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


def enforce_project_scope(jql: str, allowed: list[str]) -> None:
    """Enforce that a JQL query references at least one allowed project.

    If ``allowed`` is empty, this function is a no-op (advisory mode).
    If ``allowed`` is non-empty and the JQL contains no project clause,
    or contains only projects not in the allowlist, ``ScopeViolationError``
    is raised.

    Args:
        jql: The JQL query string to validate.
        allowed: List of allowed project keys. Empty list = no enforcement.

    Raises:
        ScopeViolationError: When the query is out of scope.
    """
    if not allowed:
        return

    if not _has_project_clause(jql):
        raise ScopeViolationError(
            f"Query has no project filter and JIRA_ALLOWED_PROJECTS is set to "
            f"{allowed!r}. Add a project clause (e.g. project in ({', '.join(allowed[:2])}...)) "
            "or set JIRA_DEFAULT_PROJECTS to auto-inject a scope."
        )

    referenced = _extract_project_keys_from_jql(jql)
    allowed_set = {p.upper() for p in allowed}
    referenced_upper = {k.upper() for k in referenced}

    if referenced and not referenced_upper.intersection(allowed_set):
        raise ScopeViolationError(
            f"Query references project(s) {referenced!r} which are not in the "
            f"allowlist {allowed!r}. Update JIRA_ALLOWED_PROJECTS or adjust your query."
        )


def enforce_space_scope(cql: str, allowed: list[str]) -> None:
    """Enforce that a CQL query references at least one allowed Confluence space.

    If ``allowed`` is empty, this function is a no-op (advisory mode).

    Args:
        cql: The CQL query string to validate.
        allowed: List of allowed space keys. Empty list = no enforcement.

    Raises:
        ScopeViolationError: When the query is out of scope.
    """
    if not allowed:
        return

    if not _has_space_clause(cql):
        raise ScopeViolationError(
            f"Query has no space filter and CONFLUENCE_ALLOWED_SPACES is set to "
            f"{allowed!r}. Add a space clause (e.g. space in ({', '.join(allowed[:2])}...)) "
            "or set CONFLUENCE_DEFAULT_SPACES to auto-inject a scope."
        )

    referenced = _extract_space_keys_from_cql(cql)
    allowed_set = {s.upper() for s in allowed}
    referenced_upper = {k.upper() for k in referenced}

    if referenced and not referenced_upper.intersection(allowed_set):
        raise ScopeViolationError(
            f"Query references space(s) {referenced!r} which are not in the "
            f"allowlist {allowed!r}. Update CONFLUENCE_ALLOWED_SPACES or adjust your query."
        )


# ---------------------------------------------------------------------------
# Default scope injection
# ---------------------------------------------------------------------------


def inject_default_project_scope(jql: str, defaults: list[str]) -> str:
    """Prepend a project filter to JQL if no project clause is present.

    Skipped if ``defaults`` is empty or if ``jql`` already has a project clause.
    The injection is logged at DEBUG level.

    Args:
        jql: The caller-supplied JQL query.
        defaults: Default project keys from ``JIRA_DEFAULT_PROJECTS``.

    Returns:
        The (possibly modified) JQL string.
    """
    if not defaults or _has_project_clause(jql):
        return jql

    proj_csv = ", ".join(f'"{p}"' for p in defaults)
    scoped = f"project in ({proj_csv}) AND {jql}"
    logger.debug("Injecting default project scope: project in (%s)", proj_csv)
    return scoped


def inject_default_space_scope(cql: str, defaults: list[str]) -> str:
    """Prepend a space filter to CQL if no space clause is present.

    Skipped if ``defaults`` is empty or if ``cql`` already has a space clause.
    The injection is logged at DEBUG level.

    Args:
        cql: The caller-supplied CQL query.
        defaults: Default space keys from ``CONFLUENCE_DEFAULT_SPACES``.

    Returns:
        The (possibly modified) CQL string.
    """
    if not defaults or _has_space_clause(cql):
        return cql

    space_csv = ", ".join(f'"{s}"' for s in defaults)
    scoped = f"space in ({space_csv}) AND {cql}"
    logger.debug("Injecting default space scope: space in (%s)", space_csv)
    return scoped


# ---------------------------------------------------------------------------
# Priority scope injection (Phase 1 and Phase 2)
# ---------------------------------------------------------------------------


def _build_label_fixversion_clause(labels: list[str], fix_versions: list[str]) -> str | None:
    """Build a JQL clause combining labels and fix versions with OR."""
    if labels and fix_versions:
        l_csv = ", ".join(f'"{l}"' for l in labels)
        fv_csv = ", ".join(f'"{v}"' for v in fix_versions)
        return f'(labels in ({l_csv}) OR fixVersion in ({fv_csv}))'
    if labels:
        l_csv = ", ".join(f'"{l}"' for l in labels)
        return f"labels in ({l_csv})"
    if fix_versions:
        fv_csv = ", ".join(f'"{v}"' for v in fix_versions)
        return f"fixVersion in ({fv_csv})"
    return None


def inject_priority_jql(
    jql: str,
    priority_projects: list[str],
    labels: list[str],
    fix_versions: list[str],
) -> str:
    """Prepend Phase 1 priority scope: project + (labels OR fix_versions).

    Skipped if ``priority_projects`` is empty or the JQL already has a project clause.

    Args:
        jql: The caller-supplied JQL query.
        priority_projects: Project keys from ``JIRA_PRIORITY_PROJECTS``.
        labels: Label values from ``JIRA_PRIORITY_LABELS``.
        fix_versions: Fix version names from ``JIRA_PRIORITY_FIX_VERSIONS``.

    Returns:
        The (possibly modified) JQL string.
    """
    if not priority_projects or _has_project_clause(jql):
        return jql

    proj_csv = ", ".join(f'"{p}"' for p in priority_projects)
    clauses = [f"project in ({proj_csv})"]

    label_fv_clause = _build_label_fixversion_clause(labels, fix_versions)
    if label_fv_clause:
        clauses.append(label_fv_clause)

    scoped = " AND ".join(clauses) + f" AND {jql}"
    logger.debug("Injecting priority (Phase 1) scope: %s", " AND ".join(clauses))
    return scoped


def inject_expanded_jql(
    jql: str,
    priority_projects: list[str],
    expanded_labels: list[str],
    expanded_fix_versions: list[str],
) -> str:
    """Prepend Phase 2 expanded scope: same projects, broader label/fix-version set.

    Skipped if ``priority_projects`` is empty or the JQL already has a project clause.

    Args:
        jql: The caller-supplied JQL query.
        priority_projects: Project keys from ``JIRA_PRIORITY_PROJECTS``.
        expanded_labels: Broader label values from ``JIRA_EXPANDED_LABELS``.
        expanded_fix_versions: Broader fix versions from ``JIRA_EXPANDED_FIX_VERSIONS``.

    Returns:
        The (possibly modified) JQL string.
    """
    if not priority_projects or _has_project_clause(jql):
        return jql

    proj_csv = ", ".join(f'"{p}"' for p in priority_projects)
    clauses = [f"project in ({proj_csv})"]

    label_fv_clause = _build_label_fixversion_clause(expanded_labels, expanded_fix_versions)
    if label_fv_clause:
        clauses.append(label_fv_clause)

    scoped = " AND ".join(clauses) + f" AND {jql}"
    logger.debug("Injecting expanded (Phase 2) scope: %s", " AND ".join(clauses))
    return scoped


def inject_priority_space_scope(cql: str, priority_spaces: list[str]) -> str:
    """Prepend a priority space filter to CQL if no space clause is present.

    Skipped if ``priority_spaces`` is empty or the CQL already has a space clause.

    Args:
        cql: The caller-supplied CQL query.
        priority_spaces: Space keys from ``CONFLUENCE_PRIORITY_SPACES``.

    Returns:
        The (possibly modified) CQL string.
    """
    if not priority_spaces or _has_space_clause(cql):
        return cql

    space_csv = ", ".join(f'"{s}"' for s in priority_spaces)
    scoped = f"space in ({space_csv}) AND {cql}"
    logger.debug("Injecting priority space scope: space in (%s)", space_csv)
    return scoped


# ---------------------------------------------------------------------------
# Result cap enforcement
# ---------------------------------------------------------------------------


def enforce_result_cap(requested: int, hard_cap: int) -> int:
    """Return the effective result count, capped at ``hard_cap``.

    Logs a warning if the requested count exceeds the cap.

    Args:
        requested: The result count requested by the caller.
        hard_cap: The configured hard maximum (``MAX_RESULTS_HARD_CAP``).

    Returns:
        ``min(requested, hard_cap)``.
    """
    if requested > hard_cap:
        logger.warning(
            "Requested %d results exceeds hard cap of %d; capping at %d. "
            "Increase MAX_RESULTS_HARD_CAP in .env if needed.",
            requested,
            hard_cap,
            hard_cap,
        )
        return hard_cap
    return requested
