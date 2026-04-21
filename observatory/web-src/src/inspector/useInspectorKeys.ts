import { useEffect } from 'react';
import { useStore } from '../store';

/**
 * Window-level keydown handler for the inspector panel.
 *
 * Bindings (spec §3.1 / §4):
 * - `Escape`  — if a region is selected, clear selection (closes panel).
 * - `[`       — if selected, cycle to previous region alphabetically.
 * - `]`       — if selected, cycle to next region alphabetically.
 * - `R` / `r` — always dispatch `observatory:camera-reset` CustomEvent;
 *               Scene.tsx listens and calls CameraControls.reset(true).
 *               The panel stays open on reset — only the camera recentres.
 *
 * Input-focus guard: early return when the event target is an `<input>`,
 * `<textarea>`, or contenteditable element, so typing inside a future
 * search box or similar does not fire these bindings.
 *
 * The bracket / Escape branches call `preventDefault()` so browser-level
 * shortcuts (e.g. `Esc` closing fullscreen) do not also fire. `R` does
 * not call `preventDefault` — we don't want to block e.g. Ctrl-R reload;
 * when `R` arrives with modifiers we read it as the reset binding here
 * but the browser still gets its normal reload path because we never
 * inspected modifier state.  Review-note: bracket keys are rarely bound
 * by browsers so preventDefault is defensive but harmless there.
 *
 * The listener reads store state via `useStore.getState()` inside the
 * handler (not via `useStore(selector)` at hook-mount time), so it sees
 * the latest `selectedRegion` on every keydown without re-subscribing.
 */
export function useInspectorKeys(): void {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === 'INPUT' ||
          t.tagName === 'TEXTAREA' ||
          t.isContentEditable)
      ) {
        return;
      }

      const { selectedRegion, select, cycle } = useStore.getState();
      if (ev.key === 'Escape' && selectedRegion) {
        ev.preventDefault();
        select(null);
      } else if (ev.key === '[' && selectedRegion) {
        ev.preventDefault();
        cycle(-1);
      } else if (ev.key === ']' && selectedRegion) {
        ev.preventDefault();
        cycle(1);
      } else if (ev.key === 'r' || ev.key === 'R') {
        // Dispatched as a CustomEvent so the hook stays decoupled from the
        // Scene's CameraControls ref. Scene.tsx registers the listener.
        window.dispatchEvent(new CustomEvent('observatory:camera-reset'));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
