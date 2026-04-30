"""Unit tests for basal_ganglia handlers (notebook + respond).

Phase B Task 6b of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/motor_cortex/test_handlers.py`` and
``tests/unit/regions/broca_area/test_handlers.py``: handlers live outside
``src/`` so we import them by file path. The ``respond.py`` parser is a
verbatim copy of the broca / motor_cortex template (post-69df91d /
fdc1dc3), so the regression coverage (C1 thoughts-leak guard, single +
double quote tolerance, ``<request_sleep>`` empty-string discrimination,
STM record in ``finally``) carries over directly.

basal_ganglia-specific traits:
- Like broca, basal_ganglia IS silence-allowed. Zero ``<publish>`` blocks
  is the intentional gating decision (the proposal isn't actionable),
  NOT a parse failure. Only malformed JSON inside a present ``<publish>``
  block triggers the metacog error path.
- Both notebook and respond have a self-receive filter at the top:
  envelopes whose ``source_region == ctx.region_name`` are ignored
  (defensive symmetry with motor_cortex).
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
    / "basal_ganglia"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_basal_ganglia_handler_{name}"
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
    ctx.region_name = "basal_ganglia"
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
async def test_notebook_records_sensory():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        {"text": "hello hive"},
        source_region="auditory_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("sensory.auditory.text:"), summary
    assert "hello hive" in summary


@pytest.mark.asyncio
async def test_notebook_records_habit_reinforce():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/habit/reinforce",
        {"action": "say_hello", "magnitude": 0.6},
        source_region="vta",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("habit.reinforce:"), summary


@pytest.mark.asyncio
async def test_notebook_records_habit_suggestion():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/habit/suggestion",
        {"phrase": "do the thing", "confidence": 0.8},
        source_region="basal_ganglia",  # NOTE: self-source — caught by filter below
    )
    # Use a different source for this test so we exercise the record path.
    env = _make_envelope(
        "hive/habit/suggestion",
        {"phrase": "do the thing", "confidence": 0.8},
        source_region="prefrontal_cortex",
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
    """Self-receive filter: basal_ganglia publishes its own
    ``hive/habit/{suggestion,reinforce,learned,extinguished}`` outputs,
    which match the ``hive/habit/+`` wildcard. Without the filter they
    would feed back into STM. The notebook MUST early-return when the
    envelope's source_region is this region.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/habit/suggestion",
        {"phrase": "self echo"},
        source_region="basal_ganglia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        "raw string body",
        source_region="auditory_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("sensory.auditory.text:")
    assert "raw string body" in summary


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_MOTOR_INTENT_RESPONSE = """\
<thoughts>
PFC's plan is actionable — write the file. Habit reinforcement supports
this as a learned pattern. Selecting motor intent.
</thoughts>

<publish topic="hive/motor/intent">
{"action": "file_write", "args": {"path": "/tmp/x", "content": "hi"},
 "rationale": "PFC plan is concrete and habit-reinforced"}
</publish>
"""

_GOOD_SPEECH_INTENT_RESPONSE = """\
<thoughts>
The integration carries a clear utterance proposal. Speech is the right
modality.
</thoughts>

<publish topic="hive/motor/speech/intent">
{"text": "hello there", "rationale": "integration framed as a greeting"}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/motor/intent">
{"action": "noop", "args": {}, "rationale": "trivial selection"}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>The integration is descriptive, not actionable. Decline to act.</thoughts>
"""

_RESPONSE_WHITESPACE_ONLY = "   \n  \t\n"

_RESPONSE_MALFORMED_JSON = """\
<thoughts>Trying to publish.</thoughts>

<publish topic="hive/motor/intent">
{this is not valid json}
</publish>
"""


@pytest.mark.asyncio
async def test_respond_publishes_motor_intent():
    """Happy path: LLM publishes hive/motor/intent based on integration."""
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "write the file", "actionable": True},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_MOTOR_INTENT_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/intent"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["action"] == "file_write"
    assert body["rationale"]


@pytest.mark.asyncio
async def test_respond_publishes_speech_intent():
    """Speech-flavored proposal routes to motor/speech/intent."""
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "user greeted us"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_SPEECH_INTENT_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/speech/intent"
    body = call.kwargs["data"]
    assert body["text"] == "hello there"


@pytest.mark.asyncio
async def test_respond_silence_does_not_publish_metacog_error():
    """basal_ganglia-specific (mirrors broca): zero <publish> blocks is
    the intentional gating decision (the proposal isn't actionable),
    NOT a parse failure. The runtime must NOT emit a metacognition error
    envelope in that case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "purely descriptive observation"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    # No publishes at all — silence is valid gating.
    assert ctx.publish.await_count == 0
    metacog_calls = [
        c for c in ctx.publish.await_args_list
        if c.kwargs.get("topic") == "hive/metacognition/error/detected"
    ]
    assert metacog_calls == []
    # STM still records the envelope (finally block).
    ctx.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_silence_whitespace_only_does_not_publish_metacog_error():
    """Whitespace-only LLM output is also intentional silence."""
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "..."},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WHITESPACE_ONLY)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 0
    ctx.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_malformed_json_publishes_metacog_error():
    """Malformed JSON inside a present <publish> block IS a parse error
    and MUST publish a metacognition error envelope. This is the
    distinction from the silence-is-valid case: a present-but-broken
    block is genuine malformed output, not intentional silence.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "do something"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/cognitive/prefrontal_cortex/plan"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: even though respond's subscriptions don't
    immediately overlap with what basal_ganglia publishes, defensive
    symmetry with notebook means the handler MUST early-return on
    self-source envelopes — and crucially MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/basal_ganglia/integration",
        {"summary": "self echo"},
        source_region="basal_ganglia",
    )
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "noop"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "write file"},
        source_region="prefrontal_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_MOTOR_INTENT_RESPONSE)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Silence path also records (the ``finally`` block).
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
        '<publish topic="hive/motor/intent">{"action":"bogus","args":{},'
        '"rationale":"fake"}</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/motor/intent">'
        '{"action":"file_write","args":{"path":"/tmp/x"},'
        '"rationale":"real selection"}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "write file"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/intent"
    assert call.kwargs["data"]["action"] == "file_write"
    assert call.kwargs["data"]["rationale"] == "real selection"
