import { useStore } from '../store';

const TABS: Array<{ id: 'firehose' | 'topics' | 'metacog'; label: string }> = [
  { id: 'firehose', label: 'Firehose' },
  { id: 'topics', label: 'Topics' },
  { id: 'metacog', label: 'Metacog' },
];

/**
 * Spec §4.2 — dock tab strip. 28 px tall; three tabs with per-tab count badge;
 * right-aligned pause + collapse buttons. Active tab has a 1 px top-border
 * accent (the spec's "soft accent line"); inactive tabs are dimmed.
 *
 * The per-tab counts are passed in as props (not read from the store) because
 * their sources live in tabs that haven't been implemented yet — wiring lands
 * in Tasks 5 (firehose rate), 6 (topic count), 7 (metacog badge).
 */
export function DockTabStrip({
  firehoseRate,
  topicCount,
  metacogBadge,
}: {
  firehoseRate: number;
  topicCount: number;
  metacogBadge: { count: number; severity: 'error' | 'conflict' | 'quiet' };
}) {
  const dockTab = useStore((s) => s.dockTab);
  const setDockTab = useStore((s) => s.setDockTab);
  const dockCollapsed = useStore((s) => s.dockCollapsed);
  const setDockCollapsed = useStore((s) => s.setDockCollapsed);
  const dockPaused = useStore((s) => s.dockPaused);
  const setDockPaused = useStore((s) => s.setDockPaused);

  const badgeColor =
    metacogBadge.severity === 'error'
      ? 'text-[#ff8a88]'
      : metacogBadge.severity === 'conflict'
        ? 'text-[#ffc07a]'
        : 'text-[rgba(230,232,238,.45)]';

  return (
    <div
      className="flex items-center h-7 px-2 border-b border-[rgba(80,84,96,.55)] select-none"
      style={{ fontSize: 11 }}
    >
      {TABS.map((t) => {
        const active = dockTab === t.id;
        const count =
          t.id === 'firehose'
            ? `${firehoseRate.toFixed(0)}/s`
            : t.id === 'topics'
              ? `${topicCount}`
              : `·${metacogBadge.count}`;
        const countClass = t.id === 'metacog' ? badgeColor : 'text-[rgba(230,232,238,.55)]';
        return (
          <button
            key={t.id}
            onClick={() => setDockTab(t.id)}
            className={[
              'px-3 h-7 mr-1',
              active
                ? 'text-[rgba(230,232,238,.95)] border-t border-[rgba(230,232,238,.9)]'
                : 'text-[rgba(230,232,238,.45)]',
            ].join(' ')}
          >
            {t.label}{' '}
            <span className={['font-mono ml-1', countClass].join(' ')} style={{ fontSize: 10 }}>
              {count}
            </span>
          </button>
        );
      })}
      <div className="flex-1" />
      <button
        className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
        onClick={() => setDockPaused(!dockPaused)}
        title={dockPaused ? 'Resume (Space)' : 'Pause (Space)'}
      >
        {dockPaused ? '▶' : '⏸'}
      </button>
      <button
        className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
        onClick={() => setDockCollapsed(!dockCollapsed)}
        title={dockCollapsed ? 'Expand (`)' : 'Collapse (`)'}
      >
        {dockCollapsed ? '˄' : '˅'}
      </button>
    </div>
  );
}
