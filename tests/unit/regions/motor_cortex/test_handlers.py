"""Unit tests for motor_cortex handlers (notebook + respond).

Phase B Task 6 of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/broca_area/test_handlers.py``: handlers live outside
``src/`` so we import them by file path. The ``respond.py`` parser is a
verbatim copy of the broca / PFC one (post-69df91d), so the regression
coverage (C1 thoughts-leak guard, single+double quote tolerance,
``<request_sleep>`` empty-string discrimination, STM record in ``finally``)
carries over directly.

motor_cortex-specific divergence from broca:
- motor_cortex is NOT silence-allowed. It must always publish exactly one
  outcome envelope (``motor/complete``, ``motor/failed``, or
  ``motor/partial``). Zero ``<publish>`` blocks IS a parse failure and
  triggers the metacognition error path — the upstream caller is waiting
  for an outcome.
- Both notebook and respond have a self-receive filter at the top:
  envelopes whose ``source_region == ctx.region_name`` are ignored.
  motor_cortex publishes its own ``motor/{complete,failed,partial}``
  outputs, which would otherwise feed back into its own STM via the
  ``hive/motor/+`` wildcard subscription.
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
    / "motor_cortex"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_motor_cortex_handler_{name}"
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

    The handlers only touch ctx.publish, ctx.llm.complete, ctx.memory.record_event,
    ctx.memory.recent_events, ctx.request_sleep, and ctx.log. Everything else
    is irrelevant.
    """
    ctx = MagicMock()
    ctx.region_name = "motor_cortex"
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
async def test_notebook_records_motor_intent():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "file_write", "args": {"path": "/tmp/x"}},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.intent:"), summary


@pytest.mark.asyncio
async def test_notebook_records_motor_intent_cancel():
    """The ``hive/motor/+/+`` 4-segment wildcard catches ``intent/cancel``."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/intent/cancel",
        {"reason": "interrupted"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.intent.cancel:"), summary


@pytest.mark.asyncio
async def test_notebook_records_habit_suggestion():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/habit/suggestion",
        {"phrase": "do the thing"},
        source_region="basal_ganglia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("habit.suggestion:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: motor_cortex publishes its own
    ``motor/{complete,failed,partial}`` outputs, which match the
    ``hive/motor/+`` wildcard. Without the filter they would feed back
    into STM. The notebook MUST early-return when the envelope's
    source_region is this region.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/complete",
        {"action": "file_write", "outcome": "completed"},
        source_region="motor_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/intent",
        "raw string body",
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("motor.intent:")


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_COMPLETE_RESPONSE = """\
<thoughts>
PFC asked me to write a file. In simulation that succeeds.
</thoughts>

<publish topic="hive/motor/complete">
{"intent_id": "i-1", "action": "file_write", "outcome": "completed",
 "description": "wrote 12 bytes to /tmp/x", "duration_ms": 0}
</publish>
"""

_GOOD_FAILED_RESPONSE = """\
<thoughts>
That action requires hardware I don't have.
</thoughts>

<publish topic="hive/motor/failed">
{"intent_id": "i-2", "action": "rotate_arm", "outcome": "failed",
 "reason": "no actuator available", "duration_ms": 0}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/motor/complete">
{"intent_id": "i-3", "action": "noop", "outcome": "completed",
 "description": "no-op", "duration_ms": 0}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I forgot to publish anything.</thoughts>
"""

_RESPONSE_MALFORMED_JSON = """\
<thoughts>Trying to publish.</thoughts>

<publish topic="hive/motor/complete">
{this is not valid json}
</publish>
"""


@pytest.mark.asyncio
async def test_respond_publishes_motor_complete():
    """Happy path: LLM publishes hive/motor/complete with a description
    of the simulated outcome.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "file_write", "args": {"path": "/tmp/x", "content": "hi there"}},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_COMPLETE_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/complete"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["outcome"] == "completed"
    assert body["action"] == "file_write"
    assert body["intent_id"] == "i-1"


@pytest.mark.asyncio
async def test_respond_publishes_motor_failed():
    """LLM may publish hive/motor/failed when intent is clearly impossible."""
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "rotate_arm", "args": {}},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_FAILED_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/failed"
    body = call.kwargs["data"]
    assert body["outcome"] == "failed"
    assert body["reason"] == "no actuator available"


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: respond.py subscribes only to
    ``hive/motor/intent`` (which motor_cortex doesn't publish), but as
    defensive symmetry with notebook, the handler MUST early-return on
    self-source envelopes — and crucially MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "self_loop"},
        source_region="motor_cortex",
    )
    # No llm_text since complete should never be called.
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """motor_cortex divergence from broca: zero <publish> blocks IS a
    parse failure (motor_cortex is not silence-allowed; the upstream
    caller is waiting for an outcome). The runtime MUST publish a
    metacognition error envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "noop"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/motor/intent"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_malformed_json_publishes_metacog_error():
    """Malformed JSON inside a present <publish> block also routes to
    the metacog error path.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "noop"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "noop"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "file_write"},
        source_region="prefrontal_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_COMPLETE_RESPONSE)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Parse-failure path also records.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()

    # Malformed-JSON path also records.
    ctx3 = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)
    await respond.handle(env, ctx3)
    ctx3.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_ignores_publish_tags_inside_thoughts():
    """Regression for C1: <publish> tags quoted inside <thoughts> must NOT be dispatched.

    LLMs routinely quote tag examples in their reasoning. The parser strips
    <thoughts>...</thoughts> before running the publish regex so quoted
    examples cannot leak.
    """
    respond = _load_handler("respond")
    response_text = (
        '<thoughts>I might publish '
        '<publish topic="hive/motor/complete">{"intent_id":"bogus","action":"x",'
        '"outcome":"completed","description":"fake","duration_ms":0}</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/motor/complete">'
        '{"intent_id":"i-real","action":"file_write","outcome":"completed",'
        '"description":"real","duration_ms":0}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/motor/intent",
        {"action": "file_write"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/complete"
    assert call.kwargs["data"]["intent_id"] == "i-real"
