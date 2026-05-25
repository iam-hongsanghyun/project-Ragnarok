import { GridRow, Primitive, RollingHorizonConfig, WorkbookModel } from '../types';

export const ROLLING_CONFIG_SHEET = 'RAGNAROK_Rolling';

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

function clampPositiveInt(value: number | null, fallback: number): number {
  if (value === null) return fallback;
  const intValue = Math.max(1, Math.floor(value));
  return Number.isFinite(intValue) ? intValue : fallback;
}

export function defaultRollingConfig(): RollingHorizonConfig {
  return {
    enabled: false,
    horizonSnapshots: 168,
    overlapSnapshots: 24,
    stepPolicy: 'derived',
    stepSnapshots: 144,
    preserveTerminalState: true,
    selectedWindow: null,
  };
}

export function deriveRollingStepSnapshots(
  horizonSnapshots: number,
  overlapSnapshots: number,
): number {
  return Math.max(1, horizonSnapshots - overlapSnapshots);
}

export function normalizeRollingConfig(config: RollingHorizonConfig): RollingHorizonConfig {
  const horizonSnapshots = clampPositiveInt(config.horizonSnapshots, 168);
  const overlapSnapshots = Math.max(0, Math.min(Math.floor(config.overlapSnapshots), horizonSnapshots - 1));
  return {
    ...config,
    horizonSnapshots,
    overlapSnapshots,
    stepPolicy: 'derived',
    stepSnapshots: deriveRollingStepSnapshots(horizonSnapshots, overlapSnapshots),
    preserveTerminalState: config.preserveTerminalState !== false,
    selectedWindow: config.selectedWindow ?? null,
  };
}

export function readRollingConfigFromModel(model: WorkbookModel): RollingHorizonConfig {
  const configRow = (model[ROLLING_CONFIG_SHEET] ?? [])[0] ?? {};
  const next = normalizeRollingConfig({
    enabled: primitiveBoolean(configRow.enabled as Primitive, false),
    horizonSnapshots: clampPositiveInt(primitiveNumber(configRow.horizonSnapshots as Primitive, 168), 168),
    overlapSnapshots: Math.max(0, primitiveNumber(configRow.overlapSnapshots as Primitive, 24) ?? 24),
    stepPolicy: 'derived',
    stepSnapshots: clampPositiveInt(primitiveNumber(configRow.stepSnapshots as Primitive, 144), 144),
    preserveTerminalState: primitiveBoolean(configRow.preserveTerminalState as Primitive, true),
    selectedWindow: primitiveNumber(configRow.selectedWindow as Primitive, null),
  });
  return next;
}

export function writeRollingConfigToModel(
  model: WorkbookModel,
  config: RollingHorizonConfig,
): WorkbookModel {
  const normalized = normalizeRollingConfig(config);
  const configRows: GridRow[] = [{
    enabled: normalized.enabled,
    horizonSnapshots: normalized.horizonSnapshots,
    overlapSnapshots: normalized.overlapSnapshots,
    stepPolicy: normalized.stepPolicy,
    stepSnapshots: normalized.stepSnapshots,
    preserveTerminalState: normalized.preserveTerminalState,
    selectedWindow: normalized.selectedWindow,
  }];
  return {
    ...model,
    [ROLLING_CONFIG_SHEET]: configRows,
  };
}

export function sameRollingConfig(left: RollingHorizonConfig, right: RollingHorizonConfig): boolean {
  return JSON.stringify(normalizeRollingConfig(left)) === JSON.stringify(normalizeRollingConfig(right));
}
