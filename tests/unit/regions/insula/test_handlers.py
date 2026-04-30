"""Unit tests for insula handlers (notebook + respond).

Phase B Task 8a of the handler bootstrap plan. Mirrors
``tests/unit/regions/basal_ganglia/test_handlers.py``: handlers live
outside ``src/`` so we import them by file path. The ``respond.py``
parser is a verbatim copy of the VTA / basal_ganglia / broca template
(post-f99b812 / 9393bd7 / 69df91d), so the regression coverage (C1
thoughts-leak guard, single + double quote tolerance, ``<request_sleep>``
empty-string discrimination, STM record in ``finally``) carries over
directly.

insula-specific traits:
- Like broca and basal_ganglia, insula IS silence-allowed. When the
  metrics haven't materially changed, zero ``<publish>`` blocks is
  intentional throttling, NOT a parse failure. Only malformed JSON
  inside a present ``<publish>`` block triggers the metacog error path.
- Both notebook and respond have a self-receive filter at the top:
  envelopes whose ``source_region == ctx.region_name`` are ignored.
- insula publishes ``hive/interoception/felt_state`` from system
  metrics aggregation; the felt-state envelope carries a categorical
  ``state`` label, a ``magnitude`` in [0.0, 1.0], and a ``rationale``.
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
    / "insula"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_insula_handler_{name}"
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
    ctx.region_name = "insula"
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
async def test_notebook_records_metrics():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.42, "mem": 0.61},
        source_region="glia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("system.metrics.compute:"), summary


@pytest.mark.asyncio
async def test_notebook_records_region_stats():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/system/region_stats/prefrontal_cortex",
        {"msg_per_s": 1.2, "avg_latency_ms": 230},
        source_region="glia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("system.region_stats.prefrontal_cortex:"), summary


@pytest.mark.asyncio
async def test_notebook_records_modulator():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/modulator/dopamine",
        {"value": 0.7, "rationale": "reward fired"},
        source_region="vta",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("modulator.dopamine:"), summary


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/system/metrics/tokens",
        "raw token-budget summary",
        source_region="glia",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("system.metrics.tokens:")
    assert "raw token-budget summary" in summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: insula publishes felt_state and may publish
    cognitive/insula/* responses. Without the filter those would feed
    back into STM. The notebook MUST early-return when the envelope's
    source_region is this region.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/insula/response",
        {"summary": "self echo"},
        source_region="insula",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_FELT_STATE_RESPONSE = """\
<thoughts>
CPU at 0.85 and tokens budget low — this maps to "overloaded".
</thoughts>

<publish topic="hive/interoception/felt_state">
{"state": "overloaded", "rationale": "compute load high and token budget low",
 "magnitude": 0.8}
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/interoception/felt_state">
{"state": "engaged", "rationale": "moderate load, smooth responses",
 "magnitude": 0.5}
</publish>

<request_sleep reason="STM overloaded" />
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>Metrics haven't materially changed since last publish — staying silent.</thoughts>
"""

_RESPONSE_MALFORMED_JSON = """\
<thoughts>Trying to publish.</thoughts>

<publish topic="hive/interoception/felt_state">
{this is not valid json}
</publish>
"""


@pytest.mark.asyncio
async def test_respond_publishes_felt_state():
    """Happy path: LLM publishes hive/interoception/felt_state from a metric envelope."""
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.85, "mem": 0.7},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_GOOD_FELT_STATE_RESPONSE)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/interoception/felt_state"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["state"] == "overloaded"
    assert body["rationale"]
    assert 0.0 <= body["magnitude"] <= 1.0


@pytest.mark.asyncio
async def test_respond_silence_does_not_publish_metacog_error():
    """insula-specific (mirrors broca / basal_ganglia): zero <publish>
    blocks is intentional throttling when metrics haven't materially
    changed. The runtime must NOT emit a metacognition error envelope
    in that case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.5, "mem": 0.5},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    # No publishes at all — silence is valid throttling.
    assert ctx.publish.await_count == 0
    metacog_calls = [
        c for c in ctx.publish.await_args_list
        if c.kwargs.get("topic") == "hive/metacognition/error/detected"
    ]
    assert metacog_calls == []
    # STM still records the envelope (finally block).
    ctx.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_malformed_json_publishes_metacog_error():
    """Malformed JSON inside a present <publish> block IS a parse error
    and MUST publish a metacognition error envelope. This is the
    distinction from the silence-is-valid case.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/system/metrics/region_health",
        {"healthy": 9, "degraded": 1},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_MALFORMED_JSON)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == "hive/system/metrics/region_health"
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: even though respond's subscriptions don't
    immediately overlap with what insula publishes, defensive symmetry
    with notebook means the handler MUST early-return on self-source
    envelopes — and crucially MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.5},
        source_region="insula",
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
        "hive/system/metrics/compute",
        {"cpu": 0.5},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_WITH_SLEEP)

    await respond.handle(env, ctx)

    ctx.request_sleep.assert_called_once_with("STM overloaded")


@pytest.mark.asyncio
async def test_respond_records_envelope_to_stm():
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.5},
        source_region="glia",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_FELT_STATE_RESPONSE)
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
        '<publish topic="hive/interoception/felt_state">'
        '{"state":"bogus","rationale":"fake","magnitude":0.0}</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/interoception/felt_state">'
        '{"state":"engaged","rationale":"real reading","magnitude":0.5}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/system/metrics/compute",
        {"cpu": 0.5},
        source_region="glia",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/interoception/felt_state"
    assert call.kwargs["data"]["state"] == "engaged"
    assert call.kwargs["data"]["rationale"] == "real reading"
