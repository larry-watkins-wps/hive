"""Unit tests for auditory_cortex handlers (notebook + respond).

Phase B Task 9 (region 2 of 3) of the handler bootstrap plan. Mirrors
the structure of ``tests/unit/regions/vta/test_handlers.py``: handlers
live outside ``src/`` so we import them by file path. The ``respond.py``
parser is a verbatim copy of VTA's (post-f99b812), so the regression
coverage (C1 thoughts-leak guard, single+double quote tolerance, STM
record in ``finally``) carries over directly.

auditory_cortex-specific notes:
- auditory_cortex is NOT silence-allowed (mirrors motor_cortex / VTA).
  Every transcribe_request MUST produce exactly one
  ``hive/sensory/auditory/text`` envelope. Zero ``<publish>`` blocks IS
  a parse failure and triggers the metacog error path.
- Notebook subs: one exact (``hive/hardware/mic``) + one wildcard
  (``hive/cognitive/auditory_cortex/+``). respond's exact subscription
  ``hive/cognitive/auditory_cortex/transcribe_request`` overlaps the
  notebook wildcard — the loader allows wildcard-vs-exact overlap.
- Both handlers have a self-receive filter (skip envelopes whose
  ``source_region == ctx.region_name``).
- Publishes are stubbed: ``channel="auditory_cortex.stub"`` so
  downstream consumers can distinguish stubbed transcription from real
  STT once mic hardware lands.
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
    / "auditory_cortex"
    / "handlers"
)


def _load_handler(name: str):
    """Import a handler module from its file path under regions/."""
    path = REGION_HANDLERS_DIR / f"{name}.py"
    module_name = f"_test_auditory_cortex_handler_{name}"
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
    """Build a HandlerContext-shaped mock."""
    ctx = MagicMock()
    ctx.region_name = "auditory_cortex"
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
async def test_notebook_records_hardware_mic():
    """``hive/hardware/mic`` exact subscription catches raw mic input."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/hardware/mic",
        {"description": "raw audio chunk: 500ms",
         "bytes_len": 16000},
        source_region="hardware_bridge",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("hardware.mic:"), summary


@pytest.mark.asyncio
async def test_notebook_records_cognitive_directed():
    """``hive/cognitive/auditory_cortex/+`` catches directed traffic."""
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "the user said hello"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary is not None
    assert summary.startswith("cognitive.auditory_cortex.transcribe_request:"), summary


@pytest.mark.asyncio
async def test_notebook_skips_self_publishes():
    """Self-receive filter: defensive symmetry with respond.py.
    auditory_cortex's notebook subscriptions don't currently overlap
    with what respond.py publishes (``hive/sensory/auditory/text``),
    but the filter is uniform across handlers.
    """
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "self echo"},
        source_region="auditory_cortex",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_notebook_handles_non_dict_payload():
    notebook = _load_handler("notebook")
    env = _make_envelope(
        "hive/hardware/mic",
        "raw bytes string body",
        source_region="hardware_bridge",
    )
    ctx = _make_ctx()

    await notebook.handle(env, ctx)

    ctx.memory.record_event.assert_awaited_once()
    args, kwargs = ctx.memory.record_event.await_args
    summary = kwargs.get("summary", args[1] if len(args) > 1 else None)
    assert summary.startswith("hardware.mic:")


# ---------------------------------------------------------------------------
# respond.py
# ---------------------------------------------------------------------------


_GOOD_TRANSCRIPTION = """\
<thoughts>
The request describes the user saying "hello world". Produce that as
the stub transcript.
</thoughts>

<publish topic="hive/sensory/auditory/text">
{"text": "hello world",
 "speaker": "user",
 "channel": "auditory_cortex.stub",
 "source_modality": "speech_transcribed",
 "confidence": 0.95}
</publish>
"""

_RESPONSE_NO_PUBLISH = """\
<thoughts>I forgot to emit a transcript.</thoughts>
"""

_RESPONSE_MALFORMED_JSON = """\
<thoughts>I want to transcribe but my JSON is broken.</thoughts>

<publish topic="hive/sensory/auditory/text">
{this is not valid json
</publish>
"""

_RESPONSE_WITH_SLEEP = """\
<thoughts>STM is filling.</thoughts>

<publish topic="hive/sensory/auditory/text">
{"text": "good morning",
 "channel": "auditory_cortex.stub",
 "source_modality": "speech_transcribed",
 "confidence": 0.8}
</publish>

<request_sleep reason="STM overloaded" />
"""


@pytest.mark.asyncio
async def test_respond_publishes_transcription_on_request():
    """Happy path: transcribe_request → exactly one
    hive/sensory/auditory/text envelope marked
    channel="auditory_cortex.stub".
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "the user said hello world"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_GOOD_TRANSCRIPTION)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/sensory/auditory/text"
    assert call.kwargs["content_type"] == "application/json"
    body = call.kwargs["data"]
    assert body["text"] == "hello world"
    assert body["channel"] == "auditory_cortex.stub"
    assert body["source_modality"] == "speech_transcribed"


@pytest.mark.asyncio
async def test_respond_skips_self_publishes():
    """Self-receive filter: defensive symmetry with notebook.py. The
    handler MUST early-return on self-source envelopes — and crucially
    MUST NOT call the LLM.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "self echo"},
        source_region="auditory_cortex",
    )
    # No llm_text since complete should never be called.
    ctx = _make_ctx()

    await respond.handle(env, ctx)

    ctx.llm.complete.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    ctx.memory.record_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_parse_failure_publishes_metacog_error():
    """auditory_cortex is NOT silence-allowed (mirrors motor_cortex /
    VTA): zero <publish> blocks IS a parse failure. Every
    transcribe_request must produce exactly one
    hive/sensory/auditory/text envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "noop"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/metacognition/error/detected"
    assert call.kwargs["data"]["kind"] == "llm_parse_failure"
    assert call.kwargs["data"]["topic"] == (
        "hive/cognitive/auditory_cortex/transcribe_request"
    )
    assert "raw_response" in call.kwargs["data"]


@pytest.mark.asyncio
async def test_respond_malformed_json_publishes_metacog_error():
    """Malformed JSON inside a present <publish> block IS a parse error
    and MUST publish a metacognition error envelope.
    """
    respond = _load_handler("respond")
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "broken transcript"},
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
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "good morning"},
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
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "hello"},
        source_region="prefrontal_cortex",
    )

    # Successful parse path records.
    ctx = _make_ctx(llm_text=_GOOD_TRANSCRIPTION)
    await respond.handle(env, ctx)
    ctx.memory.record_event.assert_awaited_once()

    # Parse-failure path also records.
    ctx2 = _make_ctx(llm_text=_RESPONSE_NO_PUBLISH)
    await respond.handle(env, ctx2)
    ctx2.memory.record_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_ignores_publish_tags_inside_thoughts():
    """Regression for C1: <publish> tags quoted inside <thoughts> must
    NOT be dispatched.
    """
    respond = _load_handler("respond")
    response_text = (
        '<thoughts>I might publish '
        '<publish topic="hive/sensory/auditory/text">'
        '{"text":"fake","channel":"auditory_cortex.stub",'
        '"source_modality":"speech_transcribed","confidence":0.99}'
        '</publish> '
        'but I will publish properly.</thoughts>\n'
        '<publish topic="hive/sensory/auditory/text">'
        '{"text":"real transcript","channel":"auditory_cortex.stub",'
        '"source_modality":"speech_transcribed","confidence":0.85}'
        '</publish>'
    )
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "real transcript"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    # Exactly one publish, the real outer one — NOT the quoted-in-thoughts one.
    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/sensory/auditory/text"
    assert call.kwargs["data"]["text"] == "real transcript"


@pytest.mark.asyncio
async def test_respond_accepts_single_quoted_topic():
    """Both double quotes (canonical) and single quotes are accepted
    around the topic attribute.
    """
    respond = _load_handler("respond")
    response_text = (
        "<thoughts>quotes vary</thoughts>\n"
        "<publish topic='hive/sensory/auditory/text'>"
        '{"text":"single-quoted topic transcript",'
        '"channel":"auditory_cortex.stub",'
        '"source_modality":"speech_transcribed","confidence":0.7}'
        "</publish>"
    )
    env = _make_envelope(
        "hive/cognitive/auditory_cortex/transcribe_request",
        {"text": "x"},
        source_region="prefrontal_cortex",
    )
    ctx = _make_ctx(llm_text=response_text)

    await respond.handle(env, ctx)

    assert ctx.publish.await_count == 1
    call = ctx.publish.await_args_list[0]
    assert call.kwargs["topic"] == "hive/sensory/auditory/text"
    assert call.kwargs["data"]["text"] == "single-quoted topic transcript"
