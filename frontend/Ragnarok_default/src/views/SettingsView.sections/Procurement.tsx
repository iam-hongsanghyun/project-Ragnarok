/**
 * Procurement surface (PP2) — a use-case tool, not a config panel.
 *
 * Goal → instruments → risk budget → answer, computed live against a price
 * series (your last run's cleared prices, or a stated reference assumption).
 * The question it answers: "How do I cover my load at the least expected cost
 * without my worst-case bill blowing past a budget?" — solved as a
 * CVaR-constrained mix of spot + PPA + forward + retail, with the full
 * cost-vs-risk efficient frontier.
 *
 * Distinct from the Settings sections around it: it does not gate the next
 * solve — it calls the procurement optimizer directly and shows the answer now.
 */
import React from 'react';
import { ValuePoint } from 'lib/types';
import {
  ProcurementResult,
  optimizeProcurement,
} from 'lib/api/procurement';

export interface ProcurementSectionProps {
  /** The last run's cleared system price series, if a run has completed. */
  priceSeries: ValuePoint[] | null;
  /** The last run's total dispatch (≈ load) per snapshot, for a load-shaped profile. */
  loadShape?: number[] | null;
  currency: string;
}

interface InstrumentState {
  ppa: { enabled: boolean; strike: number; maxMw: number };
  forward: { enabled: boolean; price: number; maxMw: number };
  retail: { enabled: boolean; price: number };
}

const LABELS: Record<string, string> = {
  ppa: 'Fixed-price PPA',
  forward: 'Forward block',
  retail: 'Retail tariff',
};

// A stated reference price when no run exists yet: a weekly (168 h) shape with a
// daily peak, scaled by the user's mean and volatility. Clearly an assumption —
// labelled as such in the UI — not fabricated market data.
function referenceSeries(mean: number, volatilityPct: number): number[] {
  const vol = volatilityPct / 100;
  const out: number[] = [];
  for (let h = 0; h < 168; h++) {
    const hour = h % 24;
    const daily = Math.sin(((hour - 6) / 24) * 2 * Math.PI); // trough ~06:00, peak ~18:00
    const weekend = h >= 120 ? 0.85 : 1.0;
    out.push(Math.max(0, mean * weekend * (1 + vol * daily)));
  }
  return out;
}

export function ProcurementSection(props: ProcurementSectionProps) {
  const c = props.currency;
  const runPrices = React.useMemo(
    () => (props.priceSeries ?? []).map((p) => p.value).filter((v) => Number.isFinite(v)),
    [props.priceSeries],
  );
  const haveRun = runPrices.length >= 2;

  const [source, setSource] = React.useState<'run' | 'reference'>(haveRun ? 'run' : 'reference');
  const [refMean, setRefMean] = React.useState(60);
  const [refVol, setRefVol] = React.useState(40);
  const [loadMw, setLoadMw] = React.useState(100);
  const [growthPct, setGrowthPct] = React.useState(0);
  const [loadShaped, setLoadShaped] = React.useState(false);

  // Normalised run load shape (mean 1), aligned to the price series length.
  const loadShape = React.useMemo(() => {
    const raw = (props.loadShape ?? []).filter((v) => Number.isFinite(v) && v > 0);
    if (raw.length < 2) return null;
    const mean = raw.reduce((a, b) => a + b, 0) / raw.length;
    return mean > 0 ? raw.map((v) => v / mean) : null;
  }, [props.loadShape]);
  const canShape = source === 'run' && !!loadShape;

  const [inst, setInst] = React.useState<InstrumentState>({
    ppa: { enabled: true, strike: 60, maxMw: 100 },
    forward: { enabled: false, price: 62, maxMw: 100 },
    retail: { enabled: false, price: 68 },
  });
  const [alpha, setAlpha] = React.useState(0.95);
  const [budgetFrac, setBudgetFrac] = React.useState(1); // 0 = min risk, 1 = min cost
  const [stress2x, setStress2x] = React.useState(true);

  const [result, setResult] = React.useState<ProcurementResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const prices = source === 'run' ? runPrices : referenceSeries(refMean, refVol);
  const avgPrice = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : 0;
  const anyInstrument = inst.ppa.enabled || inst.forward.enabled || inst.retail.enabled;

  // Effective load: flat volume (optionally shaped by the run's load profile),
  // scaled by the demand-growth factor.
  const effectiveLoad = React.useMemo((): number | number[] => {
    const g = 1 + growthPct / 100;
    if (loadShaped && canShape && loadShape) {
      return loadShape.slice(0, prices.length).map((s) => loadMw * s * g);
    }
    return loadMw * g;
  }, [loadShaped, canShape, loadShape, prices.length, loadMw, growthPct]);

  const runOptimize = React.useCallback(async (cvarBudget: number | null) => {
    if (prices.length < 2 || !anyInstrument) return;
    setBusy(true);
    setError(null);
    try {
      const res = await optimizeProcurement({
        prices,
        loadMw: effectiveLoad,
        ppa: inst.ppa,
        forward: inst.forward,
        retail: inst.retail,
        alpha,
        cvarBudget,
        bootstrap: 200,
        blockHours: prices.length >= 48 ? 24 : 6,
        stress: stress2x ? [{ label: 'Price ×2 stress', multiplier: 2 }] : [],
        currency: c,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, [prices, effectiveLoad, inst, alpha, stress2x, anyInstrument, c]);

  // Translate the frontier slider (0..1) into an absolute CVaR budget once a
  // frontier exists; 1.0 means "no budget" (pure min expected cost).
  const budgetFromFrac = (res: ProcurementResult, frac: number): number | null => {
    if (frac >= 0.999) return null;
    const { minCvar, maxCvar } = res.riskRange;
    return minCvar + frac * (maxCvar - minCvar);
  };

  const onSliderCommit = (frac: number) => {
    setBudgetFrac(frac);
    if (result) runOptimize(budgetFromFrac(result, frac));
  };

  const optimal = result?.optimal ?? null;
  const savingsPct =
    result && optimal && result.baseline.expectedCost > 0
      ? (1 - optimal.expectedCost / result.baseline.expectedCost) * 100
      : 0;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Procurement strategy</h3>
        <p>
          Cover your load at the least expected cost <em>without</em> letting the
          worst-case bill run past a risk budget. Pick the instruments you can
          actually sign, set how much tail risk you'll tolerate, and read off the
          optimal mix and the whole cost-vs-risk frontier. This answers the
          question directly — it does not change your next solve.
        </p>
      </header>

      {/* ── Price source ─────────────────────────────────────────────── */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">Price basis</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${source === 'run' ? '' : ' tb-btn--muted'}`}
            disabled={!haveRun}
            title={haveRun ? undefined : 'Run a market simulation or an optimisation first'}
            onClick={() => setSource('run')}
          >
            Last run's prices
          </button>
          <button
            className={`tb-btn sg-solver-btn${source === 'reference' ? '' : ' tb-btn--muted'}`}
            onClick={() => setSource('reference')}
          >
            Reference assumption
          </button>
        </div>
        {source === 'run' ? (
          <p className="sg-setting-hint">
            {haveRun
              ? `Using ${runPrices.length} h of cleared prices from your last run · average ${c}${avgPrice.toFixed(1)}/MWh.`
              : 'No run yet — run a market simulation or an optimisation to hedge against real cleared prices.'}
          </p>
        ) : (
          <p className="sg-setting-hint">
            A stated weekly price shape (daily peak) — an assumption for exploring,
            not market data. Average {c}{avgPrice.toFixed(1)}/MWh.
          </p>
        )}
      </div>

      {source === 'reference' && (
        <div className="sg-setting-row">
          <label className="sg-setting-label">Reference price (mean · volatility %)</label>
          <div className="sg-btn-row" style={{ gap: 8 }}>
            <input
              type="number" className="sg-number-input" min={0} step={5}
              value={refMean}
              onChange={(e) => setRefMean(Math.max(0, Number(e.target.value) || 0))}
            />
            <input
              type="number" className="sg-number-input" min={0} max={200} step={5}
              value={refVol}
              onChange={(e) => setRefVol(Math.min(200, Math.max(0, Number(e.target.value) || 0)))}
            />
          </div>
        </div>
      )}

      <div className="sg-setting-row">
        <label className="sg-setting-label">Load to cover (MW) · demand growth %</label>
        <div className="sg-btn-row" style={{ gap: 8 }}>
          <input
            type="number" className="sg-number-input" min={0} step={10}
            value={loadMw}
            onChange={(e) => setLoadMw(Math.max(0, Number(e.target.value) || 0))}
          />
          <input
            type="number" className="sg-number-input" min={-50} max={200} step={5}
            value={growthPct} title="scale the load up/down (sensitivity)"
            onChange={(e) => setGrowthPct(Math.max(-50, Math.min(200, Number(e.target.value) || 0)))}
          />
        </div>
        <p className="sg-setting-hint">
          The volume you need to procure, scaled by demand growth. Growth is a sensitivity knob —
          push it up to see how the optimal mix and cost shift if demand rises.
        </p>
      </div>
      {canShape && (
        <div className="sg-setting-row">
          <label className="sg-setting-label">Load profile</label>
          <div className="sg-btn-row">
            <button
              className={`tb-btn sg-solver-btn${!loadShaped ? '' : ' tb-btn--muted'}`}
              onClick={() => setLoadShaped(false)}
            >
              Flat (baseload)
            </button>
            <button
              className={`tb-btn sg-solver-btn${loadShaped ? '' : ' tb-btn--muted'}`}
              onClick={() => setLoadShaped(true)}
            >
              Run's load shape
            </button>
          </div>
          <p className="sg-setting-hint">
            Flat treats the volume as baseload; the run's shape scales it hour-by-hour to your
            demand profile, so hedging correctly weights the peak-price/peak-load hours.
          </p>
        </div>
      )}

      {/* ── Instruments ──────────────────────────────────────────────── */}
      <div className="sg-setting-divider" />
      <div className="sg-setting-row">
        <label className="sg-setting-label">Instruments</label>
        <p className="sg-setting-hint">
          Spot is always available (the residual settles at spot). Toggle the hedges
          you can sign and set their prices. Prices below the spot average lower
          expected cost; a fixed price above it costs a premium but caps the tail.
        </p>
      </div>

      {/* PPA */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">
          <button
            className={`tb-btn sg-solver-btn${inst.ppa.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => setInst((s) => ({ ...s, ppa: { ...s.ppa, enabled: !s.ppa.enabled } }))}
          >
            PPA {inst.ppa.enabled ? 'on' : 'off'}
          </button>
        </label>
        {inst.ppa.enabled && (
          <div className="sg-btn-row" style={{ gap: 8 }}>
            <input type="number" className="sg-number-input" min={0} step={1}
              value={inst.ppa.strike} title="Strike price (per MWh)"
              onChange={(e) => setInst((s) => ({ ...s, ppa: { ...s.ppa, strike: Math.max(0, Number(e.target.value) || 0) } }))} />
            <input type="number" className="sg-number-input" min={0} step={10}
              value={inst.ppa.maxMw} title="Max contract MW"
              onChange={(e) => setInst((s) => ({ ...s, ppa: { ...s.ppa, maxMw: Math.max(0, Number(e.target.value) || 0) } }))} />
          </div>
        )}
      </div>

      {/* Forward */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">
          <button
            className={`tb-btn sg-solver-btn${inst.forward.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => setInst((s) => ({ ...s, forward: { ...s.forward, enabled: !s.forward.enabled } }))}
          >
            Forward {inst.forward.enabled ? 'on' : 'off'}
          </button>
        </label>
        {inst.forward.enabled && (
          <div className="sg-btn-row" style={{ gap: 8 }}>
            <input type="number" className="sg-number-input" min={0} step={1}
              value={inst.forward.price} title="Forward price (per MWh)"
              onChange={(e) => setInst((s) => ({ ...s, forward: { ...s.forward, price: Math.max(0, Number(e.target.value) || 0) } }))} />
            <input type="number" className="sg-number-input" min={0} step={10}
              value={inst.forward.maxMw} title="Max block MW"
              onChange={(e) => setInst((s) => ({ ...s, forward: { ...s.forward, maxMw: Math.max(0, Number(e.target.value) || 0) } }))} />
          </div>
        )}
      </div>

      {/* Retail */}
      <div className="sg-setting-row">
        <label className="sg-setting-label">
          <button
            className={`tb-btn sg-solver-btn${inst.retail.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => setInst((s) => ({ ...s, retail: { ...s.retail, enabled: !s.retail.enabled } }))}
          >
            Retail {inst.retail.enabled ? 'on' : 'off'}
          </button>
        </label>
        {inst.retail.enabled && (
          <div className="sg-btn-row" style={{ gap: 8 }}>
            <input type="number" className="sg-number-input" min={0} step={1}
              value={inst.retail.price} title="Full-requirements rate (per MWh)"
              onChange={(e) => setInst((s) => ({ ...s, retail: { ...s.retail, price: Math.max(0, Number(e.target.value) || 0) } }))} />
          </div>
        )}
      </div>

      {/* ── Risk budget ──────────────────────────────────────────────── */}
      <div className="sg-setting-divider" />
      <div className="sg-setting-row">
        <label className="sg-setting-label">Tail level (CVaR α)</label>
        <div className="sg-btn-row">
          {[0.9, 0.95, 0.99].map((a) => (
            <button key={a}
              className={`tb-btn sg-solver-btn${alpha === a ? '' : ' tb-btn--muted'}`}
              onClick={() => setAlpha(a)}
            >
              {(a * 100).toFixed(0)}%
            </button>
          ))}
        </div>
        <p className="sg-setting-hint">
          The risk metric is the average cost in the worst {((1 - alpha) * 100).toFixed(0)}% of price scenarios.
        </p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Stress case</label>
        <button
          className={`tb-btn sg-solver-btn${stress2x ? '' : ' tb-btn--muted'}`}
          onClick={() => setStress2x((v) => !v)}
        >
          Price ×2 spike {stress2x ? 'included' : 'off'}
        </button>
        <p className="sg-setting-hint">Adds a doubled-price scenario so the tail reflects a shock, not just resampled history.</p>
      </div>

      <div className="sg-setting-row">
        <button
          className="tb-btn tb-btn--active"
          disabled={busy || prices.length < 2 || !anyInstrument}
          onClick={() => { setBudgetFrac(1); runOptimize(null); }}
        >
          {busy ? 'Optimising…' : 'Find the optimal mix →'}
        </button>
        {!anyInstrument && <p className="sg-setting-hint">Enable at least one instrument.</p>}
        {error && <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>{error}</p>}
      </div>

      {result && optimal && !result.error && (
        <ProcurementResultView
          result={result}
          optimal={optimal}
          currency={c}
          savingsPct={savingsPct}
          budgetFrac={budgetFrac}
          onSliderCommit={onSliderCommit}
        />
      )}
      {result?.error && (
        <p className="sg-setting-hint" style={{ color: 'var(--danger, #dc2626)' }}>{result.error}</p>
      )}
    </section>
  );
}

function ProcurementResultView(props: {
  result: ProcurementResult;
  optimal: NonNullable<ProcurementResult['optimal']>;
  currency: string;
  savingsPct: number;
  budgetFrac: number;
  onSliderCommit: (frac: number) => void;
}) {
  const { result, optimal, currency: c } = props;
  const num = (v: number) => Math.round(v).toLocaleString();

  // Coverage bars: each instrument's MW share of the load-equivalent. Retail is
  // already a 0..1 share; PPA/forward are MW against the (approx) load = worst
  // of the enabled maxima. Show raw values with units for honesty.
  const mixEntries = result.instrumentNames.map((n) => ({ name: n, value: optimal.mix[n] ?? 0 }));

  return (
    <div className="econ-card" style={{ marginTop: 12 }}>
      <div className="econ-kpi-row">
        <div className="econ-kpi">
          <div className="econ-kpi-label">Expected cost</div>
          <div className="econ-kpi-value">{c}{num(optimal.expectedCost)}</div>
          <div className={`econ-kpi-unit${props.savingsPct >= 0 ? '' : ''}`}>
            {props.savingsPct >= 0 ? '−' : '+'}{Math.abs(props.savingsPct).toFixed(1)}% vs all-spot ({c}{num(result.baseline.expectedCost)})
          </div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Risk (CVaR{(result.alpha * 100).toFixed(0)})</div>
          <div className="econ-kpi-value">{c}{num(optimal.cvar)}</div>
          <div className="econ-kpi-unit">all-spot: {c}{num(result.baseline.cvar)}</div>
        </div>
        <div className="econ-kpi">
          <div className="econ-kpi-label">Worst case</div>
          <div className="econ-kpi-value">{c}{num(optimal.worstCost)}</div>
          <div className="econ-kpi-unit">over {result.scenarioCount} scenarios · {result.horizonHours} h</div>
        </div>
      </div>

      {optimal.note && <p className="econ-footnote" style={{ color: 'var(--warning, #b45309)' }}>{optimal.note}</p>}

      {/* Optimal mix */}
      <div className="econ-table-wrap">
        <table className="econ-table">
          <thead><tr><th>Instrument</th><th>Optimal volume</th></tr></thead>
          <tbody>
            <tr><td>Spot (residual)</td><td>balance settled at spot</td></tr>
            {mixEntries.map((m) => (
              <tr key={m.name}>
                <td>{LABELS[m.name] ?? m.name}</td>
                <td>{m.name === 'retail' ? `${(m.value * 100).toFixed(0)}% of load` : `${num(m.value)} MW`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Efficient frontier */}
      {result.frontier.length >= 2 && (
        <FrontierPlot result={result} optimal={optimal} currency={c} />
      )}

      {/* Risk-budget slider */}
      {result.riskRange.maxCvar - result.riskRange.minCvar > 1 && (
        <div className="sg-setting-row" style={{ marginTop: 8 }}>
          <label className="sg-setting-label">Risk budget</label>
          <input
            type="range" min={0} max={1} step={0.05}
            defaultValue={props.budgetFrac}
            onMouseUp={(e) => props.onSliderCommit(Number((e.target as HTMLInputElement).value))}
            onTouchEnd={(e) => props.onSliderCommit(Number((e.target as HTMLInputElement).value))}
            style={{ width: '100%' }}
          />
          <p className="sg-setting-hint">
            Slide left for the safest mix (min CVaR {c}{num(result.riskRange.minCvar)}), right for the
            cheapest (min expected cost). Releasing re-optimises at that budget.
          </p>
        </div>
      )}

      <p className="econ-footnote">
        CVaR-constrained least-cost mix over {result.scenarioCount} bootstrapped price scenarios
        {result.stressLabels.length ? ` (incl. ${result.stressLabels.join(', ')})` : ''}. Residual settles at spot.
      </p>
    </div>
  );
}

function FrontierPlot(props: {
  result: ProcurementResult;
  optimal: NonNullable<ProcurementResult['optimal']>;
  currency: string;
}) {
  const { result, optimal } = props;
  const W = 320, H = 160, pad = 34;
  const cvars = result.frontier.map((p) => p.cvar);
  const costs = result.frontier.map((p) => p.expectedCost);
  const xMin = Math.min(...cvars), xMax = Math.max(...cvars);
  const yMin = Math.min(...costs), yMax = Math.max(...costs);
  const sx = (v: number) => pad + ((v - xMin) / (xMax - xMin || 1)) * (W - pad - 8);
  const sy = (v: number) => H - pad - ((v - yMin) / (yMax - yMin || 1)) * (H - pad - 8);
  const path = result.frontier.map((p, i) => `${i ? 'L' : 'M'}${sx(p.cvar).toFixed(1)},${sy(p.expectedCost).toFixed(1)}`).join(' ');

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, height: 'auto' }} role="img" aria-label="Cost vs risk efficient frontier">
        <line x1={pad} y1={H - pad} x2={W - 8} y2={H - pad} stroke="var(--border, #ccc)" />
        <line x1={pad} y1={8} x2={pad} y2={H - pad} stroke="var(--border, #ccc)" />
        <path d={path} fill="none" stroke="var(--accent, #2f855a)" strokeWidth={2} />
        {result.frontier.map((p, i) => (
          <circle key={i} cx={sx(p.cvar)} cy={sy(p.expectedCost)} r={3} fill="var(--accent, #2f855a)" />
        ))}
        <circle cx={sx(optimal.cvar)} cy={sy(optimal.expectedCost)} r={5} fill="none" stroke="var(--text, #111)" strokeWidth={2} />
        <text x={pad} y={H - 6} fontSize={9} fill="var(--text-muted, #888)">risk (CVaR) →</text>
        <text x={4} y={14} fontSize={9} fill="var(--text-muted, #888)">expected cost</text>
      </svg>
    </div>
  );
}
