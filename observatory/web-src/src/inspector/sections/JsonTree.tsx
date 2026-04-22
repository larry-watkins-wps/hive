import { useState } from 'react';

/**
 * Recursive JSON tree view used by the STM section (spec §3.2 item 6).
 *
 * Zero dependencies — the spec mandates an "in-repo recursive component".
 * Renders each value with a simple colour-by-type scheme matching the
 * inspector's monochrome palette:
 *
 *   null         → grey
 *   string       → green (`#8fd6a0`)
 *   number       → amber (`#ffb36a`)
 *   boolean      → violet (`#d6a0e0`)
 *   object key   → blue  (`#8ec5ff`)
 *
 * Objects and arrays get a ▸/▾ chevron toggle. Depth-0 starts expanded;
 * deeper nodes start collapsed so large STM blobs don't explode on render.
 */

export type JsonValue = string | number | boolean | null | JsonArray | JsonObject;
export type JsonArray = JsonValue[];
export type JsonObject = { [k: string]: JsonValue };

export function JsonTree({ value, depth = 0 }: { value: JsonValue; depth?: number }) {
  if (value === null) return <span className="text-[#8a8e99]">null</span>;
  if (typeof value === 'string') return <span className="text-[#8fd6a0]">{JSON.stringify(value)}</span>;
  if (typeof value === 'number') return <span className="text-[#ffb36a]">{value}</span>;
  if (typeof value === 'boolean') return <span className="text-[#d6a0e0]">{String(value)}</span>;
  if (Array.isArray(value)) return <JsonArrayView arr={value} depth={depth} />;
  return <JsonObjectView obj={value} depth={depth} />;
}

function JsonObjectView({ obj, depth }: { obj: JsonObject; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const keys = Object.keys(obj);
  if (keys.length === 0) return <span className="text-[#8a8e99]">{'{}'}</span>;
  return (
    <span>
      <button
        type="button"
        className="text-[#8a8e99] font-mono"
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'}
      </button>
      <span className="text-[#8a8e99]"> {'{'} </span>
      {open && (
        <div className="pl-3">
          {keys.map((k) => (
            <div key={k} className="font-mono text-[11px]">
              <span className="text-[#8ec5ff]">{k}</span>
              <span className="text-[#8a8e99]">: </span>
              <JsonTree value={obj[k]} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
      <span className="text-[#8a8e99]">{'}'}</span>
    </span>
  );
}

function JsonArrayView({ arr, depth }: { arr: JsonArray; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  if (arr.length === 0) return <span className="text-[#8a8e99]">[]</span>;
  return (
    <span>
      <button
        type="button"
        className="text-[#8a8e99] font-mono"
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'}
      </button>
      <span className="text-[#8a8e99]"> [</span>
      {open && (
        <div className="pl-3">
          {arr.map((item, i) => (
            <div key={i} className="font-mono text-[11px]">
              <span className="text-[#8a8e99]">{i}: </span>
              <JsonTree value={item} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
      <span className="text-[#8a8e99]">]</span>
    </span>
  );
}
