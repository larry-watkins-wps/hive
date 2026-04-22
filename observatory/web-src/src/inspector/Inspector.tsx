import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { Header } from './sections/Header';
import { Stats } from './sections/Stats';
import { ModulatorBath } from './sections/ModulatorBath';
import { Prompt } from './sections/Prompt';
import { Appendix } from './sections/Appendix';
import { Messages } from './sections/Messages';
import { Stm } from './sections/Stm';
import { Subscriptions } from './sections/Subscriptions';
import { Handlers } from './sections/Handlers';

const SLIDE_OUT_MS = 300;

/**
 * Inspector — right slide-over panel, ~420 px wide. Spec §3.1 / §3.2.
 *
 * Always mounted. When `selectedRegion` flips non-null the panel slides in
 * over 300 ms; when it flips back to null the panel slides out over 300 ms.
 * `aria-hidden` flips in lockstep so assistive tech treats the panel as
 * inert while closed.
 *
 * Two separate names drive rendering:
 *   - `open` (= `selectedRegion != null`) drives the transform class so the
 *     slide animation begins the moment the user deselects.
 *   - `displayName` (sticky during slide-out) is the name the child sections
 *     render against. When the user deselects, we hold `displayName` for the
 *     300 ms animation window so the panel slides out with its content still
 *     visible instead of collapsing to an empty rectangle. Without this the
 *     slide-out had nothing to animate (spec-review T12 Important §1).
 *
 * Section order (top → bottom) matches spec §3.2.2:
 *   Header · Stats · ModulatorBath · (scrollable:
 *   Prompt · Messages · STM · Subscriptions · Handlers) · KeyHintFooter.
 *
 * Prompt / Messages / Stm are Task 13/14 stubs today — they render `null`,
 * which is harmless. Subscriptions + Handlers are the real thing.
 */
export function Inspector() {
  const name = useStore((s) => s.selectedRegion);
  const open = name != null;
  const [displayName, setDisplayName] = useState<string | null>(name);

  useEffect(() => {
    if (name) {
      // Select or cycle — update the rendered name immediately.
      setDisplayName(name);
      return;
    }
    // Deselect — hold the prior name until the slide-out transition completes,
    // then clear so section fetches stop. Cleanup cancels the pending timer if
    // the user re-selects mid-transition (timer id is captured in closure).
    const id = window.setTimeout(() => setDisplayName(null), SLIDE_OUT_MS);
    return () => window.clearTimeout(id);
  }, [name]);

  return (
    <aside
      className={`fixed right-0 top-0 h-screen w-[420px] bg-[#121218] border-l border-[#2a2a33] text-[#cfd2da] flex flex-col transition-transform duration-300 ease-out z-20 ${
        open ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-hidden={!open}
    >
      {displayName && (
        <>
          <Header name={displayName} />
          <Stats name={displayName} />
          <ModulatorBath />
          <div className="flex-1 overflow-y-auto">
            <Prompt name={displayName} />
            <Appendix name={displayName} />
            <Messages name={displayName} />
            <Stm name={displayName} />
            <Subscriptions name={displayName} />
            <Handlers name={displayName} />
          </div>
          <KeyHintFooter />
        </>
      )}
    </aside>
  );
}

/**
 * Persistent footer documenting the keyboard bindings (spec §3.1 / §4),
 * matching the key hints the `useInspectorKeys` hook installs.
 */
function KeyHintFooter() {
  return (
    <div className="px-3 py-2 border-t border-[#2a2a33] bg-[#0e0e14] text-[10px] text-[#8a8e99] flex gap-3 font-mono">
      <span>
        <kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">Esc</kbd> close
      </span>
      <span>
        <kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">[</kbd>{' '}
        <kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">]</kbd> cycle
      </span>
      <span>
        <kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">R</kbd> reset cam
      </span>
    </div>
  );
}
