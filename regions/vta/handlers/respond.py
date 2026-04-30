"""Respond handler for VTA — LLM-driven dopamine reward signal.

Per ratified decision 2 of the handler bootstrap plan, VTA is
**LLM-driven**, not algorithmic. The reward value is computed by the
LLM reasoning over the motor outcome envelope plus recent STM events,
not derived from a fixed numeric formula. This captures nuance the
formula misses — e.g. "the response was syntactically correct but
emotionally flat → low reward" — at the cost of being slower and less
predictable than a pure counter would be.

VTA reads motor outcome envelopes from ``hive/motor/{complete,failed,
speech/complete}`` and emits a reasoned dopamine value on
``hive/modulator/dopamine`` with payload schema:

    {
      "value": <float in [0.0, 1.0]>,
      "rationale": "<short explanation>",
      "source_outcome": {"topic": "...", "envelope_id": "..."}
    }

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

VTA divergence from broca / basal_ganglia (silence-allowed) — and
mirroring motor_cortex's NOT-silence-allowed pattern:
- VTA is **NOT** silence-allowed. Every motor outcome must produce a
  dopamine signal — even a low one — so basal_ganglia's habit-formation
  loop has a reliable teaching signal. Zero ``<publish>`` blocks IS a
  parse failure and triggers ``hive/metacognition/error/detected``.
- ``temperature=0.5`` (lower than the cohort's 0.7). Dopamine values
  should be more deterministic than free-form deliberation — the same
  outcome shouldn't swing wildly between sub-baseline and spike.
- ``max_tokens=512`` — a value + short rationale doesn't need 1024.
- Self-receive filter at the top: defensive symmetry with notebook.py.
  VTA's respond subscriptions don't immediately overlap with what we
  publish (we publish ``hive/modulator/dopamine``, we read
  ``hive/motor/*``), but a misrouted self-publish or a future
  subscription change should not cause an LLM call against our own
  output.
- TIMEOUT_S=60.0 mirrors motor_cortex / basal_ganglia; 30s proved tight
  on Phase A respond handlers under real LLM latency.

Plan §4 simplification (bootstrap-only): the plan row mentioned a
``signal.py`` for VTA alongside notebook + respond. We DROP signal.py
for v0 — notebook records the motor outcome to STM, and respond reads
STM to compute the dopamine value. A separate signal handler is
over-engineering at this stage and would conflict with the LLM-driven
ratified decision.

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of motor_cortex's respond.py
(post-fdc1dc3) and basal_ganglia's respond.py (post-9393bd7), which
themselves mirror the broca / PFC / assoc_cortex template (post-241d9a9
+ 7024d3a). Deduplication into a shared module is deferred until the
handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = [
    "hive/motor/complete",
    "hive/motor/failed",
    "hive/motor/speech/complete",
]
TIMEOUT_S = 60.0  # mirrors motor_cortex / basal_ganglia; LLM-call latency.

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Ventral Tegmental Area (VTA) of Hive."

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
    ``<publish>`` blocks are present (VTA treats this as a parse failure
    — unlike broca / basal_ganglia, it is NOT silence-allowed), or
    another short reason string on JSON decode failure.
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
        f"Motor outcome received from {source} on topic {envelope.topic}:\n"
        f"payload: {payload_repr}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Reason about the dopamine signal this outcome should produce. "
        f"Consider:\n"
        f"- Did the action achieve its goal?\n"
        f"- Was the outcome predicted, or surprising "
        f"(positive/negative)?\n"
        f"- For speech: did the articulation match the intent's text "
        f"quality?\n"
        f"Publish exactly one hive/modulator/dopamine envelope per the "
        f"response format in your prompt. Every motor outcome must "
        f"produce a dopamine signal — even a low one."
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
    # Defensive symmetry with notebook.py — VTA's respond subscriptions
    # don't immediately overlap with what we publish (we publish
    # ``hive/modulator/dopamine``, we read ``hive/motor/*``), but a
    # misrouted self-publish or a future subscription change should not
    # cause an LLM call against our own output.
    if envelope.source_region == ctx.region_name:
        return

    # 1. Pull recent STM events for context.
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break execution.
        recent_events = []

    # 2. Build and run the LLM call. ``temperature=0.5`` (lower than
    #    the cohort's 0.7) since dopamine values should be more
    #    deterministic than free-form deliberation. ``max_tokens=512``
    #    is enough for a value + short rationale.
    user_msg = _build_user_message(envelope, recent_events)
    req = CompletionRequest(
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ],
        max_tokens=512,
        temperature=0.5,
        purpose="vta.respond",
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record the outcome envelope in STM, regardless of parse
    #    outcome.
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # VTA is NOT silence-allowed (mirrors motor_cortex): zero
            # <publish> blocks IS a parse failure. Every motor outcome
            # must produce a dopamine signal so basal_ganglia's habit
            # learning has a reliable teaching signal.
            ctx.log.warning(
                "vta.respond.parse_failure",
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
                "vta.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(
            envelope,
            summary=f"reward_signal:{envelope.topic}",
        )
