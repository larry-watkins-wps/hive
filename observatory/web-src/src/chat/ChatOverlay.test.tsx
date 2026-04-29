// observatory/web-src/src/chat/ChatOverlay.test.tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../store';
import { ChatOverlay } from './ChatOverlay';

describe('ChatOverlay', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    useStore.setState({
      chatVisible: false,
      chatPosition: { x: 0, y: 16 },
      chatSize: { w: 320, h: 260 },
      pendingChatTurns: {},
      envelopes: [],
    });
  });
  afterEach(() => {
    cleanup();
    useStore.setState({ chatVisible: false });
  });

  it('renders nothing when chatVisible is false', () => {
    render(<ChatOverlay />);
    expect(screen.queryByTestId('chat-overlay')).toBeNull();
  });

  it('renders the overlay when chatVisible is true', () => {
    useStore.setState({ chatVisible: true });
    render(<ChatOverlay />);
    expect(screen.queryByTestId('chat-overlay')).not.toBeNull();
    expect(screen.queryByText('chat with hive')).not.toBeNull();
  });

  it('lazy-computes default position to top-right on first open', () => {
    // chatPosition.x starts at 0; opening should snap to viewport.w - size.w - 16.
    useStore.setState({ chatPosition: { x: 0, y: 16 } });
    useStore.setState({ chatVisible: true });
    render(<ChatOverlay />);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBe(1200 - 320 - 16);  // 864
  });

  it('preserves user-set position on subsequent opens', () => {
    useStore.setState({ chatPosition: { x: 100, y: 100 }, chatVisible: true });
    render(<ChatOverlay />);
    const pos = useStore.getState().chatPosition;
    expect(pos).toEqual({ x: 100, y: 100 });
  });

  it('drag from header updates chatPosition', () => {
    useStore.setState({ chatVisible: true, chatPosition: { x: 100, y: 100 } });
    render(<ChatOverlay />);
    const header = screen.getByTestId('chat-header');
    fireEvent.pointerDown(header, { clientX: 200, clientY: 150 });
    fireEvent.pointerMove(window, { clientX: 250, clientY: 180 });
    fireEvent.pointerUp(window);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBe(150);  // 100 + (250 - 200)
    expect(pos.y).toBe(130);  // 100 + (180 - 150)
  });

  it('drag clamps position to keep overlay inside the viewport', () => {
    useStore.setState({ chatVisible: true, chatPosition: { x: 100, y: 100 } });
    render(<ChatOverlay />);
    const header = screen.getByTestId('chat-header');
    fireEvent.pointerDown(header, { clientX: 200, clientY: 150 });
    fireEvent.pointerMove(window, { clientX: 999_999, clientY: 999_999 });
    fireEvent.pointerUp(window);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBeLessThanOrEqual(1200 - 320 - 16);
    expect(pos.y).toBeLessThanOrEqual(800 - 260 - 16);
  });

  it('resize from corner handle updates chatSize and clamps to range', () => {
    useStore.setState({ chatVisible: true, chatSize: { w: 320, h: 260 } });
    render(<ChatOverlay />);
    const handle = screen.getByTestId('chat-resize-handle');
    fireEvent.pointerDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 100, clientY: 50 });
    fireEvent.pointerUp(window);
    const size = useStore.getState().chatSize;
    expect(size.w).toBe(420);  // 320 + 100
    expect(size.h).toBe(310);  // 260 + 50
  });

  it('resize clamps below minimum', () => {
    useStore.setState({ chatVisible: true, chatSize: { w: 320, h: 260 } });
    render(<ChatOverlay />);
    const handle = screen.getByTestId('chat-resize-handle');
    fireEvent.pointerDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: -10000, clientY: -10000 });
    fireEvent.pointerUp(window);
    const size = useStore.getState().chatSize;
    expect(size.w).toBe(240);   // min
    expect(size.h).toBe(180);   // min
  });
});
