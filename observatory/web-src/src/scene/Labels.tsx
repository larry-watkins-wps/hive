import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame, useThree } from '@react-three/fiber';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { useStore, type RegionMeta } from '../store';

// -----------------------------------------------------------------------------
// Formatting helpers
//
// Exported for the unit test suite — rendering <Labels /> itself requires a
// live r3f context (Canvas + WebGLRenderer) which jsdom cannot supply, so the
// format helpers are the only surface we can cover without expensive mocking.
// -----------------------------------------------------------------------------

/**
 * Compact integer formatter for token counts.
 * - `n < 1e3` → raw (`"999"`).
 * - `1e3 ≤ n < 1e6` → rounded kilo-count with `k` suffix (`1500` → `"2k"`).
 * - `n ≥ 1e6` → one-decimal mega-count with `M` suffix (`2_412_000` → `"2.4M"`).
 */
export function formatTokens(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return String(n);
}

/**
 * Byte-size formatter paralleling `formatTokens` — uses binary (1024-based)
 * divisors matching `RegionStats.stm_bytes` semantics (raw byte counts).
 */
export function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} kB`;
  return `${n} B`;
}

// -----------------------------------------------------------------------------
// DOM construction
//
// Building the label tree procedurally (document.createElement + textContent
// + appendChild) is deliberate — injecting region names or numeric stats via
// innerHTML would open an XSS path, and the security reminder hook blocks
// innerHTML writes that include interpolated values. Each region gets one
// tree built once and then mutated in place each frame via textContent /
// className; nothing is ever torn down until the region itself disappears.
// -----------------------------------------------------------------------------

type LabelEls = {
  root: HTMLDivElement;
  name: HTMLDivElement;
  stats: HTMLDivElement;
  phase: HTMLSpanElement;
  queueVal: HTMLSpanElement;
  stmVal: HTMLSpanElement;
  tokensVal: HTMLSpanElement;
};

function buildLabelEl(): LabelEls {
  const root = document.createElement('div');
  root.className = 'float-label';

  const name = document.createElement('div');
  name.className = 'name';
  root.appendChild(name);

  const stats = document.createElement('div');
  stats.className = 'stats';

  const phase = document.createElement('span');
  phase.className = 'phase-badge';
  stats.appendChild(phase);

  // "queue <n> · stm <size> · tokens <formatted>" — per spec §5.2's minimal
  // 3-field stat line. Values are child <span>s so textContent updates each
  // frame land in a single node without reserializing the parent.
  stats.appendChild(document.createTextNode('queue '));
  const queueVal = document.createElement('span');
  stats.appendChild(queueVal);

  const sep1 = document.createElement('span');
  sep1.className = 'sep';
  sep1.textContent = '·';
  stats.appendChild(sep1);

  stats.appendChild(document.createTextNode('stm '));
  const stmVal = document.createElement('span');
  stats.appendChild(stmVal);

  const sep2 = document.createElement('span');
  sep2.className = 'sep';
  sep2.textContent = '·';
  stats.appendChild(sep2);

  stats.appendChild(document.createTextNode('tokens '));
  const tokensVal = document.createElement('span');
  stats.appendChild(tokensVal);

  root.appendChild(stats);

  return { root, name, stats, phase, queueVal, stmVal, tokensVal };
}

// -----------------------------------------------------------------------------
// Labels component
// -----------------------------------------------------------------------------

type LabelsProps = {
  /**
   * Map of region name → THREE.Group published by FuzzyOrbs. Labels attaches
   * one CSS2DObject per entry at local `(0, 1.6, 0)` so the text billboards
   * above each orb's 0.55-radius core sphere. The Map is mutated (not
   * reassigned) by FuzzyOrbs' callback refs, so we read `refMap.current`
   * fresh each time rather than capturing it.
   */
  refMap: React.MutableRefObject<Map<string, THREE.Object3D>>;
};

/**
 * CSS2D floating-text labels per region (spec §5.2).
 *
 * A single CSS2DRenderer is installed as a sibling DOM element above the
 * WebGL canvas (pointer-events: none) and renders every frame at priority=1
 * so it runs *after* the default WebGL render. Each region gets one
 * CSS2DObject attached to its FuzzyOrb group; the label's DOM tree is built
 * once and mutated each frame with current `RegionStats` values.
 *
 * Hover is resolved by a window-level Raycaster on pointermove that
 * intersects the picker meshes FuzzyOrbs publishes with `userData.name`.
 * Either pointer-hover OR `selectedRegion` forces the `.hover` class on
 * the label root; CSS hides `.stats` unless `.hover` is present.
 */
export function Labels({ refMap }: LabelsProps) {
  const { scene, camera, gl } = useThree();
  const regions = useStore((s) => s.regions);
  const selectedRegion = useStore((s) => s.selectedRegion);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  // Stable identity for the dep array on the mount/unmount effect — `names`
  // is a fresh array on every store delta (same pattern as FuzzyOrbs /
  // useForceGraph) so we key on the joined string to only re-fire when the
  // region set actually changes.
  const namesKey = names.join('|');

  const rendererRef = useRef<CSS2DRenderer | null>(null);
  const labelObjRefs = useRef<Map<string, { obj: CSS2DObject; els: LabelEls }>>(
    new Map(),
  );
  // Raycaster writes; useFrame reads. Using a ref (not state) keeps the hover
  // loop off React's render path — updates happen at 60 Hz.
  const hoveredName = useRef<string | null>(null);

  // --- Renderer lifecycle ----------------------------------------------------
  //
  // One CSS2DRenderer for the lifetime of the component. We inject its DOM
  // element as a sibling of the WebGL canvas so both overlap exactly; the
  // renderer sizes itself to the canvas on mount and on every window resize.
  //
  // pointer-events: none is critical — CameraControls binds its drag listeners
  // on the canvas, and an opaque sibling div would steal every mouse event.
  useEffect(() => {
    const renderer = new CSS2DRenderer();
    renderer.setSize(gl.domElement.clientWidth, gl.domElement.clientHeight);
    renderer.domElement.style.position = 'absolute';
    renderer.domElement.style.top = '0';
    renderer.domElement.style.left = '0';
    renderer.domElement.style.pointerEvents = 'none';
    gl.domElement.parentElement?.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const onResize = () => {
      renderer.setSize(gl.domElement.clientWidth, gl.domElement.clientHeight);
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      renderer.domElement.remove();
      rendererRef.current = null;
    };
  }, [gl]);

  // --- Per-region label objects ---------------------------------------------
  //
  // Mount a CSS2DObject on each region's FuzzyOrb group as regions enter;
  // tear them down when a region leaves (e.g. observatory reconnect delivers
  // a shrunken snapshot). Position (0, 1.6, 0) sits just above the 0.55-radius
  // core sphere with room to spare for the descender-heavy stat line.
  //
  // Note: this effect runs when `namesKey` changes. The per-frame text update
  // loop in `useFrame` handles stat churn without remounting.
  useEffect(() => {
    // Remove stale
    for (const [name, entry] of labelObjRefs.current.entries()) {
      if (!regions[name]) {
        entry.obj.parent?.remove(entry.obj);
        entry.els.root.remove();
        labelObjRefs.current.delete(name);
      }
    }
    // Add new
    for (const name of names) {
      if (labelObjRefs.current.has(name)) continue;
      const parent = refMap.current.get(name);
      if (!parent) continue;
      const els = buildLabelEl();
      const obj = new CSS2DObject(els.root);
      obj.position.set(0, 1.6, 0);
      parent.add(obj);
      labelObjRefs.current.set(name, { obj, els });
    }
    // Deliberately depends on `namesKey` (not `names` or `regions`) so it
    // runs on region-set changes only, not on every heartbeat delta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namesKey, refMap]);

  // --- Hover raycaster -------------------------------------------------------
  //
  // pointermove on the canvas → NDC-space ray → intersectObjects against
  // every descendant of refMap values that carries `userData.name` (which
  // FuzzyOrbs' picker meshes do). The first hit's name is stashed in
  // `hoveredName.current` for useFrame to apply.
  //
  // We traverse lazily on each move rather than caching the picker list so
  // mid-session region churn (regions enter / leave / re-register) stays
  // correct without a separate invalidation path.
  useEffect(() => {
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const onMove = (ev: PointerEvent) => {
      const rect = gl.domElement.getBoundingClientRect();
      mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const pickers: THREE.Object3D[] = [];
      for (const obj of refMap.current.values()) {
        obj.traverse((child) => {
          if ((child as THREE.Object3D).userData?.name) pickers.push(child);
        });
      }
      const hits = raycaster.intersectObjects(pickers, false);
      hoveredName.current = hits.length
        ? (hits[0].object.userData.name as string)
        : null;
      gl.domElement.style.cursor = hoveredName.current ? 'pointer' : 'grab';
    };
    gl.domElement.addEventListener('pointermove', onMove);
    return () => gl.domElement.removeEventListener('pointermove', onMove);
  }, [gl, camera, refMap]);

  // --- Per-frame text + class update + CSS2D render -------------------------
  //
  // priority=1 runs after the default r3f WebGL render at priority=0, so the
  // DOM overlay is updated with the same-frame WebGL output underneath it.
  //
  // `.hover` is forced if the label's region is either pointer-hovered OR
  // the selected region — spec §5.2 requires the selected region's stats
  // to remain visible regardless of pointer position.
  useFrame(() => {
    for (const [name, { els }] of labelObjRefs.current.entries()) {
      const meta: RegionMeta | undefined = regions[name];
      const stats = meta?.stats;
      els.name.textContent = name;
      if (stats) {
        els.phase.textContent = stats.phase.toUpperCase();
        // Phase-badge class pins the phase-tinted color (blue/green/grey per
        // CSS). The lowercase phase string comes straight from the region's
        // LifecyclePhase (StrEnum renders lowercase by convention).
        els.phase.className = `phase-badge ${stats.phase}`;
        els.queueVal.textContent = String(stats.queue_depth);
        els.stmVal.textContent = formatBytes(stats.stm_bytes);
        els.tokensVal.textContent = formatTokens(stats.tokens_lifetime);
      }
      const force =
        name === hoveredName.current || name === selectedRegion;
      els.root.classList.toggle('hover', force);
    }
    rendererRef.current?.render(scene, camera);
  }, 1);

  return null;
}
