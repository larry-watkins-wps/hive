"""Tests for shared.message_envelope — covers spec §B.2, §B.2.1, §B.2.2, §B.12, §B.14.

Cases:
  (a) Valid envelope round-trips through from_json(to_json()) — all fields equal.
  (b) Envelope missing a required field raises EnvelopeValidationError.
  (c) Unknown content_type raises EnvelopeValidationError on from_json (strict enum).
  (d) Envelope.new() auto-fills id (UUID), timestamp (RFC3339 millis+Z), envelope_version=1.
  (e) correlation_id=None and correlation_id="<uuid>" both round-trip correctly.
  (f) source_region violating regex raises EnvelopeValidationError.
  (g) attention_hint out of [0.0, 1.0] raises EnvelopeValidationError.
"""
import json
import re
import uuid

import pytest

from shared.message_envelope import (
    ENVELOPE_VERSION,
    Envelope,
    EnvelopeValidationError,
)

EXPECTED_ATTENTION_HINT = 0.8

# ---------------------------------------------------------------------------
# (a) Valid envelope round-trips through from_json(to_json())
# ---------------------------------------------------------------------------

def test_new_envelope_round_trips():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/modulator/cortisol",
        content_type="application/hive+modulator",
        data={"value": 0.5},
    )
    raw = env.to_json()
    parsed = Envelope.from_json(raw)

    assert parsed.source_region == env.source_region
    assert parsed.topic == env.topic
    assert parsed.payload.content_type == env.payload.content_type
    assert parsed.payload.data == env.payload.data
    assert parsed.payload.encoding == env.payload.encoding
    assert parsed.id == env.id
    assert parsed.timestamp == env.timestamp
    assert parsed.envelope_version == ENVELOPE_VERSION
    assert parsed.reply_to == env.reply_to
    assert parsed.correlation_id == env.correlation_id
    assert parsed.attention_hint == env.attention_hint


def test_round_trip_preserves_all_optional_fields():
    corr_id = str(uuid.uuid4())
    env = Envelope.new(
        source_region="vta001",
        topic="hive/memory/query",
        content_type="application/hive+memory-query",
        data={"query": "what did I forget?"},
        reply_to="hive/memory/response",
        correlation_id=corr_id,
        attention_hint=EXPECTED_ATTENTION_HINT,
    )
    parsed = Envelope.from_json(env.to_json())

    assert parsed.reply_to == "hive/memory/response"
    assert parsed.correlation_id == corr_id
    assert parsed.attention_hint == EXPECTED_ATTENTION_HINT


# ---------------------------------------------------------------------------
# (b) Missing required field raises EnvelopeValidationError
# ---------------------------------------------------------------------------

def test_missing_id_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    del obj["id"]
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


def test_missing_source_region_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    del obj["source_region"]
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


def test_missing_topic_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    del obj["topic"]
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


def test_missing_payload_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    del obj["payload"]
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


def test_missing_envelope_version_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    del obj["envelope_version"]
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


# ---------------------------------------------------------------------------
# (c) Unknown content_type raises EnvelopeValidationError on from_json
# ---------------------------------------------------------------------------

def test_unknown_content_type_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    obj["payload"]["content_type"] = "application/unknown-type"
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


def test_empty_content_type_raises():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
    )
    obj = json.loads(env.to_json())
    obj["payload"]["content_type"] = ""
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


# ---------------------------------------------------------------------------
# (d) Envelope.new() auto-fills id (UUID), timestamp (RFC3339+Z), envelope_version=1
# ---------------------------------------------------------------------------

_RFC3339_MILLIS_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def test_new_auto_fills_id_as_uuid():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    # Must parse as a valid UUID without raising
    parsed_uuid = uuid.UUID(env.id)
    assert str(parsed_uuid) == env.id


def test_new_auto_fills_timestamp_rfc3339_millis():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    assert _RFC3339_MILLIS_Z.match(env.timestamp), (
        f"Timestamp '{env.timestamp}' does not match RFC3339 millis+Z pattern"
    )


def test_new_auto_fills_envelope_version_one():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    assert env.envelope_version == 1
    assert env.envelope_version == ENVELOPE_VERSION


def test_new_generates_unique_ids():
    env1 = Envelope.new(
        source_region="amygdala", topic="t", content_type="text/plain", data="x"
    )
    env2 = Envelope.new(
        source_region="amygdala", topic="t", content_type="text/plain", data="x"
    )
    assert env1.id != env2.id


# ---------------------------------------------------------------------------
# (e) correlation_id=None and correlation_id="<uuid>" both round-trip correctly
# ---------------------------------------------------------------------------

def test_correlation_id_none_round_trips():
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
        correlation_id=None,
    )
    parsed = Envelope.from_json(env.to_json())
    assert parsed.correlation_id is None


def test_correlation_id_uuid_round_trips():
    corr_id = str(uuid.uuid4())
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hello",
        correlation_id=corr_id,
    )
    parsed = Envelope.from_json(env.to_json())
    assert parsed.correlation_id == corr_id


# ---------------------------------------------------------------------------
# (f) source_region violating regex ^[a-z][a-z0-9_]{2,30}$ raises EnvelopeValidationError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_region",
    [
        "x",          # too short (1 char total, need at least 3)
        "xy",         # too short (2 chars, need at least 3)
        "AB",         # uppercase
        "1abc",       # starts with digit
        "_abc",       # starts with underscore
        "abc-def",    # hyphen not allowed
        "a" * 32,     # too long (>31 chars)
        "",           # empty
    ],
)
def test_invalid_source_region_raises(bad_region):
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    obj = json.loads(env.to_json())
    obj["source_region"] = bad_region
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


@pytest.mark.parametrize(
    "good_region",
    [
        "abc",        # exactly 3 chars (min valid)
        "amygdala",
        "vta001",
        "a23",
        "a_b_c",
        "a" + "b" * 30,  # exactly 31 chars (max valid)
    ],
)
def test_valid_source_region_passes(good_region):
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    obj = json.loads(env.to_json())
    obj["source_region"] = good_region
    # Should not raise
    parsed = Envelope.from_json(json.dumps(obj).encode())
    assert parsed.source_region == good_region


# ---------------------------------------------------------------------------
# (g) attention_hint out of [0.0, 1.0] raises EnvelopeValidationError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_hint", [-0.001, -1.0, 1.001, 2.0, 100.0])
def test_attention_hint_out_of_range_raises(bad_hint):
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    obj = json.loads(env.to_json())
    obj["attention_hint"] = bad_hint
    with pytest.raises(EnvelopeValidationError):
        Envelope.from_json(json.dumps(obj).encode())


@pytest.mark.parametrize("ok_hint", [0.0, 0.5, 1.0, 0.999, 0.001])
def test_attention_hint_in_range_passes(ok_hint):
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/test",
        content_type="text/plain",
        data="hi",
    )
    obj = json.loads(env.to_json())
    obj["attention_hint"] = ok_hint
    parsed = Envelope.from_json(json.dumps(obj).encode())
    assert parsed.attention_hint == ok_hint
