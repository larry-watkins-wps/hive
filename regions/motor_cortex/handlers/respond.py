"""Respond handler for motor_cortex — LLM-driven action stub-executor.

motor_cortex's primary input is ``hive/motor/intent`` from PFC or
basal_ganglia, which contains an ``action`` and optional ``args`` dict.
At v0 motor_cortex has no real actuators (no robotic arm, no display
driver, no file-system writer wired up); the LLM acts as a
**world-simulator**: it imagines what would happen if the action were
executed in the current context (drawing on recent_events for
situational awareness) and publishes the imagined outcome as one of
``hive/motor/complete``, ``hive/motor/failed``, or ``hive/motor/partial``.

This is faithful stub execution. Future versions plug in real actuators
that produce real outcomes and the LLM's role narrows.

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

Divergence from broca's respond.py (post-69df91d):
- motor_cortex is **NOT** silence-allowed. The upstream caller
  (PFC / basal_ganglia) is waiting on an outcome envelope. Zero
  ``<publish>`` blocks IS a parse failure and triggers the
  ``hive/metacognition/error/detected`` path. Always emit exactly one
  outcome.
- TIMEOUT_S bumped from 30s to 60s based on Phase A timeouts observed
  on PFC + hippocampus respond handlers.
- Self-receive filter at the top: defensive symmetry with notebook.py.
  respond's subscription (``hive/motor/intent``) is a topic motor_cortex
  itself doesn't publish, so the filter is mostly belt-and-suspenders,
  but a misrouted self-publish or a future subscription change should
  not cause an LLM call against our own output.

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of broca's respond.py
(post-69df91d), which itself mirrors the PFC / assoc_cortex template
(post-241d9a9 + 7024d3a). Deduplication into a shared module is deferred
until the handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = ["hive/motor/intent"]
TIMEOUT_S = 60.0  # bumped from 30s based on Phase A LLM-call latency.

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Motor Cortex of Hive."

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
    ``<publish>`` blocks are present (motor_cortex treats this as a
    parse failure — unlike broca, it is NOT silence-allowed), or another
    short reason string on JSON decode failure.
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
        action = data.get("action", "")
        args = data.get("args", {})
        if not isinstance(args, dict):
            args = {"_raw": args}
    else:
        action = str(data) if data is not None else ""
        args = {}

    source = getattr(envelope, "source_region", "unknown")

    return (
        f"Motor intent received from {source} on topic {envelope.topic}:\n"
        f"action: {action}\n"
        f"args: {json.dumps(args)}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Imagine the outcome of this action and respond per your "
        f"prompt's response format. You MUST publish exactly one outcome "
        f"envelope: hive/motor/complete (preferred), hive/motor/failed "
        f"(only when the intent is clearly impossible — missing "
        f"capability, physical impossibility, ill-formed args), or "
        f"hive/motor/partial (action started but couldn't finish). "
        f"Bias toward hive/motor/complete with a brief description."
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
    # Defensive symmetry with notebook.py — motor_cortex does not
    # currently publish ``hive/motor/intent`` itself, but a misrouted
    # self-publish or a future subscription change should not cause an
    # LLM call against our own output.
    if envelope.source_region == ctx.region_name:
        return

    # 1. Pull recent STM events for context.
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break execution.
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
        purpose="motor_cortex.respond",
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record the executed envelope in STM, regardless of
    #    parse outcome.
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # motor_cortex divergence from broca: zero <publish> blocks
            # IS a parse failure. The upstream caller is waiting on an
            # outcome envelope, so we MUST emit a metacognition error
            # so the system knows execution silently dropped.
            ctx.log.warning(
                "motor_cortex.respond.parse_failure",
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
                "motor_cortex.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(
            envelope,
            summary=f"executed:{envelope.topic}",
        )
