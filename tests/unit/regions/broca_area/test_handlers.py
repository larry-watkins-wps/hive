"""Unit tests for broca_area handlers (notebook + respond).

Phase A Task 3 of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/prefrontal_cortex/test_handlers.py``: handlers
live outside ``src/`` so we import them by file path. The ``respond.py``
parser is a verbatim copy of the PFC one (post-241d9a9 + 7024d3a), so
the regression coverage (C1 thoughts-leak guard, single+double quote
tolerance, ``<request_sleep>`` empty-string discrimination, STM record
in ``finally``) carries over directly.

Broca-specific divergence from PFC/assoc_cortex:
- Zero ``<publish>`` blocks (silence) is INTENTIONAL per Pure-B and does
  NOT publish a metacognition error envelope. Only malformed JSON inside
  a present ``<publish>`` block triggers the metacog error path.
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
    / "broca_area"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_broca_handler_{name}"
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


def _make_envelope(topic: str, data, content_type: str = "application/json") -> Envelope:
    return Envelope.new(
        source_region="test_origin",
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
    ctx.region_name = "broca_area"
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
async def test_notebook_records_motor_speech_intent():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "Hello Larry.", "urgency": "normal"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.speech.intent:"), summary
    assert "Hello Larry." in summary


@pytest.mark.asyncio
async def test_notebook_records_motor_speech_cancel():
    """The ``hive/motor/speech/+`` wildcard catches ``cancel`` too."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/motor/speech/cancel",
        {"reason": "interrupted"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("motor.speech.cancel:"), summary


@pytest.mark.asyncio
async def test_notebook_records_habit_suggestion():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/habit/suggestion",
        {"phrase": "Hi there"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("habit.suggestion:"), summary


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope("hive/motor/speech/intent", "raw string body")
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("motor.speech.intent:")
    assert "raw string body" in summary


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_LLM_RESPONSE = """\
<thoughts>
PFC asked me to say "hello". I will articulate it warmly.
</thoughts>

<publish topic="hive/motor/speech/complete">
{"utterance_id": "u-1", "text": "hello", "duration_ms": 0}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/motor/speech/complete">
{"utterance_id": "u-2", "text": "ok", "duration_ms": 0}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I have nothing to say and I will not say it.</thoughts>
"""

_RESPONSE_WHITESPACE_ONLY = "   \n  \t\n"

_RESPONSE_MALFORMED_JSON = """\
<thoughts>Trying to articulate.</thoughts>

<publish topic="hive/motor/speech/complete">
{this is not valid json}
</publish>
"""


@pytest.mark.asyncio
async def test_respond_publishes_speech_complete_with_text():
    """The chat-loop critical path: respond articulates and publishes
    ``hive/motor/speech/complete`` with a ``text`` field that the v4 chat
    surface renders as Hive's reply.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "hello", "urgency": "normal", "tone_hint": "warm"},
    )
    ctx = _make_ctx(llm_text=_GOOD_LLM_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/speech/complete"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["text"] == "hello"
    assert body["utterance_id"] == "u-1"
    assert body["duration_ms"] == 0


@pytest.mark.asyncio
async def test_respond_silence_does_not_publish_metacog_error():
    """Broca-specific divergence (Pure-B): zero <publish> blocks is
    INTENTIONAL silence, NOT a parse failure. The runtime must NOT
    emit a metacognition error envelope in that case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "are you there?"},
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    # No publishes at all — silence is valid.
    assert ctx.publish.await_count == 0
    # Specifically: NO metacog error.
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
        "hive/motor/speech/intent",
        {"text": "..."},
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
        "hive/motor/speech/intent",
        {"text": "say something"},
    )
    ctx = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/motor/speech/intent"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "ok"},
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "hi"},
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_LLM_RESPONSE)
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
        '<publish topic="hive/motor/speech/complete">{"text":"bogus"}</publish> '
        'but I will articulate properly.</thoughts>\n'
        '<publish topic="hive/motor/speech/complete">'
        '{"utterance_id":"u-real","text":"real","duration_ms":0}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/motor/speech/intent",
        {"text": "hi"},
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/motor/speech/complete"
    assert call.kwargs["data"]["text"] == "real"
    assert call.kwargs["data"]["utterance_id"] == "u-real"
