import React from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus, AnalyticsSubTab, ChartSectionConfig, GridRow, PathwayConfig, RunResults, TimeSeriesRow, TimeSeriesSeries, WorkbookModel,
} from 'lib/types';
import { AnalyticsDashboard } from '../../views/AnalyticsView.features/Dashboard/AnalyticsDashboard';
import type { AssetKind } from 'lib/api/resultsDerived';
import { buildResultPreset } from 'lib/dashboard/resultPreset';
import { PRESETS } from 'lib/dashboard/presets';

interface Props {
  results: RunResults;
  filename: string;
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
  analyticsFocus: AnalyticsFocus;
  setAnalyticsFocus: (focus: AnalyticsFocus) => void;
  chartSections: ChartSectionConfig[];
  setChartSections: React.Dispatch<React.SetStateAction<ChartSectionConfig[]>>;
  dispatchRows: TimeSeriesRow[];
  dispatchSeries: TimeSeriesSeries[];
  storageRows: TimeSeriesRow[];
  subTab: AnalyticsSubTab;
  currencySymbol: string;
  pathwayConfig?: PathwayConfig;
  onSelectedPeriodChange?: (period: number) => void;
  /** Lazily hydrate only the output-series sheets the dashboard's per-asset
   *  charts need, each at the max snapshot count requested (light "View"
   *  bundles strip them). */
  onNeedSeries?: (windows: Record<string, number>) => void;
  onNeedAssets?: (kinds: Partial<Record<AssetKind, number>>) => void;
  /** Loading / error state of the selected investment period's server payload. */
  periodStatus?: { period: number | null; loading: boolean; error: string | null };
  /** Stored-run name backing these results (for parametrised statistics queries); null when unsaved. */
  runName?: string | null;
}

function EmptyAnalytics() {
  return (
    <div className="analytics-empty">
      <h3>No run loaded</h3>
      <p>
        Results, scenario comparisons, and per-asset drill-downs appear here after a solve completes. Run the case from the top-bar, or open a stored run from History.
      </p>
    </div>
  );
}

export { EmptyAnalytics };

const ANALYTICS_STORAGE_KEY = 'ragnarok:dashboard:analytics';

export function AnalyticsPane({
  results, model, bounds, busIndex,
  analyticsFocus, setAnalyticsFocus,
  dispatchRows, dispatchSeries,
  storageRows,
  subTab,
  currencySymbol,
  pathwayConfig,
  onSelectedPeriodChange,
  onNeedSeries,
  onNeedAssets,
  periodStatus,
  runName,
}: Props) {
  return (
    <div className="pane analytics-pane">
      {results.pathway?.enabled && results.pathway.periods.length > 0 && (() => {
        // The displayed result owns its period selection (App derives it from the
        // result's own periods) — the editor's pathway config may describe a
        // different model than the one being viewed.
        const active = results.pathway.selectedPeriod ?? results.pathway.periods[0];
        return (
          <section className="chart-card" style={{ marginBottom: 16 }}>
            <div className="chart-card-header">
              <div>
                <h3>Pathway period</h3>
                <p>
                  Every figure below is read from the server for the selected investment period
                  (inactive assets masked, costs weighted by the period's objective weight).
                </p>
                {periodStatus?.loading && <p aria-busy="true">Loading {periodStatus.period}…</p>}
                {periodStatus?.error && (
                  <p role="alert" className="sg-error-text">
                    Could not load {periodStatus.period}: {periodStatus.error}. Showing the whole horizon.
                  </p>
                )}
              </div>
              <div className="period-pill-row">
                {results.pathway.periods.map((period) => (
                  <button
                    key={period}
                    className={`tb-btn period-pill${period === active ? '' : ' tb-btn--muted'}`}
                    onClick={() => onSelectedPeriodChange?.(period)}
                  >
                    {period}
                  </button>
                ))}
              </div>
            </div>
          </section>
        );
      })()}

      {/* Both Result and Analytics now use the same dashboard engine.
       * They differ only in storage key (independent localStorage) and
       * the initial layout (curated for Result, the first preset for
       * Analytics so Reset restores a real dashboard, not a blank pane). */}
      {(subTab === 'Result' || subTab === 'Analytics') && (
        <AnalyticsDashboard
          key={subTab /* force remount when sub-tab changes so the hook re-reads its storage */}
          results={results}
          model={model}
          bounds={bounds}
          busIndex={busIndex}
          dispatchRows={dispatchRows}
          dispatchSeries={dispatchSeries}
          storageRows={storageRows}
          currencySymbol={currencySymbol}
          analyticsFocus={analyticsFocus}
          onFocusChange={setAnalyticsFocus}
          /* Result NEVER persists its layout — it always rebuilds from the
           * curated preset so code updates show up immediately. Analytics
           * keeps localStorage persistence for user-built dashboards. */
          storageKey={subTab === 'Result' ? null : ANALYTICS_STORAGE_KEY}
          initialLayout={subTab === 'Result' ? buildResultPreset(results) : PRESETS[0].build()}
          showPresets={subTab === 'Analytics'}
          onNeedSeries={onNeedSeries}
          onNeedAssets={onNeedAssets}
          runName={runName}
        />
      )}
    </div>
  );
}
