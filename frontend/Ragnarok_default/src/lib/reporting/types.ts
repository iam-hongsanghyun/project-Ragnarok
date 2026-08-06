/**
 * Reporting payload types — hand-written mirrors of the backend's
 * `/api/reports/*` responses (backend/app/reporting.py). Field names mirror
 * the backend's camelCase payload byte-for-byte — do not rename.
 */

export interface ReportPerspectiveSection {
  id: string;
  title: string;
  keyQuestion: string;
}

export interface ReportPerspective {
  id: string;
  label: string;
  audience: string;
  description: string;
  sections: ReportPerspectiveSection[];
}

export interface ReportKpiItem {
  label: string;
  value: string;
  detail?: string;
}

export interface ReportTableColumn {
  key: string;
  label: string;
}

export interface ReportChartSeries {
  key: string;
  label: string;
  color?: string | null;
  values: (number | null)[];
}

export interface ReportChart {
  kind: 'donut' | 'bars' | 'line';
  title: string;
  unit: string;
  /** donut only */
  data?: { label: string; value: number; color?: string | null }[];
  /** bars only */
  labels?: string[];
  /** line only */
  xLabels?: string[];
  series?: ReportChartSeries[];
  stacked?: boolean;
  area?: boolean;
}

export type ReportBlock =
  | { type: 'kpis'; items: ReportKpiItem[] }
  | { type: 'narrative'; paragraphs: string[] }
  | { type: 'table'; title: string; columns: ReportTableColumn[]; rows: Record<string, unknown>[] }
  | { type: 'chart'; chart: ReportChart }
  | { type: 'unavailable'; reason: string; requires: string };

export interface ReportSection {
  id: string;
  title: string;
  keyQuestion: string;
  blocks: ReportBlock[];
}

export interface ReportProvenance {
  runName: string;
  savedAt?: string | null;
  origin?: string | null;
  filename?: string | null;
  note: string;
}

export interface ReportDocumentPayload {
  runName: string;
  generatedAt: string;
  perspective: string;
  perspectiveLabel: string;
  audience: string;
  title: string;
  subtitle: string;
  currency: string;
  sections: ReportSection[];
  caveats: string[];
  provenance: ReportProvenance;
}

/** The slice of `/api/runs` metadata the run picker needs. */
export interface ReportRunOption {
  name: string;
  label?: string;
  savedAt?: string;
}
