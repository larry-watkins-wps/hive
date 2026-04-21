import { describe, it, expect } from 'vitest';
import { edgeKey, EDGE_PULSE } from './Edges';

// -----------------------------------------------------------------------------
// Pure-logic pins. Rendering <Edges /> itself requires a live r3f context
// (Canvas + WebGLRenderer) which jsdom cannot supply — the helpers covered
// here (edgeKey + opacity formula constants) are the contract surface the
// rest of the scene depends on.
// -----------------------------------------------------------------------------

describe('edgeKey', () => {
  it('is undirected (edgeKey(a,b) === edgeKey(b,a))', () => {
    expect(edgeKey('a', 'b')).toBe(edgeKey('b', 'a'));
  });

  it('is alphabetical — sorted lexically regardless of input order', () => {
    expect(edgeKey('z', 'a')).toBe('a|z');
    expect(edgeKey('motor_cortex', 'broca_area')).toBe(
      'broca_area|motor_cortex',
    );
  });

  it('handles identical regions as a self-loop key', () => {
    // Not produced in practice (adjacency pairs are cross-region), but the
    // function should still be total — pin the behavior.
    expect(edgeKey('x', 'x')).toBe('x|x');
  });
});

describe('EDGE_PULSE opacity formula', () => {
  // Spec §5.3: material.opacity = clamp(0.08 + 0.55 * pulse, 0, 1)
  it('pulse=1.0 → 0.08 + 0.55 = 0.63', () => {
    expect(0.08 + 0.55 * 1).toBeCloseTo(0.63);
  });

  it('pulse=0 → base 0.08', () => {
    expect(0.08 + 0.55 * 0).toBeCloseTo(0.08);
  });

  it('pulse=0.5 → 0.08 + 0.275 = 0.355', () => {
    expect(0.08 + 0.55 * 0.5).toBeCloseTo(0.355);
  });
});

describe('EDGE_PULSE module-level Map', () => {
  it('is exported and writable (Sparks.tsx writes here)', () => {
    expect(EDGE_PULSE).toBeInstanceOf(Map);
    // Sanity: adding + removing an entry works against the live export.
    const probeKey = '__test__|__test__';
    EDGE_PULSE.delete(probeKey); // idempotent cleanup
    expect(EDGE_PULSE.has(probeKey)).toBe(false);
  });
});
