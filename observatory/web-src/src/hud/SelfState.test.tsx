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
});
