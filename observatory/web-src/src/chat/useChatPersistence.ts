/**
 * localStorage persistence for the chat overlay's position + size.
 * Mirrors useDockPersistence: hydrate from localStorage on mount,
 * debounce 200ms on store changes back to localStorage. On hydrate,
 * clamp position so the overlay can't open off-screen if the viewport
 * shrunk between sessions. Spec §6.2.
 */
import { useEffect, useRef } from 'react';
import type { StoreApi } from 'zustand';

import type { State } from '../store';

const POSITION_KEY = 'observatory.chat.position';
const SIZE_KEY = 'observatory.chat.size';
const DEBOUNCE_MS = 200;
const VIEWPORT_MARGIN = 16;

function clampPosition(
  pos: { x: number; y: number },
  size: { w: number; h: number },
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w - VIEWPORT_MARGIN);
  const maxY = Math.max(0, window.innerHeight - size.h - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, pos.x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, pos.y), maxY),
  };
}

export function useChatPersistence(store: StoreApi<State>): void {
  const hydratedRef = useRef(false);
  const posTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate once on first mount.
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;

    const sizeRaw = localStorage.getItem(SIZE_KEY);
    let size = store.getState().chatSize;
    if (sizeRaw) {
      try {
        const parsed = JSON.parse(sizeRaw);
        if (typeof parsed?.w === 'number' && typeof parsed?.h === 'number') {
          size = { w: parsed.w, h: parsed.h };
          store.getState().setChatSize(size);
        }
      } catch { /* corrupt — ignore, keep default */ }
    }

    const posRaw = localStorage.getItem(POSITION_KEY);
    if (posRaw) {
      try {
        const parsed = JSON.parse(posRaw);
        if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
          const clamped = clampPosition({ x: parsed.x, y: parsed.y }, size);
          store.getState().setChatPosition(clamped);
        }
      } catch { /* ignore */ }
    }
  }, [store]);

  // Debounced writes for position.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatPosition === prev.chatPosition) return;
      if (posTimer.current) clearTimeout(posTimer.current);
      posTimer.current = setTimeout(() => {
        localStorage.setItem(POSITION_KEY, JSON.stringify(s.chatPosition));
      }, DEBOUNCE_MS);
    });
  }, [store]);

  // Debounced writes for size.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatSize === prev.chatSize) return;
      if (sizeTimer.current) clearTimeout(sizeTimer.current);
      sizeTimer.current = setTimeout(() => {
        localStorage.setItem(SIZE_KEY, JSON.stringify(s.chatSize));
      }, DEBOUNCE_MS);
    });
  }, [store]);
}
