import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { DockTabStrip } from './DockTabStrip';
import { useDockPersistence } from './useDockPersistence';

function FirehosePlaceholder() {
  return <div className="p-3 text-xs opacity-60">Firehose — implemented in v3 Task 5</div>;
}
function TopicsPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Topics — implemented in v3 Task 6</div>;
}
function MetacogPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Metacog — implemented in v3 Task 7</div>;
}

/**
 * Spec §4 — bottom dock. Fixed-position frame at the bottom of the viewport.
 *
 * Height:
 * - Default 220 px (from `store.dockHeight`).
 * - Collapsed → 28 px (just the tab strip).
 * - Resizable by dragging the top 4 px edge; drag deltas are clamped
 *   [120, 520] via `setDockHeight` in the store.
 *
 * Drag implementation: pointerdown captures `startY` + `startH` into refs
 * (so the move handler doesn't re-subscribe to store state and re-render);
 * pointermove computes `startH + (startY - clientY)` and pushes through
 * `setDockHeight` (which clamps); pointerup releases.
 *
 * Persistence is handled by `useDockPersistence`: it hydrates the store
 * from localStorage on first mount and debounces subsequent changes back.
 *
 * Real tab content lands in Tasks 5 (Firehose), 6 (Topics), 7 (Metacog).
 * For now, each tab renders a one-line placeholder.
 */
export function Dock() {
  useDockPersistence(useStore);
  const tab = useStore((s) => s.dockTab);
  const collapsed = useStore((s) => s.dockCollapsed);
  const height = useStore((s) => s.dockHeight);
  const setDockHeight = useStore((s) => s.setDockHeight);

  const [dragging, setDragging] = useState(false);
  const startY = useRef(0);
  const startH = useRef(220);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const delta = startY.current - e.clientY;
      setDockHeight(startH.current + delta);
    };
    const onUp = () => setDragging(false);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragging, setDockHeight]);

  const activeHeight = collapsed ? 28 : height;

  return (
    <div
      id="dock-root"
      tabIndex={0}
      className="fixed bottom-0 left-0 right-0 bg-[rgba(14,15,19,.86)] border-t border-[rgba(80,84,96,.55)] text-[rgba(230,232,238,.85)] z-30 flex flex-col"
      style={{ height: activeHeight }}
    >
      <div
        className="absolute -top-1 left-0 right-0 h-1 cursor-ns-resize"
        onPointerDown={(e) => {
          startY.current = e.clientY;
          startH.current = height;
          setDragging(true);
        }}
      />
      <DockTabStrip
        firehoseRate={0}
        topicCount={0}
        metacogBadge={{ count: 0, severity: 'quiet' }}
      />
      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {tab === 'firehose' && <FirehosePlaceholder />}
          {tab === 'topics' && <TopicsPlaceholder />}
          {tab === 'metacog' && <MetacogPlaceholder />}
        </div>
      )}
    </div>
  );
}
