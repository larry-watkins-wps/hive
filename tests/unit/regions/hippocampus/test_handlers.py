"""Unit tests for hippocampus handlers (notebook + respond).

Phase A Task 4 of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/broca_area/test_handlers.py`` and the PFC /
association_cortex test files. Handlers live outside ``src/`` so we
import them by file path. The ``respond.py`` parser is a verbatim copy
of the PFC / broca / assoc_cortex one (post-241d9a9 + 7024d3a + 19e035a),
so the regression coverage (C1 thoughts-leak guard, single+double quote
tolerance, ``<request_sleep>`` empty-string discrimination, STM record
in ``finally``) carries over directly.

Hippocampus-specific divergence from PFC/assoc_cortex/broca:
- Dual-purpose respond handler: episodic encoding on most envelopes,
  query response on ``hive/cognitive/hippocampus/query``.
- NOT silence-allowed like broca — encoding/responding is its job.
  Zero ``<publish>`` blocks IS a parse error and DOES emit a metacog
  error envelope.
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
    / "hippocampus"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_hippocampus_handler_{name}"
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

    The handlers only touch ctx.publish, ctx.llm.complete,
    ctx.memory.record_event, ctx.memory.recent_events,
    ctx.request_sleep, and ctx.log. Everything else is irrelevant.
    """
    ctx = MagicMock()
    ctx.region_name = "hippocampus"
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
        {"text": "Larry says hello.", "speaker": "larry"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("external.perception:"), summary
    assert "Larry says hello." in summary


@pytest.mark.asyncio
async def test_notebook_records_sensory_auditory_text():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        {"text": "the quick brown fox"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("sensory.auditory.text:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_integration():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"text": "synthesis of modalities", "modalities_integrated": ["auditory"]},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.association_cortex.integration:"), summary


@pytest.mark.asyncio
async def test_notebook_records_metacognition_reflection_response():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/reflection/response",
        {"text": "ACC reflected on errors"},
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("metacognition.reflection.response:"), summary


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
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


_GOOD_ENCODING_RESPONSE = """\
<thoughts>
Larry just spoke. I'll encode this as a neutral episodic event since
amygdala threat assessments are not flowing yet.
</thoughts>

<publish topic="hive/cognitive/hippocampus/episode">
{
  "envelope_id_encoded": "env-1",
  "summary": "Larry greeted Hive",
  "emotional_tag": "neutral",
  "salience": 0.4,
  "modality": "external",
  "actors": ["larry"]
}
</publish>
"""

_GOOD_QUERY_RESPONSE = """\
<thoughts>
PFC asked what Larry said earlier. I'll return the matching episode.
</thoughts>

<publish topic="hive/cognitive/hippocampus/response">
{
  "query_id": "q-1",
  "results": [
    {"summary": "Larry greeted Hive", "ts": "2026-04-29T12:00:00Z", "salience": 0.4}
  ]
}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/cognitive/hippocampus/episode">
{"envelope_id_encoded": "env-2", "summary": "x",
 "emotional_tag": "neutral", "salience": 0.1,
 "modality": "external", "actors": []}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I have nothing to encode.</thoughts>
"""


@pytest.mark.asyncio
async def test_respond_encodes_episode_on_external_perception():
    """The encoding path: respond on a non-query envelope publishes an
    episode block on ``hive/cognitive/hippocampus/episode``.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hello", "speaker": "larry"},
    )
    ctx = _make_ctx(llm_text=_GOOD_ENCODING_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/hippocampus/episode"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["summary"] == "Larry greeted Hive"
    assert body["emotional_tag"] == "neutral"
    assert body["modality"] == "external"


@pytest.mark.asyncio
async def test_respond_responds_on_query():
    """The query-response path: respond on a hippocampus/query envelope
    publishes a response block on ``hive/cognitive/hippocampus/response``.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/hippocampus/query",
        {"query_id": "q-1", "query_text": "what did larry say?"},
    )
    ctx = _make_ctx(llm_text=_GOOD_QUERY_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/hippocampus/response"
    body = call.kwargs["data"]
    assert body["query_id"] == "q-1"
    assert isinstance(body["results"], list)
    assert body["results"][0]["summary"] == "Larry greeted Hive"


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """Hippocampus is NOT silence-allowed (unlike broca). Zero <publish>
    blocks IS a parse failure and MUST emit a metacog error envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "encode me"},
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/external/perception"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "ok"},
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")

    # Encoding success path records.
    env1 = _make_envelope("hive/external/perception", {"text": "hi"})
    ctx = _make_ctx(llm_text=_GOOD_ENCODING_RESPONSE)
    await respond.handle(env1, ctx)
    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("encoded:"), summary

    # Query-response success path records with the query-responded summary.
    env2 = _make_envelope(
        "hive/cognitive/hippocampus/query",
        {"query_id": "q-1", "query_text": "what?"},
    )
    ctx2 = _make_ctx(llm_text=_GOOD_QUERY_RESPONSE)
    await respond.handle(env2, ctx2)
    ctx2.memory.record_event.assert_awaited_once()
    args2, kwargs2 = ctx2.memory.record_event.await_args
    summary2 = kwargs2.get("summary", args2[1] if len(args2) > 1 else None)
    assert summary2 is not None
    assert summary2.startswith("query_responded:"), summary2

    # Parse-failure path also records (the ``finally`` block).
    env3 = _make_envelope("hive/external/perception", {"text": "x"})
    ctx3 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env3, ctx3)
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
        '<publish topic="hive/cognitive/hippocampus/episode">{"summary":"bogus"}</publish> '
        'but I will encode properly.</thoughts>\n'
        '<publish topic="hive/cognitive/hippocampus/episode">'
        '{"envelope_id_encoded":"env-real","summary":"real episode",'
        '"emotional_tag":"neutral","salience":0.2,"modality":"external","actors":[]}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hi"},
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/hippocampus/episode"
    assert call.kwargs["data"]["summary"] == "real episode"
    assert call.kwargs["data"]["envelope_id_encoded"] == "env-real"
