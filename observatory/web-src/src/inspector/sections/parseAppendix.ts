export type AppendixEntry = {
  ts: string;       // ISO timestamp from the "## <ts> — <trigger>" line (may be empty)
  trigger: string;  // word after "— " (may be empty)
  body: string;     // everything between this heading and the next (trimmed)
};

export function parseAppendix(md: string): AppendixEntry[] {
  if (md.trim() === '') return [];

  const lines = md.split('\n');
  const headings: Array<{ lineIdx: number; ts: string; trigger: string }> = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^## (.+)$/);
    if (m) {
      const inner = m[1].trim();
      const split = inner.match(/^([^—]+?)\s*(?:—\s*(.*))?$/);
      const ts = (split?.[1] ?? inner).trim();
      const trigger = (split?.[2] ?? '').trim();
      headings.push({ lineIdx: i, ts, trigger });
    }
  }

  if (headings.length === 0) {
    return [{ ts: '', trigger: '', body: md.trim() }];
  }

  const entries: AppendixEntry[] = [];
  for (let i = 0; i < headings.length; i++) {
    const start = headings[i].lineIdx + 1;
    const end = i + 1 < headings.length ? headings[i + 1].lineIdx : lines.length;
    const body = lines.slice(start, end).join('\n').trim();
    entries.push({ ts: headings[i].ts, trigger: headings[i].trigger, body });
  }
  return entries;
}
