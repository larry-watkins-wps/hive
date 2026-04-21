import { SelfPanel } from './SelfPanel';
import { Modulators } from './Modulators';
import { Counters } from './Counters';

export function Hud() {
  return (
    <>
      <div className="absolute top-3 left-3 pointer-events-none">
        <SelfPanel />
        <Modulators />
      </div>
      <div className="absolute bottom-3 left-3 pointer-events-none">
        <Counters />
      </div>
    </>
  );
}
