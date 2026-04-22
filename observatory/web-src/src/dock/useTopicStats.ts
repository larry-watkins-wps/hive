import { useEffect, useRef, useState } from 'react';
import { useStore, type Envelope } from '../store';

/**
 * Spec §6.2 `TopicStat`. Extended over the spec's literal pseudo-type in
 * two places:
 *
 * - `publisherLastSeen` (per-publisher wallclock) — required so the 1 Hz
 *   decay sweep can evict publishers whose last envelope was > 60 s ago.
 *   The spec's `publishers: Set<string>` alone can't answer "when did
 *   each one last publish?".
 *
 * - `recent5` — last 5 envelopes on this topic, newest-first. Spec §6.1
 *   row-expand shows this list; computing it reactively inside `Row`
 *   would require a reactive `useStore((s) => s.envelopes)` subscription
 *   and re-filter on every envelope push (O(N_rows * ring_size) per
 *   push). Baking it into the 1 Hz tick keeps `Row` non-reactive —
 *   decisions log entry (v3 Task 6 Drift B).
 */
export type TopicStat = {
  topic: string;
  ewmaRate: number;
  sparkBuckets: number[];
  publishers: Set<string>;
  publisherLastSeen: Map<string, number>;
  lastSeenMs: number;
  recent5: Envelope[];
};

const ALPHA = 0.1;
const BUCKETS = 6;
const PUBLISHER_DECAY_MS = 60_000;
const RECENT_N = 5;

/**
 * Spec §6.2 / §15 — 1 Hz selector producing `Map<topic, TopicStat>`.
 *
 * Runs once per second on a setInterval (NOT reactively per envelope):
 *   1. Rolls each topic's 6-bucket spark window forward by one slot.
 *   2. Decays any publisher whose `publisherLastSeen` > 60 s old.
 *   3. Reads the new envelopes since last tick (monotonic
 *      `envelopesReceivedTotal` delta — decisions entry 82 pattern —
 *      so the scan still works after the ring caps at 5000).
 *   4. Absorbs them into per-topic state (new-topic bootstrap, bucket
 *      accumulate, publisher re-ping).
 *   5. Updates EWMA rates (α=0.1) on every known topic, not just those
 *      with fresh envelopes — so a topic that went silent this tick
 *      still decays toward zero.
 *   6. Rebuilds per-topic `recent5` by a single reverse walk of the
 *      envelope ring (Drift B), so each Row reads `stat.recent5`
 *      statically from the snapshot instead of re-filtering on every
 *      envelope push.
 *   7. `setSnapshot(new Map(stateRef.current))` — reference-changed
 *      clone so React subscribers re-render. The Map VALUES are still
 *      the same `TopicStat` objects (Sets + Maps inside them are
 *      shared, so consumers MUST NOT mutate).
 */
export function useTopicStats(): Map<string, TopicStat> {
  const [snapshot, setSnapshot] = useState<Map<string, TopicStat>>(new Map());
  const stateRef = useRef<Map<string, TopicStat>>(new Map());
  const lastIndexRef = useRef<number>(0);

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const envs = useStore.getState().envelopes;
      const total = useStore.getState().envelopesReceivedTotal;

      // Monotonic-delta pattern (decisions entry 82): using
      // `envelopes.length` breaks once the ring caps at 5000. The
      // monotonic counter `envelopesReceivedTotal` still advances past
      // the cap, so we can compute how many envelopes arrived since
      // last tick and slice that many from the end of the ring.
      const delta = Math.max(0, total - lastIndexRef.current);
      const take = Math.min(delta, envs.length);
      const fresh = envs.slice(envs.length - take);
      lastIndexRef.current = total;

      // Roll bucket window forward + decay old publishers. Boundary is
      // `>= PUBLISHER_DECAY_MS` so a publisher re-ping'd exactly 60 s
      // ago evicts this tick rather than sticking around for one more.
      // Matches spec §6.2 "publishers: source_region seen last 60 s".
      for (const stat of stateRef.current.values()) {
        stat.sparkBuckets.shift();
        stat.sparkBuckets.push(0);
        for (const [pub, last] of stat.publisherLastSeen) {
          if (now - last >= PUBLISHER_DECAY_MS) {
            stat.publisherLastSeen.delete(pub);
            stat.publishers.delete(pub);
          }
        }
      }

      // Absorb new envelopes.
      for (const e of fresh) {
        let s = stateRef.current.get(e.topic);
        if (!s) {
          s = {
            topic: e.topic,
            ewmaRate: 0,
            sparkBuckets: new Array(BUCKETS).fill(0),
            publishers: new Set<string>(),
            publisherLastSeen: new Map<string, number>(),
            lastSeenMs: now,
            recent5: [],
          };
          stateRef.current.set(e.topic, s);
        }
        s.sparkBuckets[BUCKETS - 1] += 1;
        s.lastSeenMs = now;
        if (e.source_region) {
          s.publishers.add(e.source_region);
          s.publisherLastSeen.set(e.source_region, now);
        }
      }

      // EWMA on per-tick count — sweeps every known topic so silent
      // topics decay toward zero, not just those with fresh envelopes.
      const perTopicCount = new Map<string, number>();
      for (const e of fresh) perTopicCount.set(e.topic, (perTopicCount.get(e.topic) ?? 0) + 1);
      for (const stat of stateRef.current.values()) {
        const n = perTopicCount.get(stat.topic) ?? 0;
        stat.ewmaRate = ALPHA * n + (1 - ALPHA) * stat.ewmaRate;
      }

      // Rebuild `recent5` per topic (Drift B). Single reverse walk of
      // the ring; each stat's list caps at 5 newest-first. O(ring_size)
      // per tick regardless of topic count — cheaper than N reactive
      // filter-slice ops on every envelope push.
      for (const stat of stateRef.current.values()) stat.recent5 = [];
      for (let i = envs.length - 1; i >= 0; i--) {
        const e = envs[i];
        const s = stateRef.current.get(e.topic);
        if (s && s.recent5.length < RECENT_N) s.recent5.push(e);
      }

      setSnapshot(new Map(stateRef.current));
    };
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return snapshot;
}
