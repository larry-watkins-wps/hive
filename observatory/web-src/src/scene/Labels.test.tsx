import { describe, it, expect } from 'vitest';
import { formatTokens, formatBytes } from './Labels';

// Pure-logic tests only. Mounting <Labels /> requires a live r3f context
// (Canvas + WebGLRenderer + CSS2DRenderer) which jsdom cannot provide; the
// rendering path is covered by manual visual QA at `npm run dev`. These
// tests pin the format helpers so UI spec drift surfaces immediately.

describe('formatTokens', () => {
  it('sub-thousand raw', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
  });
  it('thousand shorthand (rounded)', () => {
    expect(formatTokens(1500)).toBe('2k');
  });
  it('million shorthand (one decimal)', () => {
    expect(formatTokens(2_412_000)).toBe('2.4M');
  });
});

describe('formatBytes', () => {
  it('bytes', () => {
    expect(formatBytes(900)).toBe('900 B');
  });
  it('kilobytes (rounded)', () => {
    expect(formatBytes(18432)).toBe('18 kB');
  });
  it('megabytes (one decimal)', () => {
    expect(formatBytes(2_500_000)).toBe('2.4 MB');
  });
});
