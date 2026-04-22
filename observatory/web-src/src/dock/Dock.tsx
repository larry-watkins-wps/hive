import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { DockTabStrip } from './DockTabStrip';
import { useDockPersistence } from './useDockPersistence';
import { Firehose } from './Firehose';
import { Topics } from './Topics';
import { useTopicStats } from './useTopicStats';
import { Metacog } from './Metacog';

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
 * Metacognition dock-tab badge (spec §4.2 line 86). Count = metacog
 * envelopes in the last 60 s. Severity: `error` if any `/error/` topic
 * in that window, else `conflict` if any `/conflict/`, else `quiet`.
 *
 * Drift A (v3 Task 7): computed at 1 Hz via `setInterval` reading
 * `useStore.getState()` imperatively — NOT via `useStore((s) => s.envelopes)`
 * reactively. A reactive subscription would re-scan the ring (O(ring))
 * and re-render the dock on every envelope push; at firehose rates that
 * thrashes the dock-tab-strip for no visual benefit (the badge only
 * ticks visibly at 1 Hz anyway). Same pattern as `useFirehoseRate` here
 * and `useTopicStats` — decisions entry 82.
 *
 * Initial `compute()` runs inline so the first render doesn't display a
 * 1 s zero-count; React strict-mode's double-mount is handled by the
 * `return () => clearInterval(id)` cleanup — no leak.
 */
function useMetacogBadge(): { count: number; severity: 'error' | 'conflict' | 'quiet' } {
  const [badge, setBadge] = useState<{ count: number; severity: 'error' | 'conflict' | 'quiet' }>({
    count: 0,
    severity: 'quiet',
  });
  useEffect(() => {
    const compute = () => {
      const envs = useStore.getState().envelopes;
      const now = Date.now();
      const recent = envs.filter(
        (e) => e.topic.startsWith('hive/metacognition/') && now - e.observed_at < 60_000,
      );
      const errors = recent.filter((e) => e.topic.includes('/error/')).length;
      const conflicts = recent.filter((e) => e.topic.includes('/conflict/')).length;
      setBadge({
        count: recent.length,
        severity: errors > 0 ? 'error' : conflicts > 0 ? 'conflict' : 'quiet',
      });
    };
    compute();
    const id = setInterval(compute, 1000);
    return () => clearInterval(id);
  }, []);
  return badge;
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
 * Tab content: Task 5 wires the real `<Firehose />`, Task 6 wires the
 * real `<Topics />`, Task 7 wires the real `<Metacog />` + badge.
 */
export function Dock() {
  useDockPersistence(useStore);
  const tab = useStore((s) => s.dockTab);
  const collapsed = useStore((s) => s.dockCollapsed);
  const height = useStore((s) => s.dockHeight);
  const setDockHeight = useStore((s) => s.setDockHeight);
  const firehoseRate = useFirehoseRate();
  // Drift A (v3 Task 6): call `useTopicStats()` once at the dock level
  // and thread the map down — both the tab-strip badge (`topicStats.size`)
  // and the `<Topics>` body share one selector, one setInterval, one
  // state slice. Calling the hook in both components would spin up two
  // independent 1 Hz intervals with divergent state.
  const topicStats = useTopicStats();
  const metacogBadge = useMetacogBadge();

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
        topicCount={topicStats.size}
        metacogBadge={metacogBadge}
      />
      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {tab === 'firehose' && <Firehose />}
          {tab === 'topics' && <Topics stats={topicStats} />}
          {tab === 'metacog' && <Metacog />}
        </div>
      )}
    </div>
  );
}
