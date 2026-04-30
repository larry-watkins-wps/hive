"""Respond handler for hippocampus — dual-purpose episodic encoding +
query response.

Hippocampus has two kinds of LLM work that share the same parser, prompt
loader, and STM-recording finally block, so they live in one handler
with topic-conditional branches inside ``handle()``:

1. **Episodic encoding** — on every meaningful envelope that is not a
   ``hive/cognitive/hippocampus/query``, call the LLM with the envelope
   + recent context and emit a structured episodic record as a
   ``<publish topic="hive/cognitive/hippocampus/episode">{...}</publish>``
   block.

2. **Query response** — on incoming
   ``hive/cognitive/hippocampus/query``, call the LLM with the query +
   recent_events and emit a memory-retrieval response as a
   ``<publish topic="hive/cognitive/hippocampus/response">{...}</publish>``
   block.

Tag schema (documented in prompt.md "Response format" section):

    <thoughts>...</thoughts>            -> private; discarded
    <publish topic="X">{json}</publish>  -> ctx.publish(topic=X, ...)
    <request_sleep reason="..."/>        -> ctx.request_sleep(reason)

Hippocampus does NOT have the silence-is-valid escape that broca has —
encoding and responding are its job. Zero ``<publish>`` blocks IS a
parse failure and the handler emits one metacognition error envelope
(matching PFC / assoc_cortex behavior).

Authority + template: bootstrap mode (CLAUDE.md commit 42e60df). Parser
helpers (``_THOUGHTS_RE``, ``_PUBLISH_RE``, ``_REQUEST_SLEEP_RE``,
``_parse_response``) are a verbatim copy of the assoc_cortex / PFC /
broca respond.py template (commits 19e035a + 241d9a9 + 7024d3a +
69df91d). Deduplication into a shared module is deferred until the
handler cohort lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from region_template.llm_adapter import CompletionRequest, Message

SUBSCRIPTIONS = [
    # Encoding inputs.
    "hive/external/perception",
    "hive/sensory/auditory/text",
    "hive/cognitive/association_cortex/integration",
    "hive/cognitive/prefrontal_cortex/plan",
    # Query input — the only deliberation-style topic; topic-conditional
    # branch in handle() switches to the query-response path on this one.
    "hive/cognitive/hippocampus/query",
]
TIMEOUT_S = 30.0  # LLM call may take a while.

# Topic that switches the handler from the encoding branch to the
# query-response branch.
_QUERY_TOPIC = "hive/cognitive/hippocampus/query"

# Module-level: load prompt.md once. The handler module is reloaded by
# the runtime when the file changes during sleep.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"
try:
    _SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover — region scaffolds always include prompt.md
    _SYSTEM_PROMPT = "You are the Hippocampus of Hive."

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
# real publishes. Regression test:
# tests/unit/regions/hippocampus/test_handlers.py
#   ::test_respond_ignores_publish_tags_inside_thoughts
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
    ``parse_error`` is None on success, or a short reason string when
    something went wrong (zero blocks, JSON decode failure).
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


def _build_encoding_user_message(envelope, recent_events: list[dict]) -> str:
    data = envelope.payload.data if hasattr(envelope, "payload") else None
    if isinstance(data, dict):
        text = data.get("text", "")
        speaker = data.get("speaker", "unknown")
        modality = data.get("source_modality", data.get("modality", "unknown"))
    else:
        text = str(data) if data is not None else ""
        speaker = "unknown"
        modality = "unknown"

    envelope_id = getattr(envelope, "id", "")
    source = getattr(envelope, "source_region", "unknown")

    return (
        f"Envelope to encode as an episode:\n"
        f"envelope_id: {envelope_id}\n"
        f"topic: {envelope.topic}\n"
        f"source_region: {source}\n"
        f"speaker: {speaker}\n"
        f"modality: {modality}\n"
        f"text: {text}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Encode this envelope using the tag schema described in your "
        f"prompt. Emit exactly one "
        f"<publish topic=\"hive/cognitive/hippocampus/episode\"> block. "
        f"Default emotional_tag to \"neutral\" until amygdala threat "
        f"assessments are flowing on the bus. Set "
        f"envelope_id_encoded to the envelope_id above."
    )


def _build_query_user_message(envelope, recent_events: list[dict]) -> str:
    data = envelope.payload.data if hasattr(envelope, "payload") else None
    if isinstance(data, dict):
        query_id = data.get("query_id", getattr(envelope, "id", ""))
        query_text = data.get("query_text", data.get("text", ""))
        requesting_region = data.get("requesting_region", "unknown")
    else:
        query_id = getattr(envelope, "id", "")
        query_text = str(data) if data is not None else ""
        requesting_region = "unknown"

    return (
        f"Memory query received:\n"
        f"query_id: {query_id}\n"
        f"requesting_region: {requesting_region}\n"
        f"query_text: {query_text}\n\n"
        f"Recent events (last {_RECENT_EVENTS_TAIL} from STM):\n"
        f"{_format_recent_events(recent_events)}\n\n"
        f"Search your STM and any consolidated memory for matches and "
        f"respond using the tag schema described in your prompt. Emit "
        f"exactly one <publish topic=\"hive/cognitive/hippocampus/response\"> "
        f"block carrying query_id and a results list. If you find no "
        f"matches, return an empty results list — do not confabulate."
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
    is_query = envelope.topic == _QUERY_TOPIC

    # 1. Pull recent STM events for context.
    try:
        recent_events = await ctx.memory.recent_events()
    except Exception:  # noqa: BLE001 — defensive: never let STM read break encoding.
        recent_events = []

    # 2. Build and run the LLM call (branch on topic).
    if is_query:
        user_msg = _build_query_user_message(envelope, recent_events)
        purpose = "hippocampus.respond.query"
        stm_summary = f"query_responded:{envelope.topic}"
    else:
        user_msg = _build_encoding_user_message(envelope, recent_events)
        purpose = "hippocampus.respond.encode"
        stm_summary = f"encoded:{envelope.topic}"

    req = CompletionRequest(
        messages=[
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=user_msg),
        ],
        max_tokens=2048,
        temperature=0.7,
        purpose=purpose,
    )
    result = await ctx.llm.complete(req)
    raw_text = result.text

    # 3. Always record in STM, regardless of parse outcome.
    try:
        publishes, sleep_reason, parse_error = _parse_response(raw_text)

        if parse_error is not None:
            # Hippocampus does NOT have broca's silence escape — encoding
            # and responding are its job. Zero <publish> blocks is a
            # genuine parse failure that should surface as a metacog error.
            ctx.log.warning(
                "hippocampus.respond.parse_failure",
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
                "hippocampus.respond.published",
                topic=topic,
                size=len(json.dumps(body)),
            )

        if sleep_reason is not None:
            ctx.request_sleep(sleep_reason)
    finally:
        await ctx.memory.record_event(envelope, summary=stm_summary)
