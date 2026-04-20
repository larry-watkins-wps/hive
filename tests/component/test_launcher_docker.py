"""Component test for glia.launcher against a real Docker daemon.

DEFERRED.  Launching a real ``hive-region:v0`` container requires:

  1. The image to be built locally (task 4.1 Dockerfile exists, but the
     build is not part of the test fixture chain yet).
  2. A reachable mosquitto broker on the ``hive_net`` Docker network, or
     the region process crashes immediately and ``is_running`` races the
     transient ``running -> exited`` transition.
  3. A minimal ``regions/amygdala/config.yaml`` stub on the host FS so
     the mounted ``/hive/region`` volume is non-empty.

Rather than paper over those dependencies with a flaky polling loop, we
defer the component test to a follow-up session where the broker fixture
(``tests/component/conftest.py`` can be extended) and image-build step
are wired into a module-scoped fixture.  See ``docs/HANDOFF.md`` for the
open follow-up.

Until then the launcher's behavior is covered by
``tests/unit/test_launcher.py`` with a mocked docker SDK.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Deferred: needs real mosquitto broker + regions/amygdala config "
        "stub + hive-region:v0 image build; see HANDOFF.md follow-ups."
    )
)


def test_placeholder() -> None:  # pragma: no cover
    """Present so pytest has a test to skip and the file is importable."""
