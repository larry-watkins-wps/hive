import { Modulators } from '../../hud/Modulators';

/**
 * Thin wrapper that mounts the v1 HUD `<Modulators />` gauges inside the
 * inspector panel with a section heading. Spec §3.2 item 3 — deliberate
 * re-use, no duplication of gauge logic.
 *
 * The plan's pseudocode passes `variant="compact"` to `<Modulators />`,
 * but the v1 component takes no props — kept as-is here. The spec does
 * not require a compact variant; both the HUD copy and the panel copy
 * render the same six gauges. If a future spec revision calls for a
 * different density, extend `Modulators.tsx` with an optional `variant`
 * prop rather than forking a second gauge implementation.
 */
export function ModulatorBath() {
  return (
    <div className="px-4 py-2 border-b border-[#2a2a33]">
      <div className="text-[9px] text-[#8a8e99] tracking-wider mb-1">
        MODULATOR BATH
      </div>
      <Modulators />
    </div>
  );
}
