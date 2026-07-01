/**
 * Dashboard layout types.
 *
 * The Analytics view's "Analytics" sub-tab is a Bloomberg-style
 * editable grid: rows of cards with resizable column widths and
 * variable cell counts per row. Layouts are persisted to
 * localStorage and can be named / switched.
 *
 * Card content is decoupled from layout: each cell points at a Card
 * via `cardId`; the Card carries its own typed config. This means the
 * layout JSON is small and stable, and individual cards can be
 * re-rendered as their config (e.g. a chart's metric, timeframe)
 * changes without touching the grid structure.
 */
import { ChartSectionConfig, ChartSectionType, TimeframeOption } from 'lib/types';

export type CardKind =
  | 'chart'
  | 'pivot'
  | 'map'
  | 'notes'
  | 'kpi-strip'
  | 'duration-curve'
  | 'merit-order'
  | 'co2-shadow'
  | 'generator-economics'
  | 'statistics'
  | 'near-optimal'
  | 'merchant'
  | 'company-breakdown'
  | 'company-finance'
  | 'price-formation'
  | 'commitment'
  | 'power-flow'
  | 'contingency'
  | 'emissions-breakdown'
  | 'capacity-expansion'
  | 'capacity-by-period'
  | 'carrier-analysis'
  | 'load-analysis'
  | 'stochastic-scenarios';

interface CardBase {
  id: string;
  /** User-provided title override. Falsy = auto-generate from card kind / config. */
  title?: string;
}

export interface ChartCard extends CardBase {
  kind: 'chart';
  config: ChartSectionConfig;
}

/** Operators for a pivot filter. `in` = categorical set membership; the rest are
 *  numeric comparisons. */
/** Pivot chart types — a superset of the metric chart's `ChartSectionType`.
 *  `hbar`/`grouped-bar`/`scatter` work for any value; `duration`/`daily-profile`
 *  are series-only. */
export type PivotChartType =
  | ChartSectionType            // 'line' | 'area' | 'bar' | 'donut'
  | 'hbar'
  | 'grouped-bar'
  | 'scatter'
  | 'duration'
  | 'daily-profile';

export type PivotFilterOp = 'in' | '>' | '>=' | '<' | '<=' | '=';

export interface PivotFilter {
  /** `component` filters which components are included by one of their
   *  attributes; `value` is a per-snapshot threshold on the plotted value. */
  scope: 'component' | 'value';
  /** Attribute name for a component-scope filter (ignored for value scope). */
  field: string;
  op: PivotFilterOp;
  /** Categorical picks for `op:'in'`. */
  values?: string[];
  /** Threshold for numeric operators. */
  value?: number;
}

/**
 * A generic "pivot from outputs" chart: plot any component attribute (output
 * series, static output, or input numeric), grouped by one or more input
 * dimensions (carrier, bus, …) and filtered by component attributes and/or
 * per-snapshot value thresholds. Derives everything from actual values rather
 * than the hardcoded metric registry.
 */
export interface PivotChartConfig {
  id: number;
  sheet: string;                 // component list_name: 'generators','lines',…
  valueAttribute: string;        // exact schema attr name: 'p','p_nom_opt','p_nom',…
  /** Optional extra value attributes plotted as additional series alongside
   *  `valueAttribute` (line/area/bar + grouped/horizontal bar). `valueAttribute`
   *  stays the canonical first column for back-compat. */
  valueAttributes?: string[];
  groupBy: string[];             // input dims → composite key; [] = per-component
  filters: PivotFilter[];
  aggregate: 'sum' | 'mean' | 'max' | 'min' | 'count';
  chartType: PivotChartType;
  /** Second value attribute for the scatter Y axis (X axis = valueAttribute). */
  scatterYAttribute?: string;
  timeframe: TimeframeOption;
  stacked: boolean;
  startIndex: number;
  endIndex: number;
  xAxisTitle?: string;
  yAxisTitle?: string;
  showLegend?: boolean;
  showAxisLabels?: boolean;
  xLabelAngle?: number;
}

export interface PivotCard extends CardBase {
  kind: 'pivot';
  config: PivotChartConfig;
}

export interface MapCard extends CardBase {
  kind: 'map';
}

export interface NotesCard extends CardBase {
  kind: 'notes';
}

export interface KpiStripCard extends CardBase {
  kind: 'kpi-strip';
}

export interface DurationCurveCardData extends CardBase {
  kind: 'duration-curve';
  /** 'load' = system load duration; 'price' = marginal-price duration. */
  source: 'load' | 'price';
}

export interface MeritOrderCardData extends CardBase {
  kind: 'merit-order';
}

export interface Co2ShadowCardData extends CardBase {
  kind: 'co2-shadow';
}

export interface GeneratorEconomicsCardData extends CardBase {
  kind: 'generator-economics';
}

export interface StatisticsCardData extends CardBase {
  kind: 'statistics';
}

export interface NearOptimalCardData extends CardBase {
  kind: 'near-optimal';
}

export interface MerchantCardData extends CardBase {
  kind: 'merchant';
}

export interface CompanyBreakdownCardData extends CardBase {
  kind: 'company-breakdown';
}

export interface CompanyFinanceCardData extends CardBase {
  kind: 'company-finance';
}

export interface PriceFormationCardData extends CardBase {
  kind: 'price-formation';
}

export interface CommitmentCardData extends CardBase {
  kind: 'commitment';
}

export interface PowerFlowCardData extends CardBase {
  kind: 'power-flow';
}

export interface ContingencyCardData extends CardBase {
  kind: 'contingency';
}

export interface EmissionsBreakdownCardData extends CardBase {
  kind: 'emissions-breakdown';
}

export interface CapacityExpansionCardData extends CardBase {
  kind: 'capacity-expansion';
}

export interface CapacityByPeriodCardData extends CardBase {
  kind: 'capacity-by-period';
}

export interface CarrierAnalysisCardData extends CardBase {
  kind: 'carrier-analysis';
}

export interface LoadAnalysisCardData extends CardBase {
  kind: 'load-analysis';
}

export interface StochasticScenariosCardData extends CardBase {
  kind: 'stochastic-scenarios';
}

export type Card =
  | ChartCard
  | PivotCard
  | MapCard
  | NotesCard
  | KpiStripCard
  | DurationCurveCardData
  | MeritOrderCardData
  | Co2ShadowCardData
  | GeneratorEconomicsCardData
  | StatisticsCardData
  | NearOptimalCardData
  | MerchantCardData
  | CompanyBreakdownCardData
  | CompanyFinanceCardData
  | PriceFormationCardData
  | CommitmentCardData
  | PowerFlowCardData
  | ContingencyCardData
  | EmissionsBreakdownCardData
  | CapacityExpansionCardData
  | CapacityByPeriodCardData
  | CarrierAnalysisCardData
  | LoadAnalysisCardData
  | StochasticScenariosCardData;

export interface Cell {
  id: string;
  /** flex-grow weight inside the row. 1 = equal share. */
  flex: number;
  /** Id of the card rendered in this cell. Undefined = empty placeholder
   *  the user can fill by clicking its "+" (pick a card kind). */
  cardId?: string;
}

export interface Row {
  id: string;
  /** Row height in pixels. Used when `autoHeight` is false (or unset and the
   *  user has dragged the resize handle). */
  height: number;
  /** When true, the renderer computes height from the dashboard width and
   *  the cell count using the rule:
   *    1 cell  → 0.5 × containerWidth
   *    N ≥ 2   → containerWidth / N   (square cells)
   *  Toggling cells in the row adapts the height automatically. Dragging
   *  the row-resize handle switches this to false (manual height). */
  autoHeight?: boolean;
  cells: Cell[];
}

export interface DashboardLayout {
  rows: Row[];
  cards: Card[];
}

export interface NamedLayout {
  name: string;
  layout: DashboardLayout;
  updatedAt: number;
}

/** Default storage key for the Analytics sub-tab dashboard. Override
 *  via the `storageKey` prop to give the Result sub-tab its own slot. */
export const STORAGE_KEY = 'ragnarok:dashboard:analytics';

/** A drag payload carries the cell being moved. */
export interface DragPayload {
  rowId: string;
  cellId: string;
}
