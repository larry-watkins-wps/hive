"""Unit tests for thalamus handlers (notebook + respond).

Phase B Task 9 (region 1 of 3) of the handler bootstrap plan. Mirrors
the structure of ``tests/unit/regions/vta/test_handlers.py``: handlers
live outside ``src/`` so we import them by file path. The ``respond.py``
parser is a verbatim copy of VTA's (post-f99b812), so the regression
coverage (C1 thoughts-leak guard, single+double quote tolerance, STM
record in ``finally``) carries over directly.

thalamus-specific notes:
- thalamus IS silence-allowed (mirrors basal_ganglia / broca). Zero
  ``<publish>`` blocks is the intentional "no routing hint needed"
  decision, NOT a parse failure. Only malformed JSON inside a present
  ``<publish>`` block triggers the metacog error path.
- Notebook subs are wildcards (``hive/sensory/+/+``,
  ``hive/sensory/+/+/+``, ``hive/cognitive/thalamus/+``,
  ``hive/cognitive/+/integration``). respond uses one exact topic
  (``hive/cognitive/thalamus/route_request``) plus the wildcard
  ``hive/cognitive/+/integration`` — wildcard-vs-wildcard and
  wildcard-vs-exact overlaps are allowed by the loader.
- Both handlers have a self-receive filter (skip envelopes whose
  ``source_region == ctx.region_name``). thalamus publishes
  ``hive/cognitive/thalamus/route`` so the wildcard
  ``hive/cognitive/thalamus/+`` would otherwise loop.
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
    / "thalamus"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_thalamus_handler_{name}"
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
    ctx.region_name = "thalamus"
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
async def test_notebook_records_sensory_three_segment():
    """``hive/sensory/+/+`` 3-segment wildcard catches ``auditory/text``."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        {"text": "hello world", "channel": "auditory_cortex.stub"},
        source_region="auditory_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("sensory.auditory.text:"), summary


@pytest.mark.asyncio
async def test_notebook_records_sensory_four_segment():
    """``hive/sensory/+/+/+`` 4-segment wildcard catches deeper subtopics."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/visual/scene/objects",
        {"summary": "two people, one chair"},
        source_region="visual_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("sensory.visual.scene:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_thalamus_directed():
    """``hive/cognitive/thalamus/+`` catches directed traffic."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/thalamus/route_request",
        {"reason": "PFC needs help routing this", "summary": "ambiguous input"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.thalamus.route_request:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_integration():
    """``hive/cognitive/+/integration`` catches integration outputs."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "auditory + visual converge on greeting"},
        source_region="association_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.association_cortex.integration:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: thalamus publishes
    ``hive/cognitive/thalamus/route`` which the wildcard
    ``hive/cognitive/thalamus/+`` would otherwise feed back into STM.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/thalamus/route",
        {"target_region": "amygdala", "rationale": "self echo"},
        source_region="thalamus",
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


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_ROUTE = """\
<thoughts>
This integration output is unusual — association_cortex flagged a
threat-shaped pattern but didn't escalate. amygdala should attend.
</thoughts>

<publish topic="hive/cognitive/thalamus/route">
{"target_region": "amygdala",
 "rationale": "threat-shaped pattern in integration; amygdala should attend",
 "source_envelope": {"topic": "hive/cognitive/association_cortex/integration",
                     "envelope_id": "env-1"}}
</publish>
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>This integration output is routine and routes itself via existing
topic conventions. No hint needed.</thoughts>
"""

_RESPONSE_WHITESPACE_ONLY = "   \n\n   \n"

_RESPONSE_MALFORMED_JSON = """\
<thoughts>I want to route this but my JSON is broken.</thoughts>

<publish topic="hive/cognitive/thalamus/route">
{this is not valid json
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/cognitive/thalamus/route">
{"target_region": "hippocampus",
 "rationale": "novel pattern worth encoding",
 "source_envelope": {"topic": "hive/cognitive/association_cortex/integration",
                     "envelope_id": "env-3"}}
</publish>

<request_sleep reason="STM overloaded" />
"""


@pytest.mark.asyncio
async def test_respond_publishes_route_when_ambiguous():
    """Happy path: ambiguous integration output → one
    hive/cognitive/thalamus/route envelope hinting a target region.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "fast-onset loud sound paired with stranger face"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_ROUTE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/thalamus/route"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["target_region"] == "amygdala"
    assert "rationale" in body
    assert body["source_envelope"]["topic"] == (
        "hive/cognitive/association_cortex/integration"
    )


@pytest.mark.asyncio
async def test_respond_silence_does_not_publish_metacog_error():
    """thalamus-specific (mirrors basal_ganglia / broca): zero
    <publish> blocks is the intentional "no routing hint needed"
    decision, NOT a parse failure. The runtime must NOT emit a
    metacognition error envelope in that case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "purely descriptive observation"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

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
        "hive/cognitive/thalamus/route_request",
        {"reason": "noisy"},
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
        "hive/cognitive/thalamus/route_request",
        {"reason": "needs routing"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/cognitive/thalamus/route_request"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: defensive symmetry with notebook.py. The
    handler MUST early-return on self-source envelopes — and crucially
    MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/thalamus/integration",
        {"summary": "self echo"},
        source_region="thalamus",
    )
    # No llm_text since complete should never be called.
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_request_sleep_invokes_ctx():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "novel pattern"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    """STM record runs in ``finally`` — happy path, silence path, and
    parse-failure path all record.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "x"},
        source_region="association_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_ROUTE)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Silence path also records.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()

    # Parse-failure (malformed JSON) path also records.
    ctx3 = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)
    await respond.handle(env, ctx3)
    ctx3.memory.record_event.assert_awaited_once()


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
        '<publish topic="hive/cognitive/thalamus/route">'
        '{"target_region":"amygdala","rationale":"fake",'
        '"source_envelope":{"topic":"x","envelope_id":"y"}}'
        '</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/cognitive/thalamus/route">'
        '{"target_region":"hippocampus","rationale":"real",'
        '"source_envelope":{"topic":"hive/cognitive/association_cortex/integration",'
        '"envelope_id":"env-real"}}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "ambiguous"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/thalamus/route"
    assert call.kwargs["data"]["target_region"] == "hippocampus"
    assert call.kwargs["data"]["source_envelope"]["envelope_id"] == "env-real"


@pytest.mark.asyncio
async def test_respond_accepts_single_quoted_topic():
    """Both double quotes (canonical) and single quotes are accepted
    around the topic attribute. Real LLMs occasionally emit
    ``topic='...'`` and routing those to the metacog error path is
    unnecessarily strict.
    """
    respond = _load_handler("respond")
    response_text = (
        "<thoughts>quotes vary</thoughts>\n"
        "<publish topic='hive/cognitive/thalamus/route'>"
        '{"target_region":"amygdala","rationale":"single-quoted topic",'
        '"source_envelope":{"topic":"x","envelope_id":"y"}}'
        "</publish>"
    )
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "x"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/thalamus/route"
    assert call.kwargs["data"]["target_region"] == "amygdala"
