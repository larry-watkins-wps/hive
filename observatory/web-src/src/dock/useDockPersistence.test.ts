import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useDockPersistence } from './useDockPersistence';
import { createStore } from '../store';

describe('useDockPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
  });

  it('hydrates from localStorage on mount', () => {
    localStorage.setItem('observatory.dock.height', '300');
    localStorage.setItem('observatory.dock.collapsed', 'true');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(300);
    expect(store.getState().dockCollapsed).toBe(true);
  });

  it('clamps out-of-range height on hydrate', () => {
    localStorage.setItem('observatory.dock.height', '60');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(120);
  });

  it('writes to localStorage on state change (debounced)', async () => {
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    act(() => {
      store.getState().setDockHeight(350);
    });
    await new Promise((r) => setTimeout(r, 260));
    expect(localStorage.getItem('observatory.dock.height')).toBe('350');
  });

  it('ignores malformed stored values', () => {
    localStorage.setItem('observatory.dock.height', 'abc');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(220);
  });
});
