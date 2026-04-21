"""Cross-region integration flow test (plan Task 9.3 / spec §I.4).

Bring up compose.test.yaml, inject hive/sensory/input/text, observe
hive/motor/speech/intent within 15 seconds.

Skipped when preconditions aren't met — Docker, images, LLM key, or
handler implementation.  See module-level skip functions.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("aiomqtt")

import aiomqtt  # noqa: E402  (after importorskip)

from shared.message_envelope import Envelope  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SENSORY_TOPIC = "hive/sensory/input/text"
_MOTOR_TOPIC = "hive/motor/speech/intent"
_EXPECTED_CONTENT_TYPE = "application/hive+motor-intent"
_FLOW_TIMEOUT_S = 15

# The scaffolded __init__.py is a single docstring; real handler code will be
# substantially longer.  This threshold separates stub from implementation.
_STUB_THRESHOLD_CHARS = 80


# ---------------------------------------------------------------------------
# Windows event-loop policy (aiomqtt needs add_reader / add_writer)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Force selector loop on Windows; aiomqtt needs add_reader/add_writer."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Skip-condition helpers
# ---------------------------------------------------------------------------


def _docker_reachable() -> bool:
    """Return True if the Docker daemon is reachable."""
    try:
        import docker  # noqa: PLC0415

        client = docker.from_env()
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False


def _required_images_present() -> bool:
    """Return True if both hive-region:v0 and hive-glia:v0 images exist."""
    try:
        import docker  # noqa: PLC0415

        client = docker.from_env()
        tags: set[str] = set()
        for img in client.images.list():
            for tag in img.tags:
                tags.add(tag)
        return "hive-region:v0" in tags and "hive-glia:v0" in tags
    except Exception:  # noqa: BLE001
        return False


def _pfc_has_handlers() -> bool:
    """Return True if prefrontal_cortex/handlers/ has real (non-stub) code.

    The scaffolded __init__.py is exactly one docstring line (~60 chars).
    We consider the directory "ready" when either:
      - __init__.py content (stripped) exceeds 80 characters, OR
      - There is at least one extra .py file beside __init__.py.
    """
    handlers_dir = _REPO_ROOT / "regions" / "prefrontal_cortex" / "handlers"
    init_path = handlers_dir / "__init__.py"
    if not init_path.exists():
        return False
    init_content = init_path.read_text("utf-8")
    if len(init_content.strip()) > _STUB_THRESHOLD_CHARS:
        return True
    extras = [p for p in handlers_dir.glob("*.py") if p.name != "__init__.py"]
    return len(extras) > 0


# ---------------------------------------------------------------------------
# Module-level skip checks (evaluated at collection time)
# ---------------------------------------------------------------------------

# Check 1: Docker
if not _docker_reachable():
    pytest.skip(
        "Docker daemon not available",
        allow_module_level=True,
    )

# Check 2: Required images
if not _required_images_present():
    pytest.skip(
        "Required images not built (need hive-region:v0 and hive-glia:v0)",
        allow_module_level=True,
    )

# Check 3: API key
if not os.environ.get("ANTHROPIC_API_KEY"):
    pytest.skip(
        "Real LLM required (Task 9.3 uses real LLM; no offline stub yet)",
        allow_module_level=True,
    )

# Check 4: PFC handlers
if not _pfc_has_handlers():
    pytest.skip(
        "pfc has no handler for hive/sensory/input/text yet "
        "(handlers/ is still the empty scaffold; un-skip once handlers land)",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensory_input_produces_speech_intent(compose_stack: object) -> None:
    """Inject a sensory text envelope; expect a motor-intent envelope within 15s.

    Flow (spec §I.4):
      1. Connect to the test broker (anonymous auth; compose.test.yaml).
      2. Subscribe to hive/motor/speech/intent at QoS 1.
      3. Publish a valid Envelope on hive/sensory/input/text.
      4. Wait up to 15 s for a response envelope on the motor topic.
      5. Validate the response envelope's content_type.
    """
    # compose_stack is typed as object here because the fixture is defined in
    # tests/conftest.py; the actual type is _ComposeStack but we only need the
    # two attributes below.
    broker_host: str = compose_stack.broker_host  # type: ignore[attr-defined]
    broker_port: int = compose_stack.broker_port  # type: ignore[attr-defined]

    # Give the broker and regions a moment to fully start after compose up.
    await asyncio.sleep(5)

    correlation_id = str(uuid.uuid4())

    envelope = Envelope.new(
        source_region="test_harness",
        topic=_SENSORY_TOPIC,
        content_type="text/plain",
        data="Hello, Hive.",
        correlation_id=correlation_id,
        attention_hint=0.8,
    )

    client_id = f"test_harness_{uuid.uuid4().hex[:8]}"

    async with aiomqtt.Client(
        hostname=broker_host,
        port=broker_port,
        identifier=client_id,
        timeout=10.0,
    ) as client:
        await client.subscribe(_MOTOR_TOPIC, qos=1)

        # Small delay to let SUBACK arrive before we publish.
        await asyncio.sleep(0.3)

        await client.publish(
            _SENSORY_TOPIC,
            payload=envelope.to_json(),
            qos=1,
        )

        try:
            async with asyncio.timeout(_FLOW_TIMEOUT_S):
                async for msg in client.messages:
                    if str(msg.topic) == _MOTOR_TOPIC:
                        response = Envelope.from_json(bytes(msg.payload))
                        assert response.payload.content_type == _EXPECTED_CONTENT_TYPE, (
                            f"Expected content_type={_EXPECTED_CONTENT_TYPE!r}, "
                            f"got {response.payload.content_type!r}"
                        )
                        return  # success
        except TimeoutError:
            pytest.fail(
                f"No {_MOTOR_TOPIC!r} envelope received within {_FLOW_TIMEOUT_S}s. "
                "PFC may not have handler wired for hive/sensory/input/text. "
                "If un-skipped prematurely, reconsider the `_pfc_has_handlers` gate."
            )
