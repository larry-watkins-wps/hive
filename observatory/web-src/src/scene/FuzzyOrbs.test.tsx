import { describe, it, expect } from 'vitest';
import { phaseBase } from './FuzzyOrbs';

// Pure-logic tests — we do not mount the Canvas-backed component. Rendering
// <FuzzyOrbs /> requires a live r3f context which jsdom cannot provide; the
// layer counts / lerp behavior are covered by manual visual QA at
// `npm run dev`. These tests pin the phase-driven constants from spec §5.1
// so any drift is caught immediately.

describe('phaseBase', () => {
  it('wake has high emissive', () => {
    expect(phaseBase('wake').emissive).toBeCloseTo(0.55);
  });

  it('sleep has low emissive', () => {
    expect(phaseBase('sleep').emissive).toBeCloseTo(0.15);
  });

  it('unknown phase falls back to wake-blue', () => {
    expect(phaseBase('gobbledygook').color).toBe(0x6aa8ff);
  });

  it('outer scale differs by phase', () => {
    expect(phaseBase('wake').outerScale).toBe(5.2);
    expect(phaseBase('bootstrap').outerScale).toBe(4.5);
    expect(phaseBase('sleep').outerScale).toBe(3.8);
  });
});
