import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { useChatPersistence } from './useChatPersistence';

describe('useChatPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    // Unmount any hooks rendered during the test so their subscribe
    // cleanup runs and pending debounce timers are cleared. Without
    // this, leaked subscriptions from earlier tests fire on later
    // setChatPosition / setChatSize calls (the singleton `useStore`
    // is shared across tests).
    cleanup();
    vi.useRealTimers();
  });

  it('hydrates chatPosition + chatSize from localStorage on first mount', () => {
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 50, y: 80 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 400, h: 300 }));

    renderHook(() => useChatPersistence(useStore));

    expect(useStore.getState().chatPosition).toEqual({ x: 50, y: 80 });
    expect(useStore.getState().chatSize).toEqual({ w: 400, h: 300 });
  });

  it('clamps hydrated position back inside the viewport', () => {
    Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true });
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 5000, y: 5000 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 320, h: 260 }));

    renderHook(() => useChatPersistence(useStore));

    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBeLessThanOrEqual(800 - 320 - 16);
    expect(pos.y).toBeLessThanOrEqual(600 - 260 - 16);
  });

  it('debounces writes (200ms) on chatPosition changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatPosition({ x: 100, y: 200 });
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(199);
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(2);
    expect(JSON.parse(localStorage.getItem('observatory.chat.position')!))
      .toEqual({ x: 100, y: 200 });
  });

  it('debounces writes on chatSize changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatSize({ w: 500, h: 350 });
    vi.advanceTimersByTime(201);
    expect(JSON.parse(localStorage.getItem('observatory.chat.size')!))
      .toEqual({ w: 500, h: 350 });
  });

  it('does not write if unmounted before the debounce fires', () => {
    const { unmount } = renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatPosition({ x: 123, y: 234 });
    // Mid-debounce: timer scheduled but not yet fired.
    vi.advanceTimersByTime(50);
    unmount();
    // Push past the debounce window — cleanup must have cleared the timer.
    vi.advanceTimersByTime(500);
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
  });

  it('coalesces rapid position changes within the debounce window', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatPosition({ x: 10, y: 10 });
    vi.advanceTimersByTime(100);
    useStore.getState().setChatPosition({ x: 50, y: 60 });
    // Still within the window after the second set; no write yet.
    vi.advanceTimersByTime(100);
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    // Past the second set's window: exactly one write with the latest value.
    vi.advanceTimersByTime(150);
    expect(JSON.parse(localStorage.getItem('observatory.chat.position')!))
      .toEqual({ x: 50, y: 60 });
  });

  it('falls back to defaults silently when localStorage JSON is malformed', () => {
    // Reset to the store's initial default so we can assert no hydration occurred.
    useStore.getState().setChatPosition({ x: 0, y: 16 });
    localStorage.setItem('observatory.chat.position', 'not-json{');
    expect(() => renderHook(() => useChatPersistence(useStore))).not.toThrow();
    expect(useStore.getState().chatPosition).toEqual({ x: 0, y: 16 });
  });
});
