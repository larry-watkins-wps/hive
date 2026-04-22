import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { SystemMetrics } from './SystemMetrics';
import { useStore } from '../store';

// The SystemMetrics tile reads three retained topics from the store:
//   hive/system/metrics/compute
//   hive/system/metrics/tokens
//   hive/system/metrics/region_health
// Each test seeds `useStore.setState({ retained: ... })` directly (partial
// update — other state preserved). `cleanup()` plus a retained-map reset in
// afterEach keeps tests isolated since vitest's `globals: false` disables
// auto-cleanup from @testing-library/react.
afterEach(() => {
  cleanup();
  useStore.setState({ retained: {} });
});

describe('SystemMetrics', () => {
  it('renders CPU + mem from compute topic', () => {
    useStore.setState({
      retained: { 'hive/system/metrics/compute': { total_cpu_pct: 42.7, total_mem_mb: 1024 } },
    });
    const { getByText } = render(<SystemMetrics />);
    expect(getByText(/42\.7%/)).toBeTruthy();
    expect(getByText(/1024 MB/)).toBeTruthy();
  });

  it('renders token totals', () => {
    useStore.setState({
      retained: {
        'hive/system/metrics/tokens': { total_input_tokens: 1234, total_output_tokens: 5678 },
      },
    });
    const { getByText } = render(<SystemMetrics />);
    expect(getByText(/1234/)).toBeTruthy();
    expect(getByText(/5678/)).toBeTruthy();
  });

  it('renders heatmap cells from region_health (object per_region schema)', () => {
    // Drift A: the real glia/metrics.py schema is:
    //   per_region[name] = {status, consecutive_misses, uptime_s}
    // NOT the bare status-string map the plan's fixture assumed. Liveness
    // (alive/stale/dead) is derived in the tile.
    useStore.setState({
      retained: {
        'hive/system/metrics/region_health': {
          per_region: {
            pfc: { status: 'wake', consecutive_misses: 0, uptime_s: 100 }, // alive
            amygdala: { status: 'wake', consecutive_misses: 2, uptime_s: 50 }, // stale
            acc: { status: 'dead', consecutive_misses: 0, uptime_s: 0 }, // dead
          },
        },
      },
    });
    const { container } = render(<SystemMetrics />);
    expect(container.querySelectorAll('[data-testid="health-cell"]').length).toBe(3);
  });

  it('shows dashes when topic missing', () => {
    const { getByText } = render(<SystemMetrics />);
    expect(getByText(/CPU\s+—/i)).toBeTruthy();
  });
});
