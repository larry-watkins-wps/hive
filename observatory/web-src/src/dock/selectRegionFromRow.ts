import type { StoreApi, UseBoundStore } from 'zustand';

type MinStore = UseBoundStore<StoreApi<{
  select: (name: string | null) => void;
  setPendingEnvelopeKey: (key: string | null) => void;
  selectedRegion: string | null;
}>>;

/**
 * Pure helper that implements spec §8 row-click behavior: given an envelope
 * row, select its source region and mark the envelope key as "pending" so
 * the inspector can scroll it into view.
 *
 * No-ops when `regionName` is null (envelope had no traceable source).
 */
export function selectRegionFromRow(
  store: MinStore,
  { regionName, envelopeKey }: { regionName: string | null; envelopeKey: string | null },
): void {
  if (regionName == null) return;
  store.getState().select(regionName);
  store.getState().setPendingEnvelopeKey(envelopeKey);
}
