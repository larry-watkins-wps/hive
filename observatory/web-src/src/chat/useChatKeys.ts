// observatory/web-src/src/chat/useChatKeys.ts
/**
 * Window-level keydown for the chat overlay.
 *  - `c` (no modifiers, no input/textarea/contenteditable focus): toggle
 *    chatVisible.
 *  - `Escape` (chatVisible === true, target inside the overlay): close.
 *
 * Spec §6.6.
 */
import { useEffect } from 'react';

import { useStore } from '../store';

function targetIsTextSink(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  const tag = t.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || t.isContentEditable;
}

function targetInOverlay(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return !!t.closest('[data-testid="chat-overlay"]');
}

export function useChatKeys(): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Esc dismiss
      if (e.key === 'Escape') {
        const { chatVisible, setChatVisible } = useStore.getState();
        if (chatVisible && targetInOverlay(e.target)) {
          e.preventDefault();
          setChatVisible(false);
        }
        return;
      }
      // c toggle
      if (e.key === 'c' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (targetIsTextSink(e.target)) return;
        const { chatVisible, setChatVisible } = useStore.getState();
        e.preventDefault();
        setChatVisible(!chatVisible);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
