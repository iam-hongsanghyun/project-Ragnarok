/**
 * Company comparison joined in the browser — the fallback for results with no
 * stored run on the server (an imported project). A stored run reads
 * `GET /api/runs/{name}/companies` (`lib/api/resultsDerived.ts`) which does the
 * same join by owner name and returns the same shape.
 */
import type { CompanyBreakdownResult, CompanyFinanceResult, CompanyStatementResult } from 'lib/types';
import type { CompanyMetricDef, CompanyRow } from 'lib/api/resultsDerived';

export interface CompanyComparisonData {
  currency: string;
  sortedBy: string;
  metrics: CompanyMetricDef[];
  items: CompanyRow[];
}

export function joinCompanies(
  breakdown: CompanyBreakdownResult | undefined,
  finance: CompanyFinanceResult | undefined,
  statement: CompanyStatementResult | undefined,
  sortBy?: string,
): CompanyComparisonData {
  const rows = new Map<string, CompanyRow>();
  const get = (name: string): CompanyRow => {
    let r = rows.get(name);
    if (!r) { r = { company: name }; rows.set(name, r); }
    return r;
  };
  for (const c of breakdown?.companies ?? []) {
    Object.assign(get(c.company), {
      capacityMW: c.capacityMW, energyMWh: c.energyMWh, revenue: c.revenue, emissionsTonnes: c.emissionsTonnes,
    });
  }
  for (const c of finance?.companies ?? []) {
    Object.assign(get(c.company), { npv: c.npv, irr: c.irr, paybackYears: c.paybackYears });
  }
  for (const c of statement?.companies ?? []) get(c.company).netMargin = c.netMargin;

  const metrics: CompanyMetricDef[] = [];
  if (finance) metrics.push({ key: 'npv', label: 'NPV', higherBetter: true });
  if (statement) metrics.push({ key: 'netMargin', label: 'Net margin/yr', higherBetter: true });
  if (finance) metrics.push({ key: 'irr', label: 'IRR', higherBetter: true });
  metrics.push({ key: 'revenue', label: 'Revenue/yr', higherBetter: true });
  metrics.push({ key: 'capacityMW', label: 'Capacity', higherBetter: true });
  metrics.push({ key: 'emissionsTonnes', label: 'Emissions', higherBetter: false });

  const key = metrics.some((m) => m.key === sortBy) ? (sortBy as string) : metrics[0].key;
  const higher = metrics.find((m) => m.key === key)?.higherBetter ?? true;
  const value = (r: CompanyRow): number | null => {
    const v = (r as unknown as Record<string, number | null | undefined>)[key];
    return v === undefined ? null : v;
  };
  const all = Array.from(rows.values());
  const have = all.filter((r) => value(r) !== null).sort((a, b) => (higher ? value(b)! - value(a)! : value(a)! - value(b)!));
  const missing = all.filter((r) => value(r) === null);
  return {
    currency: breakdown?.currency || finance?.currency || statement?.currency || '',
    sortedBy: key,
    metrics,
    items: [...have, ...missing],
  };
}
