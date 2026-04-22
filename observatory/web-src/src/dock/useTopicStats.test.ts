import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useTopicStats } from './useTopicStats';
import { useStore } from '../store';

describe('useTopicStats', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 });
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it('returns empty map initially', () => {
    const { result } = renderHook(() => useTopicStats());
    expect(result.current.size).toBe(0);
  });

  it('accumulates after first tick', () => {
    const { result } = renderHook(() => useTopicStats());
    for (let i = 0; i < 5; i++) {
      useStore.getState().pushEnvelope({
        observed_at: Date.now(),
        topic: 'hive/a',
        envelope: {},
        source_region: 'r',
        destinations: [],
      });
    }
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    const s = result.current.get('hive/a');
    expect(s).toBeDefined();
    expect(s!.publishers.has('r')).toBe(true);
    expect(s!.ewmaRate).toBeGreaterThan(0);
    expect(s!.sparkBuckets.at(-1)).toBe(5);
  });

  it('publishers decay after 60 s of no envelopes', () => {
    const { result } = renderHook(() => useTopicStats());
    useStore.getState().pushEnvelope({
      observed_at: Date.now(),
      topic: 'hive/a',
      envelope: {},
      source_region: 'r',
      destinations: [],
    });
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(result.current.get('hive/a')!.publishers.has('r')).toBe(true);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(result.current.get('hive/a')!.publishers.has('r')).toBe(false);
  });
});
