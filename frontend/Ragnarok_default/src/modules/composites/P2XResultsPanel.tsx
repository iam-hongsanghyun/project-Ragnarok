/**
 * ResultsPanel — P2X results of a stored run: LCOH, LCOA, LCOM and e-fuel cost, a cost waterfall, electrolyser
 * dispatch against the designated RES, H2 store state of charge, and the RFNBO compliance table. Every number is
 * computed by the backend (`/api/p2x/results/{run}`); this component only draws it.
 */
import React from 'react';
import type { CheckRow, P2XResults } from 'lib/api/p2x';
import { fetchP2XResults } from 'lib/api/p2x';
import { fetchReportRuns } from 'lib/api/reports';
import type { ReportRunOption } from 'lib/reporting/types';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../shared/echarts/useEChart';
import { buildDispatchOption, buildSocOption, buildWaterfallOption } from './charts';
import { pathwayPeriodsOf } from './pathway';

const fmt = (v: number | undefined | null, digits = 2): string =>
  v === undefined || v === null || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: digits });
const pct = (v: number | undefined): string => (v === undefined || !Number.isFinite(v) ? '—' : `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`);

function Chart({ option, label, tall }: { option: Parameters<typeof useEChart>[0]; label: string; tall?: boolean }) {
  const ref = useEChart<HTMLDivElement>(option);
  return <div ref={ref} className={`p2x-chart${tall ? ' p2x-chart--tall' : ''} echart-host`} role="img" aria-label={label} />;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="p2x-kpi"><div className="p2x-kpi-label">{label}</div><div className="p2x-kpi-value">{value}</div>{sub && <div className="p2x-kpi-sub">{sub}</div>}</div>;
}

function Checks({ title, rows }: { title: string; rows: CheckRow[] }) {
  return (
    <>
      <h4>{title}</h4>
      {rows.length === 0 ? <p className="p2x-src">No designated generators.</p> : (
        <table className="p2x-table" aria-label={title}>
          <thead><tr><th>Generator</th><th>Status</th><th>Why</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.generator}><td>{r.generator}</td><td><span className={`p2x-chip p2x-chip--${r.status}`}>{r.status}</span></td><td>{r.reason}</td></tr>)}</tbody>
        </table>
      )}
    </>
  );
}

interface Props {
  /** The Results section owns the run picker: pass the list and the chosen run and this panel shows no picker of its own. */
  runs?: ReportRunOption[];
  run?: string;
}

export function P2XResultsPanel({ runs: runsProp, run: runProp }: Props) {
  const [ownRuns, setRuns] = React.useState<ReportRunOption[]>([]);
  const [ownRun, setRun] = React.useState('');
  const runs = runsProp ?? ownRuns;
  const run = runProp ?? ownRun;
  const [period, setPeriod] = React.useState('');
  const pathway = React.useMemo(() => pathwayPeriodsOf(runs.find((r) => r.name === run)), [runs, run]);
  // a period only means something for a pathway run: drop a stale pick when the run changes to a single-period one
  React.useEffect(() => {
    if (!pathway.isPathway || (period !== '' && !pathway.periods.includes(Number(period)))) setPeriod('');
  }, [pathway, period]);
  const [mode, setMode] = React.useState<'nodal' | 'ppa'>('nodal');
  const [chain, setChain] = React.useState('');
  const [product, setProduct] = React.useState('H2');
  const [data, setData] = React.useState<P2XResults | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [fitAxis, setFitAxis] = React.useState(true);

  React.useEffect(() => {
    if (runsProp) return undefined;
    let live = true;
    fetchReportRuns()
      .then((list) => { if (live) { setRuns(list); setRun((cur) => cur || list[0]?.name || ''); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!run) return undefined;
    let live = true;
    setBusy(true); setError(null);
    const p = period.trim() === '' ? null : Number(period);
    fetchP2XResults(run, { period: p !== null && Number.isFinite(p) ? p : null, electricityCost: mode, chainId: chain || null })
      .then((r) => { if (live) { setData(r); setProduct((cur) => (cur === 'H2' || r.products[cur] ? cur : 'H2')); } })
      .catch((e) => { if (live) { setData(null); setError(e instanceof Error ? e.message : String(e)); } })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [run, period, mode, chain]);

  const theme = React.useMemo(() => readChartTheme(), []);
  const waterfall = React.useMemo(() => {
    if (!data) return null;
    const w = product === 'H2' ? data.lcoh.waterfall : data.products[product]?.waterfall;
    if (!w) return null;
    const unit = product === 'H2' ? `${data.currency}/kg H2` : product === 'eFuel' ? `${data.currency}/MWh` : `${data.currency}/t ${product}`;
    return buildWaterfallOption({ steps: w.steps, unit, theme });
  }, [data, product, theme]);
  const dispatch = React.useMemo(() => (data ? buildDispatchOption({ snapshots: data.series.snapshots, electrolyserMw: data.series.electrolyserMw, designatedMw: data.series.designatedMw, gridMw: data.series.gridMw, theme, fitToElectrolyser: fitAxis }) : null), [data, theme, fitAxis]);
  const soc = React.useMemo(() => (data && data.series.h2SocTonnes.length > 0 ? buildSocOption({ snapshots: data.series.snapshots, socTonnes: data.series.h2SocTonnes, theme }) : null), [data, theme]);

  const cur = data?.currency ?? '';
  const comp = data?.rfnbo.compliance;
  const ga = data?.rfnbo.gridAlternatives;

  return (
    <div className="p2x-results">
      <div className="p2x-card">
        <div className="p2x-row">
          {!runsProp && (<>
            <label htmlFor="p2x-run" style={{ minWidth: 0 }}>Stored run</label>
            <select id="p2x-run" value={run} onChange={(e) => setRun(e.target.value)} disabled={runs.length === 0}>
              {runs.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
            </select></>)}
          <label htmlFor="p2x-mode" style={{ minWidth: 0 }}>Electricity cost</label>
          <select id="p2x-mode" value={mode} onChange={(e) => setMode(e.target.value as 'nodal' | 'ppa')}>
            <option value="nodal">Nodal price × consumption</option><option value="ppa">PPA cost of the designated generators</option>
          </select>
          {data && data.chains.length > 1 && (<>
            <label htmlFor="p2x-chain" style={{ minWidth: 0 }}>Chain</label>
            <select id="p2x-chain" value={chain || data.chainId} onChange={(e) => setChain(e.target.value)}>{data.chains.map((c) => <option key={c} value={c}>{c}</option>)}</select></>)}
          <label htmlFor="p2x-period" style={{ minWidth: 0 }}>Period</label>
          {pathway.isPathway ? (
            <select id="p2x-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="">whole horizon</option>
              {pathway.periods.map((p) => <option key={p} value={String(p)}>{p}</option>)}
            </select>
          ) : (
            <select id="p2x-period" value="" disabled title="Only a pathway (multi-period) run has investment periods"><option value="">single-period run</option></select>
          )}
        </div>
        {runs.length === 0 && !error && <p className="p2x-note">No stored runs yet. Add a P2X composite, solve the model, then come back.</p>}
        {error && <div className="p2x-error" role="alert">{error}</div>}
        {busy && <p className="p2x-src">Reading the run…</p>}
      </div>

      {data && (<>
        {data.warnings.map((w) => <div key={w} className="p2x-warn">{w}</div>)}
        {data.electricityCostRequested !== data.electricityCost && <div className="p2x-warn">PPA electricity cost needs designated generators; nodal price was used.</div>}
        <div className="p2x-kpis">
          <Kpi label="LCOH" value={`${fmt(data.lcoh.perKg)} ${cur}/kg`} sub={`${fmt(data.lcoh.h2Kg / 1000, 1)} t H2 · electricity ${data.electricityCost}`} />
          {data.products.NH3 && <Kpi label="LCOA" value={`${fmt(data.products.NH3.costPerTonne, 0)} ${cur}/t NH3`} sub={`${fmt(data.products.NH3.producedTonnes, 1)} t produced`} />}
          {data.products.MeOH && <Kpi label="LCOM" value={`${fmt(data.products.MeOH.costPerTonne, 0)} ${cur}/t MeOH`} sub={`${fmt(data.products.MeOH.producedTonnes, 1)} t produced`} />}
          {data.products.eFuel && <Kpi label="E-fuel" value={`${fmt(data.products.eFuel.costPerMwh, 1)} ${cur}/MWh`} sub={`${fmt(data.products.eFuel.costPerLitre, 2)} ${cur}/litre`} />}
          <Kpi label="Electrolyser capacity factor" value={pct(data.electrolyser.capacityFactor)} sub={`${fmt(data.electrolyser.fullLoadHoursPerYear, 0)} full-load h/yr · ${fmt(data.electrolyser.capacityMw, 1)} MW`} />
          {comp && <Kpi label="Hourly compliant hours" value={pct(comp.hourly.compliantShareOfOperating)} sub={`${fmt(comp.hourly.unmatchedMwh, 1)} MWh unmatched · matching ${data.rfnbo.matchingEnabled ? 'on' : 'off'}`} />}
        </div>

        <div className="p2x-grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
          <div className="p2x-card">
            <h3>Cost waterfall</h3>
            <div className="p2x-row"><label htmlFor="p2x-prod" style={{ minWidth: 0 }}>Product</label>
              <select id="p2x-prod" value={product} onChange={(e) => setProduct(e.target.value)}>
                <option value="H2">Hydrogen</option>{Object.values(data.products).map((p) => <option key={p.product} value={p.product}>{p.label}</option>)}
              </select></div>
            {waterfall && <Chart option={waterfall} label="Cost waterfall" tall />}
          </div>
          <div className="p2x-card">
            <h3>H2 store state of charge</h3>
            {soc ? <Chart option={soc} label="H2 store state of charge" tall /> : <p className="p2x-note">This chain has no H2 store.</p>}
            <p className="p2x-src">Cyclic: the store ends the horizon where it began.</p>
          </div>
        </div>

        <div className="p2x-card">
          <h3>Electrolyser dispatch against the designated RES</h3>
          {data.rfnbo.designated.length === 0
            ? <p className="p2x-note">No designated generators were set, so no matching can be shown. Pick them under Connections when adding the P2X composite.</p>
            : <p className="p2x-src">Designated: {data.rfnbo.designated.join(', ')}. Drag or scroll to zoom.</p>}
          <div className="p2x-row"><label style={{ minWidth: 0 }}><input type="checkbox" checked={fitAxis} onChange={(e) => setFitAxis(e.target.checked)} /> Fit the MW axis to the electrolyser (the designated fleet is clipped where it is far larger)</label></div>
          {dispatch && <Chart option={dispatch} label="Electrolyser dispatch against the designated RES" tall />}
        </div>

        {comp && (
          <div className="p2x-card">
            <h3>RFNBO matching compliance</h3>
            <p className="p2x-src">{data.rfnbo.regulation}. Computed from the dispatch whether or not matching was on in the solve; with matching off the shortfall is the electricity that could not be matched.</p>
            <table className="p2x-table" aria-label="Compliance summary">
              <thead><tr><th>Regime</th><th className="num">Operating periods</th><th className="num">Compliant</th><th className="num">Share</th><th className="num">Unmatched MWh</th><th className="num">Unmatched share</th></tr></thead>
              <tbody>
                {([['Hourly (from 1 Jan 2030)', comp.hourly], ['Monthly (until 31 Dec 2029)', comp.monthly]] as const).map(([label, r]) => (
                  <tr key={label}><td>{label}</td><td className="num">{r.operatingPeriods}</td><td className="num">{r.compliantOperatingPeriods}</td>
                    <td className="num">{pct(r.compliantShareOfOperating)}</td><td className="num">{fmt(r.unmatchedMwh, 1)}</td><td className="num">{pct(r.unmatchedShareOfElectrolyserEnergy)}</td></tr>
                ))}
              </tbody>
            </table>
            {comp.art63.enabled && <p className="p2x-src">Art. 6(3): {comp.art63.operatingPeriodsAtOrBelow} operating period(s) at or below {comp.art63.thresholdEurPerMwh} EUR/MWh are compliant whatever the matching.</p>}
            <h4>By month</h4>
            <table className="p2x-table" aria-label="Compliance by month">
              <thead><tr><th>Month</th><th className="num">Electrolyser MWh</th><th className="num">Designated MWh</th><th className="num">Unmatched (hourly) MWh</th><th className="num">Unmatched (monthly) MWh</th></tr></thead>
              <tbody>{comp.months.map((m) => <tr key={m.month}><td>{m.month}</td><td className="num">{fmt(m.electrolyserMwh, 1)}</td><td className="num">{fmt(m.designatedMwh, 1)}</td><td className="num">{fmt(m.unmatchedHourlyMwh, 1)}</td><td className="num">{fmt(m.unmatchedMonthlyMwh, 1)}</td></tr>)}</tbody>
            </table>
          </div>
        )}

        <div className="p2x-card">
          <h3>Additionality, geography and grid alternatives</h3>
          <Checks title="Additionality (Art. 5(a))" rows={data.rfnbo.checks.additionality} />
          <Checks title="Geographic correlation (Art. 7(1)(a))" rows={data.rfnbo.checks.geographic} />
          {ga && (<>
            <h4>Grid-electricity alternatives (Art. 4, reported only)</h4>
            <table className="p2x-table" aria-label="Grid alternatives">
              <tbody>
                <tr><td>Art. 4(1) renewable share</td><td className="num">{pct(ga.art41.renewableShare)} (threshold {pct(ga.art41.threshold)})</td><td><span className={`p2x-chip p2x-chip--${ga.art41.pass ? 'pass' : 'fail'}`}>{ga.art41.pass ? 'pass' : 'fail'}</span></td></tr>
                <tr><td>Art. 4(2) emission intensity</td><td className="num">{fmt(ga.art42.emissionIntensityGPerMj, 1)} g/MJ (threshold {ga.art42.threshold})</td><td><span className={`p2x-chip p2x-chip--${ga.art42.pass ? 'pass' : 'fail'}`}>{ga.art42.pass ? 'pass' : 'fail'}</span></td></tr>
              </tbody>
            </table>
          </>)}
        </div>
        <p className="p2x-src">{data.basis}</p>
      </>)}
    </div>
  );
}
