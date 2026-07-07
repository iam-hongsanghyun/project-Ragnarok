/**
 * Pure builder for a run's `{scenario, options}` body from a ScenarioPreset.
 *
 * This is the de-Reactified form of the block that used to live inline in
 * `App.tsx`'s `handleRunModel` — it read ~25 pieces of live React state. Sourcing
 * every scenario field off a `preset` argument instead lets a BATCH build one
 * payload per scenario (each with its own settings + model overrides) without
 * touching the user's live controls. For the single-run path the caller passes
 * `captureCurrentScenario()` (a preset snapshot of the live controls), so the
 * result is byte-identical to the old inline code.
 *
 * `uiOpts` carries the fields that are NOT part of a preset (backend id, run
 * filename, date format, solver knobs) plus the `scenarioLabel` the caller wants
 * the stored run tagged with. `constraintSpecs` come from the model-level custom
 * DSL (shared across all scenarios), not the preset.
 */
import type { ConstraintSpec, ScenarioPreset } from 'lib/types';
import type { DateFormat, SolverType } from 'lib/settings/types';
import type { AppSettings } from 'lib/settings/types';
import { getDefaultSelectedPeriod } from 'lib/results/pathway';
import { normalizeRollingConfig } from 'lib/results/rolling';
import { normalizeSamplingConfig } from 'lib/results/sampling';

export interface RunUiOptions {
  /** Optimisation backend id (only 'pypsa' today). */
  backend?: string;
  /** Label the stored run is tagged with (drives the Comparison pivot). For a
   *  single run: the active scenario's label; for a batch: each preset's label. */
  scenarioLabel: string | null;
  filename: string;
  dateFormat: DateFormat;
  solverThreads: number;
  solverType: SolverType;
  solveAcceptance: AppSettings['solveAcceptance'];
  objectiveAutoScale: boolean;
  currencySymbol: string;
}

export interface RunPayloadBody {
  scenario: {
    constraints: ScenarioPreset['constraints'];
    constraintSpecs: ConstraintSpec[];
    carbonPrice: number;
    discountRate: number;
  };
  options: Record<string, unknown>;
}

export function buildRunPayload(
  preset: ScenarioPreset,
  uiOpts: RunUiOptions,
  constraintSpecs: ConstraintSpec[],
): RunPayloadBody {
  const scenario = {
    constraints: preset.constraints.filter((c) => c.enabled),
    constraintSpecs,
    carbonPrice: preset.carbonPrice,
    discountRate: preset.discountRate,
  };

  const options: Record<string, unknown> = {
    backend: uiOpts.backend ?? 'pypsa',
    snapshotCount: preset.snapshotEnd - preset.snapshotStart,
    snapshotStart: preset.snapshotStart,
    snapshotEnd: preset.snapshotEnd,
    snapshotWeight: preset.snapshotWeight,
    forceLp: preset.forceLp,
    scenarioLabel: uiOpts.scenarioLabel,
    filename: uiOpts.filename,
    dateFormat: uiOpts.dateFormat,
    solverThreads: uiOpts.solverThreads,
    solverType: uiOpts.solverType,
    solveAcceptance: uiOpts.solveAcceptance,
    objectiveAutoScale: uiOpts.objectiveAutoScale,
    currencySymbol: uiOpts.currencySymbol,
    enableLoadShedding: preset.enableLoadShedding,
    loadSheddingCost: preset.loadSheddingCost,
    pathwayConfig: {
      ...preset.pathwayConfig,
      selectedPeriod: getDefaultSelectedPeriod(preset.pathwayConfig),
    },
    rollingConfig: normalizeRollingConfig(preset.rollingConfig),
    samplingConfig: normalizeSamplingConfig(preset.samplingConfig),
    stochasticConfig: preset.stochasticConfig,
    securityConstrainedConfig: preset.securityConstrainedConfig,
    reserveConfig: preset.reserveConfig,
    outageMcConfig: preset.outageMcConfig,
    correlatedSamplingConfig: preset.correlatedSamplingConfig,
    rampConfig: preset.rampConfig,
    elccConfig: preset.elccConfig,
    convergenceConfig: preset.convergenceConfig,
    lmpDecompositionConfig: preset.lmpDecompositionConfig,
    powerFlowConfig: preset.powerFlowConfig,
    marketSimConfig: preset.marketSimConfig,
    contingencyConfig: preset.contingencyConfig,
    mgaConfig: preset.mgaConfig,
    merchantConfig: preset.merchantConfig,
    bidStrategyConfig: preset.bidStrategyConfig,
    assetSwapConfig: preset.assetSwapConfig,
    essConfig: preset.essConfig,
    ppaConfig: preset.ppaConfig,
    demandResponseConfig: preset.demandResponseConfig,
    ownerColumn: preset.ownerColumn,
    financeConfig: preset.financeConfig,
    carbonPriceSchedule: preset.carbonPriceSchedule,
  };

  // Per-scenario model overrides (capacity, etc.) — applied server-side to the
  // run's model snapshot. Only sent when present so a plain run's body is
  // unchanged from before this feature existed.
  if (preset.modelOverrides && preset.modelOverrides.length > 0) {
    options.modelOverrides = preset.modelOverrides;
  }

  return { scenario, options };
}
