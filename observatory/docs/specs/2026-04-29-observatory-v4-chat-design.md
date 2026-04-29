# Observatory v4 — Chat with Hive

*Draft: 2026-04-29 · Authoritative spec for v4 implementation*

---

## 1. Purpose

v4 turns the observatory from a passive microscope into an instrument with a probe. It adds a **floating overlay chat surface** inside the existing observatory frontend, backed by a narrowly-scoped translator module on the backend (`observatory/sensory/`) that bridges the operator into Hive's nervous system.

The translator's role is biologically grounded: every sensory cortex's job is to convert a non-thought modality (audio, pixels) into thought-form text on the bus. The translator does the same job for the operator, from outside the organism — for typed input the translation is a near pass-through; for future audio/visual input it'll do real work (STT, captioning).

Sections of the v3 spec (`observatory/docs/specs/2026-04-22-observatory-v3-design.md`) are authoritative for anything v4 does not re-scope here.

## 2. Scope

**In scope (observatory-side; *no* edits to `regions/`):**

1. New `observatory/sensory/` backend module — the **only** part of observatory permitted to publish to MQTT. Single REST endpoint for v4: `POST /sensory/text/in`. Allowlist-gated.
2. One new MQTT topic: `hive/external/perception` — the translator's output channel for thought-form text arriving from outside Hive.
3. Floating-overlay chat surface in the frontend (`observatory/web-src/src/chat/`). Translucent draggable HUD panel summoned by hotkey `c`.
4. Transcript that filters the existing observatory envelope ring for `hive/external/perception` (user turns) and `hive/motor/speech/complete` (Hive turns). No new ring, no new persistence layer.
5. Two **draft code-change proposal artifacts** under `observatory/docs/proposals/` — payloads ready for cosign via Hive's existing `hive/system/codechange/proposed` channel. v4 itself does not modify any region.

**Out of scope (deferred):**

- Audio input (browser mic capture → `hive/hardware/mic`). Future PR; same allowlist mechanism.
- Visual input (camera/screen → `hive/hardware/camera`). Future PR.
- Server-side or browser-side STT for displaying Hive's audio responses. v4 renders the `text` field of `hive/motor/speech/complete` if present; otherwise an audio-only placeholder row.
- Multi-user identity, conversation threading, reactions, attachments. Single-operator instrument.
- Hippocampus-driven persistent conversation memory. Whatever the firehose ring holds is what's visible.
- Hive-side region edits (subscriptions, prompts, handlers). Per Principle III those happen via Hive's own cosigned code-change channel, drafted as artifacts here but not executed.

## 3. Bus topology

### 3.1 What v4 adds

Exactly **one** new topic:

| Topic | Direction | Owner | Payload |
|---|---|---|---|
| `hive/external/perception` | published by `observatory/sensory/`, may be subscribed by any region after cosign | observatory (single-publisher in practice; ACL not strictly required since the topic is outside `sensory/*` and no cortex claims it) | see §3.2 |

The topic is named `hive/external/perception` rather than `hive/sensory/text/in`, `hive/sensory/external/in`, or any cortex-shaped variant. Rationale:

- **`sensory/*` is cortex-owned.** Auditory_cortex publishes `hive/sensory/auditory/text` and reserves the `sensory/auditory/*` namespace; modality isolation (Principle IV) implies the same convention for any future cortex. A topic published by a process *outside* the organism does not belong in that namespace.
- **`external/perception` reads honestly.** It says: this is perception arriving from outside the body, post-translation. Regions that subscribe know they are reading a synthetic sensory pathway, not a cortex output.
- **Modality lives in the envelope, not the topic.** Future audio and visual translator paths reuse the same topic with different `source_modality` values. Topic-space does not fragment as modalities are added.

### 3.2 Envelope on `hive/external/perception`

The translator emits a fully-formed Hive `Envelope` (`src/shared/message_envelope.py`), not a bare payload — same wrapper every region uses, no schema deviation:

```json
{
  "envelope_version": 1,
  "id": "f7c4a2…-uuid-v4",
  "timestamp": "2026-04-29T14:32:08.417Z",
  "source_region": "observatory.sensory",
  "topic": "hive/external/perception",
  "payload": {
    "content_type": "application/json",
    "encoding": "utf-8",
    "data": {
      "text": "are you there?",
      "speaker": "Larry",
      "channel": "observatory.chat",
      "source_modality": "text"
    }
  },
  "attention_hint": 0.5,
  "reply_to": null,
  "correlation_id": null
}
```

Wrapper fields (set by the existing `Envelope.new(...)` factory):

- **`source_region`** = `"observatory.sensory"` — explicit non-region origin. The translator is not a brain region and shouldn't pretend to be one. The wrapper field is a free-form string; consumers that want to filter by "is this a real cortex output" can do so by checking the prefix.
- **`timestamp`** — server-side, ISO-8601 UTC ms-precision, generated by the factory at the moment of publish (not HTTP receipt — the publish call sets it).
- **`id`** — UUID v4, generated by the factory. **This is the dedupe key the chat frontend uses (§6.5).**
- **`payload.content_type`** = `"application/json"` for v4. (Adding a typed `"application/hive+external-perception"` ContentType would require editing `src/shared/message_envelope.py::ContentType` literal, which propagates across all regions — out of v4 scope. A future cosignable proposal can add it.)
- **`attention_hint`** = `0.5` (factory default). Tunable later if chat input should bias attention; v4 keeps it neutral.
- **`reply_to`**, **`correlation_id`** = null. Chat is fire-and-forget on the bus; conversation threading is not modelled at envelope level.

Inner `data` fields:

- **`text`** *(string, required)* — the thought-form representation. For `source_modality=text` this is verbatim user input post-trim. For future `source_modality=speech_transcribed` this is STT output. For `source_modality=image_captioned` this is the caption.
- **`speaker`** *(string, required)* — who originated the input. v4 default `"Larry"` from config (§8). Required so future hippocampus encoding can build per-speaker memory without an envelope migration.
- **`channel`** *(string, required)* — which observatory affordance produced this. v4 only emits `"observatory.chat"`. Future values: `"observatory.mic"`, `"observatory.screen"`. Lets regions distinguish "Larry typing in chat" from "Larry speaking into a mic" without inferring from `source_modality`.
- **`source_modality`** *(string, required)* — what the translator did to produce `text`. v4 only emits `"text"` (pass-through). Future: `"speech_transcribed"`, `"image_captioned"`.

There is no inner `ts` field — the envelope-level `timestamp` is the single source of truth and is what the firehose carries. Frontend dedupe (§6.5) keys on envelope `id`, not on timestamp.

### 3.3 What v4 reads

The chat transcript is a filtered view over observatory's existing envelope ring (`RING_CAP = 5000`, established v1). Two topics:

| Topic | Renders as | Source |
|---|---|---|
| `hive/external/perception` | user turn, keyed by `speaker` | translator's own publish — round-trips through the firehose and lands in the ring |
| `hive/motor/speech/complete` | Hive turn | broca, when an utterance is delivered |

Reading `complete` (post-articulation) rather than `motor/speech/intent` (pre-articulation) is deliberate:

1. The chat is a *communication* surface, not a thought monitor. observatory's firehose + Inspector already give full deliberation visibility; the chat should show what Hive *actually said*, not drafts that broca cancels.
2. Pure-B's "silence is a valid response" maps cleanly: if broca refuses or cancels an intent, no `complete` fires, and the transcript stays silent — that's genuine silence, not censored deliberation.
3. Symmetric with the input side: `external/perception` is post-translation thought from outside; `motor/speech/complete` is post-articulation thought from inside.

**Payload assumption.** v4's chat reads `payload.data.text` on `hive/motor/speech/complete` envelopes. Broca's existing prompt (`regions/broca_area/prompt.md`) lists `complete`/`partial` as published events without mandating payload schema. v4 expects, but does not require, the inner `data`:

```json
{
  "utterance_id": "uuid-…",
  "text": "yes — i was thinking about something else.",
  "duration_ms": 4217
}
```

If `text` is absent, the transcript renders an audio-only placeholder row: `🔊 hive spoke · HH:MM:SS · Ns` (duration omitted if `duration_ms` also absent). Broca evolving its payload to include `text` lands via a separate cosignable code-change proposal (§5.2).

### 3.4 What v4 does *not* add

- No new `hive/sensory/*` topics. Cortex namespace stays cortex-owned.
- No new `hive/motor/*` topics. The chat reads the existing `complete` event.
- No new region subscriptions in `regions/`. Cognitive reaction to `external/perception` arrives via cosigned code-change proposal, not v4.

## 4. Sensory module (backend)

### 4.1 Module layout

```
observatory/observatory/sensory/
├── __init__.py
├── allowlist.py     # frozenset of permitted topics
├── errors.py        # ForbiddenTopicError, PublishFailedError
├── publisher.py     # aiomqtt write client; allowlist enforcement
└── routes.py        # FastAPI APIRouter; POST /sensory/text/in
```

Module is mounted into the existing FastAPI app (`observatory/observatory/service.py::build_app`) via `app.include_router(sensory.routes.router, prefix="")`. Mounted at the root prefix; routes namespaced under `/sensory/*` for forward-compat with future audio/visual endpoints.

### 4.2 Allowlist

```python
# observatory/sensory/allowlist.py
from typing import FrozenSet

ALLOWED_PUBLISH_TOPICS: FrozenSet[str] = frozenset({
    "hive/external/perception",
})
```

Any call to `publisher.publish(topic, …)` whose `topic` is not in `ALLOWED_PUBLISH_TOPICS` raises `ForbiddenTopicError(topic)`. The allowlist is the **only** mechanism by which observatory writes to MQTT; the existing `RegionReader` does not import or share this module. Read and write surfaces stay independent.

Future PRs add topics to the allowlist explicitly (e.g. `"hive/hardware/mic"` when audio input lands). Each addition gets its own PR review against this spec.

### 4.3 Publisher

```python
# observatory/sensory/publisher.py
from shared.message_envelope import Envelope

class SensoryPublisher:
    def __init__(self, settings: Settings) -> None: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def publish(self, envelope: Envelope, *, qos: int = 1) -> None: ...
```

- Reuses `aiomqtt` at the same pinned version as `region_template/mqtt_client.py` (per `observatory/CLAUDE.md` gotcha).
- Connects on FastAPI `startup` event; disconnects on `shutdown`.
- `publish()` validates `envelope.topic ∈ ALLOWED_PUBLISH_TOPICS`, serialises via `envelope.to_json()` (the existing `Envelope` method that produces UTF-8 JSON bytes the rest of Hive expects), publishes with `qos=1` default. The envelope itself carries `source_region`, `id`, `timestamp` — the publisher does not synthesise those.
- On `aiomqtt.MqttError`, raises `PublishFailedError` wrapping the original. Routes translate that to HTTP 502 (§4.4).

### 4.4 Routes

```python
# observatory/sensory/routes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

class TextInRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speaker: str | None = None  # falls through to settings default

class TextInResponse(BaseModel):
    id: str         # envelope id (UUID v4) the translator generated
    timestamp: str  # ISO-8601 UTC, the envelope timestamp

@router.post("/sensory/text/in", status_code=202, response_model=TextInResponse)
async def text_in(
    body: TextInRequest,
    publisher: SensoryPublisher = Depends(get_publisher),
    settings: Settings = Depends(get_settings),
) -> TextInResponse: ...
```

Endpoint behaviour:

- Accepts `{text, speaker?}`. Trims `text` (server-side); rejects empty post-trim with 422.
- Constructs the envelope via `Envelope.new(source_region="observatory.sensory", topic="hive/external/perception", content_type="application/json", data={...})` (the factory generates `id` and `timestamp`).
- Inner `data` fills: `speaker` defaults to `settings.chat.default_speaker`, `channel="observatory.chat"`, `source_modality="text"`.
- Calls `publisher.publish(envelope, qos=settings.chat.publish_qos)` (publisher reads `topic` off the envelope and validates it against the allowlist).
- On success: `202 Accepted`, body `{id: "<uuid>", timestamp: "<iso>"}` — the envelope identifiers the frontend uses to dedupe its locally-rendered turn against the firehose echo (§6.5).
- On `ForbiddenTopicError`: 500 (programming error — should never happen from this route, since the route always builds an allowlist-permitted topic).
- On `PublishFailedError`: 502 with body `{error: "publish_failed", message: "<aiomqtt error>"}`.
- On Pydantic validation failure: 422 with FastAPI's standard validation body.

Cache-Control: `no-store` (mirrors v2's REST-route convention).

### 4.5 Settings

`observatory/observatory/config.py::Settings` gains:

```python
class ChatSettings(BaseModel):
    default_speaker: str = "Larry"
    publish_qos: int = 1
    text_max_length: int = 4000

class Settings(BaseSettings):
    # … existing fields …
    chat: ChatSettings = ChatSettings()
```

Env overrides via Pydantic-Settings nested-env (`__` separator):

- `OBSERVATORY_CHAT__DEFAULT_SPEAKER`
- `OBSERVATORY_CHAT__PUBLISH_QOS`
- `OBSERVATORY_CHAT__TEXT_MAX_LENGTH`

## 5. Code-change proposal artifacts

v4 ships two cosignable proposal payloads under `observatory/docs/proposals/`. Both are **inert documents**, not Hive-side edits — they describe the changes you cosign via `hive/system/codechange/proposed` when ready.

### 5.1 `2026-04-29-association-cortex-perception-subscription.yaml`

Proposes adding `hive/external/perception` to `regions/association_cortex/subscriptions.yaml`. Rationale: association_cortex's existing prompt declares it integrates multi-modal sensory inputs; `external/perception` is exactly that. This makes association_cortex the first cognitive responder to chat input.

Proposal payload shape (matching Hive's existing code-change proposal envelope):

```yaml
proposal_id: assoc-cortex-perception-2026-04-29
target: regions/association_cortex/subscriptions.yaml
kind: subscription_addition
diff:
  add:
    - topic: hive/external/perception
      qos: 1
      description: "External perception — thought-form text arriving from outside the organism (chat, future STT, future captioning)."
rationale: |
  Observatory v4 introduces a chat surface that publishes typed user input
  to hive/external/perception (see observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md).
  Association_cortex is the natural first reader because its prompt already
  declares multi-modal integration as its role. Without this subscription
  no region listens to chat input, and the conversation is one-way.
cosign_required: true
```

### 5.2 `2026-04-29-broca-speech-complete-text-payload.yaml`

Proposes refining broca's `hive/motor/speech/complete` payload to include the spoken `text`. Tiny enrichment, no new topic, no new region behaviour. Lands when broca has handlers (or alongside broca's first speech-output handler PR).

```yaml
proposal_id: broca-complete-text-payload-2026-04-29
target: regions/broca_area/prompt.md  # plus any handler that emits `complete`
kind: payload_enrichment
diff:
  field: text
  on_topic: hive/motor/speech/complete
  type: string
  required: true
  semantics: "verbatim text of the utterance broca articulated"
rationale: |
  Observatory v4's chat reads hive/motor/speech/complete to render Hive's
  responses in the transcript. With audio bytes alone the chat can show
  only an "🔊 hive spoke" placeholder. Adding text to the complete payload
  is biologically natural — a speaker knows what they just said — and
  costs broca nothing because it already holds the intent text it just
  synthesised.
cosign_required: true
```

Neither artifact is shipped *active*; both wait in `proposals/` until cosigned. Until then, v4's chat is one-way (after the first proposal is cosigned regions begin reacting; after the second, Hive's responses become readable).

## 6. Frontend chat surface

### 6.1 Module layout

```
observatory/web-src/src/chat/
├── ChatOverlay.tsx          # outer floating frame; drag/resize; visibility
├── Transcript.tsx           # filtered firehose view; per-turn rendering
├── TranscriptTurn.tsx       # one row (user or hive variant)
├── ChatInput.tsx            # textarea + Enter to send
├── useChatPersistence.ts    # localStorage position/size
├── useChatKeys.ts           # global `c` toggle + Esc dismiss inside overlay
├── useChatTranscript.ts     # selector over the envelope ring filtered to
│                            # the two topics + speaker dedupe
├── api.ts                   # POST /sensory/text/in wrapper
└── *.test.tsx               # vitest unit tests
```

Mounted in `App.tsx` as a sibling to `<Inspector />` and `<Dock />`.

### 6.2 Store extension

`observatory/web-src/src/store.ts` gains a chat slice:

```ts
type ChatSlice = {
  chatVisible: boolean;
  chatPosition: { x: number; y: number };  // top-left in viewport px
  chatSize: { w: number; h: number };
  setChatVisible: (v: boolean) => void;
  setChatPosition: (p: { x: number; y: number }) => void;
  setChatSize: (s: { w: number; h: number }) => void;
};
```

Defaults: `chatVisible: false`, `chatSize: { w: 320, h: 260 }`. `chatPosition` is computed lazily on first overlay open: `{ x: window.innerWidth - chatSize.w - 16, y: 16 }` (top-right with 16 px margin); after that it persists via `useChatPersistence`. If the persisted position would land off-screen (e.g. viewport shrunk between sessions), the overlay is clamped back inside the viewport at next open.

`useChatPersistence` mirrors `useDockPersistence`'s pattern: hydrate on first mount from `localStorage['observatory.chat.*']`, debounce subsequent writes (200 ms).

### 6.3 ChatOverlay

Translucent floating frame, rendered at `position: fixed` driven by `chatPosition`/`chatSize`. Hidden when `chatVisible === false` (component returns null — no DOM node when closed).

Visual style (matching v3 dock + Larry's thin/soft/hover-reveal aesthetic per `memory/feedback_observatory_visual_language.md`):

- Background `rgba(14,15,19,.72)` with `backdrop-filter: blur(14px)`.
- Border `1px solid rgba(80,84,96,.45)`, `border-radius: 4px`.
- No shadow, no gradient.
- Header strip: 9 px Inter, `letter-spacing: .5px`, uppercase, `rgba(180,184,192,.6)`. Text "chat with hive" left, drag handle implicit (header is the drag region).
- Body: transcript scrollable, auto-scroll-to-bottom when user is within 40 px of the end (same rule as Firehose / Messages).
- Input region: 1 px top border `rgba(80,84,96,.25)`; padding `10px 14px`; textarea is borderless, transparent, Inter 200 11 px, placeholder `rgba(120,124,135,.55)` italic.

Drag: `pointerdown` on header captures `(startX, startY, startPosX, startPosY)` in refs; `pointermove` updates `chatPosition` directly through the store setter (debounced persistence). Clamp to viewport with a 16 px margin so the overlay can't be dragged fully off-screen.

Resize: bottom-right 12×12 px corner handle. Same drag pattern. Clamp `w ∈ [240, 720]`, `h ∈ [180, 720]`.

### 6.4 Transcript

`useChatTranscript` selector:

```ts
function useChatTranscript() {
  return useStore(s => s.envelopes.filter(e =>
    e.topic === "hive/external/perception" ||
    e.topic === "hive/motor/speech/complete"
  ));
}
```

Each envelope renders as a `<TranscriptTurn>`:

- `external/perception` → user turn. Speaker label = `payload.data.speaker`. Body = `payload.data.text`. Timestamp = envelope `timestamp`.
- `motor/speech/complete` with `payload.data.text` → hive turn. Speaker label = `"hive"`. Body = `payload.data.text`. Timestamp = envelope `timestamp`.
- `motor/speech/complete` without `payload.data.text` → audio placeholder turn: `🔊 hive spoke · HH:MM:SS · {duration_ms/1000}s` (duration optional). Speaker label = `"hive"`.

Turn rendering matches the Inspector's existing transcript style:

```
larry              14:32:08
are you there?

hive               14:32:14
yes — i was thinking about something else.
```

- Speaker label: 9 px uppercase Inter, `letter-spacing: .5px`. User colour `rgba(143,197,255,.65)`; hive colour `rgba(220,180,255,.65)`. Mono timestamp 9 px, `rgba(120,124,135,.6)`, right-aligned within the speaker line.
- Body text: 11 px Inter 200, `line-height: 1.5`, `rgba(230,232,238,.88)`.
- Padding `10px 16px` per turn. No card chrome, no rounded background, no border between turns.

### 6.5 Local-first user turn rendering & dedupe

The chat input renders the user's typed message **immediately** after `Enter` (don't wait for the firehose round-trip). The same envelope then arrives via the WS firehose ~tens of ms later. Without dedupe the transcript would show every user message twice.

Dedupe key: envelope `id` (UUID v4). The translator's `POST /sensory/text/in` returns `{id, timestamp}` synchronously — the frontend stores the optimistic turn keyed by `id`, and when an envelope with the same `id` lands in the firehose ring, the optimistic turn is dropped. Bulletproof: ids are unique per envelope, generated at the publish site, and round-trip through MQTT unchanged.

Implementation: a small chat-local state slice holds optimistic turns by id. `Transcript` renders the union of (optimistic turns) and (ring envelopes filtered to the two topics), with optimistic turns suppressed once their id appears in the ring. While the POST is in flight (no `id` yet), the optimistic turn carries a temporary client-side key and renders normally; on POST success the response `id` replaces the temp key; on POST failure the optimistic turn is replaced with an error placeholder.

If the POST fails (4xx/5xx), the optimistic turn becomes an error placeholder: `× failed to send · {reason}` in `rgba(220,140,140,.7)`, no retry button. The user re-types. No retry storms.

### 6.6 Hotkey & focus

`useChatKeys` installs a single window-level keydown listener:

- `c` (no modifiers, when no input/textarea/contenteditable has focus) → toggle `chatVisible`.
- `Esc` (when `chatVisible === true` and event target is inside the overlay) → set `chatVisible = false` and blur. Esc does not propagate to the inspector dismiss handler.

When the overlay opens, focus moves to the textarea (so the user can type immediately). When the overlay closes, focus returns to the previously-focused element if it still exists, else to the body.

### 6.7 ChatInput

- `<textarea>` with `rows={2}`, auto-grow up to 6 rows.
- `Enter` (no shift) → submit. `Shift+Enter` → newline.
- Submit is disabled when `text.trim() === ""`.
- On submit: render optimistic local turn; clear textarea; `POST /sensory/text/in {text, speaker: undefined}` (server fills speaker default).
- Below the textarea, a single hint line: `enter to send · esc to dismiss · c to toggle`. 9 px mono `rgba(120,124,135,.55)`. Hidden when `h < 200`.

## 7. UI behavior & visual language

Pure-B conversation shape (locked during brainstorm):

- **No spinner.** No "Hive is thinking" indicator.
- **No delivery receipt.** No "✓ delivered" mark.
- **No attention indicator.** No light-up when association_cortex receives the envelope.
- **Silence is silence.** If broca produces no `complete`, the transcript shows nothing.

The only feedback the user sees is the optimistic local turn appearing immediately and persisting once the firehose echoes it back. If the POST fails, the optimistic turn becomes an error placeholder (§6.5). That's the entire feedback surface.

Visual restraint matches existing observatory norms (Inspector, Dock, Labels): thin Inter 200 typography, soft alpha gradients, hover-reveal restraint, no card chrome, no shadows, no animation beyond the overlay's open/close fade (`transition: opacity .18s ease`, no slide).

## 8. Configuration

| Setting | Default | Env override |
|---|---|---|
| `chat.default_speaker` | `"Larry"` | `OBSERVATORY_CHAT__DEFAULT_SPEAKER` |
| `chat.publish_qos` | `1` | `OBSERVATORY_CHAT__PUBLISH_QOS` |
| `chat.text_max_length` | `4000` | `OBSERVATORY_CHAT__TEXT_MAX_LENGTH` |

The MQTT broker host/port and credentials reuse observatory's existing settings (no separate config block). Same broker at `127.0.0.1:1883` per `memory/reference_hive_broker.md`.

## 9. Tests

### 9.1 Backend unit (`observatory/tests/unit/sensory/`)

- `test_allowlist.py` — `ALLOWED_PUBLISH_TOPICS` is exactly `{"hive/external/perception"}`.
- `test_publisher.py` — `publish()` raises `ForbiddenTopicError` for any topic outside the allowlist; serialises payload as JSON; `publish_failed` wraps `aiomqtt.MqttError`.
- `test_routes.py` — `POST /sensory/text/in` validates body, fills speaker default, builds an envelope via `Envelope.new(...)`, calls `publisher.publish(envelope, qos=settings.chat.publish_qos)`, returns 202 with the envelope's `id` and `timestamp` in the response body.

### 9.2 Backend component (`observatory/tests/component/sensory/`)

- Real broker via `eclipse-mosquitto:2` testcontainer (matching v1/v2/v3 component tests).
- POST hits the route → broker confirms a publish on `hive/external/perception` with the expected envelope. Round-trip latency assertion `< 500 ms` to keep the test honest about freshness.
- Forbidden-topic injection (mock the route to call publisher with a wrong topic) → assert `ForbiddenTopicError` and 500.

### 9.3 Frontend (`observatory/web-src/src/chat/*.test.tsx`)

- `ChatOverlay.test.tsx` — open/close via store; drag updates position; resize updates size; hidden when `chatVisible === false`.
- `Transcript.test.tsx` — filters envelopes to the two topics; renders user/hive variants correctly; dedupe between optimistic and firehose-echo for the same envelope.
- `ChatInput.test.tsx` — Enter submits; Shift+Enter newlines; empty-after-trim disables submit; optimistic turn + clear textarea on submit; error placeholder on failed POST.
- `useChatKeys.test.tsx` — `c` toggles when not in input; ignored when in input/textarea/contenteditable; `Esc` closes when inside overlay.
- `useChatPersistence.test.ts` — hydrate from localStorage on mount; debounce writes.

### 9.4 Lint / typecheck

- `python -m ruff check observatory/observatory/sensory/ observatory/tests/unit/sensory/ observatory/tests/component/sensory/` clean.
- `npx tsc -b` clean; `npx vitest run` all passing.

## 10. Out of scope for v4

(Repeated from §2 for emphasis.)

- Audio input pathway. The translator's allowlist will gain `hive/hardware/mic` in a later PR; a browser-side mic capture component will publish chunks via `POST /sensory/audio/chunk`.
- Visual input pathway (camera/screen). Same shape; `hive/hardware/camera`.
- STT for displaying Hive's audio responses when broca emits audio without a `text` payload. v4 shows a placeholder; STT lands once we decide between server-side (in `observatory/sensory/`) and browser-side (Web Speech API).
- Multi-user identity, threaded conversations, attachments, reactions.
- Hippocampus-driven persistent transcript memory across observatory restarts.
- Retract / cancel an in-flight publish.
- Visualising in the 3D scene which region just received the chat envelope (overlap with v3 firehose / Inspector — already covered).

## 11. Authority and constitutional notes

- **Principle I (Biology is Tiebreaker).** The translator's existence is justified as a *synthetic external sensory pathway* — it does the same work a sensory cortex would do (translate non-thought modality → thought-form text on the bus). Its output topic is named `hive/external/perception` to signal explicitly that it is *external* to the organism. v4 does not invent any cortex-shaped topic.
- **Principle III (Regions are Sovereign).** v4 does not modify any file under `regions/`. Cognitive subscription to `hive/external/perception` and broca's payload enrichment land via cosigned code-change proposals (§5), not via v4's PR.
- **Principle IV (Modality Isolation).** `hive/sensory/*` remains cortex-owned; the translator does not publish into that namespace. `hive/hardware/mic`, `hive/hardware/speaker`, `hive/hardware/camera` remain ACL-fenced to their owning regions; the translator's allowlist may gain `hardware/mic` and `hardware/camera` in future PRs but never `hardware/speaker` (broca's exclusive output).
- **Principle XII (Every Change is Committed).** Granular commit-per-task continues per `observatory/CLAUDE.md`.
- **Observatory's "read-only" framing.** Replaced by an explicit, narrowly-scoped *write boundary* (§4.2 allowlist). Read and write surfaces stay independent (no shared imports between `RegionReader` and `SensoryPublisher`). Future expansion of the allowlist requires a PR that updates this spec.

## 12. References

- v3 spec: `observatory/docs/specs/2026-04-22-observatory-v3-design.md`
- v2 spec: `observatory/docs/specs/2026-04-21-observatory-v2-design.md`
- v1 spec: `observatory/docs/specs/2026-04-20-observatory-design.md`
- Hive v0 design (constitutional principles): `docs/superpowers/specs/2026-04-19-hive-v0-design.md`
- Auditory cortex prompt: `regions/auditory_cortex/prompt.md` (modality isolation, sensory/auditory/text ownership)
- Broca prompt: `regions/broca_area/prompt.md` (speech-complete event semantics)
- Larry's UI aesthetic: `~/.claude/projects/C--repos-hive/memory/feedback_observatory_visual_language.md`
- Hive broker location: `~/.claude/projects/C--repos-hive/memory/reference_hive_broker.md`
