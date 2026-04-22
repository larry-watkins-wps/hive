/**
 * Shared byte formatter for inspector sections. Kept here so Stats, Handlers,
 * and future Task 13/14 sections render the same units/spacing instead of
 * diverging copies (code-review T12 S1).
 *
 *   0..1023 B         → "523 B"
 *   1 kB..1023 kB     → "12 kB"   (rounded to integer)
 *   ≥ 1 MB            → "1.2 MB"  (one decimal)
 */
export function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} kB`;
  return `${n} B`;
}
