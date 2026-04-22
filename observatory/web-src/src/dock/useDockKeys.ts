import { useEffect } from 'react';
import { useStore } from '../store';

/**
 * Window-level keydown handler for dock-specific bindings (spec §4.1).
 *
 * Bindings:
 * - `` ` `` (backtick) — anywhere (no modifiers) — toggles `dockCollapsed`.
 * - `Space` — only when target is inside `#dock-root` — toggles `dockPaused`.
 *
 * Input-focus guard: early return when the event target is an `<input>`,
 * `<textarea>`, or contenteditable element, so typing inside e.g. the
 * Firehose filter never triggers a dock toggle.
 *
 * Guard is inline (duplicated from `useInspectorKeys.ts`) rather than
 * extracted — see `observatory/memory/decisions.md` for the judgment call.
 */
function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t instanceof HTMLInputElement) return true;
  if (t instanceof HTMLTextAreaElement) return true;
  return t.isContentEditable;
}

function inDock(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.closest('#dock-root') != null;
}

export function useDockKeys(): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;
      if (e.key === '`' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        const { dockCollapsed, setDockCollapsed } = useStore.getState();
        setDockCollapsed(!dockCollapsed);
        return;
      }
      if (e.key === ' ' && inDock(e.target)) {
        e.preventDefault();
        const { dockPaused, setDockPaused } = useStore.getState();
        setDockPaused(!dockPaused);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
}
