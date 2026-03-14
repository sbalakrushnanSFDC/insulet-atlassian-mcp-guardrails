"""Custom field discovery via the Jira REST API.

Enumerates all fields on the Jira instance and maps logical names
(e.g. ``tshirt_size``) to their ``customfield_XXXXX`` IDs.

The search patterns are generic and work across any Jira instance — they are
not tied to any specific program or project. Additional patterns can be added
by extending ``_SEARCH_PATTERNS``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Logical name → list of name substrings to match (case-insensitive)
_SEARCH_PATTERNS: dict[str, list[str]] = {
    "tshirt_size": ["t-shirt", "tee shirt", "t shirt", "story points", "size"],
    "start_date": ["start date", "planned start"],
    "end_date": ["end date", "planned end", "target end"],
    "acceptance_criteria": ["acceptance criteria", "acceptance_criteria"],
    "epic_link": ["epic link"],
    "sprint": ["sprint"],
    "story_points": ["story points", "story point estimate"],
}


@dataclass(slots=True)
class CustomFieldMap:
    """Maps logical field names to Jira ``customfield_XXXXX`` IDs.

    All fields default to empty string (not discovered / not present).
    """

    tshirt_size: str = ""
    start_date: str = ""
    end_date: str = ""
    acceptance_criteria: str = ""
    epic_link: str = ""
    sprint: str = ""
    story_points: str = ""

    # Additional fields discovered but not in the known set
    extra: dict[str, str] = field(default_factory=dict, repr=False)

    # Raw field list from the API (for inspection)
    _all_fields: list[dict] = field(default_factory=list, repr=False)

    _KNOWN_ATTRS = (
        "tshirt_size", "start_date", "end_date",
        "acceptance_criteria", "epic_link", "sprint", "story_points",
    )

    def to_dict(self) -> dict[str, str]:
        """Return all known field mappings as a plain dict."""
        result = {attr: getattr(self, attr) for attr in self._KNOWN_ATTRS}
        result.update(self.extra)
        return result

    def as_id_map(self) -> dict[str, str]:
        """Return a mapping of logical_name -> field_id for use in JiraClient."""
        return {k: v for k, v in self.to_dict().items() if v}


def discover_custom_fields(client: "JiraClient") -> CustomFieldMap:  # type: ignore[name-defined]
    """Call ``GET /rest/api/3/field`` and map known logical names to field IDs.

    Args:
        client: An authenticated ``JiraClient`` instance.

    Returns:
        A ``CustomFieldMap`` with discovered field IDs populated.
        Fields not found on this instance remain as empty strings.
    """
    from atlassian_mcp_guardrails.jira.client import JiraClient  # local import to avoid circular

    all_fields: list[dict] = client.get_fields()
    cfm = CustomFieldMap(_all_fields=all_fields)

    custom_only = [f for f in all_fields if f.get("custom", False)]
    logger.info(
        "Field discovery: %d total fields, %d custom fields on this instance",
        len(all_fields), len(custom_only),
    )

    for logical_name, patterns in _SEARCH_PATTERNS.items():
        _match_field(cfm, logical_name, custom_only, patterns)

    logger.info("Discovered custom field map: %s", cfm.to_dict())
    return cfm


def _match_field(
    cfm: CustomFieldMap,
    logical_name: str,
    fields: list[dict],
    patterns: list[str],
) -> None:
    """Find the first custom field whose name matches any of the search patterns."""
    for f in fields:
        name_lower = (f.get("name") or "").lower().strip()
        field_id = f.get("id", "")
        for pat in patterns:
            if re.search(re.escape(pat), name_lower, re.IGNORECASE):
                if hasattr(cfm, logical_name):
                    setattr(cfm, logical_name, field_id)
                else:
                    cfm.extra[logical_name] = field_id
                logger.debug(
                    "Mapped %s -> %s (field name: %r)",
                    logical_name, field_id, f.get("name"),
                )
                return
