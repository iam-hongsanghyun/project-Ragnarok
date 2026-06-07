/**
 * Analytics view — results dashboard with sub-tab routing.
 *
 * Sub-tabs: Validation · Result · Analytics · Comparison · Log. No file ops,
 * no run knobs — those live in Model and Settings respectively.
 *
 * The view file is a thin shell: layout + sub-tab routing only. Each
 * sub-tab body is its own feature file. Comparison reads straight from the
 * backend run metas (the single source of truth for run history) — there is
 * no browser-side history rail anymore.
 */
import React from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus,
  AnalyticsSubTab,
  BackendRunMeta,
  ChartSectionConfig,
  GridRow,
  PathwayConfig,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from 'lib/types';
import { ModelIssue } from '../features/validation/useModelIssues';
import { ValidationPane } from '../features/validation/ValidationPane';
import { AnalyticsPane, EmptyAnalytics } from '../features/analytics/AnalyticsPane';
import { ComparisonPane } from '../features/analytics/ComparisonPane';
import { AnalyticsSubnav } from './AnalyticsView.features/AnalyticsSubnav';
import { LogPane } from '../features/log/LogPane';
import { ViewPaneHeader } from '../shared/components/primitives';

interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  notes: string[];
  snapshotCount: number;
  networkSummary: Record<string, number>;
}

export interface AnalyticsViewProps {
  analyticsSubTab: AnalyticsSubTab;
  onAnalyticsSubTabChange: (s: AnalyticsSubTab) => void;

  // Validation
  validateResult: ValidationResult | null;
  modelIssues: ModelIssue[];
  onValidate: () => void;
  onRun: () => void;
  onNavigateToTable: (sheet: string, rowIndex: number) => void;

  // Results
  displayResults: RunResults | null;
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
  currencySymbol: string;
  pathwayConfig: PathwayConfig;
  onSelectedPeriodChange: (period: number) => void;

  // Comparison — backend metas are the single source of truth.
  backendRuns: BackendRunMeta[];
  activeRunName: string | null;
}

export function AnalyticsView(props: AnalyticsViewProps) {
  const { analyticsSubTab, displayResults, filename } = props;

  return (
    <div className="analytics-view">
      <div className="analytics-view-main">
      <ViewPaneHeader variant="analytics">
        <AnalyticsSubnav
          subTab={analyticsSubTab}
          onChange={props.onAnalyticsSubTabChange}
          validateResult={props.validateResult}
          modelIssues={props.modelIssues}
        />
        {displayResults && analyticsSubTab !== 'Validation' && analyticsSubTab !== 'Log' && (
          <div className="inline-stats">
            <span>{filename}</span>
            <span>{displayResults.runMeta.snapshotCount} snapshots</span>
            <span>{displayResults.runMeta.snapshotWeight}h weight</span>
          </div>
        )}
      </ViewPaneHeader>

      {analyticsSubTab === 'Validation' && (
        <ValidationPane
          validateResult={props.validateResult}
          issues={props.modelIssues}
          onValidate={props.onValidate}
          onRun={props.onRun}
          onNavigate={props.onNavigateToTable}
        />
      )}

      {analyticsSubTab === 'Comparison' && (
        <ComparisonPane
          backendRuns={props.backendRuns}
          activeRunName={props.activeRunName}
          currencySymbol={props.currencySymbol}
        />
      )}

      {analyticsSubTab === 'Log' && <LogPane />}

      {(analyticsSubTab === 'Result' || analyticsSubTab === 'Analytics') && (
        !displayResults ? (
          <EmptyAnalytics />
        ) : (
          <AnalyticsPane
            results={displayResults}
            filename={filename}
            model={props.model}
            bounds={props.bounds}
            busIndex={props.busIndex}
            analyticsFocus={props.analyticsFocus}
            setAnalyticsFocus={props.setAnalyticsFocus}
            chartSections={props.chartSections}
            setChartSections={props.setChartSections}
            dispatchRows={props.dispatchRows}
            dispatchSeries={props.dispatchSeries}
            systemLoadRows={props.systemLoadRows}
            systemPriceRows={props.systemPriceRows}
            storageRows={props.storageRows}
            subTab={analyticsSubTab}
            currencySymbol={props.currencySymbol}
            pathwayConfig={props.pathwayConfig}
            onSelectedPeriodChange={props.onSelectedPeriodChange}
          />
        )
      )}
      </div>
    </div>
  );
}
