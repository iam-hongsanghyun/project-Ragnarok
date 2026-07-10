/**
 * Scenarios section — the scenario difference table + batch runner.
 *
 * This surface is for naming and running scenarios: rename inline, add the
 * current run configuration as a new scenario, and run them all in order or
 * in parallel. Model values are edited in Model/Forge, not here. Thin
 * wrapper — the table lives in features/scenario.
 */
import React from 'react';
import { ScenarioCatalog } from 'lib/types';
import { BatchMode, ScenarioDiffTable } from '../../features/scenario/ScenarioDiffTable';

export interface ScenariosSectionProps {
  scenarioCatalog: ScenarioCatalog;
  maxConcurrency: number;
  batchBusy?: boolean;
  /** Apply a scenario's settings to the live run controls. */
  onSelectScenario: (scenarioId: string) => void;
  /** Persist a catalog edit (rename, delete). */
  onScenarioCatalogChange: (catalog: ScenarioCatalog) => void;
  /** Save the live run configuration as a new named scenario (prompts for the name). */
  onCreateScenarioFromCurrent: () => void;
  /** Queue the given scenarios sequentially (concurrency 1) or in parallel (N). */
  onRunBatch: (ids: string[], mode: BatchMode, concurrency: number) => void;
  /** Jump to Analytics → Comparison for results. */
  onGoToComparison: () => void;
}

export function ScenariosSection(props: ScenariosSectionProps) {
  return (
    <ScenarioDiffTable
      catalog={props.scenarioCatalog}
      maxConcurrency={props.maxConcurrency}
      busy={props.batchBusy}
      onCatalogChange={props.onScenarioCatalogChange}
      onLoadScenario={props.onSelectScenario}
      onAddScenarioFromCurrent={props.onCreateScenarioFromCurrent}
      onRunBatch={props.onRunBatch}
      onGoToComparison={props.onGoToComparison}
    />
  );
}
