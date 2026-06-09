/**
 * Canonical Excel name for the working model / results: `{scenario}_{ISO-T}.xlsx`.
 *
 * The name is ALWAYS derived from the scenario (never the uploaded source file),
 * with the load/build timestamp inlined in filesystem-safe ISO-8601 form
 * (`2026-06-10T14-30-00` — `T` separator, colons → dashes). No scenario → "untitled".
 * Mirrors the backend run-file convention (`run_store._derive_name`).
 */

/** Filesystem-safe ISO-8601 stamp, seconds precision: `2026-06-10T14-30-00`. */
export function isoStamp(d: Date = new Date()): string {
  return d.toISOString().slice(0, 19).replace(/:/g, '-');
}

/** `{scenario||untitled}_{ISO-T}.xlsx` with a sanitised scenario segment. */
export function scenarioFilename(scenario?: string | null, stamp: string = isoStamp()): string {
  const raw = (scenario ?? '').trim();
  const safe = raw.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  return `${safe || 'untitled'}_${stamp}.xlsx`;
}
