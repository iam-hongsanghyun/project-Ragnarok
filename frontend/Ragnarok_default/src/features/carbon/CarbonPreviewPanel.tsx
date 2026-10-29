/**
 * Carbon price preview (Settings -> Carbon price).
 *
 * Lists the carbon library stored in the model (`GET /api/scenarios/carbon-schedules`) and previews what a price would
 * add to each generator's objective (`POST /api/carbon-price/preview`: price x co2_emissions / efficiency, per MWh of
 * output). The source is the run's current setting (scalar or schedule) or any stored schedule. The server computes the
 * adders; the browser lists them.
 */
import React, { useState } from 'react';
import type { CarbonPriceScheduleEntry } from 'lib/types';
import { DEFAULT_SESSION_ID } from 'lib/api/session';
import {
  getServerCarbonSchedules,
  previewCarbonPrice,
  type CarbonPreview,
  type ServerCarbonSchedule,
} from 'lib/api/policyModules';
import { useAsync } from '../../shared/hooks/useAsync';

export interface CarbonPreviewPanelProps {
  carbonPrice: number;
  /** The run's current schedule (empty = the scalar price applies). */
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  currencySymbol: string;
  /** Push the browser's working model to the session (the server reads the session). */
  onSessionSync: () => Promise<void>;
}

const CURRENT = '__current__';
const money = (n: number): string => (Math.round(n * 100) / 100).toLocaleString('en-US', { minimumFractionDigits: 2 });

export function CarbonPreviewPanel({ carbonPrice, carbonPriceSchedule, currencySymbol, onSessionSync }: CarbonPreviewPanelProps) {
  // Re-read the stored library after each sync: edits made in this browser reach the session only then.
  const [syncs, setSyncs] = useState(0);
  const library = useAsync<ServerCarbonSchedule[]>(`carbon-library-${syncs}`, () => getServerCarbonSchedules(DEFAULT_SESSION_ID));
  const [source, setSource] = useState<string>(CURRENT);
  const [preview, setPreview] = useState<CarbonPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const schedules = library.data ?? [];
  const stored = schedules.find((s) => s.id === source);
  const schedule: CarbonPriceScheduleEntry[] = stored ? stored.schedule : carbonPriceSchedule;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSessionSync();
      setSyncs((n) => n + 1);
      setPreview(await previewCarbonPrice(carbonPrice, schedule));
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sg-setting-row" data-tour="carbon-preview">
      <label className="sg-setting-label" htmlFor="rs-carbon-preview-source">Preview</label>
      <p className="sg-setting-hint" style={{ marginTop: 0 }}>
        What a carbon price adds to each generator's objective, computed by the server from the model's carriers and efficiencies.
        Pick the run's current setting or a schedule stored in the model.
      </p>
      <div className="sg-btn-row">
        <select
          id="rs-carbon-preview-source" value={source}
          onChange={(e) => { setSource(e.target.value); setPreview(null); }}
        >
          <option value={CURRENT}>
            {carbonPriceSchedule.length > 0 ? `Run setting: schedule (${carbonPriceSchedule.length} points)` : `Run setting: scalar ${currencySymbol}${carbonPrice}/tCO2`}
          </option>
          {schedules.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button type="button" className="tb-btn" disabled={busy} onClick={() => void run()}>Preview effect</button>
      </div>
      {library.error && <p className="sg-setting-hint" role="alert">Stored schedules unavailable: {library.error}</p>}
      {library.data && schedules.length === 0 && (
        <p className="sg-setting-hint">The model stores no carbon schedules (RAGNAROK_CarbonSchedules is empty).</p>
      )}
      {stored && (
        <p className="sg-setting-hint">
          {stored.name}: {stored.schedule.length === 0 ? 'no points' : stored.schedule.map((p) => `${p.year} ${currencySymbol}${p.price}/tCO2`).join(', ')}
        </p>
      )}
      {error && <p className="sg-setting-hint" role="alert">{error}</p>}
      {preview && (
        <>
          <p className="sg-setting-hint" role="status">
            {preview.active
              ? `Price ranges ${currencySymbol}${money(preview.priceMin)} to ${currencySymbol}${money(preview.priceMax)} per tCO2 over the window.`
              : 'No carbon price is active for this source (a zero scalar and no schedule).'}
            {' '}{preview.basis}.
          </p>
          {preview.generators.length > 0 && (
            <table className="sg-table">
              <thead>
                <tr><th>Generator</th><th>Carrier</th><th>tCO2 per MWh fuel</th><th>Adder mean ({currencySymbol}/MWh)</th><th>Adder max ({currencySymbol}/MWh)</th></tr>
              </thead>
              <tbody>
                {preview.generators.map((g) => (
                  <tr key={g.generator}>
                    <td>{g.generator}</td><td>{g.carrier}</td><td>{g.co2PerMWhFuel}</td><td>{money(g.adderMean)}</td><td>{money(g.adderMax)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {preview.active && preview.generators.length === 0 && <p className="sg-setting-hint">No generator has a co2_emissions factor, so the price changes nothing.</p>}
        </>
      )}
    </div>
  );
}
