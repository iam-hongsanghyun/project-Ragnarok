/**
 * Settings — full-width overlay for one-time project configuration.
 *
 * Three tabs:
 *   Appearance · Project defaults · Solver
 *
 * Previously these lived in a single tall sidebar group. Splitting them
 * out keeps the sidebar focused on per-run knobs.
 */
import React, { useEffect, useState } from 'react';
import { WorkbookModel } from '../../shared/types';
import { DateFormat, SolverType } from '../settings/useSettings';
import { CURRENCIES, SETTINGS_CONFIG } from '../../constants';
import { resolvedColor, stringValue } from '../../shared/utils/helpers';

interface Currency { code: string; symbol: string; name: string; }

type Tab = 'appearance' | 'project' | 'solver';

interface Props {
  model: WorkbookModel;
  dateFormat: DateFormat;
  onDateFormatChange: (f: DateFormat) => void;
  currencyCode: string;
  currencySymbol: string;
  onCurrencyChange: (code: string, symbol: string) => void;
  discountRate: number;
  onDiscountRateChange: (v: number) => void;
  enableLoadShedding: boolean;
  onEnableLoadSheddingChange: (v: boolean) => void;
  loadSheddingCost: number;
  onLoadSheddingCostChange: (v: number) => void;
  solverThreads: number;
  solverType: SolverType;
  onSolverThreadsChange: (v: number) => void;
  onSolverTypeChange: (v: SolverType) => void;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierMove: (rowIndex: number, direction: -1 | 1) => void;
  onClose: () => void;
}

export function SettingsWorkspaceView(props: Props) {
  const [tab, setTab] = useState<Tab>('appearance');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') props.onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [props]);

  return (
    <div className="constraints-workspace">
      <div className="constraints-workspace-header">
        <div className="constraints-workspace-title">
          <h2>Settings</h2>
          <p>Project-level configuration. Most users set these once per project; they ride along in Save / Export Project.</p>
        </div>
        <button className="tb-btn tb-btn--muted" onClick={props.onClose} title="Close (Esc)">Close</button>
      </div>

      <nav className="subnav constraints-workspace-tabs">
        <button className={`subnav-btn${tab === 'appearance' ? ' subnav-btn--active' : ''}`} onClick={() => setTab('appearance')}>Appearance</button>
        <button className={`subnav-btn${tab === 'project' ? ' subnav-btn--active' : ''}`} onClick={() => setTab('project')}>Project defaults</button>
        <button className={`subnav-btn${tab === 'solver' ? ' subnav-btn--active' : ''}`} onClick={() => setTab('solver')}>Solver</button>
      </nav>

      <div className="constraints-workspace-body">
        {tab === 'appearance' && <AppearanceTab {...props} />}
        {tab === 'project'    && <ProjectDefaultsTab {...props} />}
        {tab === 'solver'     && <SolverTab {...props} />}
      </div>
    </div>
  );
}

// ── Appearance ───────────────────────────────────────────────────────────────

function AppearanceTab({ model, onCarrierColorChange, onCarrierMove }: Props) {
  const carrierRows = model.carriers
    .map((row, index) => ({ row, index, name: stringValue(row.name) }))
    .filter((item) => item.name);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carrier colors</h3>
        <p>Default colors for each carrier across maps, legends, and charts.</p>
      </header>
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
    </section>
  );
}

// ── Project defaults ─────────────────────────────────────────────────────────

function ProjectDefaultsTab(props: Props) {
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const loadSheddingOptions = SETTINGS_CONFIG.loadSheddingOptions as Array<{ value: boolean; label: string }>;
  const currencies: Currency[] = CURRENCIES;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Project defaults</h3>
        <p>Date parsing, currency, capital cost annuitisation, and load-shedding backstop.</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-date-format">Date format</label>
        <select
          id="set-date-format"
          className="sg-setting-select"
          value={props.dateFormat}
          onChange={(e) => props.onDateFormatChange(e.target.value as DateFormat)}
        >
          <option value="auto">Auto-detect</option>
          <option value="ymd">YYYY-MM-DD (ISO)</option>
          <option value="dmy">DD-MM-YYYY</option>
          <option value="mdy">MM-DD-YYYY</option>
        </select>
        <p className="sg-setting-hint">
          Declares the format of input data so the parser can interpret ambiguous strings. Display is always canonical ISO.
        </p>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-currency">Currency</label>
        <select
          id="set-currency"
          className="sg-setting-select"
          value={props.currencyCode}
          onChange={(e) => {
            const c = currencies.find((x) => x.code === e.target.value);
            if (c) props.onCurrencyChange(c.code, c.symbol);
          }}
        >
          {currencies.map((c) => (
            <option key={c.code} value={c.code}>{c.symbol} — {c.name} ({c.code})</option>
          ))}
        </select>
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-discount-rate">Discount rate</label>
        <div className="sg-carbon-row">
          <input
            id="set-discount-rate"
            type="number"
            className="sg-carbon-input"
            min={settingsRanges.discountRate.min}
            max={settingsRanges.discountRate.max}
            step={settingsRanges.discountRate.step}
            value={props.discountRate}
            onChange={(e) => props.onDiscountRateChange(Math.max(settingsRanges.discountRate.min, parseFloat(e.target.value) || 0))}
          />
          <span className="sg-carbon-unit">(fraction)</span>
        </div>
        <p className="sg-setting-hint">
          Used to annualise capital costs for extendable assets. 0.05 = 5% WACC.
        </p>
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label">Load shedding</label>
        <div className="sg-btn-row">
          {loadSheddingOptions.map(({ value, label }) => (
            <button
              key={String(value)}
              className={`tb-btn sg-solver-btn${props.enableLoadShedding === value ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onEnableLoadSheddingChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">
          When off, supply shortfalls surface as solver infeasibility instead of being silently absorbed.
        </p>
        {props.enableLoadShedding && (
          <>
            <label className="sg-setting-label" htmlFor="set-voll" style={{ marginTop: 10 }}>
              Value of lost load
            </label>
            <div className="sg-carbon-row">
              <span className="sg-carbon-sym">{props.currencySymbol}</span>
              <input
                id="set-voll"
                type="number"
                className="sg-carbon-input"
                min={settingsRanges.loadSheddingCost.min}
                step={settingsRanges.loadSheddingCost.step}
                value={props.loadSheddingCost}
                onChange={(e) => props.onLoadSheddingCostChange(Math.max(settingsRanges.loadSheddingCost.min, parseFloat(e.target.value) || 0))}
              />
              <span className="sg-carbon-unit">/MWh</span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

// ── Solver ───────────────────────────────────────────────────────────────────

function SolverTab(props: Props) {
  const solverThreadOptions = SETTINGS_CONFIG.solverThreads.options;
  const solverTypes = SETTINGS_CONFIG.solverTypes as Array<{ value: SolverType; label: string }>;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Solver settings</h3>
        <p>HiGHS configuration for the optimisation step.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Threads</label>
        <div className="sg-btn-row">
          {solverThreadOptions.map((n) => (
            <button
              key={n}
              className={`tb-btn sg-solver-btn${props.solverThreads === n ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSolverThreadsChange(n)}
            >
              {n === 0 ? 'auto' : String(n)}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">auto = HiGHS uses all available cores.</p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Algorithm</label>
        <div className="sg-btn-row">
          {solverTypes.map(({ value, label }) => (
            <button
              key={value}
              className={`tb-btn sg-solver-btn${props.solverType === value ? '' : ' tb-btn--muted'}`}
              onClick={() => props.onSolverTypeChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">
          IPM (interior point) is often faster for large LP models. Use Simplex for MIP / unit-commitment runs.
        </p>
      </div>
    </section>
  );
}
