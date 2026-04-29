"""Exceptions raised by the sensory bridge."""
from __future__ import annotations


class ForbiddenTopicError(Exception):
    """Raised when a publish call targets a topic outside the allowlist.

    This is a programming error — routes always build allowlist-permitted
    topics. If raised at runtime, the route returns HTTP 500.
    """

    def __init__(self, topic: str) -> None:
        self.topic = topic
        super().__init__(f"topic {topic!r} is not in the v4 publish allowlist")


class PublishFailedError(Exception):
    """Raised when the underlying aiomqtt publish call fails.

    Wraps the original `aiomqtt.MqttError` so route handlers can return
    HTTP 502 with the underlying message in the body.
    """

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(str(cause))
