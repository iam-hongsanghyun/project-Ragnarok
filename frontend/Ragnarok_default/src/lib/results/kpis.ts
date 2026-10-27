/**
 * Headline KPIs of a result computed in the browser — the fallback for results
 * with no stored run on the server (an imported project, or a pathway run whose
 * period-specific view is re-derived here). A stored run reads
 * `GET /api/runs/{name}/kpis` instead (`lib/api/resultsDerived.ts`); both return
 * the same `RunKpis` shape and the same numbers.
 */
import type { RunResults, WorkbookModel } from 'lib/types';
import type { RunKpis } from 'lib/api/resultsDerived';
import { isRenewableCarrier, numberValue, storageCarrierSet } from 'lib/utils/helpers';

export function kpisFromResults(results: RunResults, model: WorkbookModel, currencySymbol = '$'): RunKpis {
  const totalDispatch = results.carrierMix.reduce((s, m) => s + m.value, 0);

  const priceVals = (results.systemPriceSeries ?? []).map((p) => p.value).filter((v) => Number.isFinite(v));
  // Load-weighted run average (n.statistics.prices(weighting="load")) from the run's own
  // metadata; a pathway period view or a run stored before the field existed falls back
  // to the unweighted series mean - the same rule as the server (`compute_kpis`).
  const serverAvg = results.pathway?.enabled ? undefined : results.runMeta?.averageSystemPrice;
  const avgPrice = typeof serverAvg === 'number' && Number.isFinite(serverAvg)
    ? serverAvg
    : priceVals.length > 0 ? priceVals.reduce((s, v) => s + v, 0) / priceVals.length : 0;

  // Total cost: the summary's entry, else fuel + carbon + load shedding (the
  // objective) summed from the cost breakdown.
  const summaryValue = (...labels: string[]): string | null => {
    for (const label of labels) {
      const hit = results.summary.find((s) => s.label === label);
      if (hit) return hit.value;
    }
    return null;
  };
  const costParts = (results.costBreakdown ?? []).map((c) => c.value).filter((v) => Number.isFinite(v));
  const totalCost = summaryValue('Total cost', 'System cost')
    ?? (costParts.length > 0 ? `${currencySymbol}${Math.round(costParts.reduce((s, v) => s + v, 0)).toLocaleString()}` : null);

  // Peak demand from the backend summary ("8,760 MW" -> 8760); fall back to the
  // per-bus net series only when absent.
  const peakText = summaryValue('Peak demand');
  const peakFromSummary = peakText !== null ? Number(peakText.replace(/[^\d.-]/g, '')) : NaN;
  const busDetails = Object.values(results.assetDetails?.buses ?? {});
  const snapCount = busDetails[0]?.netSeries.length ?? 0;
  const systemLoadPerSnap: number[] = [];
  for (let i = 0; i < snapCount; i++) {
    let sum = 0;
    for (const detail of busDetails) sum += detail.netSeries[i]?.load ?? 0;
    if (sum > 0) systemLoadPerSnap.push(sum);
  }
  const derivedPeak = systemLoadPerSnap.length > 0 ? Math.max(...systemLoadPerSnap) : null;
  const peakLoad = Number.isFinite(peakFromSummary) ? peakFromSummary : derivedPeak;

  // Average load = energy served over hours modelled.
  const modeledHours = results.runMeta.snapshotCount * results.runMeta.snapshotWeight;
  const avgLoad = modeledHours > 0
    ? totalDispatch / modeledHours
    : systemLoadPerSnap.length > 0 ? systemLoadPerSnap.reduce((s, v) => s + v, 0) / systemLoadPerSnap.length : null;
  const loadFactor = peakLoad && avgLoad ? avgLoad / peakLoad : null;

  // Renewable share: zero-emission carriers, excluding nuclear and storage.
  const carriersBySheet = new Map(model.carriers.map((c) => [String(c.name ?? ''), c]));
  const storageCarriers = storageCarrierSet(model);
  const renewableMwh = results.carrierMix.reduce((s, m) => {
    const co2 = numberValue(carriersBySheet.get(m.label)?.co2_emissions);
    return isRenewableCarrier(m.label, co2, storageCarriers) ? s + m.value : s;
  }, 0);

  return {
    totalCost,
    dispatchMwh: totalDispatch,
    avgPrice,
    minPrice: priceVals.length > 0 ? Math.min(...priceVals) : null,
    maxPrice: priceVals.length > 0 ? Math.max(...priceVals) : null,
    peakLoadMw: peakLoad,
    loadFactor,
    renewableSharePct: totalDispatch > 0 ? (renewableMwh / totalDispatch) * 100 : 0,
    emissions: summaryValue('System emissions'),
    snapshotCount: results.runMeta.snapshotCount,
    snapshotWeightHours: results.runMeta.snapshotWeight,
    currencySymbol,
  };
}
