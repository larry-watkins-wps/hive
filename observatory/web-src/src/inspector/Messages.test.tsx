import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { Messages } from './sections/Messages';
import { useStore } from '../store';

describe('Messages', () => {
  beforeEach(() => {
    useStore.setState({ envelopes: [], envelopesReceivedTotal: 0, regions: {} });
    useStore.getState().applyRegionDelta({
      r: { role: 'x', llm_model: '', stats: { phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0, handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0, llm_in_flight: false } },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('shows only envelopes where region is source or destination', () => {
    useStore.getState().pushEnvelope({ observed_at: 0, topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [] });
    useStore.getState().pushEnvelope({ observed_at: 1, topic: 'hive/b', envelope: {}, source_region: 'other', destinations: ['r'] });
    useStore.getState().pushEnvelope({ observed_at: 2, topic: 'hive/c', envelope: {}, source_region: 'other', destinations: ['nope'] });
    render(<Messages name="r" />);
    expect(screen.getByText(/hive\/a/)).toBeTruthy();
    expect(screen.getByText(/hive\/b/)).toBeTruthy();
    expect(screen.queryByText(/hive\/c/)).toBeNull();
  });

  it('shows direction ↑ for source, ↓ for destination', () => {
    useStore.getState().pushEnvelope({ observed_at: 0, topic: 't/one', envelope: {}, source_region: 'r', destinations: [] });
    useStore.getState().pushEnvelope({ observed_at: 1, topic: 't/two', envelope: {}, source_region: 'x', destinations: ['r'] });
    render(<Messages name="r" />);
    expect(screen.getAllByText('↑').length).toBe(1);
    expect(screen.getAllByText('↓').length).toBe(1);
  });

  it('caps rendered rows at MAX_ROWS', () => {
    for (let i = 0; i < 150; i++) {
      useStore.getState().pushEnvelope({ observed_at: i, topic: `t/${i}`, envelope: {}, source_region: 'r', destinations: [] });
    }
    const { container } = render(<Messages name="r" />);
    const rows = container.querySelectorAll('.grid.grid-cols-\\[60px_14px_1fr\\]');
    expect(rows.length).toBe(100);
  });
});
