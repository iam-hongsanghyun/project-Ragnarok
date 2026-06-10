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

/** Sanitised scenario segment of the filename ("untitled" when blank).
 *
 * DENYLIST sanitisation: only filesystem-unsafe characters are replaced, so
 * non-Latin scenario names (한글, 日本語, …) survive into the filename instead
 * of being stripped to "untitled". */
export function scenarioFileStem(scenario?: string | null): string {
  const raw = (scenario ?? '').trim();
  const safe = raw.replace(/[\\/:*?"<>|\s]+/g, '-').replace(/^-+|-+$/g, '');
  return safe || 'untitled';
}

/** `{scenario||untitled}_{ISO-T}.xlsx` with a sanitised scenario segment. */
export function scenarioFilename(scenario?: string | null, stamp: string = isoStamp()): string {
  return `${scenarioFileStem(scenario)}_${stamp}.xlsx`;
}

/** True when `filename` already carries this scenario's stem (so its creation
 *  stamp should be kept rather than minting a new name). */
export function filenameMatchesScenario(filename: string, scenario?: string | null): boolean {
  return filename.startsWith(`${scenarioFileStem(scenario)}_`);
}
