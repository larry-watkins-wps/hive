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

  it('row renders with undefined JSON payload data without crashing', () => {
    // Directly push an envelope with content_type: application/json and
    // data: undefined — JSON.stringify(undefined) returns undefined, and
    // without the nullish fallback the row previously crashed on .replace().
    useStore.getState().pushEnvelope({
      observed_at: Date.now() + Math.random(),
      topic: 'hive/cognitive/pfc/plan',
      envelope: {
        payload: { content_type: 'application/json', data: undefined },
      } as unknown as Record<string, unknown>,
      source_region: 'pfc',
      destinations: [],
    });
    const { container } = render(<Firehose />);
    const rows = container.querySelectorAll('[data-testid="firehose-row"]');
    expect(rows.length).toBe(1);
    // `data ?? null` coerces undefined to null, which stringifies to "null".
    expect(rows[0].textContent).toContain('null');
  });

  it('row chevron expands JsonTree inline', () => {
    push('hive/cognitive/pfc/plan', 'pfc', { goal: 'reach_block' });
    const { container } = render(<Firehose />);
    const chevron = container.querySelector(
      '[data-testid="firehose-row"] button',
    ) as HTMLButtonElement;
    fireEvent.click(chevron);
    // After expand, JsonTree renders the key 'goal' somewhere in the tree
    // output (sibling of the row, not inside it).
    expect(container.textContent).toContain('goal');
  });
});
