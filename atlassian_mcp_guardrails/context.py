"""Per-request context for tracking API call counts, timing, and errors."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RequestContext:
    """Lightweight per-request context — no database dependency.

    Tracks API call counts, elapsed time, warnings, and errors for a single
    tool invocation. Used to enforce ``MAX_API_CALLS_PER_REQUEST`` and to
    provide structured logging for each request.
    """

    request_id: str
    started_at: str
    _start_time: float

    items_fetched: int = 0
    api_calls_made: int = 0

    warnings: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls) -> "RequestContext":
        """Create a new RequestContext with a unique ID and current timestamp."""
        now = datetime.now(timezone.utc)
        request_id = now.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        return cls(
            request_id=request_id,
            started_at=now.isoformat(),
            _start_time=time.monotonic(),
        )

    @property
    def elapsed_ms(self) -> int:
        """Elapsed time since context creation, in milliseconds."""
        return int((time.monotonic() - self._start_time) * 1000)

    @property
    def status(self) -> str:
        """Overall status: SUCCESS, PARTIAL, or FAILED."""
        if self.errors and self.items_fetched == 0:
            return "FAILED"
        if self.errors or self.warnings:
            return "PARTIAL"
        return "SUCCESS"

    def increment_api_calls(self, max_calls: int) -> None:
        """Increment the API call counter.

        Args:
            max_calls: The configured maximum. Raises ``ApiLimitExceededError``
                if this call would exceed the limit.

        Raises:
            ApiLimitExceededError: When the call count would exceed ``max_calls``.
        """
        from atlassian_mcp_guardrails.guardrails import ApiLimitExceededError

        self.api_calls_made += 1
        if self.api_calls_made > max_calls:
            raise ApiLimitExceededError(
                f"API call limit exceeded: {self.api_calls_made} calls made, "
                f"limit is {max_calls}. Reduce max_results or increase "
                "MAX_API_CALLS_PER_REQUEST in your .env."
            )

    def add_warning(self, message: str) -> None:
        logger.warning("[%s] %s", self.request_id, message)
        self.warnings.append(message)

    def add_error(self, message: str, exc: Exception | None = None) -> None:
        logger.error("[%s] %s", self.request_id, message, exc_info=exc)
        self.errors.append({"message": message, "type": type(exc).__name__ if exc else "Error"})

    def to_dict(self) -> dict:
        """Serialize context to a dict suitable for tool response metadata."""
        return {
            "request_id": self.request_id,
            "started_at": self.started_at,
            "elapsed_ms": self.elapsed_ms,
            "status": self.status,
            "api_calls_made": self.api_calls_made,
            "items_fetched": self.items_fetched,
            "warnings": self.warnings,
            "errors": self.errors,
        }
