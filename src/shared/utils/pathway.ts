import { GridRow, PathwayConfig, PathwayPeriodConfig, Primitive, WorkbookModel } from '../types';

export const PATHWAY_CONFIG_SHEET = 'RAGNAROK_Pathway';
export const PATHWAY_PERIODS_SHEET = 'RAGNAROK_PathwayPeriods';

export function defaultPathwayConfig(): PathwayConfig {
  return {
    planningMode: 'single_period',
    enabled: false,
    snapshotMappingMode: 'explicit_period_column',
    overridePolicy: 'reuse_base_inputs',
    periods: [],
    selectedPeriod: null,
  };
}

function primitiveBoolean(value: Primitive, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'yes') return true;
    if (normalized === 'false' || normalized === '0' || normalized === 'no') return false;
  }
  return fallback;
}

function primitiveNumber(value: Primitive, fallback: number | null = null): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function readPathwayConfigFromModel(model: WorkbookModel): PathwayConfig {
  const configRow = (model[PATHWAY_CONFIG_SHEET] ?? [])[0] ?? {};
  const periods = (model[PATHWAY_PERIODS_SHEET] ?? [])
    .map((row): PathwayPeriodConfig | null => {
      const period = primitiveNumber(row.period as Primitive, null);
      if (period === null) return null;
      return {
        period,
        objectiveWeight: primitiveNumber(row.objectiveWeight as Primitive, 1) ?? 1,
        yearsWeight: primitiveNumber(row.yearsWeight as Primitive, 1) ?? 1,
      };
    })
    .filter((row): row is PathwayPeriodConfig => !!row)
    .sort((left, right) => left.period - right.period);

  const selected = primitiveNumber(configRow.selectedPeriod as Primitive, null);
  const enabled = primitiveBoolean(configRow.enabled as Primitive, periods.length > 0);
  return {
    planningMode: enabled ? 'pathway' : 'single_period',
    enabled,
    snapshotMappingMode:
      configRow.snapshotMappingMode === 'repeat_all_snapshots'
        ? 'repeat_all_snapshots'
        : 'explicit_period_column',
    overridePolicy: 'reuse_base_inputs',
    periods,
    selectedPeriod: selected,
  };
}

export function writePathwayConfigToModel(
  model: WorkbookModel,
  config: PathwayConfig,
): WorkbookModel {
  const configRows: GridRow[] = [{
    enabled: config.enabled,
    planningMode: config.planningMode,
    snapshotMappingMode: config.snapshotMappingMode,
    overridePolicy: config.overridePolicy,
    selectedPeriod: config.selectedPeriod,
  }];
  const periodRows: GridRow[] = config.periods.map((period) => ({
    period: period.period,
    objectiveWeight: period.objectiveWeight,
    yearsWeight: period.yearsWeight,
  }));
  return {
    ...model,
    [PATHWAY_CONFIG_SHEET]: configRows,
    [PATHWAY_PERIODS_SHEET]: periodRows,
  };
}

export function samePathwayConfig(left: PathwayConfig, right: PathwayConfig): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function getPathwaySnapshotPeriods(model: WorkbookModel): number[] {
  const periods = new Set<number>();
  (model.snapshots ?? []).forEach((row) => {
    const period = primitiveNumber(row.period as Primitive, null);
    if (period !== null) periods.add(period);
  });
  return Array.from(periods).sort((left, right) => left - right);
}

export function getDefaultSelectedPeriod(config: PathwayConfig): number | null {
  if (!config.periods.length) return null;
  if (config.selectedPeriod !== null && config.periods.some((row) => row.period === config.selectedPeriod)) {
    return config.selectedPeriod;
  }
  return config.periods[0].period;
}
