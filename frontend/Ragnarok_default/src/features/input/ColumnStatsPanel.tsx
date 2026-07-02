/**
 * ColumnStatsPanel (X2) — per-column statistics rendered from the backend.
 *
 * Fetches the sheet's column statistics from the server (which crunches the full
 * sheet) and renders them, so the browser never processes thousands of rows for
 * the summary. Numeric columns show count/nulls/mean/min–max/σ; categorical show
 * distinct + the top value.
 */
import React from 'react';
import { ColumnStats, SheetStats, fetchColumnStats } from 'lib/api/analysis';

interface Props {
  sheet: string;
}

const fmt = (v: number) => (Math.abs(v) >= 1000 || v === 0
  ? Math.round(v).toLocaleString()
  : v.toLocaleString(undefined, { maximumFractionDigits: 3 }));

export function ColumnStatsPanel({ sheet }: Props) {
  const [data, setData] = React.useState<SheetStats | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    setBusy(true);
    setError(null);
    fetchColumnStats(sheet)
      .then((s) => { if (live) setData(s); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [sheet]);

  if (busy && !data) return <p className="ia-stats-note">Computing column statistics…</p>;
  if (error) return <p className="ia-stats-note" style={{ color: 'var(--danger, #dc2626)' }}>{error}</p>;
  if (!data || data.columns.length === 0) return null;

  const summarise = (c: ColumnStats): string => {
    if (c.kind === 'numeric') {
      return `μ ${fmt(c.mean)} · ${fmt(c.min)}–${fmt(c.max)} · σ ${fmt(c.std)}`;
    }
    const top = c.top[0];
    return `${c.distinct} distinct${top ? ` · top “${top.value}” ×${top.count}` : ''}`;
  };

  return (
    <div className="ia-stats">
      <div className="ia-stats-head">
        <span className="eyebrow">Column statistics</span>
        <span className="ia-stats-note">{data.total.toLocaleString()} rows · computed server-side</span>
      </div>
      <div className="ia-stats-tablewrap">
        <table className="ia-stats-table">
          <thead>
            <tr><th>Column</th><th>Type</th><th className="num">Count</th><th className="num">Nulls</th><th>Summary</th></tr>
          </thead>
          <tbody>
            {data.columns.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{c.kind}</td>
                <td className="num">{c.count.toLocaleString()}</td>
                <td className="num">{c.nulls ? c.nulls.toLocaleString() : '—'}</td>
                <td>{summarise(c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
