# v4 Task 8 — Transcript + TranscriptTurn

You are an implementer subagent for observatory v4 Task 8. Implement it in `C:/repos/hive`. Self-contained — do not read the plan/spec/HANDOFF beyond what's quoted here.

## Context

Tasks 6+7 already landed (`d1f3990` is the head of v4 work). The zustand store has the chat slice, including `pendingChatTurns: Record<string, PendingChatTurn>`. `useChatPersistence` and `postChatText` are also in place.

This task creates the read-only Transcript view: a filtered slice of the existing envelope ring scoped to two topics, unioned with optimistic pending turns, deduped at render time by envelope id.

## Files

- **Create:** `observatory/web-src/src/chat/Transcript.tsx`
- **Create:** `observatory/web-src/src/chat/TranscriptTurn.tsx`
- **Create:** `observatory/web-src/src/chat/Transcript.test.tsx`

## Spec excerpts

**§3.3 What v4 reads** — the chat transcript filters on two topics:
- `hive/external/perception` → user turn, keyed by `payload.data.speaker`
- `hive/motor/speech/complete` → hive turn (with `payload.data.text`) OR audio placeholder (no text)

For audio placeholder: `🔊 hive spoke · HH:MM:SS · {duration_ms/1000}s` (duration optional).

**§6.4 Transcript** — each envelope renders as a `<TranscriptTurn>`. Speaker label 9 px uppercase Inter, letter-spacing .5 px. User colour `rgba(143,197,255,.65)`; hive colour `rgba(220,180,255,.65)`. Mono timestamp 9 px, `rgba(120,124,135,.6)`, right-aligned in the speaker line. Body 11 px Inter 200, line-height 1.5, `rgba(230,232,238,.88)`. Padding `10px 16px` per turn. No card chrome, no rounded background, no border between turns.

**§6.5 Dedupe** — Optimistic pending turns are unioned with ring envelopes; when the same envelope `id` appears in the ring, the pending turn is suppressed at render time. Failed pending turns become an error placeholder: `× failed to send · {reason}` in `rgba(220,140,140,.7)`.

**§6.3 Auto-scroll** — auto-scroll-to-bottom when user is within 40 px of the end (matches Firehose/Messages behaviour).

## Existing types (confirmed via `observatory/web-src/src/store.ts`)

```ts
export type Envelope = {
  observed_at: number;
  topic: string;
  envelope: Record<string, unknown>;
  source_region: string | null;
  destinations: string[];
};

export type PendingChatTurn = {
  id: string;
  text: string;
  speaker: string;
  timestamp: string;
  status: 'sending' | 'sent' | 'failed';
  errorReason?: string;
};
```

The inner `envelope` field carries the wire-form `Envelope` (from `src/shared/message_envelope.py`): `{id, timestamp, envelope_version, source_region, topic, payload: {content_type, encoding, data}, attention_hint, reply_to, correlation_id}`.

## Implementation

### Step 1 — Test (TDD red)

Create `observatory/web-src/src/chat/Transcript.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Envelope, PendingChatTurn } from '../store';
import { useStore } from '../store';
import { Transcript } from './Transcript';

function envOnTopic(topic: string, data: unknown, id: string, ts: string): Envelope {
  return {
    observed_at: Date.parse(ts),
    topic,
    source_region: 'observatory.sensory',
    destinations: [],
    envelope: {
      id, timestamp: ts, envelope_version: 1,
      source_region: 'observatory.sensory',
      topic,
      payload: { content_type: 'application/json', encoding: 'utf-8', data },
      attention_hint: 0.5, reply_to: null, correlation_id: null,
    },
  };
}

describe('Transcript', () => {
  beforeEach(() => {
    useStore.setState({
      envelopes: [],
      pendingChatTurns: {},
    });
  });
  afterEach(() => {
    useStore.setState({ envelopes: [], pendingChatTurns: {} });
  });

  it('filters envelopes to the two transcript topics', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'hi', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
        envOnTopic('hive/cognitive/pfc/plan', { unrelated: true }, 'env-2', '2026-04-29T14:01:00.000Z'),
        envOnTopic('hive/motor/speech/complete',
          { text: 'hello', utterance_id: 'u-1' }, 'env-3', '2026-04-29T14:02:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.queryByText(/unrelated/)).toBeNull();
  });

  it('renders user turn with the speaker label from payload data', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'are you there?', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('Larry')).toBeInTheDocument();
    expect(screen.getByText('are you there?')).toBeInTheDocument();
  });

  it('renders hive turn with text when payload.data.text is present', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { text: 'yes', utterance_id: 'u-1' }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('hive')).toBeInTheDocument();
    expect(screen.getByText('yes')).toBeInTheDocument();
  });

  it('renders audio placeholder when motor/speech/complete has no text', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { utterance_id: 'u-1', duration_ms: 4200 }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText(/🔊 hive spoke/)).toBeInTheDocument();
    expect(screen.getByText(/4s/)).toBeInTheDocument();
  });

  it('renders pending optimistic turn alongside ring envelopes, then dedupes', () => {
    const pending: PendingChatTurn = {
      id: 'env-1', text: 'optimistic', speaker: 'Larry',
      timestamp: '2026-04-29T14:00:00.000Z', status: 'sent',
    };
    useStore.setState({
      envelopes: [],
      pendingChatTurns: { 'env-1': pending },
    });
    const { rerender } = render(<Transcript />);
    expect(screen.getByText('optimistic')).toBeInTheDocument();

    // Now the firehose echo arrives with the same envelope id.
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'optimistic', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
      ],
      pendingChatTurns: { 'env-1': pending },  // pending still in store; dedupe is render-time
    });
    rerender(<Transcript />);
    // The text appears exactly once — pending was suppressed because the id matches.
    expect(screen.getAllByText('optimistic')).toHaveLength(1);
  });

  it('renders error placeholder for failed pending turn', () => {
    useStore.setState({
      pendingChatTurns: {
        'tmp-1': {
          id: 'tmp-1', text: 'hi', speaker: 'Larry',
          timestamp: '2026-04-29T14:00:00.000Z',
          status: 'failed', errorReason: 'publish_failed: broker down',
        },
      },
    });
    render(<Transcript />);
    expect(screen.getByText(/× failed to send/)).toBeInTheDocument();
    expect(screen.getByText(/broker down/)).toBeInTheDocument();
  });
});
```

### Step 2 — Implement TranscriptTurn

Create `observatory/web-src/src/chat/TranscriptTurn.tsx`:

```tsx
/**
 * One row in the chat transcript. Plain text — no card chrome — matching
 * the v3 inspector message style. Spec §6.4.
 */
import type { CSSProperties } from 'react';

type Variant = 'user' | 'hive' | 'audio_placeholder' | 'error';

type Props = {
  variant: Variant;
  speaker: string;
  body: string;
  timestamp: string;       // ISO; rendered HH:MM:SS in mono
  errorReason?: string;
};

const SPEAKER_COLORS: Record<Variant, string> = {
  user: 'rgba(143,197,255,.65)',
  hive: 'rgba(220,180,255,.65)',
  audio_placeholder: 'rgba(220,180,255,.65)',
  error: 'rgba(220,140,140,.7)',
};

function fmtClock(iso: string): string {
  // ISO is "YYYY-MM-DDTHH:MM:SS.sssZ" — substring HH:MM:SS.
  const t = iso.indexOf('T');
  return t >= 0 ? iso.substring(t + 1, t + 9) : iso;
}

const speakerStyle = (variant: Variant): CSSProperties => ({
  fontSize: 9, letterSpacing: '.5px', textTransform: 'uppercase',
  color: SPEAKER_COLORS[variant], marginBottom: 3,
  display: 'flex', justifyContent: 'space-between',
});
const tsStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.6)',
};
const bodyStyle = (variant: Variant): CSSProperties => ({
  fontSize: 11, fontWeight: 200, lineHeight: 1.5,
  color: variant === 'error' ? SPEAKER_COLORS.error : 'rgba(230,232,238,.88)',
});
const rowStyle: CSSProperties = { padding: '10px 16px' };

export function TranscriptTurn({ variant, speaker, body, timestamp, errorReason }: Props) {
  return (
    <div style={rowStyle} data-testid="transcript-turn" data-variant={variant}>
      <div style={speakerStyle(variant)}>
        <span>{speaker}</span>
        <span style={tsStyle}>{fmtClock(timestamp)}</span>
      </div>
      <div style={bodyStyle(variant)}>
        {variant === 'error' && errorReason ? `× failed to send · ${errorReason}` : body}
      </div>
    </div>
  );
}
```

### Step 3 — Implement Transcript

Create `observatory/web-src/src/chat/Transcript.tsx`:

```tsx
/**
 * Filtered firehose view: hive/external/perception + hive/motor/speech/complete,
 * unioned with pending optimistic turns from the store. Dedupe happens at
 * render time by envelope id. Spec §3.3, §6.4, §6.5.
 */
import { useMemo, useRef, useEffect, type CSSProperties } from 'react';

import { useStore, type Envelope, type PendingChatTurn } from '../store';
import { TranscriptTurn } from './TranscriptTurn';

const TRANSCRIPT_TOPICS = new Set(['hive/external/perception', 'hive/motor/speech/complete']);

type Turn = {
  key: string;
  variant: 'user' | 'hive' | 'audio_placeholder' | 'error';
  speaker: string;
  body: string;
  timestamp: string;
  errorReason?: string;
  sortMs: number;
};

function envelopeToTurn(e: Envelope): Turn | null {
  const inner = e.envelope as {
    id: string; timestamp: string;
    payload?: { data?: Record<string, unknown> };
  };
  const data = inner.payload?.data ?? {};
  if (e.topic === 'hive/external/perception') {
    return {
      key: inner.id,
      variant: 'user',
      speaker: String(data.speaker ?? 'unknown'),
      body: String(data.text ?? ''),
      timestamp: inner.timestamp,
      sortMs: Date.parse(inner.timestamp) || e.observed_at,
    };
  }
  // hive/motor/speech/complete
  const text = data.text;
  if (typeof text === 'string' && text.length > 0) {
    return {
      key: inner.id,
      variant: 'hive',
      speaker: 'hive',
      body: text,
      timestamp: inner.timestamp,
      sortMs: Date.parse(inner.timestamp) || e.observed_at,
    };
  }
  // audio placeholder — no text payload
  const ms = typeof data.duration_ms === 'number' ? data.duration_ms : null;
  const dur = ms !== null ? ` · ${Math.round(ms / 1000)}s` : '';
  return {
    key: inner.id,
    variant: 'audio_placeholder',
    speaker: 'hive',
    body: `🔊 hive spoke${dur}`,
    timestamp: inner.timestamp,
    sortMs: Date.parse(inner.timestamp) || e.observed_at,
  };
}

function pendingToTurn(p: PendingChatTurn): Turn {
  return {
    key: p.id,
    variant: p.status === 'failed' ? 'error' : 'user',
    speaker: p.speaker,
    body: p.text,
    timestamp: p.timestamp,
    errorReason: p.errorReason,
    sortMs: Date.parse(p.timestamp) || Date.now(),
  };
}

export function Transcript() {
  const envelopes = useStore((s) => s.envelopes);
  const pending = useStore((s) => s.pendingChatTurns);

  const turns = useMemo(() => {
    const fromRing: Turn[] = [];
    const seenIds = new Set<string>();
    for (const e of envelopes) {
      if (!TRANSCRIPT_TOPICS.has(e.topic)) continue;
      const turn = envelopeToTurn(e);
      if (turn) {
        fromRing.push(turn);
        seenIds.add(turn.key);
      }
    }
    const fromPending: Turn[] = [];
    for (const p of Object.values(pending)) {
      if (seenIds.has(p.id)) continue;  // ring already has it — dedupe
      fromPending.push(pendingToTurn(p));
    }
    return [...fromRing, ...fromPending].sort((a, b) => a.sortMs - b.sortMs);
  }, [envelopes, pending]);

  // Auto-scroll-to-bottom when within 40px of the end (spec §6.3).
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const distanceFromEnd = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromEnd < 40) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const containerStyle: CSSProperties = { flex: 1, overflowY: 'auto' };

  return (
    <div ref={bodyRef} style={containerStyle} data-testid="transcript">
      {turns.map((t) => (
        <TranscriptTurn
          key={t.key}
          variant={t.variant}
          speaker={t.speaker}
          body={t.body}
          timestamp={t.timestamp}
          errorReason={t.errorReason}
        />
      ))}
    </div>
  );
}
```

## Gotchas

- The plan's test originally asserted `screen.getByText('larry')` (lowercase) but the speaker label in the test envelope is `'Larry'`. Spec §6.4 says the rendered label is `textTransform: 'uppercase'` via CSS — the DOM text remains the original case. I've adjusted the second test in this prompt to assert `'Larry'` (the actual DOM text). The CSS uppercases visually only.
- `vitest.config.ts` has `globals: false` — import `describe`, `it`, etc. explicitly.
- The test mutates `useStore.setState` directly — this is the established pattern in v3 tests (see `src/dock/Firehose.test.tsx`). Cleanup in `afterEach` resets to neutral.
- Add `cleanup()` from `@testing-library/react` in `afterEach` if any test produces multi-render leaks; the existing tests use `setState` reset which is sufficient — but if you find leaks while iterating, follow the precedent in `src/chat/useChatPersistence.test.ts` (also uses `cleanup`).
- Don't import `@testing-library/jest-dom` — vitest setup already provides matchers per existing v3 tests. If `toBeInTheDocument` is undefined at runtime, check `vitest.setup.ts` / `vitest.config.ts` and re-use whatever the dock tests do (see `src/dock/Firehose.test.tsx` for the pattern; do NOT add new setup files).

## Verification

From `observatory/web-src/`:
```bash
npx vitest run src/chat/Transcript.test.tsx    # 6 passed
npx tsc -b                                       # clean
npx vitest run                                   # full suite, 187 passed (was 181, +6)
```

## Commit

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/Transcript.tsx observatory/web-src/src/chat/TranscriptTurn.tsx observatory/web-src/src/chat/Transcript.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): Transcript + TranscriptTurn

Filtered view of the existing envelope ring scoped to
hive/external/perception (user turns) and hive/motor/speech/complete
(hive turns / audio placeholder). Unions with optimistic pendingChatTurns
from the store, deduped at render time by envelope id. Auto-scroll to
bottom when within 40px (matches v3 firehose / messages behaviour).

TranscriptTurn renders one row in the v3 inspector style — no card
chrome, speaker tag in caps + colour-coded (user blue, hive purple,
error red), Inter 200 body, mono timestamp. Spec §6.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Status report

Report DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED with: SHA, 1–3 sentence summary, deviations, last lines of full `npx vitest run`.
