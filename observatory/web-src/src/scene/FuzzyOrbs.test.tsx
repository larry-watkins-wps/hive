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

  it('explicit "unknown" phase (pre-heartbeat offline) reads as faint grey', () => {
    // Regions seeded from the registry but not yet heartbeated emit
    // `phase: "unknown"` — they render at a faint slate-grey so offline
    // regions are visibly distinct from live wake-blue orbs.
    const offline = phaseBase('unknown');
    expect(offline.color).toBe(0x2e3442);
    expect(offline.emissive).toBeLessThan(0.15);
    expect(offline.coreOpacity).toBeLessThan(0.85);
  });

  it('forward-compat unknown phase string falls back to offline colour', () => {
    // A novel phase string we don't model yet still resolves via the
    // `PHASE_COLOR[phase] ?? PHASE_COLOR.unknown` fallback, so it lands on
    // the offline grey rather than any other live colour.
    expect(phaseBase('gobbledygook').color).toBe(0x2e3442);
  });

  it('outer scale differs by phase', () => {
    expect(phaseBase('wake').outerScale).toBe(5.2);
    expect(phaseBase('bootstrap').outerScale).toBe(4.5);
    expect(phaseBase('sleep').outerScale).toBe(3.8);
  });
});
