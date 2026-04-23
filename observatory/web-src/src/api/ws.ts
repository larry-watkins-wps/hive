import type { StoreApi, UseBoundStore } from 'zustand';

type ServerMessage =
  | { type: 'snapshot'; payload: any }
  | { type: 'envelope'; payload: any }
  | { type: 'region_delta'; payload: { regions: Record<string, any> } }
  | {
      type: 'adjacency';
      payload: {
        pairs: Array<[string, string, number]>;
        // Ever-seen baseline union, shipped on every tick so a client
        // connected before a given pair's first envelope still picks it
        // up within one delta interval. Optional for back-compat with
        // older servers.
        baseline?: Array<[string, string]>;
      };
    }
  | { type: 'decimated'; payload: { dropped: number } };

// Envelope batcher: accumulate arrivals and flush to the store at ~10Hz so
// Firehose re-renders and sparks updates are bounded regardless of inbound
// envelope rate. Before this, a 70 env/s stream triggered 70 zustand set()
// calls/sec → 70 Firehose re-renders/sec → main thread fell behind the WS
// receive loop → server-side queue exceeded _QUEUE_HIGH_WATER (1000) → hub
// dropped all envelopes for that client → sparks stalled ~30s in.
const _FLUSH_INTERVAL_MS = 100;
let _pending: any[] = [];
let _flushTimer: ReturnType<typeof setTimeout> | null = null;
function _scheduleFlush(store: UseBoundStore<StoreApi<any>>): void {
  if (_flushTimer !== null) return;
  _flushTimer = setTimeout(() => {
    _flushTimer = null;
    if (_pending.length === 0) return;
    const batch = _pending;
    _pending = [];
    store.getState().pushEnvelopes(batch);
  }, _FLUSH_INTERVAL_MS);
}

export function handleServerMessage(store: UseBoundStore<StoreApi<any>>, msg: ServerMessage): void {
  const s = store.getState();
  switch (msg.type) {
    case 'snapshot': s.applySnapshot(msg.payload); break;
    case 'envelope':
      _pending.push(msg.payload);
      _scheduleFlush(store);
      break;
    case 'region_delta': s.applyRegionDelta(msg.payload.regions); break;
    case 'adjacency':
      s.applyAdjacency(msg.payload.pairs);
      if (msg.payload.baseline) s.applyBaselinePairs(msg.payload.baseline);
      break;
    case 'decimated': /* ignore for v1; hook for a future "lagging" badge */ break;
  }
}

export function connect(store: UseBoundStore<StoreApi<any>>, url = '/ws', onStatus?: (s: string) => void): () => void {
  let sock: WebSocket | null = null;
  let stopped = false;
  let retry = 500;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    if (stopped) return;
    const fullUrl = url.startsWith('ws') ? url : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${url}`;
    sock = new WebSocket(fullUrl);
    sock.onopen = () => { retry = 500; onStatus?.('open'); };
    sock.onmessage = (ev) => {
      try { handleServerMessage(store, JSON.parse(ev.data)); }
      catch (err) { console.warn('ws parse error', err); }
    };
    sock.onclose = () => {
      onStatus?.('closed');
      if (!stopped) {
        timer = setTimeout(open, Math.min(retry, 10000));
        retry = Math.min(retry * 2, 10000);
      }
    };
    sock.onerror = () => sock?.close();
  };

  open();
  return () => {
    stopped = true;
    if (timer) { clearTimeout(timer); timer = null; }
    sock?.close();
  };
}
