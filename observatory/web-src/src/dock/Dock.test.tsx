import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Dock } from './Dock';
import { useStore } from '../store';

afterEach(() => {
  cleanup();
  localStorage.clear();
  useStore.setState({
    dockCollapsed: false,
    dockTab: 'firehose',
    dockHeight: 220,
    envelopes: [],
    firehoseFilter: '',
    dockPaused: false,
    expandedRowIds: new Set(),
  });
});

describe('Dock frame', () => {
  it('renders at default height 220px', () => {
    const { container } = render(<Dock />);
    const root = container.querySelector('#dock-root') as HTMLElement;
    expect(root.style.height).toBe('220px');
  });

  it('collapses to 28px when dockCollapsed is true', () => {
    const { container, rerender } = render(<Dock />);
    useStore.setState({ dockCollapsed: true });
    rerender(<Dock />);
    const root = container.querySelector('#dock-root') as HTMLElement;
    expect(root.style.height).toBe('28px');
  });

  it('mounts the real Firehose on the firehose tab', () => {
    const { container, getByPlaceholderText } = render(<Dock />);
    // Firehose has an input with a distinctive placeholder
    expect(getByPlaceholderText(/filter source · topic · payload/i)).toBeTruthy();
    // Filter bar should be rendered at the top of the firehose tab body
    expect(container.querySelector('input')).toBeTruthy();
  });

  it('mounts the placeholder for the topics tab', () => {
    const { queryByText, rerender } = render(<Dock />);
    useStore.setState({ dockTab: 'topics' });
    rerender(<Dock />);
    expect(queryByText(/Topics — implemented/)).toBeTruthy();
  });
});
