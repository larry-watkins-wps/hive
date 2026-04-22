import { describe, it, expect, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
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

  it('sorts rows by ewmaRate descending', () => {
    const t1: TopicStat = makeStat({
      topic: 'hive/fast',
      ewmaRate: 20,
      sparkBuckets: [0, 0, 0, 0, 0, 20],
      publishers: new Set(['r1']),
      publisherLastSeen: new Map([['r1', Date.now()]]),
      lastSeenMs: Date.now(),
      recent5: [],
    });
    const t2: TopicStat = makeStat({
      topic: 'hive/slow',
      ewmaRate: 1,
      sparkBuckets: [0, 0, 0, 0, 0, 1],
      publishers: new Set(['r2']),
      publisherLastSeen: new Map([['r2', Date.now()]]),
      lastSeenMs: Date.now(),
      recent5: [],
    });
    // fast LAST in insert order — the sorter must not rely on insertion
    const stats = new Map<string, TopicStat>([
      ['hive/slow', t2],
      ['hive/fast', t1],
    ]);
    const { container } = render(<Topics stats={stats} />);
    const topics = Array.from(container.querySelectorAll('span')).filter((s) =>
      s.textContent?.startsWith('hive/'),
    );
    expect(topics[0]?.textContent).toBe('hive/fast');
    expect(topics[1]?.textContent).toBe('hive/slow');
  });

  it('chevron click expands row to show recent 5', () => {
    const e1 = {
      observed_at: 1000,
      topic: 'hive/a',
      envelope: {},
      source_region: 'r1',
      destinations: [],
    };
    const e2 = {
      observed_at: 2000,
      topic: 'hive/a',
      envelope: {},
      source_region: 'r2',
      destinations: [],
    };
    const stat: TopicStat = makeStat({
      topic: 'hive/a',
      ewmaRate: 1,
      sparkBuckets: [0, 0, 0, 0, 0, 1],
      publishers: new Set(['r1', 'r2']),
      publisherLastSeen: new Map(),
      lastSeenMs: 2000,
      recent5: [e2, e1], // newest-first
    });
    const stats = new Map<string, TopicStat>([['hive/a', stat]]);
    const { container } = render(<Topics stats={stats} />);
    const chevron = container.querySelector('button') as HTMLButtonElement;
    fireEvent.click(chevron);
    expect(container.textContent).toContain('r1');
    expect(container.textContent).toContain('r2');
  });
});
