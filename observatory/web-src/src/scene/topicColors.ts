import { Color } from 'three';

const PREFIXES: Array<[string, string]> = [
  ['hive/cognitive/',     '#e8e8e8'],
  ['hive/sensory/',       '#99ee66'],
  ['hive/motor/',         '#ee9966'],
  ['hive/metacognition/', '#bb66ff'],
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

export function topicColorObject(topic: string): Color {
  return COLOR_CACHE[topicColor(topic)];
}
