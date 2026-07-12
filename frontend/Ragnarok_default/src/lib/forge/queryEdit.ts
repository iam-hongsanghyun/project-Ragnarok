/**
 * Forge "Adjust values" — client types + request builder for the server-side
 * bulk-edit engine (`/api/forge/query`). The heavy work runs on the backend
 * (it needs the full model — static + series — for joins and temporal edits);
 * this module only shapes the request and mirrors the response types.
 *
 * Panel model: a filter picks a column on the target itself or on a linked
 * bus (`via` = the target's bus-ref column; the join is built silently), and
 * matches ANY of the selected values (union) — filters AND together. A
 * temporal `add` carries unit (MW per snapshot / MWh over the period), scope
 * (each matched series / group total) and split (proportional / equal).
 *
 * `buildRequest` is the one place the UI's percent-based multiply is converted
 * to the raw factor the backend expects (× 80% → factor 0.8).
 */

export type WireFilterOp = 'eq' | 'ne' | 'contains' | 'in' | 'gt' | 'lt' | 'ge' | 'le';
export type EditOp = 'set' | 'add' | 'multiply' | 'derive';
export type AddUnit = 'mw' | 'mwh';
export type AddScope = 'each' | 'total';
export type AddSplit = 'proportional' | 'equal';

/** Panel-level filter operators. `any`/`none` take a multi-select of distinct
 *  values (union); the rest take one typed value. */
export type PanelFilterOp = 'any' | 'none' | 'contains' | 'gt' | 'lt' | 'ge' | 'le';

export const PANEL_FILTER_OPS: Array<{ value: PanelFilterOp; label: string }> = [
  { value: 'any', label: 'is any of' },
  { value: 'none', label: 'is none of' },
  { value: 'contains', label: 'contains' },
  { value: 'gt', label: '>' },
  { value: 'lt', label: '<' },
  { value: 'ge', label: '≥' },
  { value: 'le', label: '≤' },
];

/** Ops whose value is a multi-select of distinct values. */
export const MULTI_OPS: PanelFilterOp[] = ['any', 'none'];
/** Ops whose value is numeric free text. */
export const NUMERIC_OPS: PanelFilterOp[] = ['gt', 'lt', 'ge', 'le'];

export interface JoinPath {
  component: string;
  ref_column: string;
}

/** One filter row in the panel. `via` = '' filters a column on the target
 *  itself; otherwise it names the target's bus-ref column ('bus', 'bus0', …)
 *  and the filter column lives on `buses` (the join is built automatically). */
export interface QueryFilterState {
  id: string;
  via: string;
  column: string;
  op: PanelFilterOp;
  /** Selected distinct values for `any`/`none` (union within the filter). */
  values: string[];
  /** Typed value for `contains` and the numeric ops. */
  text: string;
}

export interface QueryFilterWire {
  column: string;
  op: WireFilterOp;
  value?: string | number | null;
  values?: Array<string | number>;
  join?: JoinPath | null;
}

export interface QueryEditWire {
  op: EditOp;
  amount?: number;
  source_attr?: string;
  coefficient?: number;
  constant?: number;
  unit?: AddUnit;
  scope?: AddScope;
  split?: AddSplit;
}

export interface QueryEditRequest {
  sessionId?: string;
  target: string;
  attribute: string;
  temporal: boolean;
  filters: QueryFilterWire[];
  edit: QueryEditWire;
}

export interface QuerySampleRow {
  name: string;
  before: unknown;
  after: unknown;
}

export interface QueryPreview {
  matched: number;
  targetTotal: number;
  temporal: boolean;
  seriesSheet: string | null;
  seriesColumnsPresent: number | null;
  sample: QuerySampleRow[];
  /** 'energyMwh' ⇒ sample before/after are period energies [MWh]. */
  sampleKind?: 'value' | 'energyMwh';
  energyBeforeMwh?: number | null;
  energyAfterMwh?: number | null;
  warnings: string[];
}

export interface QueryApplyResult {
  matched: number;
  temporal: boolean;
  sheet?: string;
  seriesSheet?: string;
  changed: number;
}

export interface DeriveState {
  source_attr: string;
  coefficient: number;
  constant: number;
}

const num = (s: string): number => {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
};

/** A filter row is usable once it has a column and at least one value. */
export function filterReady(f: QueryFilterState): boolean {
  if (!f.column) return false;
  if (MULTI_OPS.includes(f.op)) return f.values.length > 0;
  return f.text.trim() !== '';
}

/** One panel filter → one or more wire filters. `any` maps to eq (1 value) or
 *  in (several); `none` maps to one ANDed `ne` per value ("is none of"). */
function toWire(f: QueryFilterState): QueryFilterWire[] {
  const join = f.via ? { component: 'buses', ref_column: f.via } : undefined;
  const base = (w: Omit<QueryFilterWire, 'column'>): QueryFilterWire =>
    join ? { column: f.column, ...w, join } : { column: f.column, ...w };
  if (f.op === 'any') {
    return f.values.length === 1
      ? [base({ op: 'eq', value: f.values[0] })]
      : [base({ op: 'in', values: f.values })];
  }
  if (f.op === 'none') {
    return f.values.map((v) => base({ op: 'ne', value: v }));
  }
  return [base({ op: f.op, value: f.text.trim() })];
}

/** Build the wire request. `amount` is the panel's raw input; for `multiply` it
 *  is a PERCENT and converted to a factor here (the sole percent↔factor site). */
export function buildRequest(args: {
  sessionId?: string;
  target: string;
  attribute: string;
  temporal: boolean;
  filters: QueryFilterState[];
  op: EditOp;
  amount: string;
  unit: AddUnit;
  scope: AddScope;
  split: AddSplit;
  derive: DeriveState;
}): QueryEditRequest {
  let edit: QueryEditWire;
  if (args.op === 'derive') {
    edit = {
      op: 'derive',
      source_attr: args.derive.source_attr,
      coefficient: args.derive.coefficient,
      constant: args.derive.constant,
    };
  } else if (args.op === 'multiply') {
    edit = { op: 'multiply', amount: num(args.amount) / 100 };
  } else if (args.op === 'add' && args.temporal) {
    edit = { op: 'add', amount: num(args.amount), unit: args.unit, scope: args.scope, split: args.split };
  } else {
    edit = { op: args.op, amount: num(args.amount) };
  }
  return {
    sessionId: args.sessionId,
    target: args.target,
    attribute: args.attribute,
    temporal: args.temporal,
    filters: args.filters.filter(filterReady).flatMap(toWire),
    edit,
  };
}
