"""Component test for glia.supervisor — Task 5.9.

DEFERRED. A true end-to-end supervisor test requires:

  1. A running mosquitto broker (testcontainers) reachable on the
     ``hive_net`` Docker network.
  2. The ``hive-region:v0`` image built and present locally so the
     supervisor can actually launch real region containers.
  3. A coordinated ``regions_registry.yaml`` + ``bus/acl_templates``
     directory setup so ACL generation succeeds without trampling other
     tests.
  4. A docker-events listener wired in that surfaces container-exit
     events to the supervisor (this lives in ``glia/__main__`` — Task 5.10).

Rather than paper over those with a brittle docker-in-docker fixture, the
component test is deferred to a follow-up session where the broker fixture
(``tests/component/conftest.py``) is extended with supervisor support and
the image-build + docker-events wiring is in place. See
``docs/HANDOFF.md`` for the open follow-up.

Until then the supervisor is covered by ``tests/unit/test_supervisor.py``
with injected mocks for every sub-module, the clock and the sleeper.

Un-defer plan:

  a. Build ``hive-region:v0`` in the test fixture (or in CI pre-step) and
     assert the image exists before the test body runs.
  b. Stand up ``tests/component/conftest.py::mqtt_container`` for a real
     broker.
  c. Use a ``tmp_path`` ``regions_registry.yaml`` with two entries that
     point at the built image; bind ``bus/acl_templates`` read-only.
  d. Start a supervisor that subscribes + dispatches for real; launch two
     regions; kill one container via the docker SDK; assert the supervisor
     observes the exit, restarts (new container ID), and publishes the
     expected metacog events along the way.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Deferred: needs testcontainers broker + hive-region:v0 image + "
        "docker-events wiring (see HANDOFF.md follow-ups)."
    )
)


def test_supervisor_restarts_on_heartbeat_miss() -> None:
    """Placeholder: supervisor relaunches a region with a new container ID."""
