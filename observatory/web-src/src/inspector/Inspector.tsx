import { useStore } from '../store';
import { Header } from './sections/Header';
import { Stats } from './sections/Stats';
import { ModulatorBath } from './sections/ModulatorBath';
import { Prompt } from './sections/Prompt';
import { Messages } from './sections/Messages';
import { Stm } from './sections/Stm';
import { Subscriptions } from './sections/Subscriptions';
import { Handlers } from './sections/Handlers';

/**
 * Inspector — right slide-over panel, ~420 px wide. Spec §3.1 / §3.2.
 *
 * Always mounted (for accessibility and for the CSS transition to animate
 * consistently), but visually slid off-screen to the right via
 * `translate-x-full` when nothing is selected. When `selectedRegion`
 * flips non-null the panel slides in over 300 ms. `aria-hidden` flips in
 * lockstep so assistive tech treats the panel as inert while closed.
 *
 * The slide-over uses Tailwind arbitrary-value classes (`w-[420px]`,
 * `bg-[#121218]`, etc.) which Tailwind v3 supports out of the box
 * (`tailwind.config.js` in this project is v3). If a future hardening
 * pass moves to a theme with explicit tokens, those classes can be
 * replaced without changing this file's structure.
 *
 * Section order (top → bottom) matches spec §3.2.2:
 *   Header · Stats · ModulatorBath · (scrollable:
 *   Prompt · Messages · STM · Subscriptions · Handlers) · KeyHintFooter.
 *
 * Prompt / Messages / Stm are Task 13/14 stubs today — they render
 * `null`, which is harmless. Subscriptions + Handlers are the real thing.
 *
 * Children only render when `open` is true so section `useRegionFetch`
 * hooks don't fire on idle mounts. The `<aside>` itself is always in the
 * tree so its CSS transition has both `from` and `to` keyframes.
 */
export function Inspector() {
  const name = useStore((s) => s.selectedRegion);
  const open = name != null;
  return (
    <aside
      className={`fixed right-0 top-0 h-screen w-[420px] bg-[#121218] border-l border-[#2a2a33] text-[#cfd2da] flex flex-col transition-transform duration-300 ease-out z-20 ${
        open ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-hidden={!open}
    >
      {open && name && (
        <>
          <Header name={name} />
          <Stats name={name} />
          <ModulatorBath />
          <div className="flex-1 overflow-y-auto">
            <Prompt name={name} />
            <Messages name={name} />
            <Stm name={name} />
            <Subscriptions name={name} />
            <Handlers name={name} />
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
