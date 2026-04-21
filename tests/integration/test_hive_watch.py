"""Integration tests for ``tools/dbg/hive_watch.py``.

Uses an inline fake aiomqtt client so no broker is required. Real-broker
smoke tests belong to Phase 9.

Task 7.2, per spec §H.3 lines 4089-4104.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from shared.message_envelope import Envelope
from tools.dbg.hive_watch import app, run

pytestmark = pytest.mark.integration


# Named exit codes (ruff PLR2004).
EXIT_OK = 0
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Fake aiomqtt client
# ---------------------------------------------------------------------------


class _FakeMessages:
    """Async iterator that yields a finite list of messages, then stops."""

    def __init__(self, messages: list[Any]) -> None:
        self._messages = list(messages)

    def __aiter__(self) -> _FakeMessages:
        return self

    async def __anext__(self) -> Any:
        if not self._messages:
            # End the stream; run() treats StopAsyncIteration as "drained".
            raise StopAsyncIteration
        return self._messages.pop(0)


class FakeAiomqttClient:
    """Drop-in replacement for ``aiomqtt.Client``.

    Records subscriptions so tests can assert the resolved topic pattern;
    replays a pre-loaded list of messages for the async iterator.
    """

    # Class-level injection: tests set this before invoking the CLI/run().
    _next_messages: list[Any] = []
    last_instance: FakeAiomqttClient | None = None

    def __init__(self, hostname: str, port: int = 1883, **_kwargs: Any) -> None:
        self.hostname = hostname
        self.port = port
        self.subscriptions: list[str] = []
        self.messages = _FakeMessages(list(self._next_messages))
        FakeAiomqttClient.last_instance = self

    async def __aenter__(self) -> FakeAiomqttClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def subscribe(self, topic: str) -> None:
        self.subscriptions.append(topic)


def _mk_envelope_bytes(
    *,
    topic: str = "hive/cognitive/thalamus/attend",
    source: str = "thalamus",
    content_type: str = "text/plain",
    data: Any = "hello",
) -> bytes:
    env = Envelope.new(
        source_region=source,
        topic=topic,
        content_type=content_type,  # type: ignore[arg-type]
        data=data,
    )
    return env.to_json()


def _msg(topic: str, payload: bytes, *, retain: bool = False) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=payload, retain=retain)


# ---------------------------------------------------------------------------
# Alias / pattern resolution
# ---------------------------------------------------------------------------


def test_alias_modulators_resolves_to_wildcard() -> None:
    FakeAiomqttClient._next_messages = []
    rc = run(
        "modulators",
        host="localhost",
        port=1883,
        retained=False,
        timeout=0.1,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    assert FakeAiomqttClient.last_instance is not None
    assert FakeAiomqttClient.last_instance.subscriptions == ["hive/modulator/#"]


def test_literal_pattern_passes_through() -> None:
    FakeAiomqttClient._next_messages = []
    rc = run(
        "hive/self/#",
        host="localhost",
        port=1883,
        retained=False,
        timeout=0.1,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    assert FakeAiomqttClient.last_instance is not None
    assert FakeAiomqttClient.last_instance.subscriptions == ["hive/self/#"]


def test_unknown_alias_exits_usage_with_alias_list() -> None:
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["not_a_real_alias"])
    assert result.exit_code == EXIT_USAGE
    # Known aliases must be listed in stderr.
    assert "modulators" in result.stderr
    assert "attention" in result.stderr
    assert "self" in result.stderr


# ---------------------------------------------------------------------------
# Message printing
# ---------------------------------------------------------------------------


def test_two_envelopes_printed(capsys: pytest.CaptureFixture[str]) -> None:
    FakeAiomqttClient._next_messages = [
        _msg(
            "hive/cognitive/thalamus/attend",
            _mk_envelope_bytes(
                topic="hive/cognitive/thalamus/attend",
                source="thalamus",
                data="attending to text input",
            ),
        ),
        _msg(
            "hive/cognitive/hippocampus/recall",
            _mk_envelope_bytes(
                topic="hive/cognitive/hippocampus/recall",
                source="hippocampus",
                data="recalling memory",
            ),
        ),
    ]
    rc = run(
        "hive/cognitive/#",
        host="localhost",
        port=1883,
        retained=False,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "hive/cognitive/thalamus/attend" in out
    assert "hive/cognitive/hippocampus/recall" in out
    assert "thalamus" in out
    assert "hippocampus" in out


def test_retained_mode_only_prints_retained(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAiomqttClient._next_messages = [
        _msg(
            "hive/self/state",
            _mk_envelope_bytes(
                topic="hive/self/state",
                source="self_model",
                data="retained state",
            ),
            retain=True,
        ),
        _msg(
            "hive/self/live",
            _mk_envelope_bytes(
                topic="hive/self/live",
                source="self_model",
                data="live update",
            ),
            retain=False,
        ),
    ]
    rc = run(
        "hive/self/#",
        host="localhost",
        port=1883,
        retained=True,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "hive/self/state" in out
    assert "retained state" in out
    assert "hive/self/live" not in out


def test_text_plain_preview_truncated(capsys: pytest.CaptureFixture[str]) -> None:
    long_text = "x" * 200
    FakeAiomqttClient._next_messages = [
        _msg(
            "hive/cognitive/a/b",
            _mk_envelope_bytes(
                topic="hive/cognitive/a/b",
                source="alpha",
                content_type="text/plain",
                data=long_text,
            ),
        ),
    ]
    rc = run(
        "hive/cognitive/#",
        host="localhost",
        port=1883,
        retained=False,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    # 80-char preview + quotes: the full 200-char payload must NOT be present.
    assert long_text not in out
    # Some prefix of the long text IS present (first 80 chars).
    assert "x" * 80 in out


def test_invalid_envelope_does_not_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAiomqttClient._next_messages = [
        _msg("hive/garbage/topic", b"{not valid json"),
        _msg(
            "hive/cognitive/ok/topic",
            _mk_envelope_bytes(
                topic="hive/cognitive/ok/topic",
                source="ok_region",
                data="ok",
            ),
        ),
    ]
    rc = run(
        "hive/#",
        host="localhost",
        port=1883,
        retained=False,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "<invalid envelope>" in out
    # The following valid message is still processed.
    assert "hive/cognitive/ok/topic" in out


def test_non_text_plain_shows_content_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAiomqttClient._next_messages = [
        _msg(
            "hive/modulator/dopamine/level",
            _mk_envelope_bytes(
                topic="hive/modulator/dopamine/level",
                source="dopamine",
                content_type="application/hive+modulator",
                data={"level": 0.7, "source": "reward"},
            ),
        ),
    ]
    rc = run(
        "modulators",
        host="localhost",
        port=1883,
        retained=False,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "application/hive+modulator" in out
    assert "hive/modulator/dopamine/level" in out


def test_aliases_attention_self_metrics() -> None:
    for alias, expected in [
        ("attention", "hive/attention/#"),
        ("self", "hive/self/#"),
        ("metrics", "hive/system/metrics/#"),
    ]:
        FakeAiomqttClient._next_messages = []
        rc = run(
            alias,
            host="localhost",
            port=1883,
            retained=False,
            timeout=0.1,
            client_factory=FakeAiomqttClient,
        )
        assert rc == EXIT_OK
        assert FakeAiomqttClient.last_instance is not None
        assert FakeAiomqttClient.last_instance.subscriptions == [expected]


def test_json_payload_preview_on_application_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAiomqttClient._next_messages = [
        _msg(
            "hive/system/metrics/foo",
            _mk_envelope_bytes(
                topic="hive/system/metrics/foo",
                source="metrics",
                content_type="application/json",
                data={"count": 42},
            ),
        ),
    ]
    rc = run(
        "metrics",
        host="localhost",
        port=1883,
        retained=False,
        timeout=1.0,
        client_factory=FakeAiomqttClient,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "application/json" in out
    # The string repr of the dict should appear at least in truncated form.
    assert "count" in out or "42" in out
