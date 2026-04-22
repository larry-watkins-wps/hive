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

  it('mounts the real Topics component on the topics tab', () => {
    // v3 Task 6 replaced the placeholder with the real Topics component.
    // With no envelopes pushed, `useTopicStats()` returns an empty map
    // on its first tick so Topics shows the empty-state message.
    const { queryByText, rerender } = render(<Dock />);
    useStore.setState({ dockTab: 'topics' });
    rerender(<Dock />);
    expect(queryByText(/No topics yet/i)).toBeTruthy();
  });

  it('mounts the real Metacog component on the metacog tab', () => {
    // v3 Task 7 replaced the placeholder with the real Metacog component.
    // With no envelopes pushed, the filter returns an empty list so Metacog
    // shows the empty-state message.
    const { queryByText, rerender } = render(<Dock />);
    useStore.setState({ dockTab: 'metacog' });
    rerender(<Dock />);
    expect(queryByText(/No metacognition events yet\./i)).toBeTruthy();
  });
});
