"""Respond handler for insula — LLM-driven interoception / felt_state.

insula reads system-level metric envelopes (compute load, token budget,
region health) and emits a categorical felt-state envelope describing
how Hive's computational body feels right now. The felt state is a
compression of raw numbers into a subjective label — "alert",
"overloaded", "tired", "engaged", etc. — plus a magnitude in [0.0, 1.0]
and a one-sentence rationale. Other regions subscribe to
``hive/interoception/#`` and integrate this into their deliberation
(amygdala produces cortisol from "stressed" felt states; VTA pleasure
from "engaged" felt states; etc.).

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

insula respond divergence from motor_cortex / VTA (silence-allowed) —
mirroring broca / basal_ganglia:
- insula IS silence-allowed. Metric envelopes can arrive at very high
  frequency, but the felt-state envelope is retained and only needs to
  republish when the underlying state has materially changed. If the
  LLM determines metrics haven't shifted, zero ``<publish>`` blocks is
  intentional throttling — NOT a parse failure. Only malformed JSON
  inside a present ``<publish>`` block triggers the metacog error path.
- ``temperature=0.5`` (lower than the cohort's 0.7). Felt-state labels
  should be reasonably stable across similar metric snapshots — the
  same compute_load shouldn't swing wildly between "alert" and
  "overloaded".
- ``max_tokens=512`` — a label + magnitude + short rationale doesn't
  need 1024.
- Self-receive filter at the top: defensive symmetry with notebook.py.
  insula publishes ``hive/interoception/felt_state`` which doesn't
  immediately overlap with what we read (``hive/system/metrics/*``),
  but a misrouted self-publish or a future subscription change should
  not cause an LLM call against our own output.
- TIMEOUT_S=60.0 mirrors the rest of the cohort; 30s proved tight on
  Phase A respond handlers under real LLM latency.

Plan §4 simplification (bootstrap-only): the plan row mentioned a
``signal.py`` for metric rollup alongside notebook + respond. We DROP
signal.py for v0 — notebook already records every metric envelope to
STM, and respond reads STM via ``ctx.memory.recent_events()`` for
context. A separate algorithmic counter is over-engineering at this
stage and conflicts with the LLM-driven interoception design.

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of VTA's respond.py (post-
f99b812), which itself mirrors basal_ganglia (post-9393bd7) and the
broca / PFC / assoc_cortex template. Deduplication into a shared module
is deferred until the handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = [
    "hive/system/metrics/compute",
    "hive/system/metrics/region_health",
    "hive/system/metrics/tokens",
]
TIMEOUT_S = 60.0  # mirrors the cohort; 30s tight on Phase A respond handlers.

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Insula of Hive."

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
    ``<publish>`` blocks are present (the caller decides whether that is
    an error — insula treats it as intentional throttling silence,
    mirroring broca / basal_ganglia), or another short reason string on
    JSON decode failure.
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
        f"System metric envelope received from {source} on topic "
        f"{envelope.topic}:\n"
        f"payload: {payload_repr}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM, including "
        f"recent metric snapshots, region_stats rollups, and modulator "
        f"levels):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Translate the current metric pattern into a felt state. "
        f"Consider:\n"
        f"- Has the underlying body-state materially changed since your "
        f"last felt_state publish (visible in recent events)?\n"
        f"- Which categorical label best fits — alert, engaged, "
        f"overloaded, tired, hungry for input, unwell, calm, etc.?\n"
        f"- How strongly is that state felt (magnitude in [0.0, 1.0])?\n"
        f"If the state has materially changed, publish exactly one "
        f"hive/interoception/felt_state envelope per the response format "
        f"in your prompt. If metrics haven't materially changed, emit "
        f"zero <publish> blocks — silence is intentional throttling, not "
        f"error."
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
    # Defensive symmetry with notebook.py — insula's respond
    # subscriptions don't immediately overlap with what we publish (we
    # publish ``hive/interoception/felt_state``, we read
    # ``hive/system/metrics/*``), but a misrouted self-publish or a
    # future subscription change should not cause an LLM call against
    # our own output.
    if envelope.source_region == ctx.region_name:
        return

    # 1. Pull recent STM events for context (recent metric snapshots,
    #    region_stats rollups, and modulator levels).
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break interoception.
        recent_events = []

    # 2. Build and run the LLM call. ``temperature=0.5`` (lower than the
    #    cohort's 0.7) since felt-state labels should be reasonably
    #    stable across similar metric snapshots. ``max_tokens=512`` is
    #    enough for label + magnitude + short rationale.
    user_msg = _build_user_message(envelope, recent_events)
    req = CompletionRequest(
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ],
        max_tokens=512,
        temperature=0.5,
        purpose="insula.respond",
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record the metric envelope in STM, regardless of parse
    #    outcome — including on silence (so respond's next pass can see
    #    this snapshot in recent_events context).
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # insula divergence from motor_cortex (mirrors broca /
            # basal_ganglia): zero <publish> blocks is INTENTIONAL
            # throttling silence (metrics haven't materially changed),
            # not a parse failure. Only emit a metacog error envelope
            # when a <publish> block is present but its inner JSON is
            # malformed (genuine broken output).
            if parse_error == "no_publish_blocks":
                ctx.log.info(
                    "insula.respond.silence",
                    topic=envelope.topic,
                    raw_head=raw_text[:200],
                )
                return
            ctx.log.warning(
                "insula.respond.parse_failure",
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
                "insula.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(
            envelope,
            summary=f"felt_state_input:{envelope.topic}",
        )
