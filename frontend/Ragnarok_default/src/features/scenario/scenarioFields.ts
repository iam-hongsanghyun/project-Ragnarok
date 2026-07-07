/**
 * Scenario diffing — turn a set of ScenarioPresets into the columns of a
 * "one row per scenario" difference table.
 *
 * Rather than a hand-maintained field list (which silently rots as presets gain
 * fields), we DEEP-FLATTEN each preset into `path -> display string` and treat
 * any path whose value isn't identical across all scenarios as a difference
 * column. This is inherently exhaustive — nested configs and any future preset
 * field are covered automatically — so the diff can never miss a setting.
 *
 * Model overrides get their own readable paths (`model · <sheet> · <name> ·
 * <column>`) and are the one EDITABLE column kind: they're how a scenario varies
 * capacity/model. Everything else is authored via the Run console (capture) and
 * shown read-only here.
 */
import type { ModelOverride, ScenarioPreset } from 'lib/types';

/** Top-level preset keys that are identity/metadata, not comparable settings. */
const SKIP_TOP = new Set(['id', 'label', 'notes', 'modelOverrides']);

export const OVERRIDE_PREFIX = 'model';

/** Friendly group name for a flattened path's top-level segment. */
const GROUP_LABELS: Record<string, string> = {
  snapshotStart: 'Window', snapshotEnd: 'Window', snapshotWeight: 'Window',
  carbonPrice: 'Economics', carbonPriceSchedule: 'Economics', discountRate: 'Economics',
  enableLoadShedding: 'Solve', loadSheddingCost: 'Solve', forceLp: 'Solve',
  pathwayConfig: 'Pathway', rollingConfig: 'Rolling', samplingConfig: 'Sampling',
  stochasticConfig: 'Stochastic', securityConstrainedConfig: 'Security',
  reserveConfig: 'Reserve',
  outageMcConfig: 'Outage risk',
  correlatedSamplingConfig: 'Correlated risk',
  rampConfig: 'Ramp',
  elccConfig: 'ELCC',
  convergenceConfig: 'Convergence',
  powerFlowConfig: 'Power flow', marketSimConfig: 'Market', contingencyConfig: 'Contingency',
  mgaConfig: 'MGA', merchantConfig: 'Merchant', bidStrategyConfig: 'Bidding',
  assetSwapConfig: 'Asset swap', essConfig: 'Storage', ppaConfig: 'PPA',
  demandResponseConfig: 'Demand response', ownerColumn: 'Ownership', financeConfig: 'Finance',
  constraints: 'Constraints',
  [OVERRIDE_PREFIX]: 'Model',
};

export function stringifyLeaf(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

function flattenInto(obj: Record<string, unknown>, prefix: string, out: Record<string, string>): void {
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      flattenInto(v as Record<string, unknown>, path, out);
    } else {
      out[path] = stringifyLeaf(v); // arrays are compared whole (stringified)
    }
  }
}

/** Flatten one preset into `path -> display string`. Model overrides become
 *  `model.<sheet>.<name>.<column>` paths. */
export function flattenScenario(preset: ScenarioPreset): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(preset)) {
    if (SKIP_TOP.has(k)) continue;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      flattenInto(v as Record<string, unknown>, k, out);
    } else {
      out[k] = stringifyLeaf(v);
    }
  }
  for (const ov of preset.modelOverrides ?? []) {
    out[overridePath(ov.sheet, ov.name, ov.column)] = stringifyLeaf(ov.value);
  }
  return out;
}

export interface DiffColumn {
  path: string;
  label: string;
  group: string;
  isOverride: boolean;
}

function toColumn(path: string): DiffColumn {
  const top = path.split('.')[0];
  const isOverride = top === OVERRIDE_PREFIX;
  const label = isOverride ? path.slice(OVERRIDE_PREFIX.length + 1).replace(/\./g, ' · ') : path;
  return { path, label, group: GROUP_LABELS[top] ?? top, isOverride };
}

/** The columns of the diff table: every path that differs across the scenarios
 *  (or all paths when `includeAll`). Override columns are sorted to the end. */
export function scenarioDiffColumns(
  scenarios: ScenarioPreset[],
  opts: { includeAll?: boolean } = {},
): DiffColumn[] {
  const flats = scenarios.map(flattenScenario);
  const paths = new Set<string>();
  flats.forEach((f) => Object.keys(f).forEach((p) => paths.add(p)));
  const cols: DiffColumn[] = [];
  Array.from(paths).forEach((path) => {
    const values = flats.map((f) => f[path] ?? '');
    const differs = new Set(values).size > 1;
    if (opts.includeAll || differs) cols.push(toColumn(path));
  });
  return cols.sort((a, b) => {
    if (a.isOverride !== b.isOverride) return a.isOverride ? 1 : -1;
    return a.path.localeCompare(b.path);
  });
}

/** Display value of one scenario at one column path (blank → em dash). */
export function cellValue(preset: ScenarioPreset, path: string): string {
  const v = flattenScenario(preset)[path];
  return v === undefined || v === '' ? '—' : v;
}

// ── model-override helpers (the editable column kind) ────────────────────────────

export function overridePath(sheet: string, name: string, column: string): string {
  return `${OVERRIDE_PREFIX}.${sheet}.${name}.${column}`;
}

export function parseOverridePath(path: string): { sheet: string; name: string; column: string } | null {
  // `model.<sheet>.<name>.<column>` — but a PyPSA component NAME may itself
  // contain dots (legal), so anchor on the fixed ends (prefix, sheet, column)
  // and rejoin the middle as the name. Sheet keys and attribute names don't
  // contain dots, so this is unambiguous.
  const parts = path.split('.');
  if (parts[0] !== OVERRIDE_PREFIX || parts.length < 4) return null;
  return { sheet: parts[1], name: parts.slice(2, -1).join('.'), column: parts[parts.length - 1] };
}

export function getOverride(preset: ScenarioPreset, sheet: string, name: string, column: string): ModelOverride | undefined {
  return (preset.modelOverrides ?? []).find((o) => o.sheet === sheet && o.name === name && o.column === column);
}

/** Return a new modelOverrides array with the cell set (blank value removes it). */
export function setOverride(
  overrides: ModelOverride[],
  sheet: string,
  name: string,
  column: string,
  value: string,
): ModelOverride[] {
  const without = overrides.filter((o) => !(o.sheet === sheet && o.name === name && o.column === column));
  const trimmed = value.trim();
  if (trimmed === '') return without;
  // Keep numbers numeric so the backend applies the right type.
  const num = Number(trimmed);
  const v: string | number = trimmed !== '' && Number.isFinite(num) && String(num) === trimmed ? num : trimmed;
  return [...without, { sheet, name, column, value: v }];
}
