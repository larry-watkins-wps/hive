"""Hive Message Envelope — the foundational type for all MQTT inter-region messages.

Spec: §B.2, §B.2.1, §B.2.2, §B.12, §B.14
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, ValidationError

ENVELOPE_VERSION = 1

ContentType = Literal[
    "text/plain",
    "application/json",
    "application/hive+memory-query",
    "application/hive+memory-response",
    "application/hive+sensory-features",
    "application/hive+motor-intent",
    "application/hive+modulator",
    "application/hive+self-state",
    "application/hive+spawn-proposal",
    "application/hive+spawn-request",
    "application/hive+code-change-proposal",
    "application/hive+reflection",
    "application/hive+error",
]


class EnvelopeValidationError(Exception):
    """Raised when an envelope fails JSON Schema validation or cannot be decoded."""


@dataclass(frozen=True)
class Payload:
    content_type: ContentType
    data: Any
    encoding: Literal["utf-8", "base64"] = "utf-8"


@dataclass(frozen=True)
class Envelope:
    source_region: str
    topic: str
    payload: Payload
    envelope_version: int = ENVELOPE_VERSION
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: (
            datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    )
    reply_to: str | None = None
    correlation_id: str | None = None
    attention_hint: float = 0.5

    @classmethod
    def new(
        cls,
        *,
        source_region: str,
        topic: str,
        content_type: ContentType,
        data: Any,
        encoding: Literal["utf-8", "base64"] = "utf-8",
        reply_to: str | None = None,
        correlation_id: str | None = None,
        attention_hint: float = 0.5,
    ) -> Envelope:
        """Factory method: creates an Envelope with auto-generated id and timestamp."""
        return cls(
            source_region=source_region,
            topic=topic,
            payload=Payload(content_type=content_type, data=data, encoding=encoding),
            reply_to=reply_to,
            correlation_id=correlation_id,
            attention_hint=attention_hint,
        )

    def to_json(self) -> bytes:
        """Serialize to UTF-8 encoded JSON bytes."""
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> Envelope:
        """Deserialize from UTF-8 JSON bytes, validating against the envelope schema.

        Raises:
            EnvelopeValidationError: if the JSON is malformed or fails schema validation.
        """
        try:
            obj = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EnvelopeValidationError(f"invalid JSON: {exc}") from exc

        try:
            _VALIDATOR.validate(obj)
        except ValidationError as exc:
            raise EnvelopeValidationError(str(exc)) from exc

        # Destructure payload separately so we can construct Payload dataclass.
        obj = dict(obj)  # shallow copy so we don't mutate the caller's data
        payload_dict = obj.pop("payload")
        return cls(payload=Payload(**payload_dict), **obj)


# ---------------------------------------------------------------------------
# Schema validator — loaded once at module import time.
# ---------------------------------------------------------------------------
_SCHEMA_PATH = Path(__file__).parent / "envelope_schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
