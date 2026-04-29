import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { useChatPersistence } from './useChatPersistence';

describe('useChatPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
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
});
