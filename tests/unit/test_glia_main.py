"""Smoke tests for ``glia/__main__.py`` (plan task 5.10).

Deliberately minimal: component-level exercise of the full supervisor +
aiomqtt + docker pipeline is deferred to task 5.9 / compose-stack
integration tests. Here we verify only that:

1. ``python -m glia --help`` exits 0 and prints usage — proves imports
   resolve and argparse is wired up.
2. Signal-handler installers + selector-loop policy installer are
   idempotent no-ops when invoked from a non-main thread / on POSIX.
3. ``_dispatch_loop`` drops malformed envelopes instead of crashing.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from glia.__main__ import (
    _dispatch_loop,
    _install_selector_loop_policy_on_win32,
    _install_signal_handlers,
)


def test_help_smoke() -> None:
    """``python -m glia --help`` exits 0 and prints usage."""
    result = subprocess.run(
        [sys.executable, "-m", "glia", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"--help exit != 0: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "usage: glia" in result.stdout
    assert "--registry" in result.stdout
    assert "--mqtt-host" in result.stdout
    assert "--mqtt-port" in result.stdout


def test_install_selector_loop_policy_is_noop_on_posix() -> None:
    """Selector-loop-policy installer does not raise on any platform."""
    # On win32 it mutates the policy, on POSIX it short-circuits.
    _install_selector_loop_policy_on_win32()


def test_install_signal_handlers_does_not_raise() -> None:
    """Installer tolerates non-main-thread loops via ValueError suppression."""
    loop = asyncio.new_event_loop()
    try:
        event = asyncio.Event()
        _install_signal_handlers(loop, event)
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_dispatch_loop_skips_bad_envelopes() -> None:
    """``_dispatch_loop`` drops malformed payloads and keeps going."""
    bad_msg = MagicMock()
    bad_msg.topic = "hive/system/heartbeat/test"
    bad_msg.payload = b"{not-json"
    bad_msg.retain = False

    async def _gen():
        yield bad_msg

    mqtt_client = MagicMock()
    mqtt_client.messages = _gen()

    supervisor = MagicMock()
    supervisor.on_heartbeat = AsyncMock()

    log = MagicMock()
    log.warning = MagicMock()

    await _dispatch_loop(mqtt_client, supervisor, log)

    # Bad envelope was logged and skipped — supervisor never called.
    supervisor.on_heartbeat.assert_not_called()
    assert log.warning.called
