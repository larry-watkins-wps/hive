"""Platform glue for observatory component tests.

Mirrors the top-level ``tests/component/conftest.py``:

- forces :class:`asyncio.WindowsSelectorEventLoopPolicy` (``aiomqtt`` via
  ``paho-mqtt`` needs ``add_reader`` / ``add_writer``, which Windows'
  default Proactor loop does not provide);
- disables the testcontainers Ryuk sidecar at import time — its startup
  probe expects port 8080 to map immediately, which is flaky on some
  Windows/Docker Desktop setups. Our fixtures are context-managed and
  always clean up in a ``finally``, so we do not need the reaper.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Applied before the first testcontainers import in this test package.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Override pytest-asyncio's default event-loop policy.

    On Windows, swap Proactor -> Selector so aiomqtt's socket-read/write
    registrations work.
    """
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
