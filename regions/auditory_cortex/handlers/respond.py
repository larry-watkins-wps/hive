"""Respond handler for auditory_cortex — LLM-driven STT stub.

auditory_cortex's eventual job is speech-to-text: receive audio bytes
on ``hive/hardware/mic``, transcribe, publish text to
``hive/sensory/auditory/text``. Until mic hardware lands, this respond
handler is a STUB that responds to explicit
``hive/cognitive/auditory_cortex/transcribe_request`` envelopes (e.g.
for testing and bootstrap-time chat-driven scaffolding). The LLM
produces a transcription as if it had heard the audio described in the
request payload, marked with ``channel="auditory_cortex.stub"`` so
downstream consumers can distinguish stubbed transcription from real
STT once mic hardware lands.

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

auditory_cortex divergence from basal_ganglia / broca / thalamus
(silence-allowed) — and mirroring motor_cortex / VTA's NOT-silence-
allowed pattern:
- auditory_cortex is NOT silence-allowed. Every transcribe_request
  must produce exactly one ``hive/sensory/auditory/text`` envelope.
  Zero ``<publish>`` blocks IS a parse failure and triggers
  ``hive/metacognition/error/detected``.
- Self-receive filter at the top: defensive symmetry with notebook.py.
  respond's subscription
  (``hive/cognitive/auditory_cortex/transcribe_request``) does not
  overlap with what we publish (``hive/sensory/auditory/text``), but
  a misrouted self-publish or a future subscription change should not
  cause an LLM call against our own output.
- TIMEOUT_S=60.0 mirrors the cohort; 30s proved tight on Phase A
  respond handlers under real LLM latency.

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of VTA's respond.py
(post-f99b812). Deduplication into a shared module is deferred until
the handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = [
    "hive/cognitive/auditory_cortex/transcribe_request",
]
TIMEOUT_S = 60.0  # mirrors the cohort; 30s tight on real LLM latency.

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Auditory Cortex of Hive."

_RECENT_EVENTS_TAIL = 20
_MAX_RAW_RESPONSE_CHARS = 1000
_DEFAULT_ATTENTION_HINT = 0.5

# Tag-schema parsing. We use ``re.DOTALL`` so the body can span lines and
# accept either self-closing or paired ``<request_sleep>`` forms.
#
# ``_THOUGHTS_RE`` is stripped FIRST, before the publish/request_sleep
# parsers run. LLMs commonly quote tag examples inside their <thoughts>
# reasoning ("I might publish <publish topic='example'>{...}</publish>"),
# and without this strip pass those quoted examples would be parsed as
# real publishes.
_THOUGHTS_RE = re.compile(r"<thoughts>.*?</thoughts>", re.DOTALL)
# Accept both double quotes (canonical) and single quotes around the
# topic attribute, plus optional whitespace around ``=``. Real LLMs
# occasionally emit ``topic='...'`` and routing those to the metacog
# error path is unnecessarily strict.
_PUBLISH_RE = re.compile(
    r'''<publish\s+topic\s*=\s*["']([^"']+)["']\s*>(.*?)</publish>''',
    re.DOTALL,
)
_REQUEST_SLEEP_RE = re.compile(
    r'<request_sleep\s+reason="([^"]*)"\s*/?\s*>'
    r'|<request_sleep\s+reason="([^"]*)"\s*></request_sleep>',
    re.DOTALL,
)


def _parse_response(text: str) -> tuple[list[tuple[str, dict]], str | None, str | None]:
    """Parse the LLM response.

    Returns ``(publishes, sleep_reason, parse_error)``.

    ``publishes`` is a list of ``(topic, parsed_json_dict)`` pairs.
    ``sleep_reason`` is the first matched ``<request_sleep reason="...">``
    or None.
    ``parse_error`` is None on success, ``"no_publish_blocks"`` when no
    ``<publish>`` blocks are present (auditory_cortex treats this as a
    parse failure — unlike basal_ganglia / broca / thalamus, it is NOT
    silence-allowed), or another short reason string on JSON decode
    failure.
    """
    # Strip <thoughts>...</thoughts> first so quoted tag examples inside
    # private reasoning are not parsed as real publishes / sleep requests.
    stripped_text = _THOUGHTS_RE.sub("", text)

    blocks = _PUBLISH_RE.findall(stripped_text)
    if not blocks:
        return [], None, "no_publish_blocks"

    publishes: list[tuple[str, dict]] = []
    for topic, body in blocks:
        stripped = body.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [], None, "publish_body_not_json"
        if not isinstance(parsed, dict):
            return [], None, "publish_body_not_object"
        publishes.append((topic, parsed))

    sleep_reason: str | None = None
    sleep_match = _REQUEST_SLEEP_RE.search(stripped_text)
    if sleep_match is not None:
        # Use explicit ``is not None`` discrimination: an empty-string
        # ``reason=""`` (group 1 == "") still triggers sleep, since the
        # LLM clearly intended to request it. ``or`` would short-circuit
        # on the falsy empty string and silently drop the request.
        if sleep_match.group(1) is not None:
            sleep_reason = sleep_match.group(1)
        else:
            sleep_reason = sleep_match.group(2)

    return publishes, sleep_reason, None


def _format_recent_events(events: list[dict]) -> str:
    if not events:
        return "(none)"
    lines = []
    for ev in events[-_RECENT_EVENTS_TAIL:]:
        topic = ev.get("topic", "?")
        summary = ev.get("summary", "")
        lines.append(f"- {topic}: {summary}")
    return "\n".join(lines)


def _build_user_message(envelope, recent_events: list[dict]) -> str:
    data = envelope.payload.data if hasattr(envelope, "payload") else None
    if isinstance(data, dict):
        payload_repr = json.dumps(data)
    else:
        payload_repr = json.dumps(str(data) if data is not None else "")

    source = getattr(envelope, "source_region", "unknown")

    return (
        f"Transcribe request received from {source} on topic "
        f"{envelope.topic}:\n"
        f"payload: {payload_repr}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Until mic hardware lands, this is a STUB. Produce text as if "
        f"you had heard the audio described in the request payload "
        f"(typically a `text` field describing the simulated audio). "
        f"Publish exactly one hive/sensory/auditory/text envelope per "
        f"transcribe_request. Mark channel=\"auditory_cortex.stub\" so "
        f"downstream consumers can distinguish stubbed transcription "
        f"from real STT once hardware lands."
    )


async def _publish_metacog_error(
    envelope, ctx, raw_text: str, kind: str = "llm_parse_failure"
) -> None:
    await ctx.publish(
        topic="hive/metacognition/error/detected",
        content_type="application/json",
        data={
            "kind": kind,
            "topic": envelope.topic,
            "raw_response": raw_text[:_MAX_RAW_RESPONSE_CHARS],
        },
        qos=1,
        retain=False,
        attention_hint=_DEFAULT_ATTENTION_HINT,
    )


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # Defensive symmetry with notebook.py — auditory_cortex's respond
    # subscription does not currently overlap with what we publish, but
    # a misrouted self-publish or a future subscription change should
    # not cause an LLM call against our own output.
    if envelope.source_region == ctx.region_name:
        return

    # 1. Pull recent STM events for context.
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break transcription.
        recent_events = []

    # 2. Build and run the LLM call.
    user_msg = _build_user_message(envelope, recent_events)
    req = CompletionRequest(
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ],
        max_tokens=1024,
        temperature=0.7,
        purpose="auditory_cortex.respond",
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record the request envelope in STM, regardless of parse
    #    outcome.
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # auditory_cortex is NOT silence-allowed (mirrors motor_cortex
            # / VTA): zero <publish> blocks IS a parse failure. Every
            # transcribe_request must produce exactly one
            # hive/sensory/auditory/text envelope.
            ctx.log.warning(
                "auditory_cortex.respond.parse_failure",
                topic=envelope.topic,
                reason=parse_error,
                raw_head=raw_text[:200],
            )
            await _publish_metacog_error(envelope, ctx, raw_text)
            return

        for topic, body in publishes:
            await ctx.publish(
                topic=topic,
                content_type="application/json",
                data=body,
                qos=1,
                retain=False,
                attention_hint=_DEFAULT_ATTENTION_HINT,
            )
            ctx.log.info(
                "auditory_cortex.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(
            envelope,
            summary=f"transcribed:{envelope.topic}",
        )
