import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { Messages } from './sections/Messages';
import { useStore } from '../store';

describe('Messages', () => {
  beforeEach(() => {
    useStore.setState({ envelopes: [], envelopesReceivedTotal: 0, regions: {}, pendingEnvelopeKey: null });
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
    const rows = container.querySelectorAll('[data-testid="message-row-grid"]');
    expect(rows.length).toBe(100);
  });

  it('chevron click expands row to JsonTree view', () => {
    useStore.getState().pushEnvelope({
      observed_at: 0, topic: 'hive/x', envelope: { goal: 'reach', priority: 0.7 },
      source_region: 'r', destinations: [],
    });
    const { container } = render(<Messages name="r" />);
    // Collapsed: preview contains the JSON.stringify prefix, but no JsonTree key
    // row rendered yet. Click the row to expand.
    const row = container.querySelector('[data-testid="message-row-grid"]') as HTMLElement;
    fireEvent.click(row);
    // After expand, JsonTree renders the key "goal" in the value map.
    expect(container.textContent).toContain('goal');
    expect(container.textContent).toContain('reach');
  });

  it('pendingEnvelopeKey scrolls + auto-expands then clears the key', async () => {
    useStore.getState().pushEnvelope({
      observed_at: 100, topic: 'hive/metacog/error', envelope: { kind: 'LlmError', detail: 'rate_limit' },
      source_region: 'r', destinations: [],
    });
    const { container } = render(<Messages name="r" />);
    // Trigger the consumption pathway:
    useStore.getState().setPendingEnvelopeKey('100|hive/metacog/error');
    await waitFor(() => {
      // Key should clear after consumption.
      expect(useStore.getState().pendingEnvelopeKey).toBeNull();
    });
    // Row should now be expanded (JsonTree renders "kind" key).
    expect(container.textContent).toContain('kind');
    expect(container.textContent).toContain('LlmError');
  });
});
