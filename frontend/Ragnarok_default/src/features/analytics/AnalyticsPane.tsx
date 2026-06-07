import React from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus, AnalyticsSubTab, ChartSectionConfig, GridRow, PathwayConfig, RunResults, TimeSeriesRow, TimeSeriesSeries, WorkbookModel,
} from 'lib/types';
import { AnalyticsDashboard } from '../../views/AnalyticsView.features/Dashboard/AnalyticsDashboard';
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
  systemLoadRows: TimeSeriesRow[];
  systemPriceRows: TimeSeriesRow[];
  storageRows: TimeSeriesRow[];
  subTab: AnalyticsSubTab;
  currencySymbol: string;
  pathwayConfig?: PathwayConfig;
  onSelectedPeriodChange?: (period: number) => void;
}

function EmptyAnalytics() {
  return (
    <div className="analytics-empty">
      <h3>Analytics is empty until you run the model</h3>
      <p>
        Open the run dialog, set the number of snapshots and snapshot weight, then execute the case. The dashboard will populate after a successful backend run.
      </p>
    </div>
  );
}

export { EmptyAnalytics };

const ANALYTICS_STORAGE_KEY = 'ragnarok:dashboard:analytics:v1';
const RESULT_STORAGE_KEY    = 'ragnarok:dashboard:result:v1';

export function AnalyticsPane({
  results, model, bounds, busIndex,
  analyticsFocus, setAnalyticsFocus,
  dispatchRows, dispatchSeries,
  systemLoadRows, systemPriceRows, storageRows,
  subTab,
  currencySymbol,
  pathwayConfig,
  onSelectedPeriodChange,
}: Props) {
  return (
    <div className="pane analytics-pane">
      {results.pathway?.enabled && results.pathway.periods.length > 0 && (() => {
        const active = pathwayConfig?.selectedPeriod ?? results.pathway.selectedPeriod ?? results.pathway.periods[0];
        return (
          <section className="chart-card" style={{ marginBottom: 16 }}>
            <div className="chart-card-header">
              <div>
                <h3>Pathway period</h3>
                <p>Detailed charts and asset analytics use the selected investment period.</p>
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
          systemLoadRows={systemLoadRows}
          systemPriceRows={systemPriceRows}
          storageRows={storageRows}
          currencySymbol={currencySymbol}
          analyticsFocus={analyticsFocus}
          onFocusChange={setAnalyticsFocus}
          storageKey={subTab === 'Result' ? RESULT_STORAGE_KEY : ANALYTICS_STORAGE_KEY}
          initialLayout={subTab === 'Result' ? buildResultPreset(results) : PRESETS[0].build()}
          showPresets={subTab === 'Analytics'}
        />
      )}
    </div>
  );
}
