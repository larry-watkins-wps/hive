"""Unit tests for anterior_cingulate handlers (notebook + respond).

Phase B Task 8b of the handler bootstrap plan. Mirrors the structure of
``tests/unit/regions/basal_ganglia/test_handlers.py`` and
``tests/unit/regions/vta/test_handlers.py``: handlers live outside
``src/`` so we import them by file path. The ``respond.py`` parser is a
verbatim copy of the VTA / basal_ganglia / motor_cortex template
(post-f99b812 / 9393bd7 / fdc1dc3), so the regression coverage (C1
thoughts-leak guard, single + double quote tolerance,
``<request_sleep>`` empty-string discrimination, STM record in
``finally``) carries over directly.

ACC-specific traits:
- Like broca / basal_ganglia, ACC IS silence-allowed. Zero ``<publish>``
  blocks is the intentional "no conflict here" decision (most envelopes
  do not conflict with anything in recent STM), NOT a parse failure.
  Only malformed JSON inside a present ``<publish>`` block triggers the
  metacog error path.
- Both notebook and respond have a self-receive filter at the top:
  envelopes whose ``source_region == ctx.region_name`` are ignored.
  ACC publishes ``hive/metacognition/conflict/detected`` and historically
  other ``hive/metacognition/*`` outputs which match the
  ``hive/metacognition/+/+`` wildcard — the filter prevents feedback.
- ``temperature=0.5`` (lower than the cohort's 0.7) since
  conflict-detection judgements should be consistent across runs.
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
    / "anterior_cingulate"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_anterior_cingulate_handler_{name}"
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
    ctx.region_name = "anterior_cingulate"
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
async def test_notebook_records_metacognition_error():
    """``hive/metacognition/+/+`` catches ``error/detected`` from any region."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/error/detected",
        {"kind": "llm_parse_failure", "topic": "hive/cognitive/x/y"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("metacognition.error.detected:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_integration():
    """``hive/cognitive/+/+`` catches integration outputs from any cortex."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "user is asking a question"},
        source_region="association_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.association_cortex.integration:"), summary
    assert "user is asking" in summary


@pytest.mark.asyncio
async def test_notebook_records_spawn_proposed():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/system/spawn/proposed",
        {"name": "olfactory_cortex", "role": "smell modality",
         "rationale": "olfactory inputs lack a dedicated cortex"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("system.spawn.proposed:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: ACC publishes
    ``hive/metacognition/conflict/detected`` (and historically other
    ``hive/metacognition/*`` outputs), which match the
    ``hive/metacognition/+/+`` wildcard. Without the filter they would
    feed back into STM. The notebook MUST early-return when the
    envelope's source_region is this region.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/metacognition/conflict/detected",
        {"conflict_kind": "self_echo", "severity": 0.5,
         "rationale": "self echo", "conflicting_envelopes": []},
        source_region="anterior_cingulate",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        "raw string body",
        source_region="association_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("cognitive.association_cortex.integration:")
    assert "raw string body" in summary


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_CONFLICT_RESPONSE = """\
<thoughts>
The current PFC plan says the user wants nothing, but the prior
assoc_cortex integration said the user is asking a question. That's a
direct intent disagreement — flag it.
</thoughts>

<publish topic="hive/metacognition/conflict/detected">
{"conflict_kind": "intent_disagreement",
 "severity": 0.7,
 "rationale": "PFC plan dismisses a user request that assoc_cortex flagged as a question",
 "conflicting_envelopes": [
   {"topic": "hive/cognitive/prefrontal_cortex/plan",
    "envelope_id": "env-cur",
    "summary": "user wants nothing"},
   {"topic": "hive/cognitive/association_cortex/integration",
    "envelope_id": "env-prior",
    "summary": "user is asking a question"}
 ]}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/metacognition/conflict/detected">
{"conflict_kind": "intent_disagreement",
 "severity": 0.5,
 "rationale": "mild divergence",
 "conflicting_envelopes": [
   {"topic": "hive/cognitive/x/integration",
    "envelope_id": "env-a",
    "summary": "a"}
 ]}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>
The current envelope does not conflict with anything in the recent
window. Stay silent.
</thoughts>
"""

_RESPONSE_WHITESPACE_ONLY = "   \n  \t\n"

_RESPONSE_MALFORMED_JSON = """\
<thoughts>Trying to flag a conflict.</thoughts>

<publish topic="hive/metacognition/conflict/detected">
{this is not valid json}
</publish>
"""


@pytest.mark.asyncio
async def test_respond_publishes_conflict_detected():
    """Happy path: LLM detects divergence and publishes
    ``hive/metacognition/conflict/detected`` with the conflicting
    envelopes named.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "user wants nothing", "actionable": False},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_CONFLICT_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/conflict/detected"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["conflict_kind"] == "intent_disagreement"
    assert body["severity"] == 0.7  # noqa: PLR2004
    assert "rationale" in body
    assert isinstance(body["conflicting_envelopes"], list)
    assert len(body["conflicting_envelopes"]) == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_respond_silence_does_not_publish_metacog_error():
    """ACC silence-allowed (mirrors broca / basal_ganglia): zero
    ``<publish>`` blocks is the intentional "no conflict here" decision.
    Most envelopes do not conflict with anything in recent STM. The
    runtime must NOT emit a metacognition error envelope in that case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/association_cortex/integration",
        {"summary": "purely descriptive observation"},
        source_region="association_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    # No publishes at all — silence is valid "no conflict".
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
    """Self-receive filter: respond's subscriptions
    (``hive/cognitive/+/integration``,
    ``hive/cognitive/prefrontal_cortex/plan``) don't match ACC's own
    output topic ``hive/metacognition/conflict/detected`` today, but
    defensive symmetry with notebook means the handler MUST early-return
    on self-source envelopes — and crucially MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/anterior_cingulate/integration",
        {"summary": "self echo"},
        source_region="anterior_cingulate",
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
    """STM record runs in ``finally`` — happy, silence, and parse-failure
    paths all record.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/prefrontal_cortex/plan",
        {"plan": "write file"},
        source_region="prefrontal_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_CONFLICT_RESPONSE)
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

    LLMs routinely quote tag examples in their reasoning. The parser
    strips <thoughts>...</thoughts> before running the publish regex so
    quoted examples cannot leak.
    """
    respond = _load_handler("respond")
    response_text = (
        '<thoughts>I might publish '
        '<publish topic="hive/metacognition/conflict/detected">'
        '{"conflict_kind":"bogus","severity":0.99,"rationale":"fake",'
        '"conflicting_envelopes":[]}'
        '</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/metacognition/conflict/detected">'
        '{"conflict_kind":"intent_disagreement","severity":0.6,'
        '"rationale":"real divergence",'
        '"conflicting_envelopes":[{"topic":"hive/cognitive/x/integration",'
        '"envelope_id":"env-real","summary":"real prior"}]}'
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
    assert call.kwargs["topic"] == "hive/metacognition/conflict/detected"
    assert call.kwargs["data"]["conflict_kind"] == "intent_disagreement"
    assert call.kwargs["data"]["severity"] == 0.6  # noqa: PLR2004
    assert call.kwargs["data"]["rationale"] == "real divergence"


@pytest.mark.asyncio
async def test_respond_accepts_single_quoted_topic_attr():
    """The topic regex accepts both double quotes (canonical) and single
    quotes around the topic value. Real LLMs occasionally emit
    ``topic='...'`` and routing those to the metacog error path is
    unnecessarily strict.
    """
    respond = _load_handler("respond")
    response_text = (
        "<thoughts>single quotes</thoughts>\n"
        "<publish topic='hive/metacognition/conflict/detected'>"
        '{"conflict_kind":"intent_disagreement","severity":0.4,'
        '"rationale":"mild divergence",'
        '"conflicting_envelopes":[{"topic":"hive/cognitive/x/integration",'
        '"envelope_id":"env-q","summary":"q"}]}'
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
    assert call.kwargs["topic"] == "hive/metacognition/conflict/detected"
    assert call.kwargs["data"]["conflict_kind"] == "intent_disagreement"
