/**
 * KPI strip card — Bloomberg-style terminal row with 9 headline
 * metrics for a finished run. Extracted from ResultsDashboard so the
 * dashboard engine can render it as a card alongside charts.
 */
import React from 'react';
import { RunResults, WorkbookModel } from 'lib/types';
import { isRenewableCarrier, numberValue, storageCarrierSet } from 'lib/utils/helpers';

interface KpiCardProps {
  label: string;
  value: string;
  unit: string;
  green?: boolean;
}

function KpiCard({ label, value, unit, green }: KpiCardProps) {
  return (
    <div className={`kpi-card${green ? ' kpi-card--green' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-unit">{unit}</div>
    </div>
  );
}

interface Props {
  results: RunResults;
  model: WorkbookModel;
  currencySymbol?: string;
}

export function KpiStripCard({ results, model, currencySymbol = '$' }: Props) {
  const totalDispatch = results.carrierMix.reduce((s, m) => s + m.value, 0);

  const priceVals = (results.systemPriceSeries ?? []).map((p) => p.value).filter((v) => Number.isFinite(v));
  const avgPrice = priceVals.length > 0 ? priceVals.reduce((s, v) => s + v, 0) / priceVals.length : 0;
  const minPrice = priceVals.length > 0 ? Math.min(...priceVals) : undefined;
  const maxPrice = priceVals.length > 0 ? Math.max(...priceVals) : undefined;

  const emissionsSummary = results.summary.find((s) => s.label === 'System emissions');
  const emissionsDisplay = emissionsSummary ? emissionsSummary.value : '—';

  // Total cost — the objective value, and the first number anyone looks for.
  //
  // The backend summary has never carried a 'Total cost' entry, so this tile
  // read '—' on every run while `costBreakdown` held the answer all along. Sum
  // that instead: fuel + carbon + load shedding IS the objective, and it is what
  // the training course has the learner reconcile by hand.
  const totalCostSummary = results.summary.find((s) => s.label === 'Total cost')
    ?? results.summary.find((s) => s.label === 'System cost');
  const costParts = (results.costBreakdown ?? []).map((c) => c.value).filter((v) => Number.isFinite(v));
  const totalCostDisplay = totalCostSummary
    ? totalCostSummary.value
    : costParts.length > 0
      ? `${currencySymbol}${Math.round(costParts.reduce((s, v) => s + v, 0)).toLocaleString()}`
      : '—';

  // Reconstruct sorted-load to derive peak and load-factor without taking
  // the row-shaped systemLoadRows that App.tsx computes — keep this card
  // self-contained.
  const loadVals: number[] = [];
  for (const [, detail] of Object.entries(results.assetDetails.buses)) {
    detail.netSeries.forEach((p) => {
      if (p.load > 0) loadVals.push(p.load);
    });
  }
  // Sum across buses by timestamp index to get system load per snapshot.
  // assetDetails.buses entries all share the same snapshot ordering, so
  // we can index-walk.
  const busDetails = Object.values(results.assetDetails.buses);
  const snapCount = busDetails[0]?.netSeries.length ?? 0;
  const systemLoadPerSnap: number[] = [];
  for (let i = 0; i < snapCount; i++) {
    let sum = 0;
    for (const detail of busDetails) sum += detail.netSeries[i]?.load ?? 0;
    if (sum > 0) systemLoadPerSnap.push(sum);
  }
  // `nodalBalance` carries a per-bus AVERAGE, not a per-snapshot series, so the
  // walk above yields one averaged figure and reports it as the peak — 80 MW on a
  // model whose demand peaks at 170. The backend already computes the real peak;
  // prefer it, and keep the derivation only as a fallback.
  const derivedPeak = systemLoadPerSnap.length > 0 ? Math.max(...systemLoadPerSnap) : undefined;
  const peakDemandSummary = results.summary.find((s) => s.label === 'Peak demand');
  const peakFromSummary = peakDemandSummary ? Number.parseFloat(peakDemandSummary.value) : NaN;
  const peakLoad = Number.isFinite(peakFromSummary) ? peakFromSummary : derivedPeak;
  // Average load comes from the same averaged `nodalBalance` walk as the peak
  // did, so pairing it with the corrected peak would report a load factor built
  // from two different quantities. Energy served over hours modelled is the
  // definition anyway, and it is exactly right whenever generation equals load
  // (no storage or losses); the derivation stays as the fallback.
  const modeledHours = results.runMeta.snapshotCount * results.runMeta.snapshotWeight;
  const avgLoad = modeledHours > 0
    ? totalDispatch / modeledHours
    : systemLoadPerSnap.length > 0
      ? systemLoadPerSnap.reduce((s, v) => s + v, 0) / systemLoadPerSnap.length
      : undefined;
  const loadFactor = peakLoad && avgLoad ? avgLoad / peakLoad : undefined;

  // Renewable share — zero-emission carriers, excluding nuclear (zero-carbon
  // but not renewable) and storage carriers (they re-dispatch energy rather
  // than generate it). See `isRenewableCarrier`.
  const carriersBySheet = new Map(model.carriers.map((c) => [String(c.name ?? ''), c]));
  const storageCarriers = storageCarrierSet(model);
  const renewableMwh = results.carrierMix.reduce((s, m) => {
    const co2 = numberValue(carriersBySheet.get(m.label)?.co2_emissions);
    return isRenewableCarrier(m.label, co2, storageCarriers) ? s + m.value : s;
  }, 0);
  const renewableShare = totalDispatch > 0 ? (renewableMwh / totalDispatch) * 100 : 0;

  const snapshotCount = results.runMeta.snapshotCount;

  return (
    <div className="kpi-strip">
      <KpiCard label="Total cost"   value={totalCostDisplay} unit="" />
      <KpiCard label="Dispatch"     value={Math.round(totalDispatch).toLocaleString()} unit="MWh" />
      <KpiCard label="Avg price"    value={avgPrice.toFixed(1)} unit={`${currencySymbol}/MWh`} />
      <KpiCard label="Min · Max"    value={minPrice !== undefined && maxPrice !== undefined ? `${minPrice.toFixed(0)} · ${maxPrice.toFixed(0)}` : '—'} unit={`${currencySymbol}/MWh`} />
      <KpiCard label="Peak load"    value={peakLoad !== undefined ? Math.round(peakLoad).toLocaleString() : '—'} unit="MW" />
      <KpiCard label="Load factor"  value={loadFactor !== undefined ? `${(loadFactor * 100).toFixed(1)}%` : '—'} unit="" />
      <KpiCard label="Renewables"   value={`${renewableShare.toFixed(1)}%`} unit="" green={renewableShare >= 50} />
      <KpiCard label="Emissions"    value={emissionsDisplay} unit="" />
      <KpiCard label="Snapshots"    value={String(snapshotCount)} unit={`× ${Number(results.runMeta.snapshotWeight.toFixed(2))}h`} />
    </div>
  );
}
