import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { Header } from './sections/Header';
import { useStore } from '../store';

// The Header section calls `useRegionFetch(name, fetchConfig)`. The real
// fetcher hits `/api/regions/:name/config`; in jsdom that's a network error.
// Stubbing `fetch` keeps the hook happy and lets us control the config
// payload per test. All tests here use an empty config so the header falls
// back to store.llm_model (and then to the em-dash fallback when that's
// also empty).
describe('Header', () => {
  beforeEach(() => {
    // Reset the region store; some earlier test may have left entries.
    useStore.getState().applyRegionDelta({
      testregion: {
        role: 'x',
        llm_model: '',
        stats: {
          phase: 'wake',
          queue_depth: 0,
          stm_bytes: 0,
          tokens_lifetime: 0,
          handler_count: 5,
          last_error_ts: null,
          msg_rate_in: 0,
          msg_rate_out: 0,
          llm_in_flight: false,
        },
      },
    });
    // Default to a 200 OK with an empty object payload, so fetchConfig
    // resolves to `{}`; the header then falls through to the em-dash.
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
    // vitest `globals: false` means `@testing-library/react` does not
    // auto-cleanup between tests — each `render` would leave its DOM
    // attached and break `getByText`. Call `cleanup()` explicitly.
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders phase badge and handler count', () => {
    render(<Header name="testregion" />);
    // Phase badge uppercases the phase value.
    expect(screen.getByText(/WAKE/)).toBeTruthy();
    expect(screen.getByText(/handlers 5/)).toBeTruthy();
  });

  it('falls back to em-dash when llm_model is empty', () => {
    render(<Header name="testregion" />);
    expect(screen.getByText(/model —/)).toBeTruthy();
  });

  it('renders the region name and close button', () => {
    render(<Header name="testregion" />);
    expect(screen.getByText('testregion')).toBeTruthy();
    expect(screen.getByLabelText('close inspector')).toBeTruthy();
  });
});
