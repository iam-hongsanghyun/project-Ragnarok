/**
 * CarrierAnalysisCard — per-carrier summary that gathers the carrier-level
 * numbers already computed elsewhere (energy mix, emissions breakdown) and
 * joins them with installed capacity aggregated from the generators. Carriers
 * are the aggregation dimension used across dispatch, cost, and emissions, but
 * there was no single table that put capacity, generation, share, capacity
 * factor, and emissions side by side.
 *
 * Capacity per carrier sums generator p_nom_opt (extendable) or p_nom (fixed).
 * Capacity factor = generation_MWh / (capacity_MW * modeledHours).
 * Derives entirely from (model, results) so it works on imported projects.
 */
import React, { useMemo, useState } from 'react';
import { RunResults, WorkbookModel } from '../../../shared/types';
import { carrierColor, numberValue, stringValue } from '../../../shared/utils/helpers';

interface Props {
  model: WorkbookModel;
  results: RunResults;
}

interface CarrierStat {
  carrier: string;
  color: string;
  capacity: number;
  generation: number;
  share: number;
  capacityFactor: number | null;
  emissions: number;
  intensity: number;
}

type SortKey = 'carrier' | 'capacity' | 'generation' | 'share' | 'capacityFactor' | 'emissions' | 'intensity';

export function CarrierAnalysisCard({ model, results }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('generation');
  const [sortAsc, setSortAsc] = useState(false);

  const modeledHours = results.runMeta.modeledHours || 0;

  const capacityByCarrier = useMemo(() => {
    const optStatic = results.outputs?.static?.generators ?? {};
    const caps: Record<string, number> = {};
    (model.generators ?? []).forEach((row) => {
      const name = stringValue(row.name);
      if (!name) return;
      const carrier = stringValue(row.carrier) || 'Other';
      const extendable =
        row.p_nom_extendable === true ||
        String(row.p_nom_extendable ?? '').toLowerCase() === 'true';
      const pNom = numberValue(row.p_nom);
      const optRaw = optStatic[name]?.p_nom_opt;
      const pNomOpt = optRaw !== undefined && optRaw !== null && optRaw !== ''
        ? Number(optRaw)
        : pNom;
      const cap = extendable && Number.isFinite(pNomOpt) ? pNomOpt : pNom;
      if (cap > 0) caps[carrier] = (caps[carrier] ?? 0) + cap;
    });
    return caps;
  }, [model.generators, results.outputs]);

  const stats = useMemo(() => {
    const emsByCarrier: Record<string, { emissions: number; intensity: number }> = {};
    (results.emissionsBreakdown?.byCarrier ?? []).forEach((c) => {
      emsByCarrier[c.carrier] = { emissions: c.emissions_tco2, intensity: c.intensity_kg_mwh };
    });

    const generationByCarrier: Record<string, number> = {};
    results.carrierMix.forEach((m) => { generationByCarrier[m.label] = m.value; });

    const totalGeneration = results.carrierMix.reduce((s, m) => s + m.value, 0);

    const carriers = new Set<string>([
      ...Object.keys(capacityByCarrier),
      ...Object.keys(generationByCarrier),
      ...Object.keys(emsByCarrier),
    ]);

    const rows: CarrierStat[] = Array.from(carriers).map((carrier) => {
      const capacity = capacityByCarrier[carrier] ?? 0;
      const generation = generationByCarrier[carrier] ?? 0;
      const ems = emsByCarrier[carrier];
      return {
        carrier,
        color: carrierColor(carrier),
        capacity,
        generation,
        share: totalGeneration > 0 ? generation / totalGeneration : 0,
        capacityFactor:
          capacity > 0 && modeledHours > 0 ? generation / (capacity * modeledHours) : null,
        emissions: ems?.emissions ?? 0,
        intensity: ems?.intensity ?? 0,
      };
    });
    return rows;
  }, [capacityByCarrier, results.carrierMix, results.emissionsBreakdown, modeledHours]);

  const sorted = useMemo(() => {
    const rows = [...stats];
    rows.sort((a, b) => {
      if (sortKey === 'carrier') {
        return sortAsc ? a.carrier.localeCompare(b.carrier) : b.carrier.localeCompare(a.carrier);
      }
      const av = sortKey === 'capacityFactor' ? (a.capacityFactor ?? -1) : a[sortKey];
      const bv = sortKey === 'capacityFactor' ? (b.capacityFactor ?? -1) : b[sortKey];
      return sortAsc ? av - bv : bv - av;
    });
    return rows;
  }, [stats, sortKey, sortAsc]);

  if (stats.length === 0) {
    return (
      <p className="empty-text" style={{ padding: '16px' }}>
        No carrier data available — run the model to populate the energy mix.
      </p>
    );
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(key === 'carrier'); }
  };

  const arrow = (key: SortKey) => (sortKey === key ? (sortAsc ? ' ↑' : ' ↓') : '');
  const num = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 0 });

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="comparison-table">
        <thead>
          <tr>
            <th onClick={() => toggleSort('carrier')} style={{ cursor: 'pointer' }}>Carrier{arrow('carrier')}</th>
            <th onClick={() => toggleSort('capacity')} style={{ cursor: 'pointer' }}>Capacity (MW){arrow('capacity')}</th>
            <th onClick={() => toggleSort('generation')} style={{ cursor: 'pointer' }}>Generation (MWh){arrow('generation')}</th>
            <th onClick={() => toggleSort('share')} style={{ cursor: 'pointer' }}>Share{arrow('share')}</th>
            <th onClick={() => toggleSort('capacityFactor')} style={{ cursor: 'pointer' }}>Capacity factor{arrow('capacityFactor')}</th>
            <th onClick={() => toggleSort('emissions')} style={{ cursor: 'pointer' }}>Emissions (tCO₂e){arrow('emissions')}</th>
            <th onClick={() => toggleSort('intensity')} style={{ cursor: 'pointer' }}>Intensity (kg/MWh){arrow('intensity')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.carrier}>
              <td>
                <span
                  style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: row.color, marginRight: 6 }}
                />
                {row.carrier}
              </td>
              <td>{row.capacity > 0 ? num(row.capacity) : '—'}</td>
              <td>{num(row.generation)}</td>
              <td>{(row.share * 100).toFixed(1)}%</td>
              <td>{row.capacityFactor !== null ? `${(row.capacityFactor * 100).toFixed(1)}%` : '—'}</td>
              <td>{row.emissions > 0 ? num(row.emissions) : '—'}</td>
              <td>{row.intensity > 0 ? row.intensity.toFixed(0) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
