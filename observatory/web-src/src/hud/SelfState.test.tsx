import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/react';
import { SelfState } from './SelfState';
import { useStore } from '../store';

// SelfState reads `ambient.self` directly (populated by Task 2's
// `extractAmbient` from `hive/self/*` retained topics). Tests seed
// `ambient` partially; `afterEach` resets it plus runs `cleanup()` — vitest
// `globals: false` disables @testing-library/react's automatic cleanup
// between tests.
afterEach(() => {
  cleanup();
  useStore.setState({ ambient: { modulators: {}, self: {} } });
});

describe('SelfState', () => {
  it('identity tab default, renders identity text', () => {
    useStore.setState({ ambient: { modulators: {}, self: { identity: 'I am Hive.' } } });
    const { getByText } = render(<SelfState />);
    expect(getByText(/I am Hive\./)).toBeTruthy();
  });

  it('switches to values tab', () => {
    useStore.setState({
      ambient: { modulators: {}, self: { identity: 'x', values: ['curiosity', 'care'] } },
    });
    const { getByText } = render(<SelfState />);
    fireEvent.click(getByText(/^Values$/));
    expect(getByText(/curiosity/)).toBeTruthy();
    expect(getByText(/care/)).toBeTruthy();
  });

  it('empty state per tab', () => {
    useStore.setState({ ambient: { modulators: {}, self: {} } });
    const { getByText } = render(<SelfState />);
    expect(getByText(/No data yet — mPFC hasn't published\./i)).toBeTruthy();
  });

  it('autobio sorts newest-first and truncates at 20', () => {
    // Build 25 entries with ascending ts (entry 25 has the latest ts).
    // Render should present entry 25 first and show exactly 20 rows plus a
    // single "N more…" footer (21 <li> elements total).
    const autobio = Array.from({ length: 25 }, (_, i) => ({
      ts: `2026-04-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
      headline: `entry ${i + 1}`,
    }));
    useStore.setState({ ambient: { modulators: {}, self: { autobiographical_index: autobio } } });
    const { container, getByText } = render(<SelfState />);
    fireEvent.click(getByText(/^Index$/));
    const first = container.querySelectorAll('li')[0]?.textContent ?? '';
    expect(first).toContain('entry 25');
    expect(container.querySelectorAll('li').length).toBe(21);
  });
});
