/**
 * Per-carrier operational analytics — the "Carrier performance" table.
 *
 * Capacity is INSTALLED NAMEPLATE from the input model: summed over every
 * installed generator of a carrier (input p_nom), independent of whether each
 * unit dispatched. "Generated capacity" is the subset that actually
 * produced energy (>0 MWh), so the two columns together reveal idle capacity.
 * Shares are each carrier's fraction of total nameplate / total energy.
 *
 *   - Capacity factor (CF) = energy / (nameplate capacity × modelled hours)
 *   - Curtailment          = Σ curtailed energy (renewables only), MWh
 *
 * Works for a live run (per-snapshot series in assetDetails) and a stored run
 * (light analytics bundle: assetDetails empty, energy from generatorEnergy and
 * capacity from outputs.static / the model sheet). Carriers used only by the
 * load-shedding backstop are excluded.
 */
import React from 'react';
import { RunResults, WorkbookModel } from 'lib/types';
import { numberValue, carrierColor, stringValue } from 'lib/utils/helpers';

interface Props {
  results: RunResults;
  currencySymbol: string;
  /** Input model — source of installed generators + nameplate p_nom + carriers. */
  model?: WorkbookModel;
}

interface CarrierRow {
  carrier: string;
  color: string;
  generatorCount: number;
  nameplateMw: number;
  capacityShare: number;
  generatedMw: number;
  energyMwh: number;
  generationShare: number;
  capacityFactor: number;
  curtailmentMwh: number | null;
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function pct(frac: number): string {
  return frac > 0 ? `${(frac * 100).toFixed(1)}%` : '—';
}

export function CarrierAnalysisCard({ results, model }: Props) {
  const snapshotWeight = results.runMeta.snapshotWeight ?? 1;
  const modelledHours = (results.runMeta.snapshotCount ?? 0) * snapshotWeight;
  if (modelledHours <= 0) return null;

  const staticGens = (results.outputs?.static?.['generators'] ?? {}) as Record<string, Record<string, unknown>>;
  const detail = results.assetDetails?.generators ?? {};
  const genEnergy = results.generatorEnergy ?? [];
  const geByName = new Map(genEnergy.filter((g) => g.name).map((g) => [g.name, g]));

  // Curtailment is only meaningful for generators with a time-varying p_max_pu
  // (renewables); a thermal unit running below p_nom is part-loaded, not curtailed.
  const tvGenNames = model?.['generators-p_max_pu']?.length
    ? new Set(Object.keys(model['generators-p_max_pu'][0]))
    : null;

  // Capacity = installed nameplate from the INPUT model (p_nom). Fall back to the
  // solved p_nom_opt only when an input p_nom isn't available (e.g. the model
  // sheet is missing), so the total always reconciles with the headline KPI.
  const nameplateOf = (name: string, pNomIn: number): number => {
    if (pNomIn > 0) return pNomIn;
    return numberValue(staticGens[name]?.['p_nom_opt'] as string | number | undefined);
  };

  // Per-generator record over the FULL installed fleet (energy 0 ⇒ idle).
  interface Rec { carrier: string; nameplate: number; energy: number; curt: number; hasCurt: boolean; }
  const recs = new Map<string, Rec>();

  const addRec = (name: string, carrier: string, nameplate: number): void => {
    if (!name || name.startsWith('load_shedding_') || recs.has(name)) return;
    let energy = 0;
    let curt = 0;
    let hasCurt = false;
    const d = detail[name];
    if (d) {
      // Live run: integrate the per-snapshot series.
      for (let i = 0; i < d.outputSeries.length; i++) energy += Math.max(0, d.outputSeries[i].output) * snapshotWeight;
      if (!tvGenNames || tvGenNames.has(name)) {
        for (let i = 0; i < d.curtailmentSeries.length; i++) curt += Math.max(0, d.curtailmentSeries[i]?.curtailment ?? 0) * snapshotWeight;
        hasCurt = true;
      }
      // Safety net: if no input p_nom was available, fall back to peak availability
      // (= p_nom × max p_max_pu) so a live run never reports zero capacity.
      if (nameplate <= 0) nameplate = d.availableSeries.reduce((m, p) => Math.max(m, p.available), 0);
    } else {
      // Stored run: pre-aggregated energy + curtailment (absent ⇒ idle, 0).
      const ge = geByName.get(name);
      if (ge) {
        energy = ge.value;
        if (ge.curtailmentMwh != null) { curt = ge.curtailmentMwh; hasCurt = true; }
      }
    }
    recs.set(name, { carrier: carrier || 'Other', nameplate, energy, curt, hasCurt });
  };

  // The installed universe comes from the model sheet (which excludes the
  // synthetic load-shedding backstop). Fall back to whatever the result carries
  // when the model isn't available.
  if (model?.generators?.length) {
    for (const r of model.generators) {
      const name = stringValue(r.name);
      if (!name) continue;
      addRec(name, stringValue(r.carrier), nameplateOf(name, numberValue(r.p_nom)));
    }
  } else {
    const names = Array.from(new Set<string>([...Object.keys(detail), ...genEnergy.map((g) => g.name)]));
    names.forEach((name) => {
      const carrier = detail[name]?.carrier ?? geByName.get(name)?.carrier ?? 'Other';
      addRec(name, carrier, nameplateOf(name, numberValue(staticGens[name]?.['p_nom'] as string | number | undefined)));
    });
  }

  if (recs.size === 0) return null;

  interface Bucket { count: number; nameplate: number; generated: number; energy: number; curt: number; hasCurt: boolean; }
  const byCarrier = new Map<string, Bucket>();
  Array.from(recs.values()).forEach((r) => {
    let b = byCarrier.get(r.carrier);
    if (!b) { b = { count: 0, nameplate: 0, generated: 0, energy: 0, curt: 0, hasCurt: false }; byCarrier.set(r.carrier, b); }
    b.count += 1;
    b.nameplate += r.nameplate;
    if (r.energy > 0) b.generated += r.nameplate;
    b.energy += r.energy;
    if (r.hasCurt) { b.curt += r.curt; b.hasCurt = true; }
  });

  const totalNameplate = Array.from(byCarrier.values()).reduce((s, b) => s + b.nameplate, 0);
  const totalEnergy = Array.from(byCarrier.values()).reduce((s, b) => s + b.energy, 0);

  const rows: CarrierRow[] = Array.from(byCarrier.entries()).map(([carrier, b]) => ({
    carrier,
    color: carrierColor(carrier),
    generatorCount: b.count,
    nameplateMw: b.nameplate,
    capacityShare: totalNameplate > 0 ? b.nameplate / totalNameplate : 0,
    generatedMw: b.generated,
    energyMwh: b.energy,
    generationShare: totalEnergy > 0 ? b.energy / totalEnergy : 0,
    capacityFactor: b.nameplate > 0 ? b.energy / (b.nameplate * modelledHours) : 0,
    curtailmentMwh: b.hasCurt ? b.curt : null,
  })).sort((a, b) => b.energyMwh - a.energyMwh);

  if (rows.length === 0) return null;

  const totals = {
    count: rows.reduce((s, r) => s + r.generatorCount, 0),
    nameplate: totalNameplate,
    generated: rows.reduce((s, r) => s + r.generatedMw, 0),
    energy: totalEnergy,
    curtailment: rows.some((r) => r.curtailmentMwh != null)
      ? rows.reduce((s, r) => s + (r.curtailmentMwh ?? 0), 0)
      : null,
  };

  return (
    <div className="stochastic-card">
      <div className="stochastic-card-header">
        <div>
          <h3>Carrier performance</h3>
          <p>
            Capacity is installed nameplate (all units); <b>Generated cap.</b> is the
            portion that produced energy, so the gap is idle capacity. CF is energy ÷
            (nameplate × modelled hours). Load-shedding backstop excluded.
          </p>
        </div>
      </div>
      <div className="carrier-table-wrap">
        <table className="stochastic-table carrier-perf-table">
          <thead>
            <tr>
              <th>Carrier</th>
              <th>Generators</th>
              <th>Nameplate cap. (MW)</th>
              <th>Cap. share</th>
              <th>Generated cap. (MW)</th>
              <th>Energy (MWh)</th>
              <th>Gen. share</th>
              <th>CF</th>
              <th>Curtailment (MWh)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.carrier}>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 999, background: r.color }} />
                    {r.carrier}
                  </span>
                </td>
                <td>{r.generatorCount}</td>
                <td>{fmt(r.nameplateMw)}</td>
                <td>{pct(r.capacityShare)}</td>
                <td>{fmt(r.generatedMw)}</td>
                <td>{fmt(r.energyMwh)}</td>
                <td>{pct(r.generationShare)}</td>
                <td>{r.capacityFactor > 0 ? `${(r.capacityFactor * 100).toFixed(1)}%` : '—'}</td>
                <td>{r.curtailmentMwh === null || r.curtailmentMwh <= 0 ? '—' : fmt(r.curtailmentMwh)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="carrier-perf-total">
              <td>Total</td>
              <td>{totals.count}</td>
              <td>{fmt(totals.nameplate)}</td>
              <td>100%</td>
              <td>{fmt(totals.generated)}</td>
              <td>{fmt(totals.energy)}</td>
              <td>100%</td>
              <td>—</td>
              <td>{totals.curtailment === null || totals.curtailment <= 0 ? '—' : fmt(totals.curtailment)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
