export async function getHealth(): Promise<{ status: string; version: string }> {
  const r = await fetch('/api/health');
  if (!r.ok) throw new Error(`GET /api/health ${r.status} ${r.statusText}`);
  return r.json();
}
export async function getRegions(): Promise<{ regions: Record<string, any> }> {
  const r = await fetch('/api/regions');
  if (!r.ok) throw new Error(`GET /api/regions ${r.status} ${r.statusText}`);
  return r.json();
}
