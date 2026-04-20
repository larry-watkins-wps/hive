"""Component test for glia.spawn_executor — Task 5.7a.

DEFERRED. A true end-to-end spawn requires:

  1. A running mosquitto broker reachable on the ``hive_net`` Docker network
     (so the launched container can subscribe/publish without immediately
     crashing).
  2. The ``hive-region:v0`` image built and present locally.
  3. Write access to ``regions_registry.yaml`` and the real ``bus/acl_templates``
     directory, coordinated against other tests.
  4. Ability to issue SIGHUP to the broker container (acl_manager.reload_broker).

Rather than paper over those with a brittle docker-in-docker fixture, we defer
the component test to a follow-up session where the broker fixture
(``tests/component/conftest.py``) is extended with spawn support and the
image-build step is wired in.  See ``docs/HANDOFF.md`` for the open follow-up.

Until then the executor is covered by ``tests/unit/test_spawn_executor.py``
with injected mocks for launcher, acl_manager, and the subprocess runner.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Deferred: needs real mosquitto broker + hive-region:v0 image build "
        "+ coordinated regions_registry/bus/acl_templates writes; "
        "see HANDOFF.md follow-ups."
    )
)


def test_placeholder() -> None:  # pragma: no cover
    """Present so pytest has a test to skip and the file is importable."""
