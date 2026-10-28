/**
 * Portfolio builder — pick sites (or, at the region level, regions), set weights or optimise, read the metrics.
 *
 * At the region level the portfolio is over region series (weights per region; with one
 * series per region and technology, region caps limit a region's total across technologies).
 * Region portfolios are for screening: "Add to model" needs sites, so it is offered at the
 * site level only.
 *
 * Every number comes from the backend (`/metrics`, `/optimise`): mean CF, CV,
 * P10/P50/P90 (exceedance), low-output share, worst-N-hours loss, ramp
 * statistics, coincident-low probability per pair, ramp correlation. The
 * combined output duration curve and the risk/return plot are interactive
 * (hover, legend toggle, zoom). "Add selected sites to model" previews the
 * generators and the alignment of their profiles before anything is merged.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { WorkbookFragment } from 'lib/api/databases';
import {
  MetricsResponse,
  OptimiseResponse,
  PromoteResponse,
  Level,
  ScreenParams,
  fetchMetrics,
  fetchOptimise,
  promotePreview,
} from 'lib/api/screening';
import type { ChartTheme } from 'lib/charts/theme';
import {
  buildDurationOption,
  ScreeningUnit,
  buildFrontierOption,
  equalWeights,
  fmt,
  fmtPct,
  parseRegionCaps,
} from 'lib/screening/screening';
import { useAsync } from '../../shared/hooks/useAsync';
import { useDebouncedValue } from '../../shared/hooks/useDebouncedValue';
import { useToast } from '../../shared/components/Toast';
import { ChartPanel } from './ChartPanel';

interface Props {
  /** Window / clock part of the analysis params; the sites are the portfolio. */
  params: Omit<ScreenParams, 'sites'>;
  sites: ScreeningUnit[];
  /** `region`: the units are regions (no promotion to the model). */
  level: Level;
  selected: string[];
  siteColors: Record<string, string>;
  theme: ChartTheme;
  buses: Array<{ name: string; x: number; y: number }>;
  targetSnapshots: string[];
  currencySymbol: string;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

export function PortfolioPanel({ params, sites, level, selected, siteColors, theme, buses, targetSnapshots, currencySymbol, onApplyFragment }: Props) {
  const { showToast } = useToast();
  const regionLevel = level === 'region';
  const noun = regionLevel ? 'region' : 'site';
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [lowThreshold, setLowThreshold] = useState(0.05);
  const [worstN, setWorstN] = useState(100);
  const [objective, setObjective] = useState<'min_variance' | 'max_mean'>('min_variance');
  const [targetMean, setTargetMean] = useState('');
  const [stdCap, setStdCap] = useState('');
  const [maxWeight, setMaxWeight] = useState(1);
  const [regionText, setRegionText] = useState('');
  const [optimising, setOptimising] = useState(false);
  const [optError, setOptError] = useState<string | null>(null);
  const [optimised, setOptimised] = useState<OptimiseResponse | null>(null);
  const [promoteOpen, setPromoteOpen] = useState(false);

  // Keep the weight map aligned with the selection: new sites start at an equal share.
  useEffect(() => {
    setWeights((prev) => {
      const next: Record<string, number> = {};
      for (const s of selected) next[s] = s in prev ? prev[s] : 1 / Math.max(1, selected.length);
      return next;
    });
    setOptimised(null);
  }, [selected]);

  const positive = useMemo(() => Object.fromEntries(Object.entries(weights).filter(([k, w]) => selected.includes(k) && w > 0)), [weights, selected]);
  const debouncedWeights = useDebouncedValue(positive, 350);
  const settings = useMemo(() => ({ lowThreshold, worstN }), [lowThreshold, worstN]);
  const key = selected.length > 0 && Object.keys(debouncedWeights).length > 0
    ? JSON.stringify({ params, w: debouncedWeights, settings })
    : null;
  const metrics = useAsync<MetricsResponse>(key, () => fetchMetrics({ ...params, sites: Object.keys(debouncedWeights) }, debouncedWeights, settings));

  const byName = useMemo(() => new Map(sites.map((s) => [s.name, s] as const)), [sites]);
  const durationOption = useMemo(
    () => (metrics.data ? buildDurationOption(metrics.data.durationCurve, siteColors, theme) : null),
    [metrics.data, siteColors, theme],
  );
  const frontierOption = useMemo(() => {
    if (!optimised) return null;
    const per = (metrics.data?.perSite ?? optimised.metrics.perSite).map((s) => ({ site: s.site, meanCf: s.meanCf, std: s.std }));
    return buildFrontierOption(optimised, per, siteColors, theme);
  }, [optimised, metrics.data, siteColors, theme]);

  const runOptimise = async () => {
    setOptError(null);
    let regionCaps: Record<string, number> | undefined;
    try {
      regionCaps = parseRegionCaps(regionText);
    } catch (e) {
      setOptError(e instanceof Error ? e.message : String(e));
      return;
    }
    const std = Number(stdCap);
    const target = Number(targetMean);
    if (objective === 'max_mean' && !(std > 0)) {
      setOptError('Give a standard-deviation cap above zero (CF units, for example 0.15).');
      return;
    }
    setOptimising(true);
    try {
      const res = await fetchOptimise(
        { ...params, sites: selected },
        {
          objective,
          targetMeanCf: objective === 'min_variance' && targetMean.trim() && Number.isFinite(target) ? target : undefined,
          varianceCap: objective === 'max_mean' ? std * std : undefined,
          maxWeight,
          regionCaps,
          frontierPoints: 12,
        },
        settings,
      );
      setOptimised(res);
      setWeights(Object.fromEntries(selected.map((s) => [s, res.weights[s] ?? 0])));
    } catch (e) {
      setOptError(e instanceof Error ? e.message : String(e));
    } finally {
      setOptimising(false);
    }
  };

  const total = selected.reduce((a, s) => a + Math.max(0, weights[s] ?? 0), 0);
  const p = metrics.data?.portfolio;

  return (
    <div className="scr-card">
      <div className="scr-card-head">
        <h3>{regionLevel ? 'Region portfolio' : 'Portfolio'}</h3>
        {!regionLevel && <button className="tb-btn" disabled={selected.length === 0} onClick={() => setPromoteOpen(true)}>Add selected sites to model</button>}
      </div>
      {selected.length === 0 ? (
        <p className="scr-hint">Tick {noun}s in the table above to build a portfolio.</p>
      ) : (
        <>
          <div className="scr-field-row">
            <button className="tb-btn" onClick={() => { setWeights(equalWeights(selected)); setOptimised(null); }}>Equal weights</button>
            <span className="scr-hint">Weights are scaled to sum 1 (now {total.toFixed(2)}).</span>
          </div>
          <div className="scr-table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>{regionLevel ? 'Region' : 'Site'}</th><th>Technology</th><th>{regionLevel ? 'Region label' : 'Region'}</th><th>Mean CF</th><th>Weight</th></tr>
              </thead>
              <tbody>
                {selected.map((s) => (
                  <tr key={s}>
                    <td>{s}</td>
                    <td>{byName.get(s)?.technology}</td>
                    <td>{byName.get(s)?.region || ''}</td>
                    <td className="scr-num">{fmtPct(byName.get(s)?.meanCf ?? null)}</td>
                    <td>
                      <input
                        className="scr-input scr-input--short" type="number" min={0} step={0.05} aria-label={`Weight of ${s}`}
                        value={Number.isFinite(weights[s]) ? Number((weights[s] ?? 0).toFixed(4)) : 0}
                        onChange={(e) => { setWeights({ ...weights, [s]: Math.max(0, Number(e.target.value) || 0) }); setOptimised(null); }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="scr-field-row">
            <div className="scr-field">
              <span className="scr-label">Optimise</span>
              <select className="sg-setting-select" aria-label="Objective" value={objective} onChange={(e) => setObjective(e.target.value as 'min_variance' | 'max_mean')}>
                <option value="min_variance">Minimum variance</option>
                <option value="max_mean">Maximum mean CF</option>
              </select>
            </div>
            {objective === 'min_variance' ? (
              <div className="scr-field">
                <span className="scr-label">Mean CF at least</span>
                <input className="scr-input scr-input--short" aria-label="Target mean CF" placeholder="none" value={targetMean} onChange={(e) => setTargetMean(e.target.value)} />
              </div>
            ) : (
              <div className="scr-field">
                <span className="scr-label">Std of CF at most</span>
                <input className="scr-input scr-input--short" aria-label="Std cap" placeholder="0.15" value={stdCap} onChange={(e) => setStdCap(e.target.value)} />
              </div>
            )}
            <div className="scr-field">
              <span className="scr-label">Max weight per {noun}</span>
              <input className="scr-input scr-input--short" type="number" min={0.05} max={1} step={0.05} aria-label="Max weight" value={maxWeight} onChange={(e) => setMaxWeight(Math.min(1, Math.max(0.05, Number(e.target.value) || 1)))} />
            </div>
            <div className="scr-field">
              <span className="scr-label">Region caps (region:share){regionLevel ? ', total over its technologies' : ''}</span>
              <input className="scr-input" aria-label="Region caps" placeholder="north:0.5, south:0.6" value={regionText} onChange={(e) => setRegionText(e.target.value)} />
            </div>
            <button className="tb-btn" disabled={selected.length < 2 || optimising} onClick={runOptimise}>{optimising ? 'Optimising...' : 'Optimise'}</button>
          </div>
          {optError && <p className="scr-error">{optError}</p>}
          {optimised && <p className="scr-ok">Optimised: mean CF {fmt(optimised.meanCf, 3)}, std {fmt(optimised.std, 3)}. Weights applied above.</p>}

          <div className="scr-field-row">
            <div className="scr-field">
              <span className="scr-label">Low output below CF</span>
              <input className="scr-input scr-input--short" type="number" min={0} max={1} step={0.01} aria-label="Low threshold" value={lowThreshold} onChange={(e) => setLowThreshold(Math.min(1, Math.max(0, Number(e.target.value) || 0)))} />
            </div>
            <div className="scr-field">
              <span className="scr-label">Worst N hours</span>
              <input className="scr-input scr-input--short" type="number" min={1} step={10} aria-label="Worst N" value={worstN} onChange={(e) => setWorstN(Math.max(1, Math.round(Number(e.target.value) || 1)))} />
            </div>
          </div>

          {metrics.error && <p className="scr-error">{metrics.error}</p>}
          {metrics.loading && !metrics.data && <p className="scr-hint">Computing metrics...</p>}
          {metrics.data && p && (
            <>
              <div className="scr-table-scroll">
                <table className="data-table" data-testid="metrics-table">
                  <thead>
                    <tr>
                      <th>Series</th><th>Mean CF</th><th>CV</th><th>P10</th><th>P50</th><th>P90</th>
                      <th>Low-output share</th><th>Worst {metrics.data.worstN} h loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="scr-row-focus">
                      <td><strong>Portfolio</strong></td>
                      <td className="scr-num">{fmt(p.meanCf, 3)}</td><td className="scr-num">{fmt(p.cv, 3)}</td>
                      <td className="scr-num">{fmt(p.p10, 3)}</td><td className="scr-num">{fmt(p.p50, 3)}</td><td className="scr-num">{fmt(p.p90, 3)}</td>
                      <td className="scr-num">{fmtPct(p.lowOutputShare)}</td><td className="scr-num">{fmtPct(p.worstNLossFrac)}</td>
                    </tr>
                    {metrics.data.perSite.map((s) => (
                      <tr key={s.site}>
                        <td>{s.site} ({fmtPct(s.weight, 0)})</td>
                        <td className="scr-num">{fmt(s.meanCf, 3)}</td><td className="scr-num">{fmt(s.cv, 3)}</td>
                        <td className="scr-num">{fmt(s.p10, 3)}</td><td className="scr-num">{fmt(s.p50, 3)}</td><td className="scr-num">{fmt(s.p90, 3)}</td>
                        <td className="scr-num">{fmtPct(s.lowOutputShare)}</td><td className="scr-num">{fmtPct(s.worstNLossFrac)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="scr-hint">
                P90 is the output exceeded in 90% of the hours. Std {fmt(p.std, 3)}; diversification ratio {fmt(p.diversificationRatio, 2)};
                ramp std {fmt(p.rampStd, 3)} per step, largest ramp {fmt(p.maxRamp, 3)}; {metrics.data.nObs.toLocaleString()} observations.
              </p>
              <PairTable metrics={metrics.data} />
            </>
          )}
          <div className="scr-grid-2">
            <ChartPanel option={durationOption} loading={metrics.loading} error={null} emptyText="Select sites and weights to see the duration curve." label="Combined output duration curve" />
            <ChartPanel option={frontierOption} emptyText="Run Optimise to see the risk / return frontier." label="Risk and return" />
          </div>
        </>
      )}
      {promoteOpen && !regionLevel && (
        <PromoteDialog
          params={params} selected={selected} sites={sites} buses={buses} targetSnapshots={targetSnapshots}
          currencySymbol={currencySymbol}
          onClose={() => setPromoteOpen(false)}
          onConfirm={(fragment, resp) => {
            onApplyFragment(fragment, 'Siting screening', `${resp.generators.length} site(s)`);
            showToast(`Added ${resp.generators.length} generator(s) with p_max_pu profiles.`, 'success');
            setPromoteOpen(false);
          }}
        />
      )}
    </div>
  );
}

function PairTable({ metrics }: { metrics: MetricsResponse }) {
  const rows = useMemo(() => {
    const out: Array<{ a: string; b: string; both: number; indep: number; ramp: number | null }> = [];
    const { sites, matrix, independent } = metrics.coincidentLow;
    for (let i = 0; i < sites.length; i++) {
      for (let j = i + 1; j < sites.length; j++) {
        const rampIdx = [metrics.rampCorrelation.sites.indexOf(sites[i]), metrics.rampCorrelation.sites.indexOf(sites[j])];
        out.push({
          a: sites[i], b: sites[j], both: matrix[i][j] ?? 0, indep: independent[i][j] ?? 0,
          ramp: metrics.rampCorrelation.matrix[rampIdx[0]]?.[rampIdx[1]] ?? null,
        });
      }
    }
    return out;
  }, [metrics]);
  if (rows.length === 0) return null;
  return (
    <div className="scr-table-scroll">
      <table className="data-table" data-testid="pair-table">
        <thead>
          <tr><th>Pair</th><th>Both low</th><th>If independent</th><th>Ramp correlation</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.a}|${r.b}`}>
              <td>{r.a} / {r.b}</td>
              <td className="scr-num">{fmtPct(r.both, 2)}</td><td className="scr-num">{fmtPct(r.indep, 2)}</td><td className="scr-num">{fmt(r.ramp, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface DialogProps {
  params: Omit<ScreenParams, 'sites'>;
  selected: string[];
  sites: ScreeningUnit[];
  buses: Array<{ name: string; x: number; y: number }>;
  targetSnapshots: string[];
  currencySymbol: string;
  onClose: () => void;
  onConfirm: (fragment: WorkbookFragment, resp: PromoteResponse) => void;
}

/** Preview of the generators and of how their profiles align with the model's snapshots, before the merge. */
function PromoteDialog({ params, selected, sites, buses, targetSnapshots, currencySymbol, onClose, onConfirm }: DialogProps) {
  const [utcOffset, setUtcOffset] = useState(params.utcOffsetHours);
  const [extendable, setExtendable] = useState(false);
  const [capex, setCapex] = useState<Record<string, number>>({});
  const [pNom, setPNom] = useState<Record<string, string>>({});
  const [marginal, setMarginal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<PromoteResponse | null>(null);
  const techs = useMemo(() => Array.from(new Set(sites.filter((s) => selected.includes(s.name)).map((s) => s.technology))), [sites, selected]);

  // Any option change invalidates the preview: what is shown must be what is added.
  useEffect(() => { setResp(null); }, [utcOffset, extendable, capex, pNom, marginal]);

  const preview = async () => {
    setBusy(true);
    setError(null);
    try {
      const pn = Object.fromEntries(Object.entries(pNom).filter(([, v]) => Number(v) > 0).map(([k, v]) => [k, Number(v)]));
      setResp(await promotePreview({
        datasetId: params.datasetId, sites: selected, utcOffset: Math.round(utcOffset), pNomMw: pn, extendable,
        capitalCost: capex, marginalCost: marginal, buses, targetSnapshots,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Add selected sites to model">
      <div className="modal-card scr-modal-wide">
        <h3>Add {selected.length} site(s) to the model</h3>
        <p className="scr-hint">
          Each site becomes a generator on its nearest bus with a p_max_pu profile from the dataset, aligned to the model&apos;s
          {' '}{targetSnapshots.length.toLocaleString()} snapshots. Nothing changes until you confirm.
        </p>
        <div className="scr-field-row">
          <div className="scr-field">
            <span className="scr-label">Model clock = UTC +</span>
            <input className="scr-input scr-input--short" type="number" step={1} aria-label="Model UTC offset" value={utcOffset} onChange={(e) => setUtcOffset(Number(e.target.value) || 0)} />
          </div>
          <div className="scr-field">
            <span className="scr-label">Marginal cost ({currencySymbol}/MWh)</span>
            <input className="scr-input scr-input--short" type="number" min={0} aria-label="Marginal cost" value={marginal} onChange={(e) => setMarginal(Math.max(0, Number(e.target.value) || 0))} />
          </div>
          <label className="scr-label">
            <input type="checkbox" checked={extendable} onChange={(e) => setExtendable(e.target.checked)} /> Expansion candidates (start at 0 MW)
          </label>
        </div>
        {extendable && (
          <div className="scr-field-row">
            {techs.map((t) => (
              <div className="scr-field" key={t}>
                <span className="scr-label">{t} capex ({currencySymbol}/MW)</span>
                <input className="scr-input" type="number" min={0} aria-label={`${t} capex`} value={capex[t] ?? 0} onChange={(e) => setCapex({ ...capex, [t]: Math.max(0, Number(e.target.value) || 0) })} />
              </div>
            ))}
          </div>
        )}
        <div className="scr-table-scroll">
          <table className="data-table">
            <thead><tr><th>Site</th><th>{extendable ? 'Max MW' : 'MW'}</th></tr></thead>
            <tbody>
              {selected.map((s) => (
                <tr key={s}>
                  <td>{s}</td>
                  <td>
                    <input
                      className="scr-input scr-input--short" type="number" min={0} aria-label={`MW of ${s}`}
                      placeholder={String(sites.find((x) => x.name === s)?.capacityMw ?? 100)} value={pNom[s] ?? ''}
                      onChange={(e) => setPNom({ ...pNom, [s]: e.target.value })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {error && <p className="scr-error">{error}</p>}
        {resp && (
          <div className="scr-field" data-testid="promote-report">
            <p className={resp.report.ok ? 'scr-ok' : 'scr-error'}>
              {resp.report.ok ? 'Profiles align with the model.' : 'The profiles do not align with the model snapshots.'}{' '}
              {fmtPct(resp.report.exactShare, 0)} of snapshots matched exactly ({resp.report.mode === 'own-snapshots' ? 'the dataset window becomes the snapshot axis' : 'model snapshots kept'}).
            </p>
            {resp.report.warnings.map((w) => <p key={w} className="scr-warn">{w}</p>)}
            <div className="scr-table-scroll">
              <table className="data-table">
                <thead><tr><th>Generator</th><th>Bus</th><th>Distance</th><th>MW</th><th>Mean CF</th><th>Exact</th><th>Calendar</th><th>Hour mean</th><th>Unmatched</th></tr></thead>
                <tbody>
                  {resp.report.sites.map((s) => (
                    <tr key={s.generator}>
                      <td>{s.generator}</td><td>{s.bus}</td><td className="scr-num">{s.busDistanceKm === null ? 'set' : `${s.busDistanceKm} km`}</td>
                      <td className="scr-num">{s.pNomMw}</td><td className="scr-num">{fmt(s.meanCf, 3)}</td>
                      <td className="scr-num">{s.alignment.exact}</td><td className="scr-num">{s.alignment.monthDayHour}</td>
                      <td className="scr-num">{s.alignment.hourOfDay}</td><td className="scr-num">{s.alignment.unaligned}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="modal-actions">
          <button className="tb-btn tb-btn--muted" onClick={onClose}>Cancel</button>
          <button className="tb-btn" disabled={busy} onClick={preview}>{busy ? 'Previewing...' : 'Preview'}</button>
          <button className="tb-btn" disabled={!resp || !resp.fragment} onClick={() => resp?.fragment && onConfirm(resp.fragment, resp)}>Add to model</button>
        </div>
      </div>
    </div>
  );
}
