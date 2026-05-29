/**
 * Sidebar — collapsible left-panel content.
 *
 * Five always-visible groups + Modules when present:
 *   File · Constraints · Scenarios · Run summary · Results / History · Modules
 *
 * Complex editors live in workspace overlays (Run setup, Settings,
 * Constraints) opened via shortcut buttons. This keeps the sidebar focused
 * on navigation, per-run quick state, and run-history without forcing
 * users to drill into every option from a 252-px-wide rail.
 */
import React, { useState } from 'react';
import {
  CarbonPriceScheduleEntry,
  CustomConstraint,
  GridRow,
  ModuleDescriptor,
  ModuleHostInventory,
  PathwayConfig,
  RollingHorizonConfig,
  RunHistoryEntry,
  RunResults,
  ScenarioCatalog,
  SecurityConstrainedConfig,
  StochasticConfig,
  WorkbookModel,
} from '../shared/types';
import { SidebarGroup } from '../shared/components/SidebarGroup';
import { ModuleManagerSection } from '../features/modules/ModuleManagerSection';
import { RunHistoryList } from '../features/run-history/RunHistoryList';
import { MAX_UNPINNED_HISTORY, METRIC_DEFS } from '../constants';
import { stringValue } from '../shared/utils/helpers';

export interface SidebarProps {
  model: WorkbookModel;
  results: RunResults | null;
  constraints: CustomConstraint[];
  onOpenConstraintsWorkspace: () => void;
  onOpenRunSetupWorkspace: () => void;
  onOpenSettingsWorkspace: () => void;
  onOpen: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onImportProject: () => void;
  onExportProject: () => void;
  onImportCsvFolder: () => void;
  onExportCsvFolder: () => void;
  onImportNetcdf: () => void;
  onExportNetcdf: () => void;
  onImportHdf5: () => void;
  onExportHdf5: () => void;
  onExportResult: () => void;
  onExportReport: () => void;
  scenarioCatalog: ScenarioCatalog;
  activeScenarioLabel: string | null;
  scenarioDirty: boolean;
  onSelectScenario: (scenarioId: string) => void;
  onCreateScenarioFromCurrent: () => void;
  onDuplicateScenario: () => void;
  onUpdateActiveScenarioFromCurrent: () => void;
  onDeleteScenario: () => void;
  onRenameScenario: (scenarioId: string, label: string) => void;
  onScenarioNotesChange: (scenarioId: string, notes: string) => void;
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  sclopfConfig: SecurityConstrainedConfig;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  currencySymbol: string;
  runHistory: RunHistoryEntry[];
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onToggleComparison: (id: string, inComparison: boolean) => void;
  moduleInventory: ModuleHostInventory | null;
  moduleHostLoading: boolean;
  moduleHostError: string | null;
  enabledModuleIds: string[];
  isModuleEnabled: (moduleId: string) => boolean;
  isModuleEnableEligible: (module: ModuleDescriptor) => boolean;
  onToggleModuleEnabled: (moduleId: string, enabled: boolean) => void;
  onInstallModule: (file: File) => void;
  onUninstallModule: (module: ModuleDescriptor) => void;
}

export function Sidebar({
  model,
  results,
  constraints,
  onOpenConstraintsWorkspace,
  onOpenRunSetupWorkspace,
  onOpenSettingsWorkspace,
  onOpen,
  onSave,
  onSaveAs,
  onImportProject,
  onExportProject,
  onImportCsvFolder,
  onExportCsvFolder,
  onImportNetcdf,
  onExportNetcdf,
  onImportHdf5,
  onExportHdf5,
  onExportResult,
  onExportReport,
  scenarioCatalog,
  activeScenarioLabel,
  scenarioDirty,
  onSelectScenario,
  onCreateScenarioFromCurrent,
  onDuplicateScenario,
  onUpdateActiveScenarioFromCurrent,
  onDeleteScenario,
  onRenameScenario,
  onScenarioNotesChange,
  pathwayConfig,
  rollingConfig,
  stochasticConfig,
  sclopfConfig,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  carbonPrice,
  carbonPriceSchedule,
  currencySymbol,
  runHistory,
  onRestoreRun,
  onRenameHistoryEntry,
  onPinHistoryEntry,
  onDeleteHistoryEntry,
  onToggleComparison,
  moduleInventory,
  moduleHostLoading,
  moduleHostError,
  enabledModuleIds,
  isModuleEnabled,
  isModuleEnableEligible,
  onToggleModuleEnabled,
  onInstallModule,
  onUninstallModule,
}: SidebarProps) {
  const [showAdvancedFormats, setShowAdvancedFormats] = useState(false);
  const activeScenario = scenarioCatalog.scenarios.find((s) => s.id === scenarioCatalog.activeScenarioId) ?? null;

  return (
    <>
      {/* ── File ── */}
      <SidebarGroup title="File" defaultOpen>
        <div className="sg-btn-grid">
          <button className="tb-btn sg-full" onClick={onOpen}>Open</button>
          <button className="tb-btn sg-full" onClick={onSave}>Save</button>
          <button className="tb-btn sg-full" onClick={onSaveAs}>Save As</button>
          <button className="tb-btn sg-full" onClick={onImportProject} title="Import a project workbook (input + solved outputs)">
            Import Project
          </button>
          <button
            className="tb-btn sg-full"
            onClick={onExportProject}
            title={results ? 'Export the full project: inputs + every solved output sheet' : 'Export the project workbook (inputs only — no run yet)'}
          >
            Export Project
          </button>
          <button
            className="tb-btn sg-full"
            disabled={!results}
            title={results ? 'Export the solved result + analytics workbook' : 'Run the model first to export results'}
            onClick={onExportResult}
          >
            Export Result
          </button>
          <button
            className="tb-btn sg-full"
            disabled={!results}
            title={results ? 'Export an HTML report of the current result' : 'Run the model first to export a report'}
            onClick={onExportReport}
          >
            Export Report
          </button>
          <button
            className="tb-btn sg-full tb-btn--muted"
            onClick={() => setShowAdvancedFormats((v) => !v)}
            title="PyPSA-native CSV folder / netCDF / HDF5 round-trips"
          >
            {showAdvancedFormats ? '− More formats' : '+ More formats'}
          </button>
          {showAdvancedFormats && (
            <>
              <button className="tb-btn sg-full" onClick={onImportCsvFolder} title="Import a PyPSA-native CSV folder, packaged as a .zip">
                Import CSV folder
              </button>
              <button className="tb-btn sg-full" onClick={onExportCsvFolder} title="Export the input model as a PyPSA-native CSV folder (zipped)">
                Export CSV folder
              </button>
              <button className="tb-btn sg-full" onClick={onImportNetcdf} title="Import a PyPSA-native netCDF (.nc) file via the backend">
                Import netCDF
              </button>
              <button className="tb-btn sg-full" onClick={onExportNetcdf} title="Export the input model as a PyPSA-native netCDF (.nc) file via the backend">
                Export netCDF
              </button>
              <button className="tb-btn sg-full" onClick={onImportHdf5} title="Import a PyPSA-native HDF5 (.h5) file via the backend">
                Import HDF5
              </button>
              <button className="tb-btn sg-full" onClick={onExportHdf5} title="Export the input model as a PyPSA-native HDF5 (.h5) file via the backend">
                Export HDF5
              </button>
            </>
          )}
        </div>
      </SidebarGroup>

      {/* ── Constraints ── */}
      <SidebarGroup
        title="Constraints"
        badge={
          constraints.filter((c) => c.enabled).length > 0
            ? <span className="sg-badge">{constraints.filter((c) => c.enabled).length}</span>
            : undefined
        }
      >
        <ConstraintsSummary
          constraints={constraints}
          globalConstraintRows={model.global_constraints ?? []}
          onOpen={onOpenConstraintsWorkspace}
        />
      </SidebarGroup>

      {/* ── Scenarios ── */}
      <SidebarGroup
        title="Scenarios"
        badge={<span className="sg-badge">{scenarioCatalog.scenarios.length}</span>}
      >
        <div className="sg-setting-row">
          <label className="sg-setting-label">Scenario library</label>
          <div className="period-pill-row">
            {scenarioCatalog.scenarios.map((scenario) => (
              <button
                key={scenario.id}
                className={`tb-btn period-pill${scenario.id === scenarioCatalog.activeScenarioId ? '' : ' tb-btn--muted'}`}
                onClick={() => onSelectScenario(scenario.id)}
                title={scenario.notes || scenario.label}
              >
                {scenario.label}
              </button>
            ))}
          </div>
          <p className="sg-setting-hint">
            Presets capture the current constraints, window, carbon price, pathway, and rolling settings.
          </p>
        </div>

        <div className="sg-setting-row">
          <div className="sg-btn-row">
            <button className="tb-btn sg-solver-btn" onClick={onCreateScenarioFromCurrent}>New from current</button>
            <button
              className={`tb-btn sg-solver-btn${scenarioDirty ? '' : ' tb-btn--muted'}`}
              onClick={onUpdateActiveScenarioFromCurrent}
              disabled={!activeScenario}
            >
              Update active
            </button>
            <button className="tb-btn sg-solver-btn tb-btn--muted" onClick={onDuplicateScenario} disabled={!activeScenario}>
              Duplicate
            </button>
            <button
              className="tb-btn sg-solver-btn tb-btn--muted"
              onClick={onDeleteScenario}
              disabled={!activeScenario || scenarioCatalog.scenarios.length <= 1}
            >
              Delete
            </button>
          </div>
          {activeScenario && (
            <div className="sg-scenario-status">
              <span className={`sg-scenario-dot${scenarioDirty ? ' is-dirty' : ''}`} />
              <span>{scenarioDirty ? 'Current controls differ from the active scenario.' : 'Current controls match the active scenario.'}</span>
            </div>
          )}
        </div>

        {activeScenario && (
          <>
            <div className="sg-setting-divider" />
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="sg-scenario-label">Active scenario label</label>
              <input
                id="sg-scenario-label"
                type="text"
                className="sg-num-input"
                value={activeScenario.label}
                onChange={(e) => onRenameScenario(activeScenario.id, e.target.value)}
              />
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="sg-scenario-notes">Notes</label>
              <textarea
                id="sg-scenario-notes"
                className="sg-scenario-notes"
                rows={3}
                value={activeScenario.notes}
                onChange={(e) => onScenarioNotesChange(activeScenario.id, e.target.value)}
              />
            </div>
            {activeScenarioLabel && (
              <div className="sg-setting-row">
                <div className="sg-scenario-summary">
                  <span>Active: {activeScenarioLabel}</span>
                </div>
              </div>
            )}
          </>
        )}
      </SidebarGroup>

      {/* ── Run summary — opens the Run setup workspace ── */}
      <SidebarGroup title="Run setup">
        <RunSummary
          pathwayConfig={pathwayConfig}
          rollingConfig={rollingConfig}
          stochasticConfig={stochasticConfig}
          sclopfConfig={sclopfConfig}
          snapshotStart={snapshotStart}
          snapshotEnd={snapshotEnd}
          snapshotWeight={snapshotWeight}
          carbonPrice={carbonPrice}
          carbonPriceSchedule={carbonPriceSchedule}
          currencySymbol={currencySymbol}
          onOpen={onOpenRunSetupWorkspace}
        />
      </SidebarGroup>

      {/* ── Application settings (one-time per project) ── */}
      <SidebarGroup title="Settings">
        <div className="constraints-summary">
          <p className="sg-setting-hint" style={{ marginTop: 0 }}>
            Currency, date format, carrier colors, discount rate, load shedding, solver — open the workspace to edit.
          </p>
          <button className="tb-btn constraints-summary-open" onClick={onOpenSettingsWorkspace}>
            Open settings →
          </button>
        </div>
      </SidebarGroup>

      {/* ── Results ── */}
      {results && (
        <SidebarGroup title="Results" defaultOpen>
          <div className="sg-summary">
            {results.summary.map((s) => (
              <div key={s.label} className="sg-summary-item">
                <span className="sg-summary-label">{s.label}</span>
                <span className="sg-summary-value">{s.value}</span>
                <span className="sg-summary-detail">{s.detail}</span>
              </div>
            ))}
          </div>
        </SidebarGroup>
      )}

      {/* ── History ── */}
      {runHistory.length > 0 && (
        <SidebarGroup
          title="History"
          badge={<span className="sg-badge">{runHistory.length}</span>}
        >
          <RunHistoryList
            runHistory={runHistory}
            onRestoreRun={onRestoreRun}
            onRenameHistoryEntry={onRenameHistoryEntry}
            onPinHistoryEntry={onPinHistoryEntry}
            onDeleteHistoryEntry={onDeleteHistoryEntry}
            onToggleComparison={onToggleComparison}
            currencySymbol={currencySymbol}
          />
          <p className="hist-footnote">
            Last {MAX_UNPINNED_HISTORY} runs kept · pin to preserve
          </p>
        </SidebarGroup>
      )}

      {/* ── Modules ── */}
      <SidebarGroup
        title="Modules"
        badge={
          moduleInventory
            ? <span className="sg-badge">{enabledModuleIds.length}/{moduleInventory.summary.ready}</span>
            : undefined
        }
      >
        <ModuleManagerSection
          inventory={moduleInventory}
          loading={moduleHostLoading}
          error={moduleHostError}
          enabledIds={enabledModuleIds}
          isEnabled={isModuleEnabled}
          isEnableEligible={isModuleEnableEligible}
          onToggleEnabled={onToggleModuleEnabled}
          onInstall={onInstallModule}
          onUninstall={onUninstallModule}
        />
      </SidebarGroup>
    </>
  );
}

// ── Compact constraints summary (opens the workspace overlay) ─────────────────

function ConstraintsSummary({
  constraints,
  globalConstraintRows,
  onOpen,
}: {
  constraints: CustomConstraint[];
  globalConstraintRows: GridRow[];
  onOpen: () => void;
}) {
  const enabled = constraints.filter((c) => c.enabled);
  const activeNames = enabled.map((c) => c.label || METRIC_DEFS[c.metric]?.label || c.metric).slice(0, 3);
  const extra = Math.max(0, enabled.length - activeNames.length);
  const globalNames = globalConstraintRows.map((row) => stringValue(row.name)).filter(Boolean).slice(0, 2);
  const globalExtra = Math.max(0, globalConstraintRows.length - globalNames.length);

  return (
    <div className="constraints-summary">
      <div className="constraints-summary-line">
        <span className="constraints-summary-label">Custom</span>
        <span className="constraints-summary-value">
          {enabled.length === 0
            ? <em>none active</em>
            : <>{activeNames.join(', ')}{extra > 0 ? `, +${extra} more` : ''}</>}
        </span>
      </div>
      <div className="constraints-summary-line">
        <span className="constraints-summary-label">Global</span>
        <span className="constraints-summary-value">
          {globalConstraintRows.length === 0
            ? <em>no rows</em>
            : <>{globalNames.join(', ')}{globalExtra > 0 ? `, +${globalExtra} more` : ''}</>}
        </span>
      </div>
      <button className="tb-btn constraints-summary-open" onClick={onOpen} title="Open the constraints editor">
        Open constraints editor →
      </button>
    </div>
  );
}

// ── Compact run-setup summary (opens the Run setup workspace) ────────────────

function RunSummary({
  pathwayConfig,
  rollingConfig,
  stochasticConfig,
  sclopfConfig,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  carbonPrice,
  carbonPriceSchedule,
  currencySymbol,
  onOpen,
}: {
  pathwayConfig: PathwayConfig;
  rollingConfig: RollingHorizonConfig;
  stochasticConfig: StochasticConfig;
  sclopfConfig: SecurityConstrainedConfig;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  currencySymbol: string;
  onOpen: () => void;
}) {
  const planningLabel = pathwayConfig.enabled
    ? `Pathway · ${pathwayConfig.periods.length} periods`
    : 'Single period';
  const windowLabel = pathwayConfig.enabled
    ? 'Full horizon'
    : `${snapshotEnd - snapshotStart} steps × ${snapshotWeight}h`;

  const flags: string[] = [];
  if (rollingConfig.enabled) flags.push(`Rolling ${rollingConfig.horizonSnapshots}/${rollingConfig.overlapSnapshots}`);
  if (stochasticConfig.enabled && stochasticConfig.scenarios.length >= 2) flags.push(`Stochastic · ${stochasticConfig.scenarios.length} sc`);
  if (sclopfConfig.enabled) flags.push('SCLOPF (N-1)');

  return (
    <div className="constraints-summary">
      <div className="constraints-summary-line">
        <span className="constraints-summary-label">Planning</span>
        <span className="constraints-summary-value">{planningLabel}</span>
      </div>
      <div className="constraints-summary-line">
        <span className="constraints-summary-label">Window</span>
        <span className="constraints-summary-value">{windowLabel}</span>
      </div>
      <div className="constraints-summary-line">
        <span className="constraints-summary-label">Carbon</span>
        <span className="constraints-summary-value">
          {(() => {
            if (carbonPriceSchedule.length >= 2) {
              const prices = carbonPriceSchedule.map((r) => r.price);
              const minP = Math.min(...prices);
              const maxP = Math.max(...prices);
              const firstYear = carbonPriceSchedule[0].year;
              const lastYear = carbonPriceSchedule[carbonPriceSchedule.length - 1].year;
              return minP === maxP
                ? `${currencySymbol}${minP}/t (${firstYear}–${lastYear})`
                : `${currencySymbol}${minP}→${maxP}/t (${firstYear}–${lastYear})`;
            }
            if (carbonPriceSchedule.length === 1) {
              return `${currencySymbol}${carbonPriceSchedule[0].price}/t (${carbonPriceSchedule[0].year})`;
            }
            return carbonPrice > 0 ? `${currencySymbol}${carbonPrice}/t` : <em>off</em>;
          })()}
        </span>
      </div>
      {flags.length > 0 && (
        <div className="constraints-summary-line">
          <span className="constraints-summary-label">Mode</span>
          <span className="constraints-summary-value">{flags.join(' · ')}</span>
        </div>
      )}
      <button className="tb-btn constraints-summary-open" onClick={onOpen} title="Open the run setup editor">
        Open run setup →
      </button>
    </div>
  );
}
