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
