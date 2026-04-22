import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { DockTabStrip } from './DockTabStrip';
import { useDockPersistence } from './useDockPersistence';
import { Firehose } from './Firehose';

function TopicsPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Topics — implemented in v3 Task 6</div>;
}
function MetacogPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Metacog — implemented in v3 Task 7</div>;
}

/**
 * Live messages-per-second indicator for the Firehose tab badge. Samples
 * the monotonic `envelopesReceivedTotal` counter on a 1 Hz interval and
 * reports the per-second delta.
 *
 * Per decisions entry 82: read the counter via `useStore.getState()`
 * inside the interval rather than subscribing via `useStore((s) => s...)`
 * in the hook body. A subscribing read would re-run the hook on every
 * envelope, tearing down and recreating the interval constantly; the
 * imperative read inside setInterval keeps the 1 Hz cadence stable.
 */
function useFirehoseRate(): number {
  const [rate, setRate] = useState(0);
  const lastTotal = useRef(0);
  useEffect(() => {
    const id = setInterval(() => {
      const cur = useStore.getState().envelopesReceivedTotal;
      setRate(cur - lastTotal.current);
      lastTotal.current = cur;
    }, 1000);
    return () => clearInterval(id);
  }, []);
  return rate;
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
 * Tab content: Task 5 wires the real `<Firehose />`; Topics + Metacog
 * remain placeholders until Tasks 6 + 7.
 */
export function Dock() {
  useDockPersistence(useStore);
  const tab = useStore((s) => s.dockTab);
  const collapsed = useStore((s) => s.dockCollapsed);
  const height = useStore((s) => s.dockHeight);
  const setDockHeight = useStore((s) => s.setDockHeight);
  const firehoseRate = useFirehoseRate();

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
        firehoseRate={firehoseRate}
        topicCount={0}
        metacogBadge={{ count: 0, severity: 'quiet' }}
      />
      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {tab === 'firehose' && <Firehose />}
          {tab === 'topics' && <TopicsPlaceholder />}
          {tab === 'metacog' && <MetacogPlaceholder />}
        </div>
      )}
    </div>
  );
}
