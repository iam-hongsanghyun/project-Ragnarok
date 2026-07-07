/**
 * Scenarios section — the scenario difference table + batch runner.
 *
 * Scenarios are authored from the Run console ("Add as Scenario"); this surface
 * shows one row per scenario with only the settings that differ, lets you set a
 * per-scenario model override (capacity, etc.), and runs them all in order or in
 * parallel. Thin wrapper — the table lives in features/scenario.
 */
import React from 'react';
import { ScenarioCatalog, WorkbookModel } from 'lib/types';
import { BatchMode, ScenarioDiffTable } from '../../features/scenario/ScenarioDiffTable';

export interface ScenariosSectionProps {
  scenarioCatalog: ScenarioCatalog;
  model: WorkbookModel;
  maxConcurrency: number;
  batchBusy?: boolean;
  /** Apply a scenario's settings to the live run controls. */
  onSelectScenario: (scenarioId: string) => void;
  /** Persist a catalog edit (override cell, delete). */
  onScenarioCatalogChange: (catalog: ScenarioCatalog) => void;
  /** Queue the given scenarios sequentially (concurrency 1) or in parallel (N). */
  onRunBatch: (ids: string[], mode: BatchMode, concurrency: number) => void;
  /** Jump to Analytics → Comparison for results. */
  onGoToComparison: () => void;
}

export function ScenariosSection(props: ScenariosSectionProps) {
  return (
    <ScenarioDiffTable
      catalog={props.scenarioCatalog}
      model={props.model}
      maxConcurrency={props.maxConcurrency}
      busy={props.batchBusy}
      onCatalogChange={props.onScenarioCatalogChange}
      onLoadScenario={props.onSelectScenario}
      onRunBatch={props.onRunBatch}
      onGoToComparison={props.onGoToComparison}
    />
  );
}
