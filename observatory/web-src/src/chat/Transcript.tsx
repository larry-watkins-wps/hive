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
