import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { Inspector } from './Inspector';
import { useStore, type RegionStats } from '../store';

function baseStats(): RegionStats {
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
  };
}

describe('Inspector slide-out animation', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useStore.getState().applyRegionDelta({
      r1: { role: 'x', llm_model: '', stats: baseStats() },
      r2: { role: 'x', llm_model: '', stats: baseStats() },
    });
    useStore.getState().select(null);
    // Header calls fetchConfig; stub fetch so the hook resolves cleanly.
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({}), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
      ),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('renders children after select', () => {
    act(() => useStore.getState().select('r1'));
    render(<Inspector />);
    expect(screen.getByText('r1')).toBeTruthy();
  });

  it('keeps rendering children during the 300 ms slide-out window', () => {
    act(() => useStore.getState().select('r1'));
    render(<Inspector />);
    expect(screen.getByText('r1')).toBeTruthy();

    // Deselect — the panel's transform flips to `translate-x-full` but
    // displayName should stay 'r1' until the slide-out completes so the
    // animation has content to move.
    act(() => useStore.getState().select(null));
    expect(screen.queryByText('r1')).not.toBeNull();

    // Halfway through the window — still visible.
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.queryByText('r1')).not.toBeNull();

    // After the window — children unmount.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText('r1')).toBeNull();
  });

  it('re-selecting mid-transition cancels the clear timer', () => {
    act(() => useStore.getState().select('r1'));
    render(<Inspector />);
    act(() => useStore.getState().select(null));

    // 100 ms into the slide-out the user clicks a different region.
    act(() => {
      vi.advanceTimersByTime(100);
      useStore.getState().select('r2');
    });

    // Advance past the original 300 ms deadline — 'r2' must still render
    // (the original timer was cleared by the effect's cleanup).
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.queryByText('r2')).not.toBeNull();
    expect(screen.queryByText('r1')).toBeNull();
  });
});
