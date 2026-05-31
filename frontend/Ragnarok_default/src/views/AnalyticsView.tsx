/**
 * Analytics view — results dashboard with sub-tab routing.
 *
 * Sub-tabs: Validation · Result · Analytics · Comparison. No file ops,
 * no run knobs — those live in Model and Settings respectively.
 *
 * The view file is a thin shell: layout + sub-tab routing only. Each
 * sub-tab body is its own feature file.
 */
import React from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus,
  AnalyticsSubTab,
  ChartSectionConfig,
  GridRow,
  PathwayConfig,
  RunHistoryEntry,
  RunResults,
  TimeSeriesRow,
  TimeSeriesSeries,
  WorkbookModel,
} from 'lib/types';
import { ModelIssue } from '../features/validation/useModelIssues';
import { ValidationPane } from '../features/validation/ValidationPane';
import { AnalyticsPane, EmptyAnalytics } from '../features/analytics/AnalyticsPane';
import { ComparisonPane } from '../features/analytics/ComparisonPane';
import { RunHistoryList } from '../features/run-history/RunHistoryList';
import { AnalyticsSubnav } from './AnalyticsView.features/AnalyticsSubnav';
import { LogPane } from '../features/log/LogPane';
import { ResizablePanels } from '../layout/ResizablePanels';
import { LeftRail, ViewPaneHeader } from '../shared/components/primitives';

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
  runHistory: RunHistoryEntry[];
  currencySymbol: string;
  pathwayConfig: PathwayConfig;
  onSelectedPeriodChange: (period: number) => void;
  onExportAll: () => void;

  // Comparison
  onToggleComparison: (id: string, inComparison: boolean) => void;

  // Run history rail
  onRestoreRun: (entry: RunHistoryEntry) => void;
  onRenameHistoryEntry: (id: string, label: string) => void;
  onPinHistoryEntry: (id: string, pinned: boolean) => void;
  onDeleteHistoryEntry: (id: string) => void;
  onClearHistory: () => void;
}

export function AnalyticsView(props: AnalyticsViewProps) {
  const { analyticsSubTab, displayResults, filename, runHistory } = props;

  return (
    <div className="analytics-view">
      <ResizablePanels id="analytics" direction="horizontal" initialSizes={[76, 24]} minSize={220}>
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
          runHistory={props.runHistory}
          activeResults={displayResults}
          onToggleComparison={props.onToggleComparison}
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
            runHistory={runHistory}
            subTab={analyticsSubTab}
            currencySymbol={props.currencySymbol}
            pathwayConfig={props.pathwayConfig}
            onSelectedPeriodChange={props.onSelectedPeriodChange}
            onExportAll={props.onExportAll}
          />
        )
      )}
      </div>

      {runHistory.length > 0 && (
        <LeftRail
          title="Run history"
          ariaLabel="Run history"
          side="right"
          className="analytics-view-rail"
          headerAction={
            <button
              type="button"
              className="tb-btn tb-btn--muted analytics-view-rail-clear"
              onClick={props.onClearHistory}
              title="Remove every run from the comparison history (including pinned). Does not affect the model or the displayed result."
            >
              Clear all
            </button>
          }
        >
          <RunHistoryList
            runHistory={runHistory}
            onRestoreRun={props.onRestoreRun}
            onRenameHistoryEntry={props.onRenameHistoryEntry}
            onPinHistoryEntry={props.onPinHistoryEntry}
            onDeleteHistoryEntry={props.onDeleteHistoryEntry}
            onToggleComparison={props.onToggleComparison}
            currencySymbol={props.currencySymbol}
          />
        </LeftRail>
      )}
      </ResizablePanels>
    </div>
  );
}
