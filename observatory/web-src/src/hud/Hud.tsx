import { SelfState } from './SelfState';
import { SystemMetrics } from './SystemMetrics';
import { Modulators } from './Modulators';
import { Counters } from './Counters';

// Top-left HUD stack: Self · Metrics · Modulators · Counters top-to-bottom
// per spec §10.1 line 314 (Metrics sits below Self and above v1 Counters).
//
// `pointer-events-none` on the container + `pointer-events-auto` on each
// direct child via the `[&>*]` arbitrary variant preserves scene
// click-through between tiles (Tailwind 3.3+ supports this syntax; the
// project is on 3.4). SelfState's tab buttons need pointer events to
// register clicks; without this split, the whole HUD column would either
// block scene interaction or break the new tabs.
export function Hud() {
  return (
    <div className="absolute top-3 left-3 flex flex-col gap-2 z-20 pointer-events-none [&>*]:pointer-events-auto">
      <SelfState />
      <SystemMetrics />
      <Modulators />
      <Counters />
    </div>
  );
}
