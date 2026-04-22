import { describe, it, expect } from 'vitest';
import { topicColor, topicColorObject, kindTag } from './topicColors';

describe('topicColor', () => {
  it.each([
    ['hive/cognitive/prefrontal/plan', '#e8e8e8'],
    ['hive/sensory/auditory/text', '#99ee66'],
    ['hive/motor/speech/intent', '#ee9966'],
    ['hive/metacognition/error/detected', '#bb66ff'],
    ['hive/system/heartbeat/thalamus', '#888888'],
    ['hive/habit/suggestion', '#ffcc66'],
    ['hive/attention/focus', '#66ccff'],
    ['hive/modulator/cortisol', '#ff66bb'],
    ['hive/rhythm/gamma', '#66cccc'],
    ['hive/self/identity', '#d4b3ff'],
    ['hive/interoception/felt_state', '#ffc4d8'],
    ['hive/broadcast/shutdown', '#d0d0d0'],
    ['hive/unknown/branch', '#666666'],
  ])('maps %s → %s', (topic, expected) => {
    expect(topicColor(topic)).toBe(expected);
  });

  it('topicColorObject returns cached Color instances', () => {
    const a = topicColorObject('hive/cognitive/a');
    const b = topicColorObject('hive/cognitive/b');
    expect(a).toBe(b); // same instance because both map to '#e8e8e8'
    expect(a.getHexString()).toBe('e8e8e8');
  });

  it('empty topic falls through to the FALLBACK color', () => {
    expect(topicColor('')).toBe('#666666');
  });

  it('is case-sensitive — uppercase prefix falls through to FALLBACK', () => {
    expect(topicColor('HIVE/cognitive/plan')).toBe('#666666');
    expect(topicColor('hive/Cognitive/plan')).toBe('#666666');
  });
});

describe('kindTag', () => {
  const cases: Array<[string, string]> = [
    ['hive/cognitive/pfc/plan', 'cog'],
    ['hive/sensory/visual/features', 'sns'],
    ['hive/motor/intent', 'mot'],
    ['hive/metacognition/error/detected', 'meta'],
    ['hive/self/identity', 'self'],
    ['hive/modulator/dopamine', 'mod'],
    ['hive/attention/focus', 'att'],
    ['hive/interoception/felt_state', 'intr'],
    ['hive/habit/suggestion', 'hab'],
    ['hive/rhythm/gamma', 'rhy'],
    ['hive/system/heartbeat/pfc', 'hb'],
    ['hive/system/region_stats/pfc', 'rst'],
    ['hive/system/metrics/compute', 'mtr'],
    ['hive/system/sleep/granted', 'slp'],
    ['hive/system/spawn/complete', 'spn'],
    ['hive/system/codechange/approved', 'cc'],
    ['hive/broadcast/shutdown', 'bcst'],
    ['unknown/topic', '?'],
  ];
  it.each(cases)('%s → %s', (topic, tag) => expect(kindTag(topic)).toBe(tag));
});
