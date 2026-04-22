import { describe, it, expect } from 'vitest';
import { parseAppendix } from './parseAppendix';

describe('parseAppendix', () => {
  it('returns [] for empty input', () => {
    expect(parseAppendix('')).toEqual([]);
  });

  it('parses a single entry', () => {
    const md = '## 2026-04-22T10:00:00Z — sleep\n\nbody line one\nbody line two\n';
    expect(parseAppendix(md)).toEqual([
      { ts: '2026-04-22T10:00:00Z', trigger: 'sleep', body: 'body line one\nbody line two' },
    ]);
  });

  it('parses multiple entries in file order', () => {
    const md = [
      '## 2026-04-22T10:00:00Z — sleep', '',
      'entry one', '',
      '## 2026-04-22T12:00:00Z — sleep', '',
      'entry two',
    ].join('\n');
    const entries = parseAppendix(md);
    expect(entries).toHaveLength(2);
    expect(entries[0].ts).toBe('2026-04-22T10:00:00Z');
    expect(entries[0].body).toBe('entry one');
    expect(entries[1].ts).toBe('2026-04-22T12:00:00Z');
    expect(entries[1].body).toBe('entry two');
  });

  it('tolerates missing trigger (no em-dash)', () => {
    const md = '## 2026-04-22T10:00:00Z\n\nbody';
    expect(parseAppendix(md)).toEqual([
      { ts: '2026-04-22T10:00:00Z', trigger: '', body: 'body' },
    ]);
  });

  it('tolerates trailing whitespace', () => {
    const md = '## 2026-04-22T10:00:00Z — sleep   \n\nbody\n\n';
    const [entry] = parseAppendix(md);
    expect(entry.ts).toBe('2026-04-22T10:00:00Z');
    expect(entry.trigger).toBe('sleep');
    expect(entry.body).toBe('body');
  });

  it('returns single implicit entry when file has no ## headings', () => {
    const md = 'hand-written preamble with no ## sections\nline two';
    expect(parseAppendix(md)).toEqual([
      { ts: '', trigger: '', body: 'hand-written preamble with no ## sections\nline two' },
    ]);
  });
});
