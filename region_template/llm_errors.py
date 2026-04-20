"""Classify LiteLLM exceptions into Hive's ``LlmError`` hierarchy (spec §C.7).

This module has two responsibilities:

1. A set of string constants naming the **kinds** of ``LlmError`` the adapter
   can raise. The adapter uses these as the first positional argument to
   :class:`~region_template.errors.LlmError` so consumers can branch on kind
   without depending on LiteLLM's exception classes.

2. :func:`classify_litellm_exception` — map a raised LiteLLM exception to a
   ready-to-raise ``LlmError`` with the right ``retryable`` flag set per
   spec §C.7.

LiteLLM is imported lazily so the import cost (~500 ms) isn't paid on module
load of callers that only need the kind constants.
"""
from __future__ import annotations

from region_template.errors import LlmError

__all__ = [
    "KIND_AUTH",
    "KIND_BAD_REQUEST",
    "KIND_CONNECTION",
    "KIND_CONTENT_POLICY",
    "KIND_CONTEXT_WINDOW",
    "KIND_INTERNAL_SERVER",
    "KIND_MALFORMED_TOOL_CALL",
    "KIND_OVER_BUDGET",
    "KIND_RATE_LIMIT",
    "KIND_RATE_LIMIT_EXHAUSTED",
    "KIND_SERVICE_UNAVAILABLE",
    "KIND_STREAM_TRUNCATED",
    "KIND_UNKNOWN",
    "classify_litellm_exception",
]

# ---------------------------------------------------------------------------
# Kind constants
# ---------------------------------------------------------------------------

# Retryable kinds
KIND_RATE_LIMIT = "rate_limit"
KIND_CONNECTION = "connection"
KIND_SERVICE_UNAVAILABLE = "service_unavailable"
KIND_INTERNAL_SERVER = "internal_server"

# Non-retryable kinds
KIND_RATE_LIMIT_EXHAUSTED = "rate_limit_exhausted"
KIND_AUTH = "auth"
KIND_BAD_REQUEST = "bad_request"
KIND_CONTEXT_WINDOW = "context_window_exceeded"
KIND_CONTENT_POLICY = "content_policy"
KIND_OVER_BUDGET = "over_budget"
KIND_STREAM_TRUNCATED = "stream_truncated"
KIND_MALFORMED_TOOL_CALL = "malformed_tool_call"
KIND_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_litellm_exception(exc: BaseException) -> LlmError:  # noqa: PLR0911
    """Return an ``LlmError`` describing ``exc`` with the right retryable flag.

    Uses LiteLLM's exception class names (imported lazily). Anything not in
    the known list falls back to ``KIND_UNKNOWN`` with ``retryable=False`` —
    callers should treat unknown errors as terminal to avoid retry storms.

    Per spec §C.7:

    - Retryable: RateLimitError, APIConnectionError, ServiceUnavailableError,
      InternalServerError.
    - Non-retryable: AuthenticationError, BadRequestError,
      ContextWindowExceededError, ContentPolicyViolationError.
    """
    # Lazy import — see module docstring.
    import litellm  # noqa: PLC0415

    # Order matters: subclasses before their parents if LiteLLM uses
    # inheritance. At present ContextWindowExceededError inherits from
    # BadRequestError in some LiteLLM releases, so check it first.
    if isinstance(exc, litellm.ContextWindowExceededError):
        return LlmError(KIND_CONTEXT_WINDOW, retryable=False)
    if isinstance(exc, litellm.ContentPolicyViolationError):
        return LlmError(KIND_CONTENT_POLICY, retryable=False)
    if isinstance(exc, litellm.AuthenticationError):
        return LlmError(KIND_AUTH, retryable=False)
    if isinstance(exc, litellm.BadRequestError):
        return LlmError(KIND_BAD_REQUEST, retryable=False)
    if isinstance(exc, litellm.RateLimitError):
        return LlmError(KIND_RATE_LIMIT, retryable=True)
    if isinstance(exc, litellm.APIConnectionError):
        return LlmError(KIND_CONNECTION, retryable=True)
    if isinstance(exc, litellm.ServiceUnavailableError):
        return LlmError(KIND_SERVICE_UNAVAILABLE, retryable=True)
    if isinstance(exc, litellm.InternalServerError):
        return LlmError(KIND_INTERNAL_SERVER, retryable=True)

    return LlmError(KIND_UNKNOWN, retryable=False)
