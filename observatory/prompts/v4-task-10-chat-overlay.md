# Task 10 — ChatOverlay (frame + drag + resize)

You are an implementer subagent. Implement the v4 ChatOverlay floating frame for the observatory chat surface, with drag + resize, per the verbatim plan + spec excerpts below.

## Scope

**Create exactly two files:**

1. `observatory/web-src/src/chat/ChatOverlay.tsx`
2. `observatory/web-src/src/chat/ChatOverlay.test.tsx`

Do not modify anything else. Do not edit `App.tsx` (Task 12). Do not create `useChatKeys` (Task 11). Do not edit anything under `regions/`.

## Repo facts you must know

- Working directory: `C:\repos\hive` (Windows + bash). Vitest runs from `observatory/web-src/`.
- `observatory/web-src/src/store.ts` already exposes the chat slice (`chatVisible`, `chatPosition`, `chatSize`, `pendingChatTurns` plus 7 setters). `setChatPosition` and `setChatSize` are plain setters — no clamping inside the store; the component is responsible for clamp.
- `Transcript` and `ChatInput` already exist at `observatory/web-src/src/chat/Transcript.tsx` and `observatory/web-src/src/chat/ChatInput.tsx`. Mount them as-is.
- `useChatPersistence` already exists; mounted in App.tsx in Task 12 (not your concern).
- Tests use jsdom; `vitest.config.ts` has `globals: false` (always import `describe`/`it`/`expect`/`beforeEach`/`afterEach`/`cleanup` explicitly) and **no auto-cleanup between tests** (existing tests in this codebase add `afterEach(() => cleanup())` when needed; see `inspector/Stm.test.tsx` for the pattern).
- Strict-mode safe: keep the lazy default-position effect idempotent.

## Spec excerpt — §6.3 (authoritative)

> Translucent floating frame, rendered at `position: fixed` driven by `chatPosition`/`chatSize`. Hidden when `chatVisible === false` (component returns null — no DOM node when closed).
>
> Visual style:
> - Background `rgba(14,15,19,.72)` with `backdrop-filter: blur(14px)`.
> - Border `1px solid rgba(80,84,96,.45)`, `border-radius: 4px`.
> - No shadow, no gradient.
> - Header strip: 9 px Inter, `letter-spacing: .5px`, uppercase, `rgba(180,184,192,.6)`. Text "chat with hive" left, drag handle implicit (header is the drag region).
> - Body: transcript scrollable, auto-scroll-to-bottom when user is within 40 px of the end (same rule as Firehose / Messages).
> - Input region: 1 px top border `rgba(80,84,96,.25)`; padding `10px 14px`; textarea is borderless, transparent, Inter 200 11 px, placeholder `rgba(120,124,135,.55)` italic.
>
> Drag: `pointerdown` on header captures `(startX, startY, startPosX, startPosY)` in refs; `pointermove` updates `chatPosition` directly through the store setter (debounced persistence). Clamp to viewport with a 16 px margin so the overlay can't be dragged fully off-screen.
>
> Resize: bottom-right 12×12 px corner handle. Same drag pattern. Clamp `w ∈ [240, 720]`, `h ∈ [180, 720]`.

## Plan code (verbatim — implement this; preserve every line / comment)

### Test file: `observatory/web-src/src/chat/ChatOverlay.test.tsx`

```tsx
// observatory/web-src/src/chat/ChatOverlay.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
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
    useStore.setState({ chatVisible: false });
  });

  it('renders nothing when chatVisible is false', () => {
    render(<ChatOverlay />);
    expect(screen.queryByTestId('chat-overlay')).toBeNull();
  });

  it('renders the overlay when chatVisible is true', () => {
    useStore.setState({ chatVisible: true });
    render(<ChatOverlay />);
    expect(screen.getByTestId('chat-overlay')).toBeInTheDocument();
    expect(screen.getByText('chat with hive')).toBeInTheDocument();
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
```

### Implementation file: `observatory/web-src/src/chat/ChatOverlay.tsx`

```tsx
// observatory/web-src/src/chat/ChatOverlay.tsx
/**
 * Floating chat overlay. Spec §6.3.
 *
 * On first open with default chatPosition (x === 0), snap to top-right
 * (viewport.w - size.w - 16, 16). Subsequent opens preserve whatever
 * position the user dragged it to (also persisted via useChatPersistence).
 *
 * Drag: pointerdown on the header captures (startClientX/Y, startPosX/Y)
 * in refs; pointermove on window updates chatPosition with the delta,
 * clamped to viewport. pointerup releases.
 *
 * Resize: same pattern from the bottom-right corner handle. Width clamped
 * [240, 720]; height clamped [180, 720].
 */
import { useEffect, useRef, type CSSProperties, type PointerEvent as RPE } from 'react';

import { useStore } from '../store';
import { Transcript } from './Transcript';
import { ChatInput } from './ChatInput';

const VIEWPORT_MARGIN = 16;
const W_MIN = 240, W_MAX = 720;
const H_MIN = 180, H_MAX = 720;

const frameStyle: CSSProperties = {
  position: 'fixed',
  background: 'rgba(14,15,19,.72)',
  backdropFilter: 'blur(14px)',
  border: '1px solid rgba(80,84,96,.45)',
  borderRadius: 4,
  display: 'flex', flexDirection: 'column',
  fontFamily: 'Inter, ui-sans-serif, sans-serif',
  zIndex: 50,
  transition: 'opacity .18s ease',
};
const headerStyle: CSSProperties = {
  fontSize: 9, letterSpacing: '.5px', textTransform: 'uppercase',
  color: 'rgba(180,184,192,.6)',
  padding: '10px 14px',
  borderBottom: '1px solid rgba(80,84,96,.25)',
  cursor: 'grab', userSelect: 'none',
};
const resizeHandleStyle: CSSProperties = {
  position: 'absolute', bottom: 0, right: 0,
  width: 12, height: 12, cursor: 'nwse-resize',
};

function clampPos(
  pos: { x: number; y: number }, size: { w: number; h: number },
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w - VIEWPORT_MARGIN);
  const maxY = Math.max(0, window.innerHeight - size.h - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, pos.x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, pos.y), maxY),
  };
}
function clampSize(s: { w: number; h: number }): { w: number; h: number } {
  return {
    w: Math.min(Math.max(W_MIN, s.w), W_MAX),
    h: Math.min(Math.max(H_MIN, s.h), H_MAX),
  };
}

export function ChatOverlay() {
  const visible = useStore((s) => s.chatVisible);
  const pos = useStore((s) => s.chatPosition);
  const size = useStore((s) => s.chatSize);
  const setPos = useStore((s) => s.setChatPosition);
  const setSize = useStore((s) => s.setChatSize);

  // Lazy default-position computation on first open.
  // chatPosition.x starts at 0 (placeholder); we snap to top-right when
  // the user opens the overlay and the position hasn't been set.
  useEffect(() => {
    if (!visible) return;
    if (pos.x === 0 && pos.y === 16) {
      setPos({
        x: window.innerWidth - size.w - VIEWPORT_MARGIN,
        y: VIEWPORT_MARGIN,
      });
    }
  }, [visible, pos.x, pos.y, size.w, setPos]);

  // Drag refs
  const dragStart = useRef<{ cx: number; cy: number; px: number; py: number } | null>(null);
  const resizeStart = useRef<{ cx: number; cy: number; w: number; h: number } | null>(null);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (dragStart.current) {
        const { cx, cy, px, py } = dragStart.current;
        setPos(clampPos({ x: px + (e.clientX - cx), y: py + (e.clientY - cy) }, size));
      } else if (resizeStart.current) {
        const { cx, cy, w, h } = resizeStart.current;
        setSize(clampSize({ w: w + (e.clientX - cx), h: h + (e.clientY - cy) }));
      }
    }
    function onUp() {
      dragStart.current = null;
      resizeStart.current = null;
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [setPos, setSize, size.w, size.h]);

  if (!visible) return null;

  function onHeaderDown(e: RPE) {
    dragStart.current = { cx: e.clientX, cy: e.clientY, px: pos.x, py: pos.y };
  }
  function onResizeDown(e: RPE) {
    e.stopPropagation();
    resizeStart.current = { cx: e.clientX, cy: e.clientY, w: size.w, h: size.h };
  }

  return (
    <div
      data-testid="chat-overlay"
      style={{ ...frameStyle, left: pos.x, top: pos.y, width: size.w, height: size.h }}
    >
      <div data-testid="chat-header" style={headerStyle} onPointerDown={onHeaderDown}>
        chat with hive
      </div>
      <Transcript />
      <ChatInput />
      <div data-testid="chat-resize-handle" style={resizeHandleStyle} onPointerDown={onResizeDown} />
    </div>
  );
}
```

## Procedure (TDD — red then green)

1. **Write the test file FIRST.** `cd observatory/web-src && npx vitest run src/chat/ChatOverlay.test.tsx` — expect failure (no `./ChatOverlay` module). Capture the red.
2. **Write the implementation file.**
3. **Run the focused vitest:** `npx vitest run src/chat/ChatOverlay.test.tsx` — expect 8 passed.
4. **Run typecheck:** `npx tsc -b` — expect clean (no emitted errors).
5. **Run the FULL vitest suite:** `npx vitest run` — should be **201 passed** (was 193 + 8 new).
6. **Self-review:** re-read your two files. Did you preserve every line of the plan code? Did the comments survive? Are the styles byte-equivalent to the spec? Are clamp boundaries `[240, 720]` × `[180, 720]`? Is the lazy-default trigger condition `pos.x === 0 && pos.y === 16` (matching the store's initial `chatPosition`)? Is `chat-resize-handle`'s pointer event `stopPropagation`'d so it doesn't double-fire as drag? Anything sloppy → fix before commit.
7. **Commit** (HEREDOC, exact message from plan):

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/ChatOverlay.tsx observatory/web-src/src/chat/ChatOverlay.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): ChatOverlay — floating frame with drag + resize

Translucent draggable HUD panel. Mounts Transcript + ChatInput. Header
is the drag region; bottom-right corner is the resize handle. Position
clamps inside viewport with 16px margin; size clamps to [240,720] x
[180,720]. On first open with default position the overlay snaps to
top-right; subsequent opens preserve user-set position.

Visual style matches the spec §6.3 / Larry's thin/soft/hover-reveal
aesthetic: rgba(14,15,19,.72) bg with backdrop-blur(14px), 1px soft
border, 4px radius, no shadow, .18s opacity fade, Inter 200 throughout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Reporting protocol

Reply to the controller with one of:
- `DONE` + the commit SHA + numeric vitest count + tsc status. Include any non-obvious decisions you made (e.g. "kept comments verbatim from plan; styles match exactly").
- `DONE_WITH_CONCERNS` + the same + a short list of doubts.
- `NEEDS_CONTEXT` — what info you need.
- `BLOCKED` — what's stopping you.

Never amend; never push; never edit other files; never modify the commit message footer.
