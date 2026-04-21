// Ambient declarations for `d3-force-3d`.
//
// Upstream ships no `.d.ts`, and DefinitelyTyped has never published
// `@types/d3-force-3d` (see decisions.md entry 46). Task 11 is the first
// file that imports from the package; without this shim `tsc -b` fails
// with TS7016 and — because the plan's `useForceGraph.ts` calls
// `forceSimulation<ForceNode>(...)`, `forceX<ForceNode>(...)`, etc. —
// a bare `declare module 'd3-force-3d';` is not sufficient under
// `strict` + generic call syntax (TS2347 "Untyped function calls may
// not accept type arguments").
//
// The minimum-typed shim below declares each imported symbol as a
// generic function returning `any`, which is enough to satisfy the
// verbatim plan code while preserving the nominal `<ForceNode>` generic
// threading at the call sites. Swap this for a real type package if
// DefinitelyTyped ever ships one.
declare module 'd3-force-3d' {
  export function forceSimulation<N = unknown>(nodes?: N[], numDimensions?: number): any;
  export function forceManyBody<N = unknown>(): any;
  // `forceLink` returns a chainable whose `.id()` accepts a node->id
  // callback. We type the callback's parameter as the node generic so
  // the plan's verbatim `.id((d) => d.id)` type-checks without an
  // explicit annotation.
  export interface ForceLinkChainable<N> {
    id(accessor: (d: N) => string | number): ForceLinkChainable<N>;
    distance(d: number | ((link: unknown) => number)): ForceLinkChainable<N>;
    strength(s: number | ((link: unknown) => number)): ForceLinkChainable<N>;
    links(links?: unknown[]): any;
    [key: string]: any;
  }
  export function forceLink<N = unknown, _L = unknown>(links?: _L[]): ForceLinkChainable<N>;
  export function forceX<N = unknown>(x?: number | ((d: N) => number)): any;
  export function forceY<N = unknown>(y?: number | ((d: N) => number)): any;
  export function forceZ<N = unknown>(z?: number | ((d: N) => number)): any;
  export function forceCenter<N = unknown>(x?: number, y?: number, z?: number): any;
  export function forceCollide<N = unknown>(radius?: number | ((d: N) => number)): any;
  export function forceRadial<N = unknown>(radius: number | ((d: N) => number), x?: number, y?: number, z?: number): any;
}
