/**
 * CompositesCard — one row per composite asset (BESS, CCGT / OCGT, gas + H2 co-firing, P2X chain) of a stored run.
 *
 * Everything is served by `GET /api/build/plant/results/{run}` (a server-side groupby over the `plant` column); the browser only
 * formats it: output and capacity factor, starts by tier and the start cost, BESS equivalent cycles, H2 share and avoided CO2 for
 * co-firing, LCOH / product cost for a P2X chain. A value that does not apply to a composite is a dash.
 */
import React from 'react';
import { fetchPlantResults, type PlantResult } from 'lib/api/plants';
import { useAsync } from '../../../shared/hooks/useAsync';

interface Props {
  runName?: string | null;
  period?: number | null;
  currencySymbol?: string;
}

const num = (v: number | undefined | null, digits = 1): string =>
  v === undefined || v === null || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: digits });
const pct = (v: number | undefined | null): string => (v === undefined || v === null || !Number.isFinite(v) ? '—' : `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`);

/** "hot 3, warm 1, cold 0 (cost 12,000)" for a plant with start tiers; a plain count when no tier costs are set. */
function startsText(p: PlantResult): string {
  if (p.startCosts) {
    const tiers = Object.entries(p.startCosts.starts).map(([k, n]) => `${k} ${n}`).join(', ');
    return `${tiers}; cost ${num(p.startCosts.startCost, 0)}`;
  }
  return p.starts !== undefined ? num(p.starts, 0) : '—';
}

function fuelText(p: PlantResult): string {
  if (!p.fuel || !p.cofiring) return '—';                 // a plain CCGT / OCGT burns gas only: nothing to blend or avoid
  return `H2 ${pct(p.fuel.h2EnergyShare)} of fuel; avoided ${num(p.emissions?.avoidedT, 0)} tCO2 (${pct(p.emissions?.avoidedShare)})`;
}

function productText(p: PlantResult): string {
  if (!p.p2x) return '—';
  const parts = [`LCOH ${num(p.p2x.lcohPerKg, 2)} per kg H2`];
  for (const [prod, v] of Object.entries(p.p2x.products)) parts.push(`${prod} ${num(v.costPerTonne, 0)} per t`);
  return parts.join('; ');
}

export function CompositesCard({ runName, period, currencySymbol }: Props) {
  const { data, loading, error } = useAsync(runName ? `${runName}|${period ?? ''}|composites` : null, () => fetchPlantResults(runName as string, undefined, period ?? null));
  if (!runName) return <p className="dashboard-cell-missing">Composite results are read from a stored run; this result has none.</p>;
  if (error) return <p className="dashboard-cell-missing" role="alert">{/no plants/i.test(error) ? 'This run has no composite assets.' : `Could not load the composites: ${error}`}</p>;
  if (loading || !data) return <p className="dashboard-cell-missing" aria-busy="true">Loading the composites…</p>;
  if (data.plants.length === 0) return <p className="dashboard-cell-missing">This run has no composite assets.</p>;
  const cur = currencySymbol ?? data.currency;

  return (
    <div className="result-table-card" data-tour="composites-card">
      <table className="sg-table">
        <thead>
          <tr>
            <th>Composite</th><th>Type</th>
            <th className="sg-table__num">Capacity (MW)</th><th className="sg-table__num">Output (MWh)</th><th className="sg-table__num">Capacity factor</th>
            <th>Starts (by tier)</th><th className="sg-table__num">BESS cycles</th><th>Fuel and CO2 (co-firing)</th><th>Product cost (P2X)</th>
            <th className="sg-table__num">Total cost ({cur})</th>
          </tr>
        </thead>
        <tbody>
          {data.plants.map((p) => (
            <tr key={p.plantId}>
              <td title={p.label}>{p.plantId}</td>
              <td>{p.type ?? 'imported'}</td>
              <td className="sg-table__num">{num(p.capacityMwEl)}</td>
              <td className="sg-table__num" title={p.electricityInMwh !== undefined ? `H2 output; electricity in ${num(p.electricityInMwh, 0)} MWh` : undefined}>{num(p.generationMwh, 0)}</td>
              <td className="sg-table__num">{pct(p.capacityFactor)}</td>
              <td>{startsText(p)}</td>
              <td className="sg-table__num">{p.storage ? num(p.storage.equivalentCycles, 2) : '—'}</td>
              <td>{fuelText(p)}</td>
              <td>{productText(p)}</td>
              <td className="sg-table__num" title={`operating ${num(p.operatingCost, 0)}, fixed ${num(p.fixedCost, 0)}, fuel ${num(p.fuelCost, 0)}, commitment ${num(p.commitmentCost ?? 0, 0)}`}>{num(p.totalCost, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.plants.flatMap((p) => p.warnings.map((w) => <p key={`${p.plantId}:${w}`} className="result-table-card__note">{p.plantId}: {w}</p>))}
      <p className="result-table-card__note">
        Costs cover the window of the run ({num(data.windowYears, 4)} years). Start tiers follow the solved on/off status; the start cost is the sum over
        the tiers, of which PyPSA's own start_up_cost is the hot cost. Avoided CO2 compares the same dispatch burnt as 100 % gas.
      </p>
    </div>
  );
}
