"""Shared fixtures for component tests.

On Windows, Python's default ``WindowsProactorEventLoopPolicy`` does not
support :meth:`asyncio.AbstractEventLoop.add_reader` / ``add_writer``,
which ``aiomqtt`` (via ``paho-mqtt``) requires. We force the selector
policy for every coroutine-based test in this directory.

Linux/macOS default to selector-based loops, so the event-loop override
is effectively a no-op there.

We also disable testcontainers' Ryuk sidecar at import time. Ryuk is a
Java container that testcontainers normally starts first, to reap leaked
containers when the test suite crashes. Its startup probe expects port
8080 to map immediately, which fails on some Windows/Docker Desktop setups.
Our tests use module-scoped fixtures that always call ``container.stop()``
in a ``finally``, so we do not need the reaper.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Applied before the first testcontainers import in this test module.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Override pytest-asyncio's default event-loop policy.

    On Windows, swap Proactor -> Selector so aiomqtt's socket-read/write
    registrations work.
    """
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
