/**
 * Forge — seasonal line ratings (PyPSA 1.4 `Lines.apply_seasonal_rating`).
 *
 * The user enters a summer and a winter MVA rating per line; the backend writes
 * `lines-s_max_pu` = rating / s_nom per snapshot (summer months use the summer
 * rating, all other months the winter rating) and leaves `s_nom` unchanged. The
 * math runs in PyPSA — this is the thin UI. Needs datetime snapshots.
 */
import React, { useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';

export interface SeasonalRatingOptions {
  ratings: Record<string, { summer: number; winter: number }>;
  summerMonths: number[];
  compose: boolean;
}

export interface SeasonalRatingResult {
  lines: string[];
  summerMonths: number[];
  compose: boolean;
  snapshots: number;
}

interface Props {
  model: WorkbookModel;
  onApplySeasonalRating?: (opts: SeasonalRatingOptions) => Promise<SeasonalRatingResult>;
  onStatus: (msg: string) => void;
}

const NORTH = [4, 5, 6, 7, 8, 9];
const SOUTH = [10, 11, 12, 1, 2, 3];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** Parse "4-9", "10,11,12,1,2,3" or "10-3" (wrapping) into month numbers 1-12. */
export function parseMonths(text: string): number[] {
  const out = new Set<number>();
  for (const part of text.split(',').map((p) => p.trim()).filter(Boolean)) {
    const m = part.match(/^(\d{1,2})\s*-\s*(\d{1,2})$/);
    if (m) {
      let a = Number(m[1]);
      const b = Number(m[2]);
      for (let i = 0; i < 12; i += 1) {
        if (a >= 1 && a <= 12) out.add(a);
        if (a === b) break;
        a = a === 12 ? 1 : a + 1;
      }
    } else {
      const v = Number(part);
      if (Number.isInteger(v) && v >= 1 && v <= 12) out.add(v);
    }
  }
  return Array.from(out).sort((a, b) => a - b);
}

export function SeasonalRatingPanel({ model, onApplySeasonalRating, onStatus }: Props) {
  const lines = useMemo(() => model.lines ?? [], [model.lines]);
  const [rows, setRows] = useState<Record<string, { summer: string; winter: string }>>({});
  const [monthsText, setMonthsText] = useState('4-9');
  const [compose, setCompose] = useState(true);
  const [busy, setBusy] = useState(false);

  const months = useMemo(() => parseMonths(monthsText), [monthsText]);
  const ratings = useMemo(() => {
    const out: Record<string, { summer: number; winter: number }> = {};
    for (const [name, r] of Object.entries(rows)) {
      const s = num(r.summer);
      const w = num(r.winter);
      if (s > 0 && w > 0) out[name] = { summer: s, winter: w };
    }
    return out;
  }, [rows]);
  const nRated = Object.keys(ratings).length;
  const canApply = !!onApplySeasonalRating && nRated > 0 && months.length > 0 && !busy;

  const setCell = (name: string, key: 'summer' | 'winter', value: string) =>
    setRows((prev) => ({ ...prev, [name]: { ...(prev[name] ?? { summer: '', winter: '' }), [key]: value } }));

  const apply = async () => {
    if (!canApply || !onApplySeasonalRating) return;
    setBusy(true);
    try {
      const r = await onApplySeasonalRating({ ratings, summerMonths: months, compose });
      onStatus(`Seasonal ratings written to ${r.lines.length} line(s) over ${r.snapshots} snapshots (lines-s_max_pu).`);
    } catch (e) {
      onStatus(e instanceof Error ? e.message : 'Seasonal rating failed.');
    } finally {
      setBusy(false);
    }
  };

  if (lines.length === 0) {
    return (
      <section className="forge-section">
        <header className="forge-section-header"><h3>Seasonal line ratings</h3></header>
        <p className="sg-setting-hint">No lines in this model.</p>
      </section>
    );
  }

  return (
    <section className="forge-section">
      <header className="forge-section-header">
        <h3>Seasonal line ratings</h3>
        <p>
          Enter a <b>summer</b> and <b>winter</b> rating (MVA) per line. Each snapshot gets{' '}
          <code>s_max_pu = rating / s_nom</code> in <code>lines-s_max_pu</code>; <code>s_nom</code> is unchanged.
          TSOs usually rate summer lower (less cooling). Needs datetime snapshots.
        </p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Summer months</label>
        <input
          type="text" className="forge-number" value={monthsText} style={{ width: 160 }}
          onChange={(e) => setMonthsText(e.target.value)}
          aria-label="Summer months"
        />
        <button type="button" className="secondary-button" onClick={() => setMonthsText('4-9')}>Northern (Apr-Sep)</button>
        <button type="button" className="secondary-button" onClick={() => setMonthsText('10-3')}>Southern (Oct-Mar)</button>
        <span className="sg-setting-hint" style={{ margin: 0 }}>
          {months.length ? months.map((m) => MONTHS[m - 1]).join(' ') : 'enter months 1-12, e.g. 4-9 or 10,11,12,1,2,3'}
        </span>
      </div>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Existing s_max_pu</label>
        <select className="forge-adjust-select" value={compose ? 'compose' : 'overwrite'} onChange={(e) => setCompose(e.target.value === 'compose')}>
          <option value="compose">Multiply into it (keeps N-1 margins)</option>
          <option value="overwrite">Overwrite</option>
        </select>
      </div>

      <div className="forge-captarget-custom">
        {lines.map((l) => {
          const name = String(l.name);
          const sNom = num(l.s_nom);
          return (
            <div className="forge-adjust-row" key={name}>
              <span className="sg-setting-label" style={{ minWidth: 160 }}>{name}</span>
              <input
                type="number" className="forge-number" min={0} step={10} placeholder="summer"
                aria-label={`${name} summer rating`}
                value={rows[name]?.summer ?? ''} style={{ width: 100 }}
                onChange={(e) => setCell(name, 'summer', e.target.value)}
              />
              <input
                type="number" className="forge-number" min={0} step={10} placeholder="winter"
                aria-label={`${name} winter rating`}
                value={rows[name]?.winter ?? ''} style={{ width: 100 }}
                onChange={(e) => setCell(name, 'winter', e.target.value)}
              />
              <span className="sg-setting-hint" style={{ margin: 0 }}>MVA (s_nom {sNom || '—'})</span>
            </div>
          );
        })}
      </div>

      <div className="forge-adjust-actions">
        <button type="button" className="primary-button" onClick={apply} disabled={!canApply}>
          {busy ? 'Applying…' : `Apply to ${nRated} line${nRated === 1 ? '' : 's'}`}
        </button>
      </div>
    </section>
  );
}

export { NORTH as NORTHERN_SUMMER_MONTHS, SOUTH as SOUTHERN_SUMMER_MONTHS };
