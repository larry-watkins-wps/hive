"""Respond handler for anterior_cingulate — LLM-driven conflict detection.

ACC's biological role in Hive v0 is metacognitive monitoring: it watches
multiple cognitive integration streams for divergence. When two
cognitive regions produce contradictory output (e.g. assoc_cortex says
"user is asking a question" while PFC says "user wants nothing"), ACC
publishes ``hive/metacognition/conflict/detected`` flagging the conflict
for downstream observers.

Subscribes to ``hive/cognitive/+/integration`` (any cortex's integration
output) plus the directed ``hive/cognitive/prefrontal_cortex/plan``
(PFC's deliberation conclusions) and reasons over the current envelope
plus the recent integration / plan window from STM.

Output topic: ``hive/metacognition/conflict/detected`` with payload::

    {
      "conflict_kind": "...",
      "severity": <float in [0.0, 1.0]>,
      "rationale": "why these envelopes conflict",
      "conflicting_envelopes": [
        {"topic": "...", "envelope_id": "...", "summary": "..."}
      ]
    }

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

ACC silence-allowed (mirrors broca / basal_ganglia, NOT motor_cortex /
VTA): zero ``<publish>`` blocks is the intentional "no conflict here"
decision. Most envelopes do NOT conflict with anything in recent STM;
silence is the expected default. The runtime does NOT publish a
metacognition error envelope on silence. Only malformed JSON inside a
present ``<publish>`` block triggers the metacog error path.

- Self-receive filter at the top: ACC publishes
  ``hive/metacognition/conflict/detected``. respond's subscriptions
  don't match that topic, but defensive symmetry with notebook.py is
  cheap and guards against future subscription drift.
- TIMEOUT_S=60.0 mirrors motor_cortex / basal_ganglia / VTA; 30s proved
  tight on Phase A respond handlers under real LLM latency.
- ``temperature=0.5`` (lower than the cohort's 0.7). Conflict-detection
  judgements should be consistent — the same input pair should not flip
  between "no conflict" and "severe conflict" across runs. Mirrors VTA's
  determinism rationale.
- ``max_tokens=768`` — the conflict envelope plus a short rationale
  doesn't need 1024 but is roomier than VTA's 512.

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of VTA's respond.py
(post-f99b812), which itself mirrors basal_ganglia (post-9393bd7) /
motor_cortex (post-fdc1dc3) / broca (post-69df91d) / PFC / assoc_cortex
(post-241d9a9 + 7024d3a). Deduplication into a shared module is deferred
until the handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = [
    # Any cortex's integration output is a candidate for conflict
    # detection against the recent integration window.
    "hive/cognitive/+/integration",
    # PFC's deliberation conclusions are a canonical conflict candidate
    # — they often diverge from raw integration outputs.
    "hive/cognitive/prefrontal_cortex/plan",
]
TIMEOUT_S = 60.0  # mirrors motor_cortex / basal_ganglia / VTA; LLM-call latency.

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Anterior Cingulate Cortex (ACC) of Hive."

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
    an error — ACC treats it as intentional "no conflict" silence,
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
    envelope_id = getattr(envelope, "envelope_id", "unknown")

    return (
        f"Cognitive output received from {source} on topic {envelope.topic} "
        f"(envelope_id={envelope_id}):\n"
        f"payload: {payload_repr}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM, including "
        f"prior cognitive integration / plan envelopes):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Decide: does the current envelope CONFLICT with any prior "
        f"envelope in the recent window? A conflict is a real divergence "
        f"in interpretation, intent, or proposed action — not just a "
        f"topical difference. If yes, publish exactly one "
        f"hive/metacognition/conflict/detected block per the response "
        f"format in your prompt, naming the conflicting envelopes. If "
        f"no, emit zero <publish> blocks — silence is the expected "
        f"default since most envelopes do not conflict."
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
    # Defensive symmetry with notebook.py — ACC publishes
    # ``hive/metacognition/conflict/detected`` which respond's
    # subscriptions don't match today, but a misrouted self-publish or
    # a future subscription change should not cause an LLM call against
    # our own output.
    if envelope.source_region == ctx.region_name:
        return

    # 1. Pull recent STM events for context (prior integrations / plans
    #    against which the current envelope is checked for divergence).
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break detection.
        recent_events = []

    # 2. Build and run the LLM call. ``temperature=0.5`` (lower than
    #    the cohort's 0.7) since conflict-detection judgements should
    #    be consistent across runs. ``max_tokens=768`` is enough for a
    #    conflict envelope plus short rationale.
    user_msg = _build_user_message(envelope, recent_events)
    req = CompletionRequest(
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ],
        max_tokens=768,
        temperature=0.5,
        purpose="anterior_cingulate.respond",
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record the inspected envelope in STM, regardless of
    #    parse outcome — including on silence.
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # ACC silence-allowed (mirrors broca / basal_ganglia): zero
            # <publish> blocks is the intentional "no conflict here"
            # decision. Most envelopes do not conflict with anything in
            # recent STM. Only emit a metacog error envelope when a
            # <publish> block is present but its inner JSON is malformed
            # (genuine broken output).
            if parse_error == "no_publish_blocks":
                ctx.log.info(
                    "anterior_cingulate.respond.silence",
                    topic=envelope.topic,
                    raw_head=raw_text[:200],
                )
                return
            ctx.log.warning(
                "anterior_cingulate.respond.parse_failure",
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
                "anterior_cingulate.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(
            envelope,
            summary=f"inspected:{envelope.topic}",
        )
