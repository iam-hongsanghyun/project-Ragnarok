/**
 * MATPOWER `.m` block parser — TypeScript port of build_kpg193_pypsa.py's
 * extract_scalar / extract_block / parse_matrix helpers.
 *
 * The MATPOWER case format embeds the network in MATLAB-style assignments:
 *
 *   mpc.baseMVA = 100;
 *   mpc.bus = [
 *     1   2   ... ; %% comment
 *     ...
 *   ];
 *   mpc.gen = [ ... ];
 *   mpc.branch = [ ... ];
 *   mpc.gencost = [ ... ];
 *   mpc.genthermal = [ ... ];
 *   mpc.dcline = [ ... ];   % (optional — not in every release)
 *
 * We do not try to be a general MATLAB parser. We only need to:
 *   1. Read scalars by name (baseMVA).
 *   2. Read each named matrix block as numeric rows, with the trailing
 *      `% <comment>` per row captured as a string column (the comment
 *      carries carrier / fuel info — gen_fuel, gencost_fuel, …).
 */

export type MatrixRow = number[];

/**
 * Find the first `mpc.<key> = <value>;` and return the right-hand side as
 * a string (with surrounding quotes stripped). Throws if missing.
 */
export function extractScalar(text: string, key: string): string {
  const marker = `mpc.${key} =`;
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line.startsWith(marker)) continue;
    const rhs = line.slice(marker.length).trim();
    return rhs.replace(/;$/, '').trim().replace(/^'|'$/g, '');
  }
  throw new Error(`MATPOWER scalar not found: mpc.${key}`);
}

/**
 * Find `mpc.<key> = [ ... ];` and return the inner lines (everything
 * between the opening bracket and the closing `];`). Returns `[]` when
 * the block is absent — older case files may not carry `mpc.dcline` etc.
 */
export function extractBlockLines(text: string, key: string): string[] {
  const marker = `mpc.${key} = [`;
  const start = text.indexOf(marker);
  if (start === -1) return [];
  const end = text.indexOf('];', start);
  if (end === -1) return [];
  // Slice from after the opening `[` to just before the closing `];`,
  // then split on newlines. Drop the first line — it's the `mpc.<key> = [`
  // line itself.
  const block = text.slice(start, end);
  const blockLines = block.split(/\r?\n/);
  return blockLines.slice(1);
}

/**
 * Parse the inner lines of a block into an array of `{ values, comment }`
 * rows. Values are numeric (NaN for unparseable tokens, although real
 * MATPOWER files are clean). Comments are everything after the `%` on the
 * row's data line.
 */
export interface ParsedRow {
  values: number[];
  comment: string;
}

export function parseMatrixLines(lines: string[]): ParsedRow[] {
  const rows: ParsedRow[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('%')) continue; // section-level comment, skip

    // Split into data part + trailing comment (first `%`).
    const pctIdx = line.indexOf('%');
    const dataPart = (pctIdx === -1 ? line : line.slice(0, pctIdx))
      .replace(/;/g, ' ')
      .trim();
    if (!dataPart) continue;
    const comment = pctIdx === -1 ? '' : line.slice(pctIdx + 1).trim();

    const tokens = dataPart.split(/\s+/);
    const values: number[] = [];
    for (const t of tokens) {
      const v = Number(t);
      // MATPOWER files sometimes use `0` rather than blanks; everything
      // should parse. Push NaN for genuinely bad tokens so the caller can
      // see them in column alignment without us silently dropping rows.
      values.push(Number.isFinite(v) ? v : NaN);
    }
    rows.push({ values, comment });
  }
  return rows;
}

/**
 * Wrap parseMatrixLines with a named-column projection so downstream
 * code can read `row.Pmax` instead of `row.values[8]`.
 */
export function parseMatrix<T extends string>(
  lines: string[],
  columns: readonly T[],
  commentColumn: string,
): Array<Record<T | string, number | string>> {
  const parsed = parseMatrixLines(lines);
  return parsed.map((row) => {
    const out: Record<string, number | string> = {};
    for (let i = 0; i < columns.length; i++) {
      out[columns[i] as string] = i < row.values.length ? row.values[i] : NaN;
    }
    out[commentColumn] = row.comment;
    return out;
  });
}

// ── MATPOWER column schemas (mirrors build_kpg193_pypsa.py) ─────────────────

export const BUS_COLUMNS = [
  'bus_i', 'type', 'Pd', 'Qd', 'Gs', 'Bs', 'area',
  'Vm', 'Va', 'baseKV', 'zone', 'Vmax', 'Vmin',
] as const;

export const GEN_COLUMNS = [
  'bus', 'Pg', 'Qg', 'Qmax', 'Qmin', 'Vg', 'mBase', 'status',
  'Pmax', 'Pmin', 'Pc1', 'Pc2', 'Qc1min', 'Qc1max', 'Qc2min', 'Qc2max',
  'ramp_agc', 'ramp_10', 'ramp_30', 'ramp_q', 'apf',
] as const;

export const BRANCH_COLUMNS = [
  'fbus', 'tbus', 'r', 'x', 'b',
  'rateA', 'rateB', 'rateC',
  'ratio', 'angle', 'status', 'angmin', 'angmax',
] as const;

export const DCLINE_COLUMNS = [
  'f_bus', 't_bus', 'br_status', 'Pf', 'Pt', 'Qf', 'Qt', 'Vf', 'Vt',
  'Pmin', 'Pmax', 'QminF', 'QmaxF', 'QminT', 'QmaxT', 'loss0', 'loss1',
] as const;

export const GENCOST_COLUMNS = [
  'model', 'startup', 'shutdown', 'n', 'c2', 'c1', 'c0',
] as const;

export const GENTHERMAL_COLUMNS = [
  'type_thermal', 'UT', 'DT', 'inistate', 'initialpower',
  'ramp_up', 'ramp_down', 'startup_limit', 'shutdown_limit',
  'startup1', 'startup2', 'startup3',
  'startupdelay1', 'startupdelay2', 'startupdelay3',
] as const;
