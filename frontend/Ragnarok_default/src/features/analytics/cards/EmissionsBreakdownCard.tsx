/**
 * EmissionsBreakdownCard — shows post-optimisation emissions split
 * by carrier (bar chart) and a detailed per-generator table.
 *
 * Units:
 *   energy_mwh       → MWh dispatched in the modelled period
 *   emissions_tco2   → tCO₂e total
 *   intensity_kg_mwh → kg CO₂e / MWh (emission factor)
 */

import React, { useState } from 'react';
import { CarrierEmission, EmissionsBreakdown, GeneratorEmission } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';
import type { ResultTotals } from 'lib/api/resultsDerived';

interface Props {
  data: EmissionsBreakdown;
  /** Server totals and carrier shares (`analysis/totals`); null while loading. */
  totals?: ResultTotals['emissions'];
}

// ── Carrier bar chart ─────────────────────────────────────────────────────────

function CarrierBars({ carriers, sharePct }: { carriers: CarrierEmission[]; sharePct: Map<string, number> }) {
  const maxEms = Math.max(...carriers.map((c) => c.emissions_tco2), 1);

  return (
    <div className="ems-carrier-chart">
      {carriers.map((c) => {
        const pct = (c.emissions_tco2 / maxEms) * 100;
        const share = sharePct.get(c.carrier) ?? 0;
        const color = carrierColor(c.carrier);
        return (
          <div key={c.carrier} className="ems-bar-row">
            <div className="ems-bar-label" title={c.carrier}>{c.carrier}</div>
            <div className="ems-bar-track">
              <div
                className="ems-bar-fill"
                style={{ width: `${pct}%`, background: color }}
                title={`${c.emissions_tco2.toLocaleString()} tCO₂e`}
              />
            </div>
            <div className="ems-bar-values">
              <span className="ems-bar-tco2">{c.emissions_tco2 >= 1000
                ? `${(c.emissions_tco2 / 1000).toFixed(1)} ktCO₂e`
                : `${c.emissions_tco2.toFixed(0)} tCO₂e`}</span>
              <span className="ems-bar-share">{share.toFixed(1)}%</span>
              {c.intensity_kg_mwh > 0 && (
                <span className="ems-bar-intensity">{c.intensity_kg_mwh.toFixed(0)} kg/MWh</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Generator table ───────────────────────────────────────────────────────────

type SortKey = 'emissions_tco2' | 'energy_mwh' | 'intensity_kg_mwh' | 'name' | 'carrier';

function GeneratorTable({ generators }: { generators: GeneratorEmission[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('emissions_tco2');
  const [sortAsc, setSortAsc] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const sorted = [...generators].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === 'string' && typeof bv === 'string') {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const rows = showAll ? sorted : sorted.slice(0, 10);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(false); }
  };

  const th = (key: SortKey, label: string, align: 'left' | 'right' = 'right') => (
    <th
      className={`ems-th ems-th--${align} ems-th--sortable${sortKey === key ? ' ems-th--active' : ''}`}
      onClick={() => toggleSort(key)}
      title={`Sort by ${label}`}
    >
      {label} {sortKey === key ? (sortAsc ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <div className="ems-gen-table-wrap">
      <table className="ems-gen-table">
        <thead>
          <tr>
            {th('name', 'Generator', 'left')}
            {th('carrier', 'Carrier', 'left')}
            {th('energy_mwh', 'Energy (MWh)')}
            {th('emissions_tco2', 'Emissions (tCO₂e)')}
            {th('intensity_kg_mwh', 'Intensity (kg CO₂e/MWh)')}
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => (
            <tr key={g.name} className="ems-gen-row">
              <td className="ems-td ems-td--left ems-td--name" title={g.name}>{g.name}</td>
              <td className="ems-td ems-td--left">
                <span
                  className="ems-carrier-dot"
                  style={{ background: carrierColor(g.carrier) }}
                />
                {g.carrier}
              </td>
              <td className="ems-td">{g.energy_mwh.toLocaleString()}</td>
              <td className={`ems-td ems-td--ems${g.emissions_tco2 > 0 ? ' ems-td--nonzero' : ''}`}>
                {g.emissions_tco2 > 0 ? g.emissions_tco2.toLocaleString() : '—'}
              </td>
              <td className="ems-td">
                {g.intensity_kg_mwh > 0 ? g.intensity_kg_mwh.toFixed(0) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {generators.length > 10 && (
        <button className="ems-show-more" onClick={() => setShowAll((s) => !s)}>
          {showAll ? 'Show less' : `Show all ${generators.length} generators`}
        </button>
      )}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function EmissionsBreakdownCard({ data, totals = null }: Props) {
  const totalTco2 = totals?.totalTco2 ?? null;
  const avgIntensity = totals?.averageIntensityKgPerMwh ?? null;
  const sharePct = new Map((totals?.byCarrier ?? []).map((c) => [c.carrier, c.sharePct]));
  const emittingCarriers = data.byCarrier.filter((c) => c.emissions_tco2 > 0);
  const zeroCarriers = data.byCarrier.filter((c) => c.emissions_tco2 === 0);

  return (
    <div className="ems-card">
      {/* KPI row */}
      <div className="ems-kpi-row">
        <div className="ems-kpi">
          <span className="ems-kpi-value">
            {totalTco2 === null ? '—' : totalTco2 >= 1000
              ? `${(totalTco2 / 1000).toFixed(1)} ktCO₂e`
              : `${totalTco2.toFixed(0)} tCO₂e`}
          </span>
          <span className="ems-kpi-label">Total emissions</span>
        </div>
        <div className="ems-kpi">
          <span className="ems-kpi-value">{avgIntensity !== null ? `${avgIntensity.toFixed(0)} kg CO₂e/MWh` : '—'}</span>
          <span className="ems-kpi-label">System average intensity</span>
        </div>
        <div className="ems-kpi">
          <span className="ems-kpi-value">{emittingCarriers.length}</span>
          <span className="ems-kpi-label">Emitting carriers</span>
        </div>
        {zeroCarriers.length > 0 && (
          <div className="ems-kpi ems-kpi--green">
            <span className="ems-kpi-value">{zeroCarriers.map((c) => c.carrier).join(', ')}</span>
            <span className="ems-kpi-label">Zero-emission carriers</span>
          </div>
        )}
      </div>

      {/* Carrier bars */}
      {emittingCarriers.length > 0 && (
        <div className="ems-section">
          <h4 className="ems-section-title">By carrier</h4>
          <CarrierBars carriers={emittingCarriers} sharePct={sharePct} />
        </div>
      )}

      {/* Generator table */}
      {data.byGenerator.length > 0 && (
        <div className="ems-section">
          <h4 className="ems-section-title">By generator</h4>
          <GeneratorTable generators={data.byGenerator} />
        </div>
      )}
    </div>
  );
}
