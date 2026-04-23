"""Tests for observatory MQTT reconnect behavior.

Mirrors the regions' reconnect discipline (see region_template/mqtt_client.py
§B.10): on broker disconnect, log, back off exponentially, reopen, and resume
— so the observatory survives a broker restart without manual intervention.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiomqtt
import pytest

from observatory.service import _backoff_delay, _mqtt_run_with_reconnect


class _FakeMessages:
    """Async-iterator stub for ``aiomqtt.Client.messages``.

    - If ``fail_on_iter`` is True, raises MqttError on first ``__anext__``.
    - Otherwise blocks on ``stop_event`` and raises StopAsyncIteration when set,
      so the subscriber loop can exit cleanly.
    """

    def __init__(self, fail_on_iter: bool, stop_event: asyncio.Event) -> None:
        self._fail = fail_on_iter
        self._stop = stop_event

    def __aiter__(self) -> _FakeMessages:
        return self

    async def __anext__(self) -> Any:
        if self._fail:
            raise aiomqtt.MqttError("iter_boom")
        await self._stop.wait()
        raise StopAsyncIteration


class _FakeClient:
    """Configurable aiomqtt.Client stub."""

    def __init__(
        self,
        *,
        fail_on_enter: bool = False,
        fail_during_messages: bool = False,
        stop_event: asyncio.Event,
    ) -> None:
        self.fail_on_enter = fail_on_enter
        self.fail_during_messages = fail_during_messages
        self.stop_event = stop_event
        self.entered = False
        self.exited = False
        self.subscribe_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeClient:
        if self.fail_on_enter:
            raise aiomqtt.MqttError("enter_boom")
        self.entered = True
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.exited = True

    async def subscribe(self, *args: Any, **kwargs: Any) -> None:
        self.subscribe_calls.append((args, kwargs))

    @property
    def messages(self) -> _FakeMessages:
        return _FakeMessages(self.fail_during_messages, self.stop_event)


class _FakeSubscriber:
    """Protocol-compatible subscriber: iterates messages until stop_event."""

    def __init__(self) -> None:
        self.run_calls = 0

    async def run(self, client: Any, stop_event: asyncio.Event) -> None:
        self.run_calls += 1
        async for _ in client.messages:
            if stop_event.is_set():
                break


class TestBackoffDelay:
    """Pure function — exponential backoff capped at a ceiling."""

    def test_zero_attempt_returns_initial(self) -> None:
        assert _backoff_delay(0, initial=1.0, cap=30.0) == 1.0

    def test_progression_doubles_each_attempt(self) -> None:
        assert [_backoff_delay(n, initial=1.0, cap=30.0) for n in range(5)] == [
            1.0, 2.0, 4.0, 8.0, 16.0,
        ]

    def test_caps_at_ceiling(self) -> None:
        # 2**5 = 32 → capped at 30.
        assert _backoff_delay(5, initial=1.0, cap=30.0) == 30.0  # noqa: PLR2004
        # 2**10 = 1024 → still 30.
        assert _backoff_delay(10, initial=1.0, cap=30.0) == 30.0  # noqa: PLR2004

    def test_respects_custom_initial(self) -> None:
        assert _backoff_delay(0, initial=0.5, cap=30.0) == 0.5  # noqa: PLR2004
        assert _backoff_delay(3, initial=0.5, cap=30.0) == 4.0  # noqa: PLR2004


class TestReconnectLoop:
    async def test_reconnects_after_initial_enter_failure(self) -> None:
        """First factory call returns a client whose __aenter__ raises; second
        returns a working one. The loop must retry and then succeed."""
        stop_event = asyncio.Event()
        clients: list[_FakeClient] = []

        def factory() -> _FakeClient:
            # Second call (index 1) is the "healthy" broker after restart.
            client = _FakeClient(
                fail_on_enter=len(clients) == 0,
                stop_event=stop_event,
            )
            clients.append(client)
            return client

        subscriber = _FakeSubscriber()

        async def stop_soon() -> None:
            # Give the loop time to fail once, back off, and reconnect.
            await asyncio.sleep(0.02)
            stop_event.set()

        await asyncio.gather(
            _mqtt_run_with_reconnect(
                client_factory=factory,
                subscriber=subscriber,
                stop_event=stop_event,
                backoff_initial_s=0.001,
                backoff_cap_s=0.01,
            ),
            stop_soon(),
        )

        # At least two client instances were built (first failed, second worked).
        assert len(clients) >= 2  # noqa: PLR2004
        # The second (healthy) client was entered, subscribed, and exited.
        assert clients[1].entered is True
        assert clients[1].subscribe_calls, "expected hive/# subscribe on reconnect"
        assert subscriber.run_calls >= 1

    async def test_reconnects_after_mid_session_disconnect(self) -> None:
        """Session is live, then client.messages raises MqttError
        (broker dropped the connection). The loop reopens and resumes."""
        stop_event = asyncio.Event()
        clients: list[_FakeClient] = []

        def factory() -> _FakeClient:
            # First client: fails during messages iteration.
            # Second client: healthy.
            client = _FakeClient(
                fail_during_messages=len(clients) == 0,
                stop_event=stop_event,
            )
            clients.append(client)
            return client

        subscriber = _FakeSubscriber()

        async def stop_soon() -> None:
            await asyncio.sleep(0.02)
            stop_event.set()

        await asyncio.gather(
            _mqtt_run_with_reconnect(
                client_factory=factory,
                subscriber=subscriber,
                stop_event=stop_event,
                backoff_initial_s=0.001,
                backoff_cap_s=0.01,
            ),
            stop_soon(),
        )

        assert len(clients) >= 2  # noqa: PLR2004
        assert clients[0].entered is True
        assert clients[1].entered is True
        # Subscriber.run was invoked on both clients (once per connect).
        assert subscriber.run_calls >= 2  # noqa: PLR2004

    async def test_stop_event_during_backoff_exits_cleanly(self) -> None:
        """If stop_event is set while the loop is sleeping in backoff, the
        function returns promptly without another reconnect attempt."""
        stop_event = asyncio.Event()
        call_count = {"n": 0}

        def factory() -> _FakeClient:
            call_count["n"] += 1
            return _FakeClient(fail_on_enter=True, stop_event=stop_event)

        subscriber = _FakeSubscriber()

        async def stop_during_backoff() -> None:
            # Wait long enough for at least one failure + entry into backoff,
            # but shorter than the (intentionally long) backoff itself.
            await asyncio.sleep(0.05)
            stop_event.set()

        # Use a long backoff so the test only exits because stop_event fired.
        await asyncio.wait_for(
            asyncio.gather(
                _mqtt_run_with_reconnect(
                    client_factory=factory,
                    subscriber=subscriber,
                    stop_event=stop_event,
                    backoff_initial_s=10.0,  # long — would block the test
                    backoff_cap_s=10.0,
                ),
                stop_during_backoff(),
            ),
            timeout=2.0,
        )

        # At least one factory call happened (the initial failing attempt),
        # and the loop then exited via stop_event rather than retrying.
        assert call_count["n"] >= 1

    async def test_clean_shutdown_when_stop_event_set_mid_session(self) -> None:
        """Normal shutdown path: session is healthy, stop_event fires, the
        subscriber loop exits, and ``_mqtt_run_with_reconnect`` returns."""
        stop_event = asyncio.Event()
        clients: list[_FakeClient] = []

        def factory() -> _FakeClient:
            client = _FakeClient(stop_event=stop_event)
            clients.append(client)
            return client

        subscriber = _FakeSubscriber()

        async def stop_soon() -> None:
            await asyncio.sleep(0.01)
            stop_event.set()

        await asyncio.wait_for(
            asyncio.gather(
                _mqtt_run_with_reconnect(
                    client_factory=factory,
                    subscriber=subscriber,
                    stop_event=stop_event,
                    backoff_initial_s=0.001,
                    backoff_cap_s=0.01,
                ),
                stop_soon(),
            ),
            timeout=2.0,
        )

        # Exactly one client: no reconnect was needed.
        assert len(clients) == 1
        assert clients[0].entered is True
        assert clients[0].exited is True


@pytest.mark.asyncio
async def test_non_mqtt_exceptions_are_not_swallowed() -> None:
    """A non-MqttError raised by the client factory must propagate. The
    reconnect loop is specifically for broker-side failures; programmer
    bugs should bubble up so we can see them."""
    stop_event = asyncio.Event()

    def exploding_factory() -> Any:
        raise RuntimeError("programmer bug")

    with pytest.raises(RuntimeError, match="programmer bug"):
        await _mqtt_run_with_reconnect(
            client_factory=exploding_factory,
            subscriber=_FakeSubscriber(),
            stop_event=stop_event,
            backoff_initial_s=0.001,
            backoff_cap_s=0.01,
        )
