/**
 * Physical Risk — Map sub-tab.
 *
 * A leaflet map of the portfolio's assets — ported from climaterisk's
 * `MapView.tsx` (facility markers) + `components/ResultsMap.tsx` (risk-colored
 * sizing from a completed run), built onto Ragnarok's own map conventions via
 * `features/physicalRisk/AssetRiskMap`, not climaterisk's maplibre-gl map.
 *
 * When the latest physical run (`run.result.perils`) is done, markers are
 * scaled/colored by each asset's total EAI (summed across perils, or a single
 * peril via the filter dropdown below); otherwise markers are uniform.
 */
import React, { useMemo, useState } from 'react';
import { AssetRiskMap } from '../../features/physicalRisk/AssetRiskMap';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';
import { totalEaiByAsset } from 'lib/physicalRisk/mapAdaptation';

export function MapSection({ portfolio, run }: PhysicalRiskSectionProps) {
  // `run` is always a physical run here — the Results tab (the only submitter of
  // `props.run`) never sends a `kind` override, so the backend defaults to 'physical'.
  const perils = useMemo(
    () => (run?.status === 'done' && run.result ? run.result.perils : []),
    [run],
  );
  const hasResult = perils.length > 0;
  const currency = run?.result?.currency || portfolio?.assets[0]?.currency || 'USD';

  const [perilFilter, setPerilFilter] = useState<string>('');

  const eaiByAsset = useMemo(() => (hasResult ? totalEaiByAsset(perils) : null), [hasResult, perils]);

  if (!portfolio || portfolio.assets.length === 0) {
    return (
      <div className="pane">
        <div className="pane-header">
          <div>
            <h2>Map</h2>
            <p className="chart-card p">Georeferenced view of the portfolio's assets.</p>
          </div>
        </div>
        <div className="analytics-empty">
          <h3>No assets loaded</h3>
          <p>Load the fleet on the Assets tab first, then come back here to see it on the map.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Map</h2>
          <p className="chart-card p">
            {hasResult
              ? "Markers are sized and colored by each asset's expected annual impact (EAI)."
              : 'Run a physical-risk analysis on the Results tab to size markers by risk.'}
          </p>
        </div>
        {hasResult && perils.length > 1 && (
          <div className="sg-setting-row" style={{ margin: 0 }}>
            <label className="sg-setting-label">Peril</label>
            <select value={perilFilter} onChange={(e) => setPerilFilter(e.target.value)}>
              <option value="">All perils (summed)</option>
              {perils.map((p) => (
                <option key={p.peril} value={p.peril}>{p.peril.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      <AssetRiskMap
        assets={portfolio.assets}
        eaiByAsset={eaiByAsset}
        perilFilter={perilFilter || null}
        currency={currency}
      />
    </div>
  );
}
