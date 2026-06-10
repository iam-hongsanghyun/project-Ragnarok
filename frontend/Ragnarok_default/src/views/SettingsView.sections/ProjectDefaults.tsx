/**
 * Project defaults section — date format, currency, discount rate, load shedding.
 */
import React from 'react';
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
  enableLoadShedding: boolean;
  onEnableLoadSheddingChange: (v: boolean) => void;
  loadSheddingCost: number;
  onLoadSheddingCostChange: (v: number) => void;
}

export function ProjectDefaultsSection(props: ProjectDefaultsSectionProps) {
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
            max={settingsRanges.discountRate.max}
            step={settingsRanges.discountRate.step}
            value={props.discountRate}
            onCommit={props.onDiscountRateChange}
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
