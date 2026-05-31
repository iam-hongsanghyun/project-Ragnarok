/**
 * OSM `voltage` tag parser. Ported verbatim from
 * `backend/app/importers/databases/osm/voltage.py` so the existing semantics
 * (and unit-tested edge cases) carry over unchanged.
 *
 * The tag is wildly inconsistent in the wild. Examples:
 *
 *   "110000"           → 110 kV
 *   "110000;220000"    → [110, 220] kV
 *   "110 kV" / "110kV" → 110 kV
 *   "110000 V"         → 110 kV
 *   "110,220"          → [110, 220] kV
 *   "110"              → 110 kV (lone bare numbers are conventionally kV)
 *   "0.4"              → 0.4 kV (LV; filtered by the user's threshold)
 *   "" / "unknown"     → []
 *
 * Convention: any bare number ≥ 1000 is interpreted as volts (and divided
 * by 1000); anything smaller is taken as kV.
 */

const NUM_RE = /-?\d+(?:[.,]\d+)?/;
const VOLTS_THRESHOLD = 1000.0;

function coerceToKv(raw: number): number {
  return raw >= VOLTS_THRESHOLD ? raw / 1000.0 : raw;
}

function maybeFloat(token: string): number | null {
  const trimmed = token.trim();
  if (!trimmed) return null;
  const match = trimmed.replace(/,/g, '.').match(NUM_RE);
  if (!match) return null;
  const v = parseFloat(match[0]);
  return Number.isFinite(v) ? v : null;
}

/**
 * Parse a raw OSM `voltage` tag into a list of voltages in kV.
 * Returns an empty list for missing / unparseable values.
 */
export function parseVoltageKv(value: string | null | undefined): number[] {
  if (!value) return [];
  let text = String(value).trim().toLowerCase();
  if (!text || text === 'unknown' || text === 'none' || text === 'n/a') return [];
  // Strip explicit "kv" markers — the magnitude tells us anyway.
  text = text.replace(/kv/g, '').replace(/volts/g, '').replace(/v/g, '');
  const seen = new Set<number>();
  const out: number[] = [];
  for (const chunk of text.split(/[;,]/)) {
    const v = maybeFloat(chunk);
    if (v === null) continue;
    const kv = Math.round(coerceToKv(v) * 10000) / 10000;
    if (kv <= 0 || seen.has(kv)) continue;
    seen.add(kv);
    out.push(kv);
  }
  return out;
}

/** Convenience: max parsed voltage, or `null` if nothing parsed. */
export function maxVoltageKv(value: string | null | undefined): number | null {
  const parsed = parseVoltageKv(value);
  return parsed.length ? Math.max(...parsed) : null;
}
