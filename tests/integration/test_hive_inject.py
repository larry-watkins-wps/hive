"""Integration tests for ``tools/dbg/hive_inject.py``.

Mocks the aiomqtt client via an injected ``client_factory`` so no real
broker is required. Real-broker smoke tests belong to Phase 9.

Task 7.4, per spec §H.3 / §K.2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import tools.dbg.hive_inject as hive_inject_mod
from shared.message_envelope import Envelope
from tools.dbg.hive_inject import app, run

pytestmark = pytest.mark.integration

# Named exit codes — keep ruff PLR2004 quiet on "magic values".
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
QOS_EXACTLY_ONCE = 2


# ---------------------------------------------------------------------------
# Fake aiomqtt client
# ---------------------------------------------------------------------------


class _FakePublishCall:
    def __init__(
        self,
        topic: str,
        payload: bytes,
        qos: int,
        retain: bool,
    ) -> None:
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain


class _FakeClient:
    """Async-context-manager fake for ``aiomqtt.Client`` with ``.publish``."""

    # Class-level registry so tests can inspect what the factory produced.
    instances: list[_FakeClient] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.publishes: list[_FakePublishCall] = []
        _FakeClient.instances.append(self)

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def publish(
        self,
        topic: str,
        *,
        payload: bytes,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        self.publishes.append(_FakePublishCall(topic, payload, qos, retain))


@pytest.fixture(autouse=True)
def _reset_fake_client() -> None:
    _FakeClient.instances = []


def _factory(**kwargs: Any) -> _FakeClient:
    return _FakeClient(**kwargs)


# ---------------------------------------------------------------------------
# Payload-shorthand mode
# ---------------------------------------------------------------------------


def test_payload_shorthand_inline_json() -> None:
    rc = run(
        "hive/sensory/input/text",
        '{"data":"hi","content_type":"text/plain"}',
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    assert len(_FakeClient.instances) == 1
    client = _FakeClient.instances[0]
    assert len(client.publishes) == 1
    call = client.publishes[0]
    assert call.topic == "hive/sensory/input/text"
    env = Envelope.from_json(call.payload)
    assert env.topic == "hive/sensory/input/text"
    assert env.source_region == "hive_inject"
    assert env.payload.data == "hi"
    assert env.payload.content_type == "text/plain"


def test_payload_shorthand_from_file(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"data": "hi"}), encoding="utf-8")
    rc = run(
        "hive/sensory/input/text",
        str(p),
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    call = _FakeClient.instances[0].publishes[0]
    env = Envelope.from_json(call.payload)
    # Default content_type when omitted.
    assert env.payload.content_type == "text/plain"
    assert env.payload.data == "hi"


# ---------------------------------------------------------------------------
# Full-envelope mode
# ---------------------------------------------------------------------------


def _full_envelope_bytes(
    topic: str = "hive/sensory/input/text",
    correlation_id: str | None = None,
    reply_to: str | None = None,
) -> bytes:
    env = Envelope.new(
        source_region="operator",
        topic=topic,
        content_type="text/plain",
        data="hello",
        correlation_id=correlation_id,
        reply_to=reply_to,
    )
    return env.to_json()


def test_full_envelope_from_file(tmp_path: Path) -> None:
    p = tmp_path / "env.json"
    p.write_bytes(_full_envelope_bytes())
    rc = run(
        "hive/sensory/input/text",
        str(p),
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    call = _FakeClient.instances[0].publishes[0]
    env = Envelope.from_json(call.payload)
    # Full-envelope mode must NOT rewrite source_region.
    assert env.source_region == "operator"


def test_full_envelope_topic_mismatch_exits_2(tmp_path: Path) -> None:
    p = tmp_path / "env.json"
    p.write_bytes(_full_envelope_bytes(topic="hive/other/topic"))
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        app,
        ["hive/sensory/input/text", str(p)],
        catch_exceptions=False,
    )
    assert result.exit_code == EXIT_USAGE
    assert "mismatch" in result.stderr.lower() or "topic" in result.stderr.lower()
    # No publishes should have been made.
    assert all(len(c.publishes) == 0 for c in _FakeClient.instances)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_malformed_json_exits_2(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json at all{", encoding="utf-8")
    rc = run(
        "hive/sensory/input/text",
        str(p),
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_USAGE


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bogus = tmp_path / "does-not-exist.json"
    rc = run(
        "hive/sensory/input/text",
        str(bogus),
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_USAGE
    captured = capsys.readouterr()
    assert str(bogus) in captured.err


# ---------------------------------------------------------------------------
# Flags: qos, retain, correlation-id, reply-to
# ---------------------------------------------------------------------------


def test_qos_and_retain_flags() -> None:
    rc = run(
        "hive/sensory/input/text",
        '{"data":"hi"}',
        host="localhost",
        port=1883,
        qos=2,
        retain=True,
        correlation_id=None,
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    call = _FakeClient.instances[0].publishes[0]
    assert call.qos == QOS_EXACTLY_ONCE
    assert call.retain is True


def test_correlation_id_flag_shorthand() -> None:
    rc = run(
        "hive/sensory/input/text",
        '{"data":"hi"}',
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id="abc",
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    env = Envelope.from_json(_FakeClient.instances[0].publishes[0].payload)
    assert env.correlation_id == "abc"


def test_correlation_id_flag_overrides_full_envelope(tmp_path: Path) -> None:
    p = tmp_path / "env.json"
    p.write_bytes(_full_envelope_bytes(correlation_id="original"))
    rc = run(
        "hive/sensory/input/text",
        str(p),
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id="abc",
        reply_to=None,
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    env = Envelope.from_json(_FakeClient.instances[0].publishes[0].payload)
    assert env.correlation_id == "abc"


def test_reply_to_flag_shorthand() -> None:
    rc = run(
        "hive/sensory/input/text",
        '{"data":"hi"}',
        host="localhost",
        port=1883,
        qos=1,
        retain=False,
        correlation_id=None,
        reply_to="hive/reply/here",
        client_factory=_factory,
    )
    assert rc == EXIT_OK
    env = Envelope.from_json(_FakeClient.instances[0].publishes[0].payload)
    assert env.reply_to == "hive/reply/here"


# ---------------------------------------------------------------------------
# CLI smoke test via typer runner
# ---------------------------------------------------------------------------


def test_cli_runner_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hive_inject_mod, "_default_client_factory", _factory)
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(
        app,
        ["hive/sensory/input/text", '{"data":"hi","content_type":"text/plain"}'],
        catch_exceptions=False,
    )
    assert result.exit_code == EXIT_OK
    assert "published" in result.stdout
