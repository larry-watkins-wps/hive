import { describe, it, expect, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
import { Firehose } from './Firehose';
import { useStore } from '../store';

function push(topic: string, source: string, data: unknown = {}) {
  useStore.getState().pushEnvelope({
    observed_at: Date.now() + Math.random(),
    topic,
    envelope: { payload: { content_type: 'application/json', data } } as unknown as Record<string, unknown>,
    source_region: source,
    destinations: [],
  });
}

afterEach(() => {
  cleanup();
  useStore.setState({ envelopes: [], firehoseFilter: '', dockPaused: false, expandedRowIds: new Set() });
});

describe('Firehose', () => {
  it('renders rows from envelope ring', () => {
    push('hive/cognitive/pfc/plan', 'pfc');
    push('hive/cognitive/pfc/plan', 'pfc');
    const { container } = render(<Firehose />);
    expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
  });

  it('substring filter is case-insensitive', async () => {
    push('hive/cognitive/pfc/plan', 'prefrontal_cortex');
    push('hive/modulator/dopamine', 'glia');
    const { container, getByPlaceholderText } = render(<Firehose />);
    const input = getByPlaceholderText(/filter source · topic · payload/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'DOPAMINE' } });
    await new Promise((r) => setTimeout(r, 200));
    const rows = container.querySelectorAll('[data-testid="firehose-row"]');
    rows.forEach((r) => expect(r.textContent).toMatch(/dopamine/i));
  });

  it('regex filter honours /pattern/i', async () => {
    push('hive/cognitive/pfc/plan', 'pfc');
    push('hive/modulator/dopamine', 'glia');
    const { container, getByPlaceholderText } = render(<Firehose />);
    const input = getByPlaceholderText(/filter source · topic · payload/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '/modulator/i' } });
    await new Promise((r) => setTimeout(r, 200));
    expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(1);
  });

  it('pause snapshots the ring', () => {
    push('hive/a', 'r');
    push('hive/b', 'r');
    const { container, rerender } = render(<Firehose />);
    expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
    useStore.setState({ dockPaused: true });
    rerender(<Firehose />);
    push('hive/c', 'r');
    rerender(<Firehose />);
    expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
  });
});
