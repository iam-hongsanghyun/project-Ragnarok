/**
 * Forge "Query & Edit" — client types + request builder for the server-side
 * bulk-edit engine (`/api/forge/query`). The heavy work runs on the backend
 * (it needs the full model — static + series — for joins and temporal edits);
 * this module only shapes the request and mirrors the response types.
 *
 * `buildRequest` is the one place the UI's percent-based multiply is converted
 * to the raw factor the backend expects (× 80% → factor 0.8), matching the
 * legacy `adjust.ts` convention at the wire boundary.
 */

export type FilterOp = 'eq' | 'ne' | 'contains' | 'in' | 'gt' | 'lt' | 'ge' | 'le';
export type EditOp = 'set' | 'add' | 'multiply' | 'derive';

export const FILTER_OPS: Array<{ value: FilterOp; label: string }> = [
  { value: 'eq', label: '=' },
  { value: 'ne', label: '≠' },
  { value: 'contains', label: 'contains' },
  { value: 'in', label: 'in (a, b, …)' },
  { value: 'gt', label: '>' },
  { value: 'lt', label: '<' },
  { value: 'ge', label: '≥' },
  { value: 'le', label: '≤' },
];

/** Ops whose value is a discrete match (offer a distinct-value dropdown). */
export const EQUALITY_OPS: FilterOp[] = ['eq', 'ne'];
/** Ops whose value is numeric. */
export const NUMERIC_OPS: FilterOp[] = ['gt', 'lt', 'ge', 'le'];

export interface JoinPath {
  component: string;
  ref_column: string;
}

/** One filter row in the panel. `join` on ⇒ the predicate is evaluated on a
 *  linked component and matched against the target's `refColumn`. */
export interface QueryFilterState {
  id: string;
  join: boolean;
  joinComponent: string;
  refColumn: string;
  column: string;
  op: FilterOp;
  value: string;
}

export interface QueryFilterWire {
  column: string;
  op: FilterOp;
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

/** A filter row is usable once it has a column and (for value-taking ops) a value. */
export function filterReady(f: QueryFilterState): boolean {
  if (!f.column) return false;
  if (f.join && (!f.joinComponent || !f.refColumn)) return false;
  return f.value.trim() !== '';
}

function toWire(f: QueryFilterState): QueryFilterWire {
  const base: QueryFilterWire = { column: f.column, op: f.op };
  if (f.op === 'in') {
    base.values = f.value.split(',').map((s) => s.trim()).filter((s) => s !== '');
  } else {
    base.value = f.value.trim();
  }
  if (f.join) base.join = { component: f.joinComponent, ref_column: f.refColumn };
  return base;
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
  } else {
    edit = { op: args.op, amount: num(args.amount) };
  }
  return {
    sessionId: args.sessionId,
    target: args.target,
    attribute: args.attribute,
    temporal: args.temporal,
    filters: args.filters.filter(filterReady).map(toWire),
    edit,
  };
}
