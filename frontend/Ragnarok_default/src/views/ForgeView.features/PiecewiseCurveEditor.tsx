/**
 * Forge — piecewise-linear curve editor (PyPSA >= 1.3, P10/P46).
 *
 * Pick a component class and a curve attribute (`marginal_cost`, `capital_cost`,
 * `efficiency` / `rate`), narrow the rows with equality filters (the Adjust
 * machinery), type the breakpoints, and Apply: the curve is written to the
 * `<list>-<attribute>-pw` sheet for every matched component, replacing its scalar.
 *
 * All rules — strictly increasing x, start at 0, per-unit end at 1, fixed capacity for
 * per-unit axes, convex (LP) vs non-convex (MIP) — live in `lib/forge/piecewise.ts`
 * and mirror what the backend enforces, so Apply never produces a run-time 400.
 */
import React, { useMemo } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { AdjustFilter, columnsOf, rowMatches, uniqueValues } from 'lib/forge/adjust';
import {
  Breakpoint,
  checkCurve,
  costAt,
  curveFromRows,
  curveNames,
  defaultCurve,
  piecewiseSheetName,
  portAttributes,
  priceAt,
  replaceCurves,
} from 'lib/forge/piecewise';
import { piecewiseCapableSheets, piecewiseSpecFor, piecewiseSpecsFor } from 'lib/forge/piecewiseSchema';

interface Props {
  model: WorkbookModel;
  sheetsWithRows: string[];
  currencySymbol?: string;
  onApplySheets: (partial: Record<string, GridRow[]>) => void;
  onStatus: (msg: string) => void;
  /** The mode switch rendered by the parent panel (quadratic fit | piecewise). */
  modeSwitch?: React.ReactNode;
}

const rowsOf = (model: WorkbookModel, sheet: string): GridRow[] => model[sheet] ?? [];
const EXTENDABLE_COLUMNS = ['p_nom_extendable', 's_nom_extendable', 'e_nom_extendable'];
const isTrue = (v: unknown): boolean => v === true || String(v).toLowerCase() === 'true' || v === 1;

const VBW = 440;
const VBH = 220;
const PAD = { l: 52, r: 14, t: 14, b: 32 };
const PLOT_W = VBW - PAD.l - PAD.r;
const PLOT_H = VBH - PAD.t - PAD.b;

export function PiecewiseCurveEditor({ model, sheetsWithRows, currencySymbol, onApplySheets, onStatus, modeSwitch }: Props) {
  const cur = currencySymbol || '';
  const capable = useMemo(
    () => piecewiseCapableSheets().filter((s) => sheetsWithRows.includes(s)),
    [sheetsWithRows],
  );
  const [sheet, setSheet] = usePersistedState<string>('ui:forge-pw-sheet', capable[0] ?? '');
  const [attrChoice, setAttrChoice] = usePersistedState<string>('ui:forge-pw-attr', 'marginal_cost');
  const [filters, setFilters] = usePersistedState<AdjustFilter[]>('ui:forge-pw-filters', []);
  const [points, setPoints] = usePersistedState<Breakpoint[]>('ui:forge-pw-points', [
    { x: 0, y: 0 },
    { x: 0.5, y: 10 },
    { x: 1, y: 40 },
  ]);

  const activeSheet = capable.includes(sheet) ? sheet : (capable[0] ?? '');
  const rows = useMemo(() => rowsOf(model, activeSheet), [model, activeSheet]);
  const columns = useMemo(() => columnsOf(rows), [rows]);
  const specs = useMemo(() => piecewiseSpecsFor(activeSheet), [activeSheet]);
  const attributes = useMemo(() => specs.flatMap((s) => portAttributes(s, rows)), [specs, rows]);
  const attribute = attributes.includes(attrChoice) ? attrChoice : (attributes[0] ?? '');
  const spec = attribute ? piecewiseSpecFor(activeSheet, attribute) : null;

  const matched = useMemo(() => rows.filter((r) => rowMatches(r, filters)), [rows, filters]);
  const names = useMemo(() => matched.map((r) => String(r.name ?? '').trim()).filter(Boolean), [matched]);
  const pwSheet = spec ? piecewiseSheetName(activeSheet, attribute) : '';
  const pwRows = useMemo(() => (pwSheet ? rowsOf(model, pwSheet) : []), [model, pwSheet]);
  const withCurve = useMemo(() => new Set(curveNames(pwRows)), [pwRows]);
  const haveCurve = names.filter((n) => withCurve.has(n)).length;

  const perUnit = !!spec && spec.x.endsWith('_pu');
  const anyExtendable = matched.some((r) => EXTENDABLE_COLUMNS.some((c) => isTrue(r[c])));
  const check = useMemo(
    () =>
      spec
        ? checkCurve(points, {
            perUnit,
            anyExtendable,
            kind: spec.kind,
            invert: activeSheet === 'generators' && spec.attribute === 'efficiency',
          })
        : null,
    [points, spec, perUnit, anyExtendable, activeSheet],
  );

  const nominalCol = spec && !perUnit ? spec.x : null;
  const xUnit = !spec ? '' : perUnit ? 'p.u. of nominal capacity' : spec.x === 'p_nom' ? 'MW' : spec.x === 's_nom' ? 'MVA' : 'MWh';
  const yUnit = !spec
    ? ''
    : spec.kind === 'efficiency'
      ? 'per unit'
      : spec.attribute === 'marginal_cost'
        ? `${cur}/MWh`
        : `${cur}/${spec.x === 'e_nom' ? 'MWh' : spec.x === 's_nom' ? 'MVA' : 'MW'} (overnight)`;

  const setPoint = (i: number, patch: Partial<Breakpoint>) =>
    setPoints(points.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  const addPoint = () => {
    const last = [...points].sort((a, b) => a.x - b.x).slice(-1)[0];
    setPoints([...points, { x: last ? (perUnit ? Math.min(1, last.x + 0.1) : last.x * 1.5 || 1) : 0, y: last?.y ?? 0 }]);
  };

  const loadFromSelection = () => {
    const first = names.find((n) => withCurve.has(n));
    if (first && spec) {
      const pts = curveFromRows(pwRows, first, spec.x, attribute);
      if (pts.length) {
        setPoints(pts);
        onStatus(`Loaded the ${attribute} curve of ${first} (${pts.length} breakpoints).`);
        return;
      }
    }
    if (spec) {
      const nominals = matched.map((r) => Number(r[spec.x])).filter(Number.isFinite);
      setPoints(defaultCurve(spec, nominals.length ? Math.max(1, Math.max(...nominals)) : 100));
      onStatus('No curve on the matched rows yet — loaded a starting curve.');
    }
  };

  const apply = () => {
    if (!spec || !check) return;
    if (names.length === 0) { onStatus('No rows match — adjust the filters first.'); return; }
    if (check.errors.length > 0) { onStatus(`Cannot apply: ${check.errors[0]}`); return; }
    onApplySheets({ [pwSheet]: replaceCurves(pwRows, names, spec.x, attribute, points) });
    onStatus(
      `Wrote the ${attribute} curve (${points.length} breakpoints, ${check.shape}${check.isMip ? ', MIP' : ''}) ` +
        `to ${names.length} ${activeSheet} row${names.length === 1 ? '' : 's'} in ${pwSheet}.`,
    );
  };

  const clear = () => {
    if (!spec || haveCurve === 0) { onStatus('No matched row has a curve to clear.'); return; }
    onApplySheets({ [pwSheet]: replaceCurves(pwRows, names, spec.x, attribute, []) });
    onStatus(`Cleared the ${attribute} curve from ${haveCurve} ${activeSheet} row${haveCurve === 1 ? '' : 's'}; the scalar applies again.`);
  };

  // ── Chart: marginal price (cost) or efficiency vs x ──────────────────────
  const sorted = useMemo(() => [...points].filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x), [points]);
  const xMax = Math.max(perUnit ? 1 : 1, ...sorted.map((p) => p.x));
  const yMax = Math.max(1e-9, ...sorted.map((p) => p.y)) * 1.15;
  const xPix = (x: number) => PAD.l + (xMax > 0 ? x / xMax : 0) * PLOT_W;
  const yPix = (y: number) => PAD.t + PLOT_H - (yMax > 0 ? Math.max(0, y) / yMax : 0) * PLOT_H;
  const path = useMemo(() => {
    if (!spec || sorted.length < 2) return '';
    if (spec.kind === 'efficiency') return sorted.map((p, i) => `${i ? 'L' : 'M'}${xPix(p.x)},${yPix(p.y)}`).join(' ');
    // staircase: the price on (x[i-1], x[i]] is y[i]
    let d = `M${xPix(sorted[0].x)},${yPix(sorted[1].y)}`;
    for (let i = 1; i < sorted.length; i += 1) {
      d += ` L${xPix(sorted[i].x)},${yPix(sorted[i].y)}`;
      if (i + 1 < sorted.length) d += ` L${xPix(sorted[i].x)},${yPix(sorted[i + 1].y)}`;
    }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sorted, spec, xMax, yMax]);

  if (!modeSwitch && capable.length === 0) return null;

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Piecewise cost / efficiency curve</h3>
        <p>
          Give components a piecewise-linear <code>marginal_cost</code>, <code>capital_cost</code> or
          <code> efficiency</code> (PyPSA 1.3+). Curves live on <code>&lt;component&gt;-&lt;attribute&gt;-pw</code>
          {' '}sheets and replace the scalar value of the rows they are written to.
        </p>
      </header>
      {modeSwitch}

      {capable.length === 0 ? (
        <p className="sg-setting-hint">
          No generators, links, processes, storage units or stores in this model — or the backend predates
          PyPSA 1.3 curves (its schema has no <code>piecewise_attributes</code>).
        </p>
      ) : (
        <>
          <div className="forge-adjust-row forge-adjust-spec">
            <SearchableSelect
              className="forge-adjust-select"
              value={activeSheet}
              placeholder="component"
              options={capable.map((s) => ({ value: s, label: `${s} (${rowsOf(model, s).length})` }))}
              onChange={(v) => { setSheet(v); setFilters([]); }}
            />
            <SearchableSelect
              className="forge-adjust-select"
              value={attribute}
              placeholder="curve"
              options={attributes.map((a) => ({ value: a, label: a }))}
              onChange={setAttrChoice}
            />
            <span className="forge-adjust-match">
              {names.length} row{names.length === 1 ? '' : 's'} match{haveCurve ? ` · ${haveCurve} already have a curve` : ''}
            </span>
          </div>

          {filters.map((f, idx) => (
            <div className="forge-adjust-row forge-adjust-filter" key={idx}>
              <span className="forge-adjust-and">{idx === 0 ? 'where' : 'and'}</span>
              <SearchableSelect
                className="forge-adjust-select"
                value={f.column}
                placeholder="column"
                options={columns.map((c) => ({ value: c, label: c }))}
                onChange={(v) => setFilters(filters.map((g, i) => (i === idx ? { column: v, value: '' } : g)))}
              />
              <span className="forge-adjust-eq">=</span>
              <SearchableSelect
                className="forge-adjust-select"
                value={f.value}
                placeholder="value"
                disabled={!f.column}
                options={uniqueValues(rows, f.column).map((v) => ({ value: v, label: v }))}
                onChange={(v) => setFilters(filters.map((g, i) => (i === idx ? { ...g, value: v } : g)))}
              />
              <button type="button" className="forge-adjust-remove" onClick={() => setFilters(filters.filter((_, i) => i !== idx))} aria-label="Remove filter">×</button>
            </div>
          ))}

          <div className="forge-adjust-row">
            <button type="button" className="tb-btn tb-btn--muted forge-adjust-addfilter" onClick={() => setFilters([...filters, { column: '', value: '' }])}>
              + Add filter
            </button>
            <button type="button" className="tb-btn tb-btn--muted" onClick={loadFromSelection} title="Load the curve of the first matched row that has one, else a starting curve">
              Load from selection
            </button>
          </div>

          {spec && (
            <>
              <p className="sg-setting-hint">
                x = <b>{spec.x}</b> ({xUnit}) · y = <b>{attribute}</b> ({yUnit}).{' '}
                {spec.kind === 'cost'
                  ? 'y on each row is the price per unit of x on the segment ending at that breakpoint; y on the first row (x = 0) is ignored.'
                  : 'y is the operating value at each breakpoint.'}
                {nominalCol ? ' Capital curves are overnight prices — the run annuitises them like the scalar capital_cost.' : ''}
              </p>

              <table className="forge-pw-table">
                <thead>
                  <tr><th>#</th><th>{spec.x}</th><th>{attribute}</th><th /></tr>
                </thead>
                <tbody>
                  {points.map((p, i) => (
                    <tr key={i}>
                      <td>{i}</td>
                      <td>
                        <input type="number" className="forge-number" step={perUnit ? 0.05 : 1} value={Number.isFinite(p.x) ? p.x : ''} aria-label={`breakpoint ${i} ${spec.x}`}
                          onChange={(e) => setPoint(i, { x: e.target.value === '' ? Number.NaN : Number(e.target.value) })} />
                      </td>
                      <td>
                        <input type="number" className="forge-number" step="any" value={Number.isFinite(p.y) ? p.y : ''} aria-label={`breakpoint ${i} ${attribute}`}
                          onChange={(e) => setPoint(i, { y: e.target.value === '' ? Number.NaN : Number(e.target.value) })} />
                      </td>
                      <td>
                        <button type="button" className="forge-adjust-remove" aria-label={`Remove breakpoint ${i}`}
                          disabled={points.length <= 2} onClick={() => setPoints(points.filter((_, idx) => idx !== i))}>×</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="forge-adjust-row">
                <button type="button" className="tb-btn tb-btn--muted" onClick={addPoint}>+ Add breakpoint</button>
                <button type="button" className="tb-btn tb-btn--muted" onClick={() => setPoints([...points].sort((a, b) => a.x - b.x))}>Sort by x</button>
                <button type="button" className="tb-btn tb-btn--muted" onClick={() => setPoints(defaultCurve(spec))}>Reset</button>
              </div>

              <div className="forge-costcurve-chartwrap">
                <svg viewBox={`0 0 ${VBW} ${VBH}`} className="forge-costcurve-chart" role="img"
                  aria-label={spec.kind === 'cost' ? 'Marginal price versus output' : 'Efficiency versus output'}>
                  {[0, 0.5, 1].map((f) => (
                    <g key={`y${f}`}>
                      <line x1={PAD.l} y1={yPix(f * yMax)} x2={VBW - PAD.r} y2={yPix(f * yMax)} className="cc-grid" />
                      <text x={PAD.l - 6} y={yPix(f * yMax) + 3} className="cc-axis-label" textAnchor="end">{(f * yMax).toPrecision(3)}</text>
                    </g>
                  ))}
                  {[0, 0.5, 1].map((f) => (
                    <text key={`x${f}`} x={xPix(f * xMax)} y={VBH - PAD.b + 16} className="cc-axis-label" textAnchor="middle">{+(f * xMax).toPrecision(3)}</text>
                  ))}
                  <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + PLOT_H} className="cc-axis" />
                  <line x1={PAD.l} y1={PAD.t + PLOT_H} x2={VBW - PAD.r} y2={PAD.t + PLOT_H} className="cc-axis" />
                  <text x={4} y={PAD.t - 2} className="cc-axis-title">{yUnit}</text>
                  <text x={VBW - PAD.r} y={VBH - 4} className="cc-axis-title" textAnchor="end">{spec.x}</text>
                  {path && <path d={path} className="cc-fit" fill="none" />}
                  {sorted.map((p, i) => (
                    <circle key={i} className="cc-point" cx={xPix(p.x)} cy={yPix(p.y)} r={4}>
                      <title>{`${spec.x} = ${p.x} → ${attribute} = ${p.y}`}</title>
                    </circle>
                  ))}
                </svg>
              </div>

              {spec.kind === 'cost' && check && check.errors.length === 0 && sorted.length > 1 && (
                <div className="forge-costcurve-readout">
                  <span>Price at x = {sorted[sorted.length - 1].x / 2}: <b>{priceAt(sorted, sorted[sorted.length - 1].x / 2).toFixed(2)}</b> {yUnit}</span>
                  <span>Total cost at x = {sorted[sorted.length - 1].x}: <b>{costAt(sorted, sorted[sorted.length - 1].x).toFixed(2)}</b></span>
                </div>
              )}

              {check && (
                <ul className="forge-pw-messages" aria-live="polite">
                  {check.errors.map((m) => <li key={m} className="forge-pw-error">{m}</li>)}
                  {check.warnings.map((m) => <li key={m} className={check.isMip && m.includes('MIP') ? 'forge-pw-mip' : 'sg-setting-hint'}>{m}</li>)}
                </ul>
              )}
              {anyExtendable && perUnit && (
                <p className="sg-setting-hint" style={{ color: 'var(--warning, #b45309)' }}>
                  Some matched rows are extendable; per-unit curves need a fixed capacity.
                </p>
              )}

              <div className="forge-adjust-actions">
                <button type="button" className="primary-button" onClick={apply}
                  disabled={names.length === 0 || !check || check.errors.length > 0}>
                  Apply to {names.length} row{names.length === 1 ? '' : 's'}
                </button>
                <button type="button" className="tb-btn tb-btn--muted" onClick={clear} disabled={haveCurve === 0}>
                  Clear curve ({haveCurve})
                </button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
