import { useEffect, useRef } from 'react';
import type { StoreApi, UseBoundStore } from 'zustand';

const KEY_HEIGHT = 'observatory.dock.height';
const KEY_COLLAPSED = 'observatory.dock.collapsed';
const DEBOUNCE_MS = 200;
const MIN = 120;
const MAX = 520;

type AnyStore = UseBoundStore<StoreApi<{
  dockHeight: number;
  dockCollapsed: boolean;
  setDockHeight: (n: number) => void;
  setDockCollapsed: (b: boolean) => void;
}>>;

/**
 * Hydrates the dock's height + collapsed state from localStorage on first mount
 * and debounces subsequent state changes back to localStorage (200 ms window).
 *
 * Spec §4.1 — bottom dock default 220 px, resize clamped to [120, 520]. The
 * persistence keys (`observatory.dock.height`, `observatory.dock.collapsed`)
 * are observatory-scoped so we never collide with other apps on the same origin.
 *
 * Hydration is strict-mode safe via a `hydrated` ref: under React 18 strict
 * mode, effects fire twice on dev mount; the ref guard prevents a second
 * `setDockHeight` from stomping a value the user may have changed between
 * the double-invoke.
 *
 * Malformed or out-of-range values are ignored on hydrate — `Number()` yields
 * `NaN` for junk (which `Number.isFinite` rejects), and an in-range value is
 * clamped to `[MIN, MAX]` before commit. `collapsed` accepts only the two
 * string literals `'true'` / `'false'`.
 */
export function useDockPersistence(store: AnyStore): void {
  const hydrated = useRef(false);

  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    const raw = localStorage.getItem(KEY_HEIGHT);
    if (raw !== null) {
      const h = Number(raw);
      if (Number.isFinite(h) && h > 0) {
        store.getState().setDockHeight(Math.max(MIN, Math.min(MAX, h)));
      }
    }
    const c = localStorage.getItem(KEY_COLLAPSED);
    if (c === 'true' || c === 'false') {
      store.getState().setDockCollapsed(c === 'true');
    }
  }, [store]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = (fn: () => void) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(fn, DEBOUNCE_MS);
    };
    const unsub = store.subscribe((s, prev) => {
      if (s.dockHeight !== prev.dockHeight) {
        schedule(() => localStorage.setItem(KEY_HEIGHT, String(s.dockHeight)));
      }
      if (s.dockCollapsed !== prev.dockCollapsed) {
        schedule(() => localStorage.setItem(KEY_COLLAPSED, String(s.dockCollapsed)));
      }
    });
    return () => {
      unsub();
      if (timer) clearTimeout(timer);
    };
  }, [store]);
}
