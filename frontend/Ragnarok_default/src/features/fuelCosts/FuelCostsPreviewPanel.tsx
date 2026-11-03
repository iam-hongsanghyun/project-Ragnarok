/**
 * Fuel costs preview (Settings -> Carbon price, under the carbon preview).
 *
 * Fuel prices become each unit's marginal cost at run time: fuel price / efficiency + variable O&M per MWh of electricity
 * (`POST /api/fuel-costs/preview`). Carbon is not part of it - the carbon-pricing module adds it to the objective - but the
 * breakdown shows it next to fuel and VOM for the run's current carbon setting. The server computes; the browser lists.
 */
import React, { useState } from 'react';
import type { CarbonPriceScheduleEntry } from 'lib/types';
import { previewFuelCosts, type FuelCostsPreview } from 'lib/api/fuelCosts';

export interface FuelCostsPreviewPanelProps {
  carbonPrice: number;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  currencySymbol: string;
  /** Push the browser's working model to the session (the server reads the session). */
  onSessionSync: () => Promise<void>;
}

const money = (n: number | null | undefined): string =>
  n == null ? '-' : (Math.round(n * 100) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 });

export function FuelCostsPreviewPanel({ carbonPrice, carbonPriceSchedule, currencySymbol, onSessionSync }: FuelCostsPreviewPanelProps) {
  const [preview, setPreview] = useState<FuelCostsPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      setPreview(await previewFuelCosts(carbonPrice, carbonPriceSchedule));
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sg-setting-row" data-tour="fuel-costs-preview">
      <span className="sg-setting-label">Fuel costs</span>
      <p className="sg-setting-hint" style={{ marginTop: 0 }}>
        At run time each thermal unit's marginal cost is fuel price / efficiency + variable O&amp;M. Fuel prices: the model sheet
        RAGNAROK_FuelPrices (a column per fuel carrier, {currencySymbol}/MWh thermal, blank = no price) or the carriers column
        fuel_cost_thermal as a constant. VOM: the sheet RAGNAROK_VariableOM (component, name or carrier, vom in {currencySymbol}/MWh electric).
        The system marginal price is a result of the run, not an input.
      </p>
      <div className="sg-btn-row">
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void run()}>Preview fuel costs</button>
      </div>
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {preview && (
        <>
          {!preview.active && <p className="sg-setting-hint" role="status">{preview.notes[0] ?? 'No unit is priced by the module.'}</p>}
          {preview.active && (
            <p className="sg-setting-hint" role="status">
              {preview.carbonPriceActive ? 'Carbon shown for the run\'s current carbon setting (it is an objective term, not in marginal cost). ' : 'No carbon price active. '}
              {preview.basis}.
            </p>
          )}
          {preview.units.length > 0 && (
            <table className="sg-table">
              <thead>
                <tr>
                  <th>Unit</th><th>Role</th><th>Fuel</th><th>Efficiency</th>
                  <th>Fuel ({currencySymbol}/MWh)</th><th>VOM</th><th>Carbon</th><th>Total</th>
                  <th>Marginal cost sent (mean)</th><th>Workbook (mean)</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {preview.units.map((u) => (
                  <tr key={`${u.component}-${u.name}`}>
                    <td>{u.name} <span className="sg-setting-hint">{u.component}</span></td>
                    <td>{u.role}</td><td>{u.fuelCarrier ?? '-'}</td><td>{u.efficiencyMean ?? '-'}</td>
                    <td>{money(u.timeMean.fuel)}</td><td>{money(u.timeMean.vom)}</td><td>{money(u.timeMean.carbon)}</td><td>{money(u.timeMean.total)}</td>
                    <td>{money(u.marginalCost.newMean)}</td><td>{money(u.marginalCost.oldMean)}</td>
                    <td title={u.reason}>{u.status}{u.unpricedSnapshots > 0 ? ` (${u.unpricedSnapshots} unpriced)` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {preview.units.length > 0 && (
            <p className="sg-setting-hint">
              Per MWh of electricity (MWh thermal for a fuel supplier), time mean over the priced snapshots. A Link carries VOM x efficiency per MWh of
              input; its fuel is priced on the supply generator on its input bus.
            </p>
          )}
          {preview.notes.length > 0 && preview.active && (
            <ul className="sg-setting-hint">{preview.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          )}
        </>
      )}
    </div>
  );
}
