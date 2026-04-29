import { Color } from 'three';

// Scene palette — one color per branch for visual coherence of the
// force-directed scene. v1 entries are preserved verbatim; v3 adds three new
// prefixes (self, interoception, broadcast) per spec §5.3
// ("reuse existing v1 topicColors where overlap exists; v3 adds the missing
// prefixes"). Subdivisions of `hive/system/*` (heartbeat, region_stats,
// metrics, sleep, spawn, codechange) intentionally stay on the single
// generic `hive/system/` color here — those subdivisions only matter for
// the Firehose kind-tag badge LABEL (`kindTag` below), not the scene color.
const PREFIXES: Array<[string, string]> = [
  ['hive/cognitive/',     '#e8e8e8'],
  ['hive/sensory/',       '#99ee66'],
  ['hive/external/',      '#7be3c8'],   // v4 — chat input from outside the organism (spec §3.1, §3.2)
  ['hive/motor/',         '#ee9966'],
  ['hive/metacognition/', '#bb66ff'],
  ['hive/self/',          '#d4b3ff'],   // v3 — spec §5.3
  ['hive/interoception/', '#ffc4d8'],   // v3 — spec §5.3
  ['hive/broadcast/',     '#d0d0d0'],   // v3 — spec §5.3
  ['hive/system/',        '#888888'],
  ['hive/habit/',         '#ffcc66'],
  ['hive/attention/',     '#66ccff'],
  ['hive/modulator/',     '#ff66bb'],
  ['hive/rhythm/',        '#66cccc'],
];
const FALLBACK = '#666666';

export function topicColor(topic: string): string {
  for (const [prefix, color] of PREFIXES) {
    if (topic.startsWith(prefix)) return color;
  }
  return FALLBACK;
}

// Pre-built cache of three.js Color instances keyed by hex string.
// Mirrors the PHASE_COLOR_CACHE pattern in Regions.tsx (decisions entry 66-67):
// avoids allocating one Color per envelope destination under live traffic
// (~50-300 allocations/sec at typical rates).
const COLOR_CACHE: Record<string, Color> = Object.fromEntries(
  [...PREFIXES.map(([, hex]) => hex), FALLBACK].map((hex) => [hex, new Color(hex)]),
);

/**
 * Returns the cached three.js Color for this topic's branch.
 *
 * **DO NOT MUTATE** the returned Color — it is shared across all callers.
 * If you need to modify (e.g. `.multiplyScalar`, `.lerp`), call `.clone()`
 * first. `InstancedMesh.setColorAt` copies internally and is safe to pass
 * the cached instance directly.
 */
export function topicColorObject(topic: string): Color {
  return COLOR_CACHE[topicColor(topic)];
}

/**
 * Firehose kind-tag label (spec §5.3). Three-letter shorthand derived from
 * the topic's top two segments, used in the dock's Firehose rows. Unlike
 * `topicColor` (single color per branch for scene coherence), `kindTag`
 * subdivides `hive/system/*` so operators can eyeball whether the flood is
 * heartbeats vs metrics vs codechange without reading the full topic.
 *
 * Longest-prefix-wins by explicit ordering: `hive/system/heartbeat/` must
 * be checked BEFORE the bare `hive/system/` generic would match.
 */
export function kindTag(topic: string): string {
  if (topic.startsWith('hive/cognitive/')) return 'cog';
  if (topic.startsWith('hive/sensory/')) return 'sns';
  if (topic.startsWith('hive/external/')) return 'ext';
  if (topic.startsWith('hive/motor/')) return 'mot';
  if (topic.startsWith('hive/metacognition/')) return 'meta';
  if (topic.startsWith('hive/self/')) return 'self';
  if (topic.startsWith('hive/modulator/')) return 'mod';
  if (topic.startsWith('hive/attention/')) return 'att';
  if (topic.startsWith('hive/interoception/')) return 'intr';
  if (topic.startsWith('hive/habit/')) return 'hab';
  if (topic.startsWith('hive/rhythm/')) return 'rhy';
  if (topic.startsWith('hive/system/heartbeat/')) return 'hb';
  if (topic.startsWith('hive/system/region_stats/')) return 'rst';
  if (topic.startsWith('hive/system/metrics/')) return 'mtr';
  if (topic.startsWith('hive/system/sleep/')) return 'slp';
  if (topic.startsWith('hive/system/spawn/')) return 'spn';
  if (topic.startsWith('hive/system/codechange/')) return 'cc';
  if (topic.startsWith('hive/broadcast/')) return 'bcst';
  return '?';
}
