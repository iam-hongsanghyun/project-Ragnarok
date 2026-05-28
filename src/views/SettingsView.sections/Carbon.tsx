/**
 * Carbon price section — scalar price + year-indexed schedule.
 */
import React from 'react';
import { CarbonPriceScheduleEntry } from '../../shared/types';
import { SETTINGS_CONFIG } from '../../constants';

export interface CarbonSectionProps {
  carbonPrice: number;
  onCarbonPriceChange: (v: number) => void;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  onCarbonPriceScheduleChange: (next: CarbonPriceScheduleEntry[]) => void;
  currencySymbol: string;
}

export function CarbonSection(props: CarbonSectionProps) {
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const schedule = props.carbonPriceSchedule;
  const scheduleActive = schedule.length > 0;

  const setSchedule = (next: CarbonPriceScheduleEntry[]) => {
    const sorted = [...next].sort((a, b) => a.year - b.year);
    props.onCarbonPriceScheduleChange(sorted);
  };

  const addRow = () => {
    const lastYear = schedule.length > 0 ? schedule[schedule.length - 1].year : new Date().getFullYear();
    const lastPrice = schedule.length > 0 ? schedule[schedule.length - 1].price : Math.max(props.carbonPrice, 30);
    setSchedule([...schedule, { year: lastYear + 5, price: lastPrice * 1.5 }]);
  };

  const updateRow = (i: number, patch: Partial<CarbonPriceScheduleEntry>) =>
    setSchedule(schedule.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const removeRow = (i: number) => setSchedule(schedule.filter((_, idx) => idx !== i));

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carbon price</h3>
        <p>Added to each generator's marginal cost proportional to its carrier's <code>co2_emissions</code> factor. Use a schedule to ramp the price across years (pathway runs apply the price for each investment period; single-period runs use the snapshot timestamp's year).</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="rs-carbon-price">
          Scalar price <span style={{ color: 'var(--muted)', fontSize: '0.78rem', marginLeft: 6 }}>(used when the schedule below is empty)</span>
        </label>
        <div className="sg-carbon-row">
          <span className="sg-carbon-sym">{props.currencySymbol}</span>
          <input
            id="rs-carbon-price"
            type="number"
            className="sg-carbon-input"
            min={settingsRanges.carbonPrice.min}
            max={settingsRanges.carbonPrice.max}
            step={settingsRanges.carbonPrice.step}
            value={props.carbonPrice}
            disabled={scheduleActive}
            onChange={(e) => props.onCarbonPriceChange(Math.max(settingsRanges.carbonPrice.min, parseFloat(e.target.value) || 0))}
          />
          <span className="sg-carbon-unit">/tCO₂</span>
        </div>
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label">Schedule</label>
        {schedule.length === 0 ? (
          <p className="sg-setting-hint" style={{ marginTop: 0 }}>
            No schedule rows — the scalar above applies to every snapshot. Add a row to switch to a year-indexed schedule.
          </p>
        ) : (
          <table className="constraints-table" style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th>Year</th>
                <th>Price ({props.currencySymbol}/tCO₂)</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {schedule.map((row, i) => (
                <tr key={`carbon-row-${i}`}>
                  <td>
                    <input
                      type="number"
                      className="constraints-cell-input constraints-cell-input--num"
                      value={row.year}
                      step={1}
                      onChange={(e) => updateRow(i, { year: parseInt(e.target.value, 10) || row.year })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="constraints-cell-input constraints-cell-input--num"
                      value={row.price}
                      step={settingsRanges.carbonPrice.step}
                      min={0}
                      onChange={(e) => updateRow(i, { price: parseFloat(e.target.value) || 0 })}
                    />
                  </td>
                  <td>
                    <button className="gcc-del" onClick={() => removeRow(i)} title="Delete row">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="tb-btn" onClick={addRow}>+ Add schedule row</button>
        {scheduleActive && (
          <p className="sg-setting-hint">
            Snapshot resolution: each snapshot uses the most-recent schedule entry whose year is ≤ the snapshot's year. Pathway runs use the investment period year; single-period runs use the snapshot timestamp year.
          </p>
        )}
      </div>
    </section>
  );
}
