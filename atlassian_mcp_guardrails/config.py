"""Configuration for Atlassian MCP Guardrails.

All configuration is loaded from environment variables via ``from_env()``.
No project-specific defaults exist in this module — all scope values are
caller-supplied through environment variables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_REQUIRED_ENV_VARS = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_TOKEN")


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _validate_url(url: str, label: str) -> str:
    """Validate that a URL has an http/https scheme and strip trailing slashes."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(
            f"{label} must start with http:// or https://, got: {url!r}"
        )
    if not parsed.netloc:
        raise ConfigError(f"{label} has no host: {url!r}")
    return url


def _parse_csv_list(value: str) -> list[str]:
    """Parse a comma-separated string into a stripped, non-empty list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def build_scoped_jql(
    projects: list[str] | None = None,
    issue_types: list[str] | None = None,
    labels: list[str] | None = None,
    fix_versions: list[str] | None = None,
    extra_clauses: list[str] | None = None,
    order_by: str = "key ASC",
) -> str:
    """Build a JQL query from caller-supplied components.

    All parameters are optional and caller-supplied — no hardcoded defaults.
    Returns a valid JQL string with an ORDER BY clause.

    Args:
        projects: Jira project keys to restrict the query to.
        issue_types: Issue type names (e.g. ``["Story", "Bug"]``).
        labels: Label values to filter by (OR-combined).
        fix_versions: Fix version names to filter by (OR-combined).
        extra_clauses: Additional raw JQL clauses (AND-combined).
        order_by: ORDER BY expression; defaults to ``"key ASC"``.

    Returns:
        A JQL string ready to send to the Jira search API.
    """
    clauses: list[str] = []

    if projects:
        proj_csv = ", ".join(f'"{p}"' for p in projects)
        clauses.append(f"project in ({proj_csv})")

    if issue_types:
        type_csv = ", ".join(f'"{t}"' for t in issue_types)
        clauses.append(f"issuetype in ({type_csv})")

    if labels and fix_versions:
        label_csv = ", ".join(f'"{lb}"' for lb in labels)
        fv_csv = ", ".join(f'"{fv}"' for fv in fix_versions)
        clauses.append(f'(labels in ({label_csv}) OR fixVersion in ({fv_csv}))')
    elif labels:
        label_csv = ", ".join(f'"{lb}"' for lb in labels)
        clauses.append(f"labels in ({label_csv})")
    elif fix_versions:
        fv_csv = ", ".join(f'"{fv}"' for fv in fix_versions)
        clauses.append(f"fixVersion in ({fv_csv})")

    if extra_clauses:
        clauses.extend(extra_clauses)

    if not clauses:
        return f"ORDER BY {order_by}"

    return " AND ".join(clauses) + f" ORDER BY {order_by}"


@dataclass(slots=True)
class AtlassianConfig:
    """All configuration for the Atlassian MCP Guardrails server.

    Instantiate only via ``from_env()`` to ensure all fields are populated
    from environment variables with proper validation.
    """

    # Required credentials
    jira_base_url: str
    jira_email: str
    jira_token: str

    # Confluence URL — set by from_env(); defaults to jira_base_url when unset
    confluence_base_url: str = ""

    # Default scope — auto-injected into queries that have no project/space clause
    jira_default_projects: list[str] = field(default_factory=list)
    confluence_default_spaces: list[str] = field(default_factory=list)

    # Priority scope (Phase 1) — project + label/fix-version filter; scope="priority"
    jira_priority_projects: list[str] = field(default_factory=list)
    jira_priority_labels: list[str] = field(default_factory=list)
    jira_priority_fix_versions: list[str] = field(default_factory=list)

    # Expanded scope (Phase 2) — broader label/fix-version set; scope="expanded"
    jira_expanded_labels: list[str] = field(default_factory=list)
    jira_expanded_fix_versions: list[str] = field(default_factory=list)

    # Confluence priority spaces — used when scope="priority" in confluence_search
    confluence_priority_spaces: list[str] = field(default_factory=list)

    # Allowlist — hard enforcement; empty list means advisory mode only
    jira_allowed_projects: list[str] = field(default_factory=list)
    confluence_allowed_spaces: list[str] = field(default_factory=list)

    # Rate limiting and result caps
    max_results_per_request: int = 50
    max_results_hard_cap: int = 200
    max_api_calls_per_request: int = 20
    request_delay_ms: int = 100
    http_timeout: int = 30

    # Text field caps — 0 means unlimited
    description_max_chars: int = 0
    ac_max_chars: int = 0

    # Logging
    log_level: str = "INFO"

    @property
    def confluence_wiki_url(self) -> str:
        """Return the Confluence wiki base URL (with /wiki suffix)."""
        base = self.confluence_base_url.rstrip("/")
        if not base.endswith("/wiki"):
            return f"{base}/wiki"
        return base

    @classmethod
    def from_env(cls) -> "AtlassianConfig":
        """Load configuration from environment variables.

        Required variables: JIRA_BASE_URL, JIRA_EMAIL, JIRA_TOKEN.
        All other variables are optional with safe defaults.

        Raises:
            ConfigError: If any required variable is missing or invalid.
        """
        # Validate required vars are present
        missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v, "").strip()]
        if missing:
            raise ConfigError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Copy .env.example to .env and fill in your Atlassian credentials."
            )

        jira_base_url = _validate_url(os.environ["JIRA_BASE_URL"], "JIRA_BASE_URL")
        jira_email = os.environ["JIRA_EMAIL"].strip()
        jira_token = os.environ["JIRA_TOKEN"].strip()

        # Confluence defaults to Jira base URL when not explicitly set
        raw_conf = os.environ.get("CONFLUENCE_BASE_URL", "").strip()
        confluence_base_url = _validate_url(raw_conf, "CONFLUENCE_BASE_URL") if raw_conf else jira_base_url

        # Default scope
        jira_default_projects = _parse_csv_list(os.environ.get("JIRA_DEFAULT_PROJECTS", ""))
        confluence_default_spaces = _parse_csv_list(os.environ.get("CONFLUENCE_DEFAULT_SPACES", ""))

        # Priority scope (Phase 1)
        jira_priority_projects = _parse_csv_list(os.environ.get("JIRA_PRIORITY_PROJECTS", ""))
        jira_priority_labels = _parse_csv_list(os.environ.get("JIRA_PRIORITY_LABELS", ""))
        jira_priority_fix_versions = _parse_csv_list(os.environ.get("JIRA_PRIORITY_FIX_VERSIONS", ""))

        # Expanded scope (Phase 2)
        jira_expanded_labels = _parse_csv_list(os.environ.get("JIRA_EXPANDED_LABELS", ""))
        jira_expanded_fix_versions = _parse_csv_list(os.environ.get("JIRA_EXPANDED_FIX_VERSIONS", ""))

        # Confluence priority spaces
        confluence_priority_spaces = _parse_csv_list(os.environ.get("CONFLUENCE_PRIORITY_SPACES", ""))

        # Allowlists
        jira_allowed_projects = _parse_csv_list(os.environ.get("JIRA_ALLOWED_PROJECTS", ""))
        confluence_allowed_spaces = _parse_csv_list(os.environ.get("CONFLUENCE_ALLOWED_SPACES", ""))

        # Rate limiting
        def _int(key: str, default: int) -> int:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                logger.warning("Invalid integer for %s=%r, using default %d", key, raw, default)
                return default

        max_results_per_request = _int("MAX_RESULTS_PER_REQUEST", 50)
        max_results_hard_cap = _int("MAX_RESULTS_HARD_CAP", 200)
        max_api_calls_per_request = _int("MAX_API_CALLS_PER_REQUEST", 20)
        request_delay_ms = _int("REQUEST_DELAY_MS", 100)
        http_timeout = _int("HTTP_TIMEOUT", 30)
        description_max_chars = _int("DESCRIPTION_MAX_CHARS", 0)
        ac_max_chars = _int("AC_MAX_CHARS", 0)

        log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            logger.warning("Unknown LOG_LEVEL=%r, defaulting to INFO", log_level)
            log_level = "INFO"

        return cls(
            jira_base_url=jira_base_url,
            jira_email=jira_email,
            jira_token=jira_token,
            confluence_base_url=confluence_base_url,
            jira_default_projects=jira_default_projects,
            confluence_default_spaces=confluence_default_spaces,
            jira_priority_projects=jira_priority_projects,
            jira_priority_labels=jira_priority_labels,
            jira_priority_fix_versions=jira_priority_fix_versions,
            jira_expanded_labels=jira_expanded_labels,
            jira_expanded_fix_versions=jira_expanded_fix_versions,
            confluence_priority_spaces=confluence_priority_spaces,
            jira_allowed_projects=jira_allowed_projects,
            confluence_allowed_spaces=confluence_allowed_spaces,
            max_results_per_request=max_results_per_request,
            max_results_hard_cap=max_results_hard_cap,
            max_api_calls_per_request=max_api_calls_per_request,
            request_delay_ms=request_delay_ms,
            http_timeout=http_timeout,
            description_max_chars=description_max_chars,
            ac_max_chars=ac_max_chars,
            log_level=log_level,
        )
