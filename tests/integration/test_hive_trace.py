"""Integration tests for ``tools/dbg/hive_trace.py``.

Mocks the aiomqtt client via an injected ``client_factory`` so no real
broker is required. Real-broker smoke tests belong to Phase 9.

Task 7.1, per spec §H.4.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from shared.message_envelope import Envelope, Payload
from tools.dbg.hive_trace import app, run

pytestmark = pytest.mark.integration

# Named exit codes — keep ruff PLR2004 quiet on "magic values".
EXIT_OK = 0
EXIT_USAGE = 2
EXPECTED_MATCHES = 3
PREVIEW_MAX_CHARS = 60


# ---------------------------------------------------------------------------
# Fake aiomqtt client
# ---------------------------------------------------------------------------


class _FakeMessage:
    """Minimal stand-in for ``aiomqtt.Message`` (only ``.topic`` + ``.payload``)."""

    def __init__(self, topic: str, payload: bytes) -> None:
        # aiomqtt exposes ``topic.value`` as the matched topic string.
        self.topic = SimpleNamespace(value=topic)
        self.payload = payload


class _FakeMessagesIterator:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._messages = list(messages)

    def __aiter__(self) -> _FakeMessagesIterator:
        return self

    async def __anext__(self) -> _FakeMessage:
        if not self._messages:
            # Signal no more messages — the trace code is expected to be
            # wrapped in asyncio.wait_for() so it will time out here.
            raise StopAsyncIteration
        return self._messages.pop(0)


class _FakeClient:
    """Async-context-manager fake for ``aiomqtt.Client``."""

    def __init__(self, messages: list[_FakeMessage], **_: Any) -> None:
        self._messages = messages
        self.subscribed: list[str] = []
        self.messages = _FakeMessagesIterator(messages)

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def subscribe(self, topic: str, **_: Any) -> None:
        self.subscribed.append(topic)


def _make_factory(messages: list[_FakeMessage]):
    def factory(**_: Any) -> _FakeClient:
        return _FakeClient(messages)

    return factory


def _env(
    *,
    corr: str | None,
    ts: str,
    source: str = "thalamus",
    topic: str = "hive/cognitive/thalamus/attend",
    content_type: str = "text/plain",
    data: object = "hello",
) -> Envelope:
    # Construct directly (not via .new()) so we can fix the timestamp.
    return Envelope(
        source_region=source,
        topic=topic,
        payload=Payload(content_type=content_type, data=data),  # type: ignore[arg-type]
        timestamp=ts,
        correlation_id=corr,
    )


def _msg(env: Envelope) -> _FakeMessage:
    return _FakeMessage(topic=env.topic, payload=env.to_json())


# ---------------------------------------------------------------------------
# Logic tests via run()
# ---------------------------------------------------------------------------


def test_run_filters_by_correlation_id_and_sorts_by_timestamp(capsys):
    a = _env(corr="c1", ts="2026-04-19T10:30:00.100Z", source="thalamus")
    b = _env(corr="c2", ts="2026-04-19T10:30:00.050Z", source="hippocampus")
    c = _env(corr="c1", ts="2026-04-19T10:30:00.000Z", source="sensory")
    d = _env(corr="c1", ts="2026-04-19T10:30:00.200Z", source="motor")
    e = _env(corr="other", ts="2026-04-19T10:30:00.300Z", source="amygdala")

    factory = _make_factory([_msg(x) for x in (a, b, c, d, e)])
    rc = run(
        "c1",
        host="localhost",
        port=1883,
        timeout=0.2,
        live=False,
        client_factory=factory,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out

    # Only c1 envelopes present.
    assert "c2" not in out
    assert "amygdala" not in out

    # Sorted by timestamp — sensory (.000) before thalamus (.100) before motor (.200).
    i_sensory = out.find("sensory")
    i_thalamus = out.find("thalamus")
    i_motor = out.find("motor")
    assert 0 <= i_sensory < i_thalamus < i_motor

    # Count of matching rows reported.
    assert str(EXPECTED_MATCHES) in out


def test_run_ignores_envelopes_without_correlation_id(capsys):
    a = _env(corr="c1", ts="2026-04-19T10:30:00.000Z", source="thalamus")
    b = _env(corr=None, ts="2026-04-19T10:30:00.100Z", source="rogue")

    factory = _make_factory([_msg(a), _msg(b)])
    rc = run(
        "c1",
        host="localhost",
        port=1883,
        timeout=0.2,
        live=False,
        client_factory=factory,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "thalamus" in out
    assert "rogue" not in out


def test_run_payload_preview_text_plain_truncated(capsys):
    long_text = "x" * 200
    env = _env(
        corr="c1",
        ts="2026-04-19T10:30:00.000Z",
        content_type="text/plain",
        data=long_text,
    )
    factory = _make_factory([_msg(env)])
    rc = run(
        "c1",
        host="localhost",
        port=1883,
        timeout=0.2,
        live=False,
        client_factory=factory,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    # First 60 chars appear; should NOT contain the full 200 Xs.
    assert "x" * PREVIEW_MAX_CHARS in out
    assert "x" * (PREVIEW_MAX_CHARS + 1) not in out


def test_run_payload_preview_json_shows_content_type_not_raw(capsys):
    env = _env(
        corr="c1",
        ts="2026-04-19T10:30:00.000Z",
        content_type="application/json",
        data={"secret": "should-not-appear-raw"},
    )
    factory = _make_factory([_msg(env)])
    rc = run(
        "c1",
        host="localhost",
        port=1883,
        timeout=0.2,
        live=False,
        client_factory=factory,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "application/json" in out
    assert "should-not-appear-raw" not in out


def test_run_timeout_with_no_matches_exits_clean(capsys):
    # Feed only non-matching envelopes; the run should still exit 0 with an
    # empty timeline / "0 events" indicator.
    other = _env(corr="nope", ts="2026-04-19T10:30:00.000Z", source="thalamus")
    factory = _make_factory([_msg(other)])
    rc = run(
        "needle",
        host="localhost",
        port=1883,
        timeout=0.2,
        live=False,
        client_factory=factory,
    )
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    # Best-effort semantics: tool reports 0 matches, does not crash.
    assert "0" in out


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_requires_correlation_id():
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, [])
    assert result.exit_code == EXIT_USAGE, result.output
