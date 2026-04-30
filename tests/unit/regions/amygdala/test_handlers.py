"""Unit tests for amygdala handlers (notebook + respond).

Phase B Task 7b of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/motor_cortex/test_handlers.py``: handlers live
outside ``src/`` so we import them by file path. The ``respond.py``
parser is a verbatim copy of motor_cortex's (commit fdc1dc3), so the
regression coverage (C1 thoughts-leak guard, single+double quote
tolerance, ``<request_sleep>`` empty-string discrimination, STM record
in ``finally``) carries over directly.

amygdala-specific divergence from broca:
- amygdala is NOT silence-allowed. Every input MUST produce at least
  one ``hive/cognitive/amygdala/threat_assessment`` envelope (even when
  threat_score=0). Zero ``<publish>`` blocks IS a parse failure and
  triggers the metacognition error path.
- Dual-output pattern: when threat_score > 0.3 the LLM ALSO publishes
  ``hive/modulator/cortisol``. The handler does not gate this — it
  dispatches every <publish> block the LLM emits. The threshold lives in
  the prompt.
- Both notebook and respond have a self-receive filter at the top:
  envelopes whose ``source_region == ctx.region_name`` are ignored.
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
    / "amygdala"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_amygdala_handler_{name}"
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
    ctx.region_name = "amygdala"
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
        {"text": "hello there", "source": "chat"},
        source_region="glia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("external.perception:"), summary


@pytest.mark.asyncio
async def test_notebook_records_sensory_visual_processed():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/visual/processed",
        {"label": "face", "novelty": 0.7},
        source_region="visual_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("sensory.visual.processed:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_hippocampus_response():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/hippocampus/response",
        {"summary": "matched prior safe context"},
        source_region="hippocampus",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.hippocampus.response:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: even though amygdala's current subscriptions
    don't overlap with its own publishes today, the handler MUST
    early-return on self-source envelopes (defensive symmetry with the
    rest of the handler cohort).
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/sensory/visual/processed",  # any subscribed topic
        {"label": "test"},
        source_region="amygdala",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/external/perception",
        "raw string body",
        source_region="glia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("external.perception:")


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_ASSESSMENT_ONLY_RESPONSE = """\
<thoughts>
Chat greeting. No threat indicators. Score 0 with kind "none".
</thoughts>

<publish topic="hive/cognitive/amygdala/threat_assessment">
{"threat_score": 0.0, "threat_kind": "none",
 "rationale": "neutral greeting, no threat content",
 "source_input": {"topic": "hive/external/perception", "envelope_id": "e-1"}}
</publish>
"""

_HIGH_THREAT_RESPONSE = """\
<thoughts>
Audio text contains overt aggression. Elevate cortisol.
</thoughts>

<publish topic="hive/cognitive/amygdala/threat_assessment">
{"threat_score": 0.8, "threat_kind": "social",
 "rationale": "overtly aggressive language detected",
 "source_input": {"topic": "hive/sensory/auditory/text", "envelope_id": "e-2"}}
</publish>

<publish topic="hive/modulator/cortisol">
{"value": 0.7, "source_threat": {"envelope_id": "e-2"}}
</publish>
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I forgot to publish anything.</thoughts>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/cognitive/amygdala/threat_assessment">
{"threat_score": 0.0, "threat_kind": "none",
 "rationale": "ambient",
 "source_input": {"topic": "hive/external/perception", "envelope_id": "e-3"}}
</publish>

<request_sleep reason="STM overloaded" />
"""


@pytest.mark.asyncio
async def test_respond_publishes_threat_assessment_on_external_perception():
    """Happy path, low threat: LLM emits ONLY the threat_assessment
    envelope (threat_score=0, no cortisol). Handler dispatches it.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hello there"},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_ASSESSMENT_ONLY_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/amygdala/threat_assessment"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["threat_score"] == 0.0
    assert body["threat_kind"] == "none"
    assert "rationale" in body
    assert body["source_input"]["envelope_id"] == "e-1"


@pytest.mark.asyncio
async def test_respond_publishes_cortisol_when_threat_high():
    """Dual-output: when threat_score > 0.3 the LLM emits BOTH the
    threat_assessment AND cortisol. The handler dispatches both blocks.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/sensory/auditory/text",
        {"text": "I will hurt you"},
        source_region="auditory_cortex",
    )
    ctx = _make_ctx(llm_text=_HIGH_THREAT_RESPONSE)

    await respond.handle(env, ctx)

    expected_publish_count = 2  # threat_assessment + cortisol
    assert ctx.publish.await_count == expected_publish_count
    topics = [c.kwargs["topic"] for c in ctx.publish.await_args_list]
    assert "hive/cognitive/amygdala/threat_assessment" in topics
    assert "hive/modulator/cortisol" in topics

    # Find the cortisol publish and verify the value scales with threat.
    cortisol_call = next(
        c
        for c in ctx.publish.await_args_list
        if c.kwargs["topic"] == "hive/modulator/cortisol"
    )
    expected_cortisol_value = 0.7  # serious-threat band per prompt rules
    assert cortisol_call.kwargs["data"]["value"] == expected_cortisol_value
    assert cortisol_call.kwargs["data"]["source_threat"]["envelope_id"] == "e-2"


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: respond.py's subscriptions don't include
    amygdala's own publishes today, but as defensive symmetry with
    notebook the handler MUST early-return on self-source envelopes —
    and crucially MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "self-loop probe"},
        source_region="amygdala",
    )
    ctx = _make_ctx()  # no llm_text — complete must not be called

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """amygdala is NOT silence-allowed: every input must produce at
    least the threat_assessment envelope. Zero <publish> blocks IS a
    parse failure and routes to the metacognition error topic.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hello"},
        source_region="glia",
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
        {"text": "hi"},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    """STM record happens in ``finally`` — across success, parse-failure,
    and malformed-JSON paths.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hi"},
        source_region="glia",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_ASSESSMENT_ONLY_RESPONSE)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Parse-failure path also records.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()

    # Malformed-JSON path also records.
    malformed = (
        '<thoughts>Trying to publish.</thoughts>\n'
        '<publish topic="hive/cognitive/amygdala/threat_assessment">'
        '{this is not valid json}</publish>'
    )
    ctx3 = _make_ctx(llm_text=malformed)
    await respond.handle(env, ctx3)
    ctx3.memory.record_event.assert_awaited_once()
    # And it routes to metacog error.
    assert ctx3.publish.await_count == 1
    assert (
        ctx3.publish.await_args_list[0].kwargs["topic"]
        == "hive/metacognition/error/detected"
    )


@pytest.mark.asyncio
async def test_respond_ignores_publish_tags_inside_thoughts():
    """Regression for C1: <publish> tags quoted inside <thoughts> must
    NOT be dispatched. LLMs routinely quote tag examples in their
    reasoning; the parser strips <thoughts>...</thoughts> before running
    the publish regex so quoted examples cannot leak.
    """
    respond = _load_handler("respond")
    response_text = (
        '<thoughts>I might publish '
        '<publish topic="hive/cognitive/amygdala/threat_assessment">'
        '{"threat_score":0.99,"threat_kind":"BOGUS","rationale":"fake",'
        '"source_input":{"topic":"x","envelope_id":"x"}}</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/cognitive/amygdala/threat_assessment">'
        '{"threat_score":0.0,"threat_kind":"none","rationale":"real",'
        '"source_input":{"topic":"hive/external/perception","envelope_id":"e-real"}}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/external/perception",
        {"text": "hi"},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/cognitive/amygdala/threat_assessment"
    assert call.kwargs["data"]["threat_kind"] == "none"
    assert call.kwargs["data"]["source_input"]["envelope_id"] == "e-real"
