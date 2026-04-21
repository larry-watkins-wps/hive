import { describe, it, expect } from 'vitest';
import { topicColor, topicColorObject } from './topicColors';

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
