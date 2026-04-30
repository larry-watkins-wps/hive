"""Unit tests for VTA handlers (notebook + respond).

Phase B Task 7a of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/motor_cortex/test_handlers.py``: handlers live outside
``src/`` so we import them by file path. The ``respond.py`` parser is a
verbatim copy of the motor_cortex one (post-fdc1dc3), so the regression
coverage (C1 thoughts-leak guard, single+double quote tolerance, STM
record in ``finally``) carries over directly.

VTA-specific notes (per ratified decision 2: VTA is LLM-driven, not
algorithmic):
- VTA is NOT silence-allowed. Every motor outcome MUST produce exactly
  one ``hive/modulator/dopamine`` envelope. Zero ``<publish>`` blocks IS
  a parse failure and triggers the metacognition error path.
- Notebook subs are wildcards (``hive/motor/+`` 3-segment +
  ``hive/motor/+/+`` 4-segment) so the exact-topic respond subscriptions
  don't collide with notebook (the loader allows wildcard-vs-exact
  overlap; only exact-vs-exact across files hard-fails).
- Both handlers have a self-receive filter (skip envelopes whose
  ``source_region == ctx.region_name``). VTA does not currently publish
  motor topics itself, but defensive symmetry mirrors motor_cortex /
  basal_ganglia.
- ``temperature=0.5`` (lower than the cohort's 0.7) since dopamine
  values should be more deterministic than free-form deliberation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from region_template.llm_adapter import CompletionResult
from region_template.token_ledger import TokenUsage
from shared.message_envelope import Envelope

# ---------------------------------------------------------------------------
# Module loading helpers — handlers live outside src/, import by file path.
# ---------------------------------------------------------------------------

REGION_HANDLERS_DIR = (
    Path(__file__).resolve().parents[4]
    / "regions"
    / "vta"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_vta_handler_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None, (
        f"could not load handler at {path}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helpers for building envelopes and ctx mocks.
# ---------------------------------------------------------------------------


def _make_envelope(
    topic: str,
    data,
    *,
    source_region: str = "test_origin",
    content_type: str = "application/json",
) -> Envelope:
    return Envelope.new(
        source_region=source_region,
        topic=topic,
        content_type=content_type,
        data=data,
    )


def _make_ctx(*, llm_text: str | None = None) -> MagicMock:
    """Build a HandlerContext-shaped mock.

    The handlers only touch ctx.publish, ctx.llm.complete,
    ctx.memory.record_event, ctx.memory.recent_events, ctx.request_sleep,
    and ctx.log. Everything else is irrelevant.
    """
    ctx = MagicMock()
    ctx.region_name = "vta"
    ctx.publish = AsyncMock()
    ctx.memory.record_event = AsyncMock()
    ctx.memory.recent_events = AsyncMock(return_value=[])
    ctx.request_sleep = MagicMock()
    ctx.log = structlog.get_logger("test")

    if llm_text is not None:
        result = CompletionResult(
            text=llm_text,
            tool_calls=(),
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=10,
                output_tokens=20,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            model="stub-model",
            cached_prefix_tokens=0,
            elapsed_ms=1,
            raw={},
        )
        ctx.llm.complete = AsyncMock(return_value=result)
    else:
        ctx.llm.complete = AsyncMock()

    return ctx


# ---------------------------------------------------------------------------
# notebook.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notebook_records_motor_complete():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "file_write", "outcome": "completed",
         "description": "wrote 12 bytes"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.complete:"), summary


@pytest.mark.asyncio
async def test_notebook_records_motor_failed():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/failed",
        {"action": "rotate_arm", "outcome": "failed",
         "reason": "no actuator available"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.failed:"), summary


@pytest.mark.asyncio
async def test_notebook_records_motor_speech_complete():
    """The ``hive/motor/+/+`` 4-segment wildcard catches ``speech/complete``."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/speech/complete",
        {"text": "hello world", "duration_ms": 1200, "outcome": "completed"},
        source_region="broca_area",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.speech.complete:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: defensive symmetry with respond.py. VTA does
    not currently publish motor/* topics, but a misrouted self-publish
    or future subscription change should not feed back into STM.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "x", "outcome": "completed"},
        source_region="vta",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/complete",
        "raw string body",
        source_region="motor_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("motor.complete:")


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_DOPAMINE_HIGH = """\
<thoughts>
The action succeeded cleanly. That is rewarding — bump dopamine above
baseline.
</thoughts>

<publish topic="hive/modulator/dopamine">
{"value": 0.7,
 "rationale": "successful file_write outcome — modest positive prediction error",
 "source_outcome": {"topic": "hive/motor/complete", "envelope_id": "env-1"}}
</publish>
"""

_GOOD_DOPAMINE_LOW = """\
<thoughts>
The action failed. That is punishing — drop dopamine below baseline.
</thoughts>

<publish topic="hive/modulator/dopamine">
{"value": 0.1,
 "rationale": "motor/failed — negative prediction error",
 "source_outcome": {"topic": "hive/motor/failed", "envelope_id": "env-2"}}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/modulator/dopamine">
{"value": 0.5,
 "rationale": "neutral outcome, expected",
 "source_outcome": {"topic": "hive/motor/complete", "envelope_id": "env-3"}}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I forgot to emit a dopamine signal.</thoughts>
"""


@pytest.mark.asyncio
async def test_respond_publishes_dopamine_on_motor_complete():
    """Happy path: motor/complete outcome → one hive/modulator/dopamine
    envelope with reasoned value.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "file_write", "outcome": "completed",
         "description": "wrote 12 bytes"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_DOPAMINE_HIGH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/modulator/dopamine"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["value"] == 0.7  # noqa: PLR2004
    assert "rationale" in body
    assert body["source_outcome"]["topic"] == "hive/motor/complete"


@pytest.mark.asyncio
async def test_respond_publishes_dopamine_on_motor_failed():
    """motor/failed outcome → one hive/modulator/dopamine envelope with
    a low value (negative prediction error).
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/failed",
        {"action": "rotate_arm", "outcome": "failed",
         "reason": "no actuator available"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_DOPAMINE_LOW)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/modulator/dopamine"
    body = call.kwargs["data"]
    assert body["value"] == 0.1  # noqa: PLR2004
    assert body["source_outcome"]["topic"] == "hive/motor/failed"


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: defensive symmetry with notebook.py. The
    handler MUST early-return on self-source envelopes — and crucially
    MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "self_loop", "outcome": "completed"},
        source_region="vta",
    )
    # No llm_text since complete should never be called.
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """VTA divergence from broca/basal_ganglia: zero <publish> blocks IS
    a parse failure (VTA is NOT silence-allowed; every motor outcome
    must produce a dopamine signal — even a low one). The runtime MUST
    publish a metacognition error envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "noop", "outcome": "completed"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/motor/complete"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "noop", "outcome": "completed"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    """STM record runs in ``finally`` — both happy path and parse-failure
    path record.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "file_write", "outcome": "completed"},
        source_region="motor_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_DOPAMINE_HIGH)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Parse-failure path also records.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_ignores_publish_tags_inside_thoughts():
    """Regression for C1: <publish> tags quoted inside <thoughts> must
    NOT be dispatched. LLMs routinely quote tag examples in their
    reasoning. The parser strips <thoughts>...</thoughts> before running
    the publish regex so quoted examples cannot leak.
    """
    respond = _load_handler("respond")
    response_text = (
        '<thoughts>I might publish '
        '<publish topic="hive/modulator/dopamine">{"value":0.99,'
        '"rationale":"fake","source_outcome":{"topic":"x","envelope_id":"y"}}'
        '</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/modulator/dopamine">'
        '{"value":0.6,"rationale":"real",'
        '"source_outcome":{"topic":"hive/motor/complete","envelope_id":"env-real"}}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "file_write", "outcome": "completed"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/modulator/dopamine"
    assert call.kwargs["data"]["value"] == 0.6  # noqa: PLR2004
    assert call.kwargs["data"]["source_outcome"]["envelope_id"] == "env-real"
