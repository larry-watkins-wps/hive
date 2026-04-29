"""Unit tests for association_cortex handlers (notebook + respond).

Phase A Task 1 of the handler bootstrap plan. No LLM fixtures (ratified
decision 3): we stub ``ctx.llm.complete`` only when verifying purely
structural parser/publisher behaviour.
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
    / "association_cortex"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_assoc_handler_{name}"
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
    ctx.region_name = "association_cortex"
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
async def test_notebook_records_external_perception():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "Hello, are you there?", "speaker": "Larry"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("external.perception:"), summary
    assert "Hello, are you there?" in summary


@pytest.mark.asyncio
async def test_notebook_records_sensory_auditory_text():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        {"text": "the sound of one hand clapping"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("sensory.auditory.text:"), summary


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    # content_type still "application/json" but data is a bare string —
    # the handler must not crash and must record something stringy.
    env = _make_envelope("hive/external/perception", "raw string body")
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("external.perception:")
    assert "raw string body" in summary


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_LLM_RESPONSE = """\
<thoughts>
Larry just said hello — first contact. I should integrate and reply.
</thoughts>

<publish topic="hive/cognitive/association_cortex/integration">
{"text": "First contact from Larry.", "modalities_integrated": ["external"], "confidence": 0.9}
</publish>

<publish topic="hive/motor/speech/intent">
{"text": "Hello Larry."}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>tired.</thoughts>

<publish topic="hive/cognitive/association_cortex/integration">
{"text": "ok", "modalities_integrated": [], "confidence": 0.1}
</publish>

<request_sleep reason="STM is filling fast" />
"""

_RESPONSE_WITH_BAD_JSON = """\
<thoughts>broken.</thoughts>

<publish topic="hive/cognitive/association_cortex/integration">
{not valid json at all}
</publish>
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I have nothing to say and I will not say it.</thoughts>
"""


@pytest.mark.asyncio
async def test_respond_parses_publish_blocks():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "Hello", "speaker": "Larry"},
    )
    ctx = _make_ctx(llm_text=_GOOD_LLM_RESPONSE)

    await respond.handle(env, ctx)

    # Two <publish> blocks → two ctx.publish awaits.
    assert ctx.publish.await_count == 2  # noqa: PLR2004
    topics = [call.kwargs["topic"] for call in ctx.publish.await_args_list]
    assert "hive/cognitive/association_cortex/integration" in topics
    assert "hive/motor/speech/intent" in topics

    # JSON bodies parsed into dicts.
    by_topic = {call.kwargs["topic"]: call.kwargs["data"] for call in ctx.publish.await_args_list}
    integration = by_topic["hive/cognitive/association_cortex/integration"]
    assert integration["text"] == "First contact from Larry."
    assert integration["confidence"] == 0.9  # noqa: PLR2004
    assert by_topic["hive/motor/speech/intent"] == {"text": "Hello Larry."}

    # content_type is application/json on every publish.
    for call in ctx.publish.await_args_list:
        assert call.kwargs["content_type"] == "application/json"


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope("hive/external/perception", {"text": "hi"})
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM is filling fast")


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error_bad_json():
    respond = _load_handler("respond")
    env = _make_envelope("hive/external/perception", {"text": "hi"})
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_BAD_JSON)

    await respond.handle(env, ctx)

    # Exactly one publish, to the metacog error topic.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/external/perception"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error_no_publish():
    respond = _load_handler("respond")
    env = _make_envelope("hive/external/perception", {"text": "hi"})
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")
    env = _make_envelope("hive/external/perception", {"text": "hi"})
    ctx = _make_ctx(llm_text=_GOOD_LLM_RESPONSE)

    await respond.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    # Even on parse failure, STM bookkeeping still happens.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()
