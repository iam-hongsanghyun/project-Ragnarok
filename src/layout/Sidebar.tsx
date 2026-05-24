/**
 * Sidebar — collapsible left-panel content.
 *
 * Owns four SidebarGroup sections: File, Constraints, Results, History.
 * The parent (<App>) keeps the <aside> shell and the collapse toggle button.
 */
import React, { useEffect, useState } from 'react';
import { CustomConstraint, ModuleDescriptor, ModuleHostInventory, PathwayConfig, RunHistoryEntry, RunResults, WorkbookModel } from '../shared/types';
import { SidebarGroup } from '../shared/components/SidebarGroup';
import { GlobalConstraintsSection } from '../features/constraints/GlobalConstraintsSection';
import { ModuleManagerSection } from '../features/modules/ModuleManagerSection';
import { RunHistoryList } from '../features/run-history/RunHistoryList';
import { DateFormat, SolverType } from '../features/settings/useSettings';
import { CURRENCIES, MAX_UNPINNED_HISTORY, SETTINGS_CONFIG } from '../constants';
import { resolvedColor, stringValue } from '../shared/utils/helpers';

interface Currency { code: string; symbol: string; name: string; }


// ── Sidebar ───────────────────────────────────────────────────────────────────

export interface SidebarProps {
  model: WorkbookModel;
  results: RunResults | null;
  constraints: CustomConstraint[];
  onConstraintsChange: (c: CustomConstraint[]) => void;
  onOpen: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onImportProject: () => void;
  onExportProject: () => void;
  onExportResult: () => void;
  onExportReport: () => void;
  pathwayConfig: PathwayConfig;
  onPathwayConfigChange: (config: PathwayConfig) => void;
  runHistory: RunHistoryEntry[];
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onToggleComparison: (id: string, inComparison: boolean) => void;
  dateFormat: DateFormat;
  onDateFormatChange: (f: DateFormat) => void;
  solverThreads: number;
  solverType: SolverType;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
  currencyCode: string;
  currencySymbol: string;
  onCurrencyChange: (code: string, symbol: string) => void;
  carbonPrice: number;
  onCarbonPriceChange: (v: number) => void;
  enableLoadShedding: boolean;
  onEnableLoadSheddingChange: (v: boolean) => void;
  loadSheddingCost: number;
  onLoadSheddingCostChange: (v: number) => void;
  discountRate: number;
  onDiscountRateChange: (v: number) => void;
  moduleInventory: ModuleHostInventory | null;
  moduleHostLoading: boolean;
  moduleHostError: string | null;
  enabledModuleIds: string[];
  isModuleEnabled: (moduleId: string) => boolean;
  isModuleEnableEligible: (module: ModuleDescriptor) => boolean;
  onToggleModuleEnabled: (moduleId: string, enabled: boolean) => void;
  onInstallModule: (file: File) => void;
  onUninstallModule: (module: ModuleDescriptor) => void;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierMove: (rowIndex: number, direction: -1 | 1) => void;
}

export function Sidebar({
  model,
  results,
  constraints,
  onConstraintsChange,
  onOpen,
  onSave,
  onSaveAs,
  onImportProject,
  onExportProject,
  onExportResult,
  onExportReport,
  pathwayConfig,
  onPathwayConfigChange,
  runHistory,
  onRestoreRun,
  onRenameHistoryEntry,
  onPinHistoryEntry,
  onDeleteHistoryEntry,
  onToggleComparison,
  dateFormat,
  onDateFormatChange,
  solverThreads,
  solverType,
  onSolverThreadsChange,
  onSolverTypeChange,
  currencyCode,
  currencySymbol,
  onCurrencyChange,
  carbonPrice,
  onCarbonPriceChange,
  enableLoadShedding,
  onEnableLoadSheddingChange,
  loadSheddingCost,
  onLoadSheddingCostChange,
  discountRate,
  onDiscountRateChange,
  moduleInventory,
  moduleHostLoading,
  moduleHostError,
  enabledModuleIds,
  isModuleEnabled,
  isModuleEnableEligible,
  onToggleModuleEnabled,
  onInstallModule,
  onUninstallModule,
  onCarrierColorChange,
  onCarrierMove,
}: SidebarProps) {
  const [currencies, setCurrencies] = useState<Currency[]>(CURRENCIES);
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const solverThreadOptions = SETTINGS_CONFIG.solverThreads.options;
  const solverTypes = SETTINGS_CONFIG.solverTypes as Array<{ value: SolverType; label: string }>;
  const loadSheddingOptions = SETTINGS_CONFIG.loadSheddingOptions as Array<{ value: boolean; label: string }>;
  useEffect(() => {
    setCurrencies(CURRENCIES);
  }, []);
  const carriers = Array.from(
    new Set(model.carriers.map((c) => String(c.name ?? '')).filter(Boolean)),
  );
  const carrierRows = model.carriers
    .map((row, index) => ({ row, index, name: stringValue(row.name) }))
    .filter((item) => item.name);

  return (
    <>
      <SidebarGroup title="File" defaultOpen>
        <div className="sg-btn-grid">
          <button className="tb-btn sg-full" onClick={onOpen}>Open</button>
          <button className="tb-btn sg-full" onClick={onSave}>Save</button>
          <button className="tb-btn sg-full" onClick={onSaveAs}>Save As</button>
          <button
            className="tb-btn sg-full"
            onClick={onImportProject}
            title="Import a project workbook (input + solved outputs)"
          >
            Import Project
          </button>
          <button
            className="tb-btn sg-full"
            onClick={onExportProject}
            title={
              results
                ? 'Export the full project: inputs + every solved output sheet'
                : 'Export the project workbook (inputs only — no run yet)'
            }
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
        </div>
      </SidebarGroup>

      <SidebarGroup
        title="Constraints"
        badge={
          constraints.filter((c) => c.enabled).length > 0
            ? <span className="sg-badge">{constraints.filter((c) => c.enabled).length}</span>
            : undefined
        }
      >
        <GlobalConstraintsSection
          constraints={constraints}
          carriers={carriers}
          onChange={onConstraintsChange}
        />
      </SidebarGroup>

      <SidebarGroup
        title="Multi-year planning"
        badge={
          pathwayConfig.enabled
            ? <span className="sg-badge">{pathwayConfig.periods.length} periods</span>
            : undefined
        }
      >
        <div className="sg-setting-row">
          <label className="sg-setting-label">Mode</label>
          <div className="sg-btn-row">
            <button
              className={`tb-btn sg-solver-btn${!pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onPathwayConfigChange({ ...pathwayConfig, enabled: false, planningMode: 'single_period' })}
            >
              Single period
            </button>
            <button
              className={`tb-btn sg-solver-btn${pathwayConfig.enabled ? '' : ' tb-btn--muted'}`}
              onClick={() => onPathwayConfigChange({
                ...pathwayConfig,
                enabled: true,
                planningMode: 'pathway',
                periods: pathwayConfig.periods.length
                  ? pathwayConfig.periods
                  : [
                    { period: 2030, objectiveWeight: 1, yearsWeight: 5 },
                    { period: 2040, objectiveWeight: 1, yearsWeight: 10 },
                  ],
                selectedPeriod: pathwayConfig.selectedPeriod ?? 2030,
              })}
            >
              Pathway
            </button>
          </div>
          <p className="sg-setting-hint">
            Single period solves one snapshot window. Pathway optimises investment + dispatch jointly across all configured periods.
          </p>
        </div>

        {pathwayConfig.enabled && (
          <>
            <div className="sg-setting-divider" />
            <div className="sg-setting-row">
              <label className="sg-setting-label">Investment periods</label>
              <div className="sg-pathway-grid">
                <strong>Period</strong>
                <strong>Obj. weight</strong>
                <strong>Years</strong>
                <span />
                {pathwayConfig.periods.map((row, index) => (
                  <React.Fragment key={`${row.period}-${index}`}>
                    <input
                      type="number"
                      className="sg-pathway-input"
                      value={row.period}
                      onChange={(e) => onPathwayConfigChange({
                        ...pathwayConfig,
                        periods: pathwayConfig.periods.map((item, i) =>
                          i === index ? { ...item, period: Number(e.target.value) || item.period } : item,
                        ),
                      })}
                    />
                    <input
                      type="number"
                      step="0.1"
                      className="sg-pathway-input"
                      value={row.objectiveWeight}
                      onChange={(e) => onPathwayConfigChange({
                        ...pathwayConfig,
                        periods: pathwayConfig.periods.map((item, i) =>
                          i === index ? { ...item, objectiveWeight: Number(e.target.value) || 1 } : item,
                        ),
                      })}
                    />
                    <input
                      type="number"
                      step="0.1"
                      className="sg-pathway-input"
                      value={row.yearsWeight}
                      onChange={(e) => onPathwayConfigChange({
                        ...pathwayConfig,
                        periods: pathwayConfig.periods.map((item, i) =>
                          i === index ? { ...item, yearsWeight: Number(e.target.value) || 1 } : item,
                        ),
                      })}
                    />
                    <button
                      className="tb-btn tb-btn--muted sg-pathway-remove"
                      onClick={() => onPathwayConfigChange({
                        ...pathwayConfig,
                        periods: pathwayConfig.periods.filter((_, i) => i !== index),
                      })}
                    >
                      ×
                    </button>
                  </React.Fragment>
                ))}
              </div>
              <button
                className="tb-btn sg-full"
                style={{ marginTop: 8 }}
                onClick={() => {
                  const last = pathwayConfig.periods[pathwayConfig.periods.length - 1]?.period ?? 2030;
                  onPathwayConfigChange({
                    ...pathwayConfig,
                    periods: [...pathwayConfig.periods, { period: last + 10, objectiveWeight: 1, yearsWeight: 10 }],
                  });
                }}
              >
                Add period
              </button>
            </div>
            <div className="sg-setting-row">
              <label className="sg-setting-label" htmlFor="sg-pathway-mapping">Snapshot mapping</label>
              <select
                id="sg-pathway-mapping"
                className="sg-setting-select"
                value={pathwayConfig.snapshotMappingMode}
                onChange={(e) => onPathwayConfigChange({
                  ...pathwayConfig,
                  snapshotMappingMode: e.target.value as PathwayConfig['snapshotMappingMode'],
                })}
              >
                <option value="explicit_period_column">Use snapshots.period column</option>
                <option value="repeat_all_snapshots">Repeat all snapshots for each period</option>
              </select>
              <p className="sg-setting-hint">
                Pathway runs need either a <code>period</code> column on the snapshots sheet, or repeat-all mapping.
              </p>
            </div>
          </>
        )}
      </SidebarGroup>

      <SidebarGroup
        title="Carbon price"
        badge={carbonPrice > 0 ? <span className="sg-badge">{currencySymbol}{carbonPrice}/t</span> : undefined}
      >
        <div className="sg-setting-row">
          <div className="sg-carbon-row">
            <span className="sg-carbon-sym">{currencySymbol}</span>
            <input
              id="sg-carbon-price"
              type="number"
              className="sg-carbon-input"
              min={settingsRanges.carbonPrice.min}
              max={settingsRanges.carbonPrice.max}
              step={settingsRanges.carbonPrice.step}
              value={carbonPrice}
              onChange={(e) => onCarbonPriceChange(Math.max(settingsRanges.carbonPrice.min, parseFloat(e.target.value) || 0))}
            />
            <span className="sg-carbon-unit">/tCO₂</span>
          </div>
          <p className="sg-setting-hint">
            Added to each generator's marginal cost proportional to CO₂ emissions.
          </p>
        </div>
      </SidebarGroup>

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

      <SidebarGroup title="Settings">
        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="date-format-select">
            Date format
          </label>
          <select
            id="date-format-select"
            className="sg-setting-select"
            value={dateFormat}
            onChange={(e) => onDateFormatChange(e.target.value as DateFormat)}
          >
            <option value="auto">Auto-detect</option>
            <option value="ymd">YYYY-MM-DD (ISO)</option>
            <option value="dmy">DD-MM-YYYY</option>
            <option value="mdy">MM-DD-YYYY</option>
          </select>
          <p className="sg-setting-hint">
            Applies to snapshot and time-series date columns.
          </p>
        </div>

        {currencies.length > 0 && (
          <div className="sg-setting-row">
            <label className="sg-setting-label" htmlFor="currency-select">
              Currency
            </label>
            <select
              id="currency-select"
              className="sg-setting-select"
              value={currencyCode}
              onChange={(e) => {
                const c = currencies.find((x) => x.code === e.target.value);
                if (c) onCurrencyChange(c.code, c.symbol);
              }}
            >
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.symbol} — {c.name} ({c.code})
                </option>
              ))}
            </select>
            <p className="sg-setting-hint">
              Used in all cost and price displays. Edit src/config/currencies.json to add more.
            </p>
          </div>
        )}

        <div className="sg-setting-divider" />

        <p className="sg-setting-section-title">Appearance</p>

        <div className="sg-setting-row">
          <label className="sg-setting-label">Carrier colors</label>
          <div className="sg-color-list">
            {carrierRows.map(({ row, index, name }) => (
              <div key={`carrier-${name}-${index}`} className="sg-color-item">
                <span className="sg-color-name" title={name}>{name}</span>
                <div className="sg-color-actions">
                  <button
                    className="tb-btn tb-btn--muted sg-order-btn"
                    disabled={index === 0}
                    onClick={() => onCarrierMove(index, -1)}
                    title="Move up"
                  >
                    ^
                  </button>
                  <button
                    className="tb-btn tb-btn--muted sg-order-btn"
                    disabled={index === carrierRows.length - 1}
                    onClick={() => onCarrierMove(index, 1)}
                    title="Move down"
                  >
                    v
                  </button>
                </div>
                <input
                  type="color"
                  className="sg-color-input"
                  value={resolvedColor(row.color, row.name)}
                  onChange={(e) => onCarrierColorChange(index, e.target.value)}
                />
              </div>
            ))}
          </div>
          <p className="sg-setting-hint">
            Sets the default color for each carrier across maps, legends, and charts.
          </p>
        </div>

        <div className="sg-setting-divider" />

        <div className="sg-setting-row">
          <label className="sg-setting-label" htmlFor="sg-discount-rate">
            Discount rate
          </label>
          <div className="sg-carbon-row">
            <input
              id="sg-discount-rate"
              type="number"
              className="sg-carbon-input"
              min={settingsRanges.discountRate.min}
              max={settingsRanges.discountRate.max}
              step={settingsRanges.discountRate.step}
              value={discountRate}
              onChange={(e) => onDiscountRateChange(Math.max(settingsRanges.discountRate.min, parseFloat(e.target.value) || 0))}
            />
            <span className="sg-carbon-unit">(fraction)</span>
          </div>
          <p className="sg-setting-hint">
            Used to annualise capital costs for extendable assets. e.g. 0.05 = 5% WACC.
          </p>
        </div>

        <div className="sg-setting-divider" />

        <div className="sg-setting-row">
          <label className="sg-setting-label">Load shedding</label>
          <div className="sg-btn-row">
            {loadSheddingOptions.map(({ value, label }) => (
              <button
                key={String(value)}
                className={`tb-btn sg-solver-btn${enableLoadShedding === value ? '' : ' tb-btn--muted'}`}
                onClick={() => onEnableLoadSheddingChange(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="sg-setting-hint">
            When off, supply shortfalls surface as solver infeasibility instead of being silently absorbed.
          </p>
          {enableLoadShedding && (
            <>
              <label className="sg-setting-label" htmlFor="sg-loadshed-cost" style={{ marginTop: 10 }}>
                Value of lost load
              </label>
              <div className="sg-carbon-row">
                <span className="sg-carbon-sym">{currencySymbol}</span>
                <input
                  id="sg-loadshed-cost"
                  type="number"
                  className="sg-carbon-input"
                  min={settingsRanges.loadSheddingCost.min}
                  step={settingsRanges.loadSheddingCost.step}
                  value={loadSheddingCost}
                  onChange={(e) => onLoadSheddingCostChange(Math.max(settingsRanges.loadSheddingCost.min, parseFloat(e.target.value) || 0))}
                />
                <span className="sg-carbon-unit">/MWh</span>
              </div>
              <p className="sg-setting-hint">
                Penalty applied to each MWh of unserved demand. Set well above the most expensive real generator.
              </p>
            </>
          )}
        </div>

        <div className="sg-setting-divider" />

        <p className="sg-setting-section-title">Solver settings</p>

        <div className="sg-setting-row">
          <label className="sg-setting-label">Threads</label>
          <div className="sg-btn-row">
            {solverThreadOptions.map((n) => (
              <button
                key={n}
                className={`tb-btn sg-solver-btn${solverThreads === n ? '' : ' tb-btn--muted'}`}
                onClick={() => onSolverThreadsChange(n)}
              >
                {n === 0 ? 'auto' : String(n)}
              </button>
            ))}
          </div>
          <p className="sg-setting-hint">
            auto = HiGHS uses all available cores.
          </p>
        </div>

        <div className="sg-setting-row">
          <label className="sg-setting-label">Algorithm</label>
          <div className="sg-btn-row">
            {solverTypes.map(({ value, label }) => (
              <button
                key={value}
                className={`tb-btn sg-solver-btn${solverType === value ? '' : ' tb-btn--muted'}`}
                onClick={() => onSolverTypeChange(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="sg-setting-hint">
            IPM (interior point) is often faster for large LP models. Use Simplex for MIP / unit commitment runs.
          </p>
        </div>
      </SidebarGroup>

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
