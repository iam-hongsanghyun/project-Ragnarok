import {
  CustomConstraint,
  GridRow,
  PathwayConfig,
  Primitive,
  RollingHorizonConfig,
  ScenarioCatalog,
  ScenarioPreset,
  WorkbookModel,
} from '../types';
import { defaultPathwayConfig } from 'lib/results/pathway';
import { defaultRollingConfig, normalizeRollingConfig } from 'lib/results/rolling';

export const SCENARIO_SHEET = 'RAGNAROK_Scenarios';

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

function primitiveNumber(value: Primitive, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function primitiveString(value: Primitive, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function clonePathwayConfig(config: PathwayConfig): PathwayConfig {
  return {
    ...config,
    periods: config.periods.map((row) => ({ ...row })),
  };
}

function cloneRollingConfig(config: RollingHorizonConfig): RollingHorizonConfig {
  return normalizeRollingConfig({ ...config });
}

function cloneConstraints(constraints: CustomConstraint[]): CustomConstraint[] {
  return constraints.map((row) => ({ ...row }));
}

export function createScenarioId(): string {
  return `scenario-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function buildScenarioPreset(input: {
  id?: string;
  label?: string;
  notes?: string;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  discountRate: number;
  forceLp: boolean;
  enableLoadShedding: boolean;
  loadSheddingCost: number;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  constraints: CustomConstraint[];
}): ScenarioPreset {
  return {
    id: input.id ?? createScenarioId(),
    label: input.label?.trim() || 'Scenario',
    notes: input.notes ?? '',
    snapshotStart: input.snapshotStart,
    snapshotEnd: input.snapshotEnd,
    snapshotWeight: input.snapshotWeight,
    carbonPrice: input.carbonPrice,
    discountRate: input.discountRate,
    forceLp: input.forceLp,
    enableLoadShedding: input.enableLoadShedding,
    loadSheddingCost: input.loadSheddingCost,
    pathwayConfig: clonePathwayConfig(input.pathwayConfig),
    rollingConfig: cloneRollingConfig(input.rollingConfig),
    constraints: cloneConstraints(input.constraints),
  };
}

export function defaultScenarioCatalog(base: Omit<ScenarioPreset, 'id' | 'label' | 'notes'>): ScenarioCatalog {
  const scenario = buildScenarioPreset({
    ...base,
    id: 'scenario-base',
    label: 'Base case',
    notes: '',
  });
  return {
    activeScenarioId: scenario.id,
    scenarios: [scenario],
  };
}

function normalizeScenarioCatalog(catalog: ScenarioCatalog): ScenarioCatalog {
  if (catalog.scenarios.length === 0) {
    return { activeScenarioId: null, scenarios: [] };
  }
  const activeExists = catalog.activeScenarioId !== null
    && catalog.scenarios.some((scenario) => scenario.id === catalog.activeScenarioId);
  return {
    activeScenarioId: activeExists ? catalog.activeScenarioId : catalog.scenarios[0].id,
    scenarios: catalog.scenarios.map((scenario) => ({
      ...scenario,
      label: scenario.label.trim() || 'Scenario',
      notes: scenario.notes ?? '',
      pathwayConfig: clonePathwayConfig(scenario.pathwayConfig ?? defaultPathwayConfig()),
      rollingConfig: cloneRollingConfig(scenario.rollingConfig ?? defaultRollingConfig()),
      constraints: cloneConstraints(scenario.constraints ?? []),
    })),
  };
}

export function readScenarioCatalogFromModel(model: WorkbookModel): ScenarioCatalog {
  const rows = model[SCENARIO_SHEET] ?? [];
  const scenarios = rows.map((row): ScenarioPreset | null => {
    const id = primitiveString(row.id as Primitive).trim();
    if (!id) return null;
    try {
      const payload = typeof row.json === 'string' && row.json.trim()
        ? JSON.parse(row.json)
        : {};
      return buildScenarioPreset({
        id,
        label: primitiveString(row.label as Primitive, payload.label ?? 'Scenario'),
        notes: primitiveString(row.notes as Primitive, payload.notes ?? ''),
        snapshotStart: primitiveNumber(payload.snapshotStart as Primitive, 0),
        snapshotEnd: primitiveNumber(payload.snapshotEnd as Primitive, 24),
        snapshotWeight: primitiveNumber(payload.snapshotWeight as Primitive, 1),
        carbonPrice: primitiveNumber(payload.carbonPrice as Primitive, 0),
        discountRate: primitiveNumber(payload.discountRate as Primitive, 0),
        forceLp: primitiveBoolean(payload.forceLp as Primitive, false),
        enableLoadShedding: primitiveBoolean(payload.enableLoadShedding as Primitive, false),
        loadSheddingCost: primitiveNumber(payload.loadSheddingCost as Primitive, 1000),
        pathwayConfig: payload.pathwayConfig ?? defaultPathwayConfig(),
        rollingConfig: payload.rollingConfig ?? defaultRollingConfig(),
        constraints: Array.isArray(payload.constraints) ? payload.constraints : [],
      });
    } catch {
      return null;
    }
  }).filter((row): row is ScenarioPreset => !!row);

  const activeScenarioId =
    rows.find((row) => primitiveBoolean(row.active as Primitive, false))?.id as string | undefined;

  return normalizeScenarioCatalog({
    activeScenarioId: activeScenarioId ?? null,
    scenarios,
  });
}

export function writeScenarioCatalogToModel(
  model: WorkbookModel,
  catalog: ScenarioCatalog,
): WorkbookModel {
  const normalized = normalizeScenarioCatalog(catalog);
  const rows: GridRow[] = normalized.scenarios.map((scenario) => ({
    id: scenario.id,
    label: scenario.label,
    active: scenario.id === normalized.activeScenarioId,
    notes: scenario.notes,
    json: JSON.stringify({
      snapshotStart: scenario.snapshotStart,
      snapshotEnd: scenario.snapshotEnd,
      snapshotWeight: scenario.snapshotWeight,
      carbonPrice: scenario.carbonPrice,
      discountRate: scenario.discountRate,
      forceLp: scenario.forceLp,
      enableLoadShedding: scenario.enableLoadShedding,
      loadSheddingCost: scenario.loadSheddingCost,
      pathwayConfig: scenario.pathwayConfig,
      rollingConfig: scenario.rollingConfig,
      constraints: scenario.constraints,
    }),
  }));
  return {
    ...model,
    [SCENARIO_SHEET]: rows,
  };
}

export function sameScenarioCatalog(left: ScenarioCatalog, right: ScenarioCatalog): boolean {
  return JSON.stringify(normalizeScenarioCatalog(left)) === JSON.stringify(normalizeScenarioCatalog(right));
}
