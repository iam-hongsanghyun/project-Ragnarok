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

  const totalCostSummary = results.summary.find((s) => s.label === 'Total cost')
    ?? results.summary.find((s) => s.label === 'System cost');
  const totalCostDisplay = totalCostSummary ? totalCostSummary.value : '—';

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
  const peakLoad = systemLoadPerSnap.length > 0 ? Math.max(...systemLoadPerSnap) : undefined;
  const avgLoad = systemLoadPerSnap.length > 0
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
