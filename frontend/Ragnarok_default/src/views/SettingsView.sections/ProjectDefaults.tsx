/**
 * Project defaults section — date format, currency, discount rate, load shedding.
 */
import React, { useState } from 'react';
import { fillDiscountRate } from 'lib/api/forgeBuild';
import { DateFormat } from '../../features/settings/useSettings';
import { CURRENCIES, SETTINGS_CONFIG } from 'lib/constants';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';
import { SearchableSelect } from '../../shared/components/SearchableSelect';

interface Currency { code: string; symbol: string; name: string; }

export interface ProjectDefaultsSectionProps {
  dateFormat: DateFormat;
  onDateFormatChange: (f: DateFormat) => void;
  currencyCode: string;
  currencySymbol: string;
  onCurrencyChange: (code: string, symbol: string) => void;
  discountRate: number;
  onDiscountRateChange: (v: number) => void;
  onWorkbookChanged?: () => void;
  enableLoadShedding: boolean;
  onEnableLoadSheddingChange: (v: boolean) => void;
  loadSheddingCost: number;
  onLoadSheddingCostChange: (v: number) => void;
}

export function ProjectDefaultsSection(props: ProjectDefaultsSectionProps) {
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const loadSheddingOptions = SETTINGS_CONFIG.loadSheddingOptions as Array<{ value: boolean; label: string }>;
  const currencies: Currency[] = CURRENCIES;
  // Forge action: write the rate into the workbook's discount_rate column (PyPSA annuitises
  // overnight_cost with the ROW's rate; nothing is filled in at run time).
  const [fillNote, setFillNote] = useState('');
  const [filling, setFilling] = useState(false);
  const runFill = async (overwrite: boolean) => {
    setFilling(true);
    try {
      const out = await fillDiscountRate(props.discountRate, { overwrite, apply: true });
      setFillNote(
        out.filled + out.overwritten === 0
          ? `No row needed it (${out.skipped} already carry a discount_rate).`
          : `Wrote discount_rate ${props.discountRate} into ${out.filled + out.overwritten} row(s)`
            + (out.skipped ? `; ${out.skipped} already had one.` : '.'),
      );
      props.onWorkbookChanged?.();
    } catch (e) {
      setFillNote(e instanceof Error ? e.message : 'Could not fill the discount rate.');
    } finally {
      setFilling(false);
    }
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Project defaults</h3>
        <p>Date parsing, currency, the discount rate written into the workbook, and load-shedding backstop.</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-date-format">Date format</label>
        <SearchableSelect
          className="sg-setting-select"
          value={props.dateFormat}
          options={[
            { value: 'auto', label: 'Auto-detect' },
            { value: 'ymd', label: 'YYYY-MM-DD (ISO)' },
            { value: 'dmy', label: 'DD-MM-YYYY' },
            { value: 'mdy', label: 'MM-DD-YYYY' },
          ]}
          onChange={(v) => props.onDateFormatChange(v as DateFormat)}
        />
        <p className="sg-setting-hint">
          Declares the format of input data so the parser can interpret ambiguous strings. Display is always canonical ISO.
        </p>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-currency">Currency</label>
        <SearchableSelect
          className="sg-setting-select"
          value={props.currencyCode}
          options={currencies.map((c) => ({ value: c.code, label: `${c.symbol} — ${c.name} (${c.code})` }))}
          onChange={(v) => {
            const c = currencies.find((x) => x.code === v);
            if (c) props.onCurrencyChange(c.code, c.symbol);
          }}
        />
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="set-discount-rate">Discount rate</label>
        <div className="sg-carbon-row">
          <NumberDraftInput
            id="set-discount-rate"
            className="sg-carbon-input"
            min={settingsRanges.discountRate.min}
            step={settingsRanges.discountRate.step}
            value={props.discountRate}
            onCommit={props.onDiscountRateChange}
          />
          <span className="sg-carbon-unit">(fraction)</span>
        </div>
        <p className="sg-setting-hint">
          The project discount rate (0.05 = 5% WACC). It does not change any cost at run time: PyPSA annuitises each
          row's <code>overnight_cost</code> with that row's own <code>discount_rate</code> and <code>lifetime</code>.
          Use the Forge action below to write this rate into the workbook column; a row with an overnight cost and no
          rate is refused at run time.
        </p>
        <div className="sg-btn-row">
          <button className="tb-btn sg-solver-btn" disabled={filling} onClick={() => { void runFill(false); }}>
            Fill discount_rate in rows that lack it
          </button>
          <button className="tb-btn sg-solver-btn tb-btn--muted" disabled={filling} onClick={() => { void runFill(true); }}>
            Overwrite every row
          </button>
        </div>
        {fillNote && <p className="sg-setting-hint">{fillNote}</p>}
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
              <NumberDraftInput
                id="set-voll"
                className="sg-carbon-input"
                min={settingsRanges.loadSheddingCost.min}
                step={settingsRanges.loadSheddingCost.step}
                value={props.loadSheddingCost}
                onCommit={props.onLoadSheddingCostChange}
              />
              <span className="sg-carbon-unit">/MWh</span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
