/**
 * EnergyBalanceCard (M1) — per-carrier supply vs demand for a sector-coupled run.
 *
 * For each energy vector (electricity, gas, H₂, heat…) two stacked bars show
 * where the energy came from (sources) and where it went (sinks). A gas→power
 * CCGT appears as a sink on gas (fuel burned) and a source on electricity (power
 * made) — the two sides of the conversion. Only shown for multi-carrier models.
 */
import React from 'react';
import { EnergyBalanceCarrier, EnergyBalanceFlow, EnergyBalanceResult } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';

interface Props {
  data: EnergyBalanceResult;
}

function energy(mwh: number): string {
  if (mwh >= 1e6) return `${(mwh / 1e6).toFixed(2)} TWh`;
  if (mwh >= 1e4) return `${(mwh / 1e3).toFixed(1)} GWh`;
  return `${Math.round(mwh).toLocaleString()} MWh`;
}

// Generation labels are fuel carriers → carrierColor; the rest get stable hues.
const KIND_COLOR: Record<string, string> = {
  load: 'var(--muted, #9ca3af)',
  conversion: '#8b5cf6',
  storage: '#0ea5e9',
};
const flowColor = (f: EnergyBalanceFlow): string =>
  f.kind === 'generation' ? carrierColor(f.label) : (KIND_COLOR[f.kind] ?? carrierColor(f.label));

function StackBar({ title, flows, total }: { title: string; flows: EnergyBalanceFlow[]; total: number }) {
  return (
    <div className="eb-bar-block">
      <div className="eb-bar-head">
        <span className="eb-bar-title">{title}</span>
        <span className="eb-bar-total">{energy(total)}</span>
      </div>
      <div className="eb-bar" style={{ display: 'flex', height: 18, width: '100%', borderRadius: 3, overflow: 'hidden', background: 'var(--surface-2, #f1f5f9)' }}>
        {flows.map((f) => (
          <div
            key={`${title}-${f.label}`}
            title={`${f.label}: ${energy(f.energyMWh)} (${total > 0 ? ((f.energyMWh / total) * 100).toFixed(0) : 0}%)`}
            style={{ width: `${total > 0 ? (f.energyMWh / total) * 100 : 0}%`, background: flowColor(f) }}
          />
        ))}
      </div>
    </div>
  );
}

function CarrierBlock({ c }: { c: EnergyBalanceCarrier }) {
  // Legend = union of sources + sinks, deduped by label, for a compact key.
  const legend: EnergyBalanceFlow[] = [];
  const seen = new Set<string>();
  for (const f of [...c.sources, ...c.sinks]) {
    if (!seen.has(f.label)) { seen.add(f.label); legend.push(f); }
  }
  return (
    <div className="eb-carrier" style={{ marginBottom: 18 }}>
      <div className="econ-section-label">
        <span className="carrier-dot" style={{ backgroundColor: carrierColor(c.carrier) }} /> {c.carrier}
      </div>
      <StackBar title="Supply" flows={c.sources} total={c.supplyMWh} />
      <StackBar title="Demand" flows={c.sinks} total={c.demandMWh} />
      <div className="eb-legend" style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 6 }}>
        {legend.map((f) => (
          <span key={f.label} className="eb-legend-item" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.78rem', color: 'var(--muted, #6b7280)' }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: flowColor(f), display: 'inline-block' }} />
            {f.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function EnergyBalanceCard({ data }: Props) {
  if (!data.carriers.length) {
    return <p className="dashboard-cell-missing">No multi-carrier energy balance for this run.</p>;
  }
  return (
    <div className="econ-card">
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Energy vectors</div>
          <div className="econ-kpi-value">{data.carriers.length}</div>
          <div className="econ-kpi-unit">{data.carriers.map((c) => c.carrier).join(' · ')}</div>
        </div>
      </div>
      <div className="econ-body">
        <div className="econ-table-col">
          {data.carriers.map((c) => <CarrierBlock key={c.carrier} c={c} />)}
        </div>
      </div>
      <p className="econ-note">
        Per-carrier supply vs demand over the modelled window (snapshot-weighted MWh). Conversion
        Links appear on both sides — as a sink on the input carrier (fuel consumed) and a source on
        the output carrier (energy produced), the loss being the efficiency gap. Link bus2+ outputs
        (CHP heat, CO₂ tracking) are not split out.
      </p>
    </div>
  );
}
