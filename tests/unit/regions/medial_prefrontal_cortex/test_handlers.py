"""Unit tests for mPFC handlers (notebook + respond).

Phase B Task 8c of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/vta/test_handlers.py``: handlers live outside
``src/`` so we import them by file path. The ``respond.py`` parser is a
verbatim copy of the VTA one (post-f99b812), so the regression coverage
(C1 thoughts-leak guard, single+double quote tolerance, STM record in
``finally``) carries over directly.

mPFC-specific notes:
- mPFC is **NOT silence-allowed**. Every reflection request MUST produce
  exactly one ``hive/metacognition/reflection/response`` envelope. Zero
  ``<publish>`` blocks IS a parse failure and triggers the metacognition
  error path.
- Notebook subs are ``hive/metacognition/reflection/+`` (wildcard) +
  ``hive/cognitive/medial_prefrontal_cortex/+``. The wildcard avoids
  exact-topic collision with respond.py's
  ``hive/metacognition/reflection/request`` exact subscription (the
  loader allows wildcard-vs-exact overlap; only exact-vs-exact across
  files hard-fails).
- Both handlers have a self-receive filter (skip envelopes whose
  ``source_region == ctx.region_name``). mPFC publishes
  ``hive/metacognition/reflection/response`` itself, so the
  ``reflection/+`` wildcard in notebook would otherwise feed our own
  outputs back into STM.
- ``temperature=0.6`` (between VTA's 0.5 and the cohort's 0.7) since
  reflection should feel considered but still allow personality
  variance.
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
    / "medial_prefrontal_cortex"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_mpfc_handler_{name}"
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
    ctx.region_name = "medial_prefrontal_cortex"
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
async def test_notebook_records_reflection_request():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {
            "request_id": "req-1",
            "trigger": "cycle_complete",
            "topic_to_reflect_on": "recent_decisions",
            "observation": "PFC chose curiosity over caution three cycles in a row",
        },
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("metacognition.reflection.request:"), summary


@pytest.mark.asyncio
async def test_notebook_records_reflection_response():
    """The ``hive/metacognition/reflection/+`` wildcard catches
    ``response`` (which other regions may publish in echo / observation
    flows, and which mPFC also wants in STM as long as it isn't its own).
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/reflection/response",
        {
            "request_id": "req-1",
            "reflection": "the pattern is consistent with the curious value",
            "confidence": 0.7,
            "follow_up_recommended": "",
        },
        source_region="some_other_region",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("metacognition.reflection.response:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: mPFC publishes
    ``hive/metacognition/reflection/response`` itself, so the
    ``reflection/+`` wildcard would otherwise feed our own outputs back
    into STM.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/reflection/response",
        {"reflection": "self-loop should be filtered"},
        source_region="medial_prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/medial_prefrontal_cortex/note",
        "raw string body",
        source_region="anterior_cingulate",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("cognitive.medial_prefrontal_cortex.note:")


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_REFLECTION = """\
<thoughts>
The pattern in STM suggests the curious value is doing real work.
</thoughts>

<publish topic="hive/metacognition/reflection/response">
{"request_id": "req-1",
 "reflection": "Hive has chosen exploration this cycle. Coheres with 'curious' value.",
 "confidence": 0.7,
 "follow_up_recommended": ""}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/metacognition/reflection/response">
{"request_id": "req-2",
 "reflection": "I notice my STM is dense. Reflection quality is starting to suffer.",
 "confidence": 0.5,
 "follow_up_recommended": "consolidate before continuing"}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I am uncertain how to reflect on this and will say nothing.</thoughts>
"""


@pytest.mark.asyncio
async def test_respond_publishes_reflection_response():
    """Happy path: reflection request → exactly one
    ``hive/metacognition/reflection/response`` envelope with
    request_id, reflection text, confidence, and follow_up.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {
            "request_id": "req-1",
            "trigger": "cycle_complete",
            "topic_to_reflect_on": "recent_decisions",
            "observation": "PFC chose curiosity three cycles in a row",
        },
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_REFLECTION)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/reflection/response"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["request_id"] == "req-1"
    assert "reflection" in body
    assert body["confidence"] == 0.7  # noqa: PLR2004
    assert "follow_up_recommended" in body


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: defensive symmetry with notebook.py. The
    handler MUST early-return on self-source envelopes — and crucially
    MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {"request_id": "self-loop", "topic_to_reflect_on": "x"},
        source_region="medial_prefrontal_cortex",
    )
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """mPFC is NOT silence-allowed: zero <publish> blocks IS a parse
    failure (every reflection request must produce a response). The
    runtime MUST publish a metacognition error envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {"request_id": "req-3", "topic_to_reflect_on": "x"},
        source_region="anterior_cingulate",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/metacognition/reflection/request"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {"request_id": "req-2", "topic_to_reflect_on": "stm_density"},
        source_region="prefrontal_cortex",
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
        "hive/metacognition/reflection/request",
        {"request_id": "req-1", "topic_to_reflect_on": "x"},
        source_region="prefrontal_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_REFLECTION)
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
        '<publish topic="hive/metacognition/reflection/response">'
        '{"request_id":"fake","reflection":"fake","confidence":0.99,'
        '"follow_up_recommended":""}'
        '</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/metacognition/reflection/response">'
        '{"request_id":"req-real","reflection":"real reflection",'
        '"confidence":0.6,"follow_up_recommended":""}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/metacognition/reflection/request",
        {"request_id": "req-real", "topic_to_reflect_on": "x"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/reflection/response"
    assert call.kwargs["data"]["request_id"] == "req-real"
    assert call.kwargs["data"]["confidence"] == 0.6  # noqa: PLR2004
