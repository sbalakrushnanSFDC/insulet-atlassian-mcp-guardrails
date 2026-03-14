"""Atlassian authentication helpers.

Provides Basic auth header construction, session factory, and canonical URL
resolution for both Jira and Confluence. This module has no external
dependencies beyond ``requests`` — it does not import from any other internal
package.

Canonical URL resolution handles the common case where an organization uses a
custom domain (e.g. ``jira.company.com``) that proxies to an Atlassian Cloud
instance (``company.atlassian.net``). Calling ``resolve_canonical_url`` at
client initialization ensures all subsequent API calls go to the correct host,
preventing 403 Forbidden errors caused by proxy URL mismatches.
"""

from __future__ import annotations

import base64
import logging

import requests

logger = logging.getLogger(__name__)


def build_auth_header(email: str, token: str) -> dict[str, str]:
    """Return HTTP headers with Basic auth and JSON Accept.

    Args:
        email: Atlassian account email address.
        token: Atlassian API token (not password).

    Returns:
        Dict with ``Authorization`` and ``Accept`` headers.
    """
    encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Accept": "application/json",
    }


def create_session(email: str, token: str) -> requests.Session:
    """Return a ``requests.Session`` pre-configured with Atlassian auth headers.

    Args:
        email: Atlassian account email address.
        token: Atlassian API token.

    Returns:
        A ``requests.Session`` with ``Authorization`` and ``Accept`` headers set.
        Credentials are stored only in the session headers and are never logged.
    """
    session = requests.Session()
    session.headers.update(build_auth_header(email, token))
    return session


def resolve_canonical_url(
    base_url: str,
    session: requests.Session,
    timeout: int = 30,
) -> str:
    """Detect a custom-domain proxy and return the canonical Atlassian host.

    Calls ``GET /rest/api/3/serverInfo`` on the configured base URL. If the
    response contains a ``baseUrl`` that differs from the input and ends with
    ``.atlassian.net``, that canonical URL is returned instead.

    If the call fails (network error, timeout, non-200), the original
    ``base_url`` is returned unchanged with a warning logged.

    Args:
        base_url: The configured Jira base URL (may be a proxy/vanity domain).
        session: An authenticated ``requests.Session``.
        timeout: HTTP timeout in seconds.

    Returns:
        The canonical Atlassian host URL (no trailing slash, no ``/wiki``).
    """
    root = base_url.replace("/wiki", "").rstrip("/")
    url = f"{root}/rest/api/3/serverInfo"
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            canonical_base = data.get("baseUrl", "").rstrip("/")
            if canonical_base and ".atlassian.net" in canonical_base:
                if canonical_base != root:
                    logger.info(
                        "Canonical URL resolved: %s -> %s (update JIRA_BASE_URL in .env to silence this)",
                        root,
                        canonical_base,
                    )
                return canonical_base
        else:
            logger.warning(
                "serverInfo returned HTTP %d for %s; using configured URL as-is",
                resp.status_code,
                root,
            )
    except (requests.ConnectionError, requests.Timeout) as exc:
        logger.warning(
            "Could not reach %s for canonical URL resolution (%s); "
            "using configured URL. Check JIRA_BASE_URL in .env.",
            root,
            exc,
        )
    return root


def resolve_canonical_wiki_url(
    wiki_url: str,
    session: requests.Session,
    timeout: int = 30,
) -> str:
    """Like ``resolve_canonical_url`` but for Confluence (appends ``/wiki``).

    Args:
        wiki_url: The configured Confluence wiki URL (may or may not end in ``/wiki``).
        session: An authenticated ``requests.Session``.
        timeout: HTTP timeout in seconds.

    Returns:
        The canonical Confluence wiki URL ending in ``/wiki``.
    """
    root = wiki_url.replace("/wiki", "").rstrip("/")
    canonical_root = resolve_canonical_url(root, session, timeout)
    canonical_wiki = canonical_root.rstrip("/") + "/wiki"
    if canonical_wiki != wiki_url.rstrip("/"):
        logger.info("Canonical wiki URL: %s -> %s", wiki_url, canonical_wiki)
    return canonical_wiki
