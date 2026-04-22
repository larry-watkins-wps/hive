import { describe, it, expect } from 'vitest';
import { createStore } from '../store';
import { selectRegionFromRow } from './selectRegionFromRow';

describe('selectRegionFromRow', () => {
  it('sets selectedRegion and pendingEnvelopeKey', () => {
    const store = createStore();
    selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: '123|hive/cog' });
    expect(store.getState().selectedRegion).toBe('pfc');
    expect(store.getState().pendingEnvelopeKey).toBe('123|hive/cog');
  });

  it('accepts null envelopeKey', () => {
    const store = createStore();
    selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: null });
    expect(store.getState().selectedRegion).toBe('pfc');
    expect(store.getState().pendingEnvelopeKey).toBeNull();
  });

  it('no-op when regionName is null', () => {
    const store = createStore();
    store.getState().select('existing');
    selectRegionFromRow(store, { regionName: null, envelopeKey: null });
    expect(store.getState().selectedRegion).toBe('existing');
  });
});
