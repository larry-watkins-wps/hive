import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { Stm } from './sections/Stm';
import { useStore, type RegionStats } from '../store';

function stats(partial: Partial<RegionStats> = {}): RegionStats {
  return {
    phase: 'wake',
    queue_depth: 0,
    stm_bytes: 0,
    tokens_lifetime: 0,
    handler_count: 0,
    last_error_ts: null,
    msg_rate_in: 0,
    msg_rate_out: 0,
    llm_in_flight: false,
    ...partial,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('Stm section', () => {
  beforeEach(() => {
    useStore
      .getState()
      .applyRegionDelta({ r: { role: 'x', llm_model: '', stats: stats() } });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders empty-state copy when STM is {}', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({})));
    const { container } = render(<Stm name="r" />);
    // Expand the collapsed <details> so inner content is queryable.
    container.querySelector('details')!.open = true;
    await screen.findByText('STM is empty.');
  });

  it('renders the JSON tree when STM has keys', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ scratch: 'hello', count: 3 })),
    );
    const { container } = render(<Stm name="r" />);
    container.querySelector('details')!.open = true;
    // Key names appear in the tree as plain text.
    await screen.findByText('scratch');
    expect(screen.getByText('count')).toBeTruthy();
    // String values are quoted by JsonTree.
    expect(screen.getByText('"hello"')).toBeTruthy();
    // `STM is empty.` must NOT appear in the populated case.
    expect(screen.queryByText('STM is empty.')).toBeNull();
  });

  it('shows "· N keys" count in the summary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ a: 1, b: 2, c: 3 })),
    );
    render(<Stm name="r" />);
    await screen.findByText('· 3 keys');
  });
});
