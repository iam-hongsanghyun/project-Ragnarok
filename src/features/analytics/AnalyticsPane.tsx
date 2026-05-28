import React from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus, AnalyticsSubTab, ChartSectionConfig, GridRow, PathwayConfig, RunHistoryEntry, RunResults, TimeSeriesRow, TimeSeriesSeries, WorkbookModel,
} from '../../shared/types';
import { ResultsDashboard } from './ResultsDashboard';
import { AnalyticsDashboard } from '../../views/AnalyticsView.features/Dashboard/AnalyticsDashboard';

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
  runHistory: RunHistoryEntry[];
  subTab: AnalyticsSubTab;
  currencySymbol: string;
  onExportAll?: () => void;
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

export function AnalyticsPane({
  results, model,
  dispatchRows, dispatchSeries,
  systemLoadRows, systemPriceRows, storageRows,
  subTab,
  currencySymbol,
  onExportAll,
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
      {/* ── Result sub-tab — predefined charts ───────────────────────── */}
      {subTab === 'Result' && (
        <ResultsDashboard
          results={results}
          model={model}
          dispatchRows={dispatchRows}
          dispatchSeries={dispatchSeries}
          systemLoadRows={systemLoadRows}
          systemPriceRows={systemPriceRows}
          storageRows={storageRows}
          currencySymbol={currencySymbol}
          onExportAll={onExportAll}
          selectedPeriod={pathwayConfig?.selectedPeriod ?? results.pathway?.selectedPeriod ?? null}
        />
      )}

      {/* ── Analytics sub-tab — Bloomberg-style editable grid ───────── */}
      {subTab === 'Analytics' && (
        <AnalyticsDashboard
          results={results}
          model={model}
          currencySymbol={currencySymbol}
        />
      )}
    </div>
  );
}
