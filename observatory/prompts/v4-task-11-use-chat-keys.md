# Task 11 — useChatKeys hotkey

You are an implementer subagent. Implement the chat overlay's window-level keydown listener (`c` toggle / `Esc` dismiss) per the spec + plan code below.

## Scope

**Create exactly two files:**
1. `observatory/web-src/src/chat/useChatKeys.ts`
2. `observatory/web-src/src/chat/useChatKeys.test.tsx`

Do NOT modify `App.tsx` (Task 12), `ChatOverlay.tsx`, or anything outside those two files. Do NOT edit anything under `regions/`.

## Repo facts

- Working directory: `C:\repos\hive` (Windows + bash). Vitest from `observatory/web-src/`.
- Store has `chatVisible` + `setChatVisible` already. `useStore.getState()` reads inside the handler so the listener sees the latest store state without re-subscribing (canonical pattern in `dock/useDockKeys.ts` and `inspector/useInspectorKeys.ts`).
- Vitest config: `globals: false`, no auto-cleanup. Existing `dock/useDockKeys` has no test file; `useChatKeys` adds one. Use `afterEach(() => cleanup())` if jsdom DOM remnants leak between tests (rendered Harness components).
- Spec §6.6: `c` (no modifiers, no input/textarea/contenteditable focus) toggles `chatVisible`; `Escape` (when `chatVisible === true` and target inside the overlay) closes. Esc must not propagate to the inspector dismiss handler (which reads its own targeting check, so this is naturally satisfied — both listeners run independently, but the inspector's `Escape` branch only fires when `selectedRegion` is set; both can coexist).

## Spec excerpt — §6.6 (authoritative)

> `useChatKeys` installs a single window-level keydown listener:
>
> - `c` (no modifiers, when no input/textarea/contenteditable has focus) → toggle `chatVisible`.
> - `Esc` (when `chatVisible === true` and event target is inside the overlay) → set `chatVisible = false` and blur. Esc does not propagate to the inspector dismiss handler.
>
> When the overlay opens, focus moves to the textarea (so the user can type immediately). When the overlay closes, focus returns to the previously-focused element if it still exists, else to the body.

**Note on focus management:** the spec says focus-on-open and focus-restore-on-close should happen, but the plan's verbatim hook code does NOT implement that — neither the test nor the implementation in the plan touches focus. Treat the focus-management bullet as **out of scope for Task 11** (the textarea autofocus is more naturally handled inside `ChatInput` when `chatVisible` flips to true, which is a separate concern; defer to a follow-up if anyone notices it missing in smoke testing). Implement only what the plan code specifies.

## Plan code (verbatim — implement exactly)

### Test file

```tsx
// observatory/web-src/src/chat/useChatKeys.test.tsx
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../store';
import { useChatKeys } from './useChatKeys';

function Harness() {
  useChatKeys();
  return null;
}

describe('useChatKeys', () => {
  beforeEach(() => {
    useStore.setState({ chatVisible: false });
  });
  afterEach(() => {
    useStore.setState({ chatVisible: false });
  });

  function fireKey(key: string, target: EventTarget = document.body) {
    const e = new KeyboardEvent('keydown', { key, bubbles: true });
    target.dispatchEvent(e);
  }

  it('c toggles chatVisible', () => {
    render(<Harness />);
    expect(useStore.getState().chatVisible).toBe(false);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(true);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('c is ignored when an input has focus', () => {
    render(<Harness />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    fireKey('c', input);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(input);
  });

  it('c is ignored when a textarea has focus', () => {
    render(<Harness />);
    const ta = document.createElement('textarea');
    document.body.appendChild(ta);
    ta.focus();
    fireKey('c', ta);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(ta);
  });

  it('Esc closes the overlay when chatVisible is true and target is inside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    const overlay = document.createElement('div');
    overlay.setAttribute('data-testid', 'chat-overlay');
    document.body.appendChild(overlay);
    fireKey('Escape', overlay);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(overlay);
  });

  it('Esc is ignored when chatVisible is false', () => {
    render(<Harness />);
    fireKey('Escape');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('Esc is ignored when target is outside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    fireKey('Escape', document.body);
    expect(useStore.getState().chatVisible).toBe(true);
  });
});
```

### Implementation file

```ts
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
```

## Procedure (TDD)

1. **Write the test file FIRST.** Run `cd observatory/web-src && npx vitest run src/chat/useChatKeys.test.tsx` — expect failure (no `./useChatKeys` module).
2. **Write the implementation file.**
3. **Re-run focused vitest** — expect 6 passed.
4. **Run typecheck:** `npx tsc -b` — clean.
5. **Run full vitest:** `npx vitest run` — should be 207 passed (was 201 + 6 new).
6. **Self-review** for fidelity (comments preserved, helpers as written, listener cleanup symmetric).
7. **Commit** (verbatim HEREDOC):

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/useChatKeys.ts observatory/web-src/src/chat/useChatKeys.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): useChatKeys — c toggles overlay, Esc dismisses

Single window-level keydown listener:
  - `c` (no modifiers, no input/textarea/contenteditable focus) toggles
    chatVisible. Same input-focus guard as useDockKeys.
  - `Escape` (chatVisible true + target inside overlay) closes the
    overlay. Doesn't propagate to the inspector dismiss handler because
    the inspector listens with its own targeting check.

Spec §6.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Reporting

Reply: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED with commit SHA, focused vitest count, full vitest count, tsc status, and any non-obvious decisions.
