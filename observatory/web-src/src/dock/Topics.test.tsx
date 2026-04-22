import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Topics } from './Topics';
import type { TopicStat } from './useTopicStats';
import { useStore } from '../store';

afterEach(() => {
  cleanup();
  useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 });
});

function makeStat(overrides: Partial<TopicStat> = {}): TopicStat {
  return {
    topic: 'hive/a',
    ewmaRate: 0,
    sparkBuckets: [0, 0, 0, 0, 0, 0],
    publishers: new Set<string>(),
    publisherLastSeen: new Map<string, number>(),
    lastSeenMs: Date.now(),
    recent5: [],
    ...overrides,
  };
}

describe('Topics', () => {
  it('shows empty state when no topics', () => {
    const { getByText } = render(<Topics stats={new Map()} />);
    expect(getByText(/No topics yet/i)).toBeTruthy();
  });

  it('renders without crashing when envelopes exist', () => {
    const stats = new Map<string, TopicStat>();
    stats.set('hive/a', makeStat({ topic: 'hive/a', publishers: new Set(['r']), ewmaRate: 1.0 }));
    const { container } = render(<Topics stats={stats} />);
    expect(container).toBeTruthy();
    expect(container.textContent).toContain('hive/a');
  });
});
