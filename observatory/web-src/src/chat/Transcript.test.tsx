import { render, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Envelope, PendingChatTurn } from '../store';
import { useStore } from '../store';
import { Transcript } from './Transcript';

function envOnTopic(topic: string, data: unknown, id: string, ts: string): Envelope {
  return {
    observed_at: Date.parse(ts),
    topic,
    source_region: 'observatory_sensory',
    destinations: [],
    envelope: {
      id, timestamp: ts, envelope_version: 1,
      source_region: 'observatory_sensory',
      topic,
      payload: { content_type: 'application/json', encoding: 'utf-8', data },
      attention_hint: 0.5, reply_to: null, correlation_id: null,
    },
  };
}

// jest-dom matchers are not configured in this project's vitest setup
// (see vitest.config.ts and src/dock/Firehose.test.tsx); use plain text /
// element-presence assertions instead.
function findByText(container: HTMLElement, text: string | RegExp): Element | null {
  const all = container.querySelectorAll('*');
  for (const el of Array.from(all)) {
    // Only consider leaf-ish nodes whose own text (not concatenated children) matches.
    const direct = Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent ?? '')
      .join('');
    const haystack = direct.trim();
    if (!haystack) continue;
    if (typeof text === 'string') {
      if (haystack === text) return el;
    } else if (text.test(haystack)) {
      return el;
    }
  }
  return null;
}

function countByText(container: HTMLElement, text: string): number {
  const all = container.querySelectorAll('*');
  let count = 0;
  for (const el of Array.from(all)) {
    const direct = Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent ?? '')
      .join('')
      .trim();
    if (direct === text) count += 1;
  }
  return count;
}

describe('Transcript', () => {
  beforeEach(() => {
    useStore.setState({
      envelopes: [],
      pendingChatTurns: {},
    });
  });
  afterEach(() => {
    cleanup();
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
    const { container } = render(<Transcript />);
    expect(findByText(container, 'hi')).toBeTruthy();
    expect(findByText(container, 'hello')).toBeTruthy();
    expect(findByText(container, /unrelated/)).toBeNull();
  });

  it('renders user turn with the speaker label from payload data', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'are you there?', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    const { container } = render(<Transcript />);
    expect(findByText(container, 'Larry')).toBeTruthy();
    expect(findByText(container, 'are you there?')).toBeTruthy();
  });

  it('renders hive turn with text when payload.data.text is present', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { text: 'yes', utterance_id: 'u-1' }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    const { container } = render(<Transcript />);
    expect(findByText(container, 'hive')).toBeTruthy();
    expect(findByText(container, 'yes')).toBeTruthy();
  });

  it('renders audio placeholder when motor/speech/complete has no text', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { utterance_id: 'u-1', duration_ms: 4200 }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    const { container } = render(<Transcript />);
    expect(findByText(container, /🔊 hive spoke/)).toBeTruthy();
    expect(findByText(container, /4s/)).toBeTruthy();
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
    const { container, rerender } = render(<Transcript />);
    expect(findByText(container, 'optimistic')).toBeTruthy();

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
    expect(countByText(container, 'optimistic')).toBe(1);
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
    const { container } = render(<Transcript />);
    expect(findByText(container, /× failed to send/)).toBeTruthy();
    expect(findByText(container, /broker down/)).toBeTruthy();
  });
});
