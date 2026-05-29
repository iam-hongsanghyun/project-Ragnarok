/**
 * Export the current `RunResults` as a self-contained HTML report.
 *
 * The output is a single .html file with inline CSS and inline SVG charts —
 * no external scripts, no network calls. Open it in any browser to read the
 * summary, dispatch / price / emissions time series, cost breakdown,
 * carrier mix, expansion results, merit order, line loading, nodal balance,
 * and emissions breakdown for the run.
 */
import { RunResults, SeriesPoint, ValuePoint } from '../types';
import { carrierColor } from './helpers';

interface ExportReportOptions {
  filename?: string;
  projectName?: string;
  currencySymbol?: string;
}

// ── HTML escaping ────────────────────────────────────────────────────────────

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmt(n: number, digits = 0): string {
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ── SVG chart helpers ────────────────────────────────────────────────────────

const CHART_W = 720;
const CHART_H = 240;
const CHART_PAD = { top: 12, right: 12, bottom: 32, left: 56 };

function chartViewBox(): string {
  return `0 0 ${CHART_W} ${CHART_H}`;
}

function axisX(i: number, n: number): number {
  const w = CHART_W - CHART_PAD.left - CHART_PAD.right;
  return CHART_PAD.left + (n <= 1 ? w / 2 : (i * w) / (n - 1));
}

function axisY(v: number, min: number, max: number): number {
  const h = CHART_H - CHART_PAD.top - CHART_PAD.bottom;
  if (max === min) return CHART_PAD.top + h / 2;
  return CHART_PAD.top + h - ((v - min) / (max - min)) * h;
}

function svgAxisFrame(yMin: number, yMax: number, xLabels: string[], yUnit: string): string {
  const yTicks = 4;
  const ticks: string[] = [];
  for (let t = 0; t <= yTicks; t++) {
    const v = yMin + ((yMax - yMin) * t) / yTicks;
    const y = axisY(v, yMin, yMax);
    ticks.push(
      `<line x1="${CHART_PAD.left}" x2="${CHART_W - CHART_PAD.right}" y1="${y}" y2="${y}" stroke="#e5e7eb" stroke-width="1"/>` +
      `<text x="${CHART_PAD.left - 6}" y="${y + 3}" text-anchor="end" font-size="10" fill="#6b7280">${esc(fmt(v))}</text>`,
    );
  }
  const xN = xLabels.length;
  const xPicks = Math.min(6, xN);
  const xTicks: string[] = [];
  for (let t = 0; t < xPicks; t++) {
    const idx = Math.round((t * (xN - 1)) / Math.max(xPicks - 1, 1));
    const x = axisX(idx, xN);
    const label = xLabels[idx] ?? '';
    xTicks.push(
      `<text x="${x}" y="${CHART_H - CHART_PAD.bottom + 14}" text-anchor="middle" font-size="10" fill="#6b7280">${esc(label)}</text>`,
    );
  }
  const yLabel =
    `<text x="14" y="${CHART_PAD.top + 8}" font-size="10" fill="#374151">${esc(yUnit)}</text>`;
  return ticks.join('') + xTicks.join('') + yLabel;
}

function svgLineChart(title: string, points: ValuePoint[], unit: string, color = '#0f766e'): string {
  if (!points.length) return '';
  const values = points.map((p) => p.value);
  const yMin = Math.min(0, ...values);
  const yMax = Math.max(1, ...values);
  const labels = points.map((p) => p.label);
  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${axisX(i, points.length)} ${axisY(p.value, yMin, yMax)}`)
    .join(' ');
  return `
    <div class="chart">
      <h3>${esc(title)}</h3>
      <svg viewBox="${chartViewBox()}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(title)}">
        ${svgAxisFrame(yMin, yMax, labels, unit)}
        <path d="${path}" fill="none" stroke="${color}" stroke-width="1.6"/>
      </svg>
    </div>`;
}

function svgStackedAreaChart(title: string, points: SeriesPoint[], unit: string): string {
  if (!points.length) return '';
  const carriers = Array.from(
    new Set(points.flatMap((p) => Object.keys(p.values))),
  );
  if (carriers.length === 0) return '';
  // Sort carriers by total contribution descending so the dominant carrier sits at the bottom.
  const totals = carriers.map((c) =>
    points.reduce((s, p) => s + Math.max(p.values[c] ?? 0, 0), 0),
  );
  const order = carriers
    .map((c, i) => ({ c, t: totals[i] }))
    .sort((a, b) => b.t - a.t)
    .map((x) => x.c);

  const stackedTotals = points.map((p) =>
    order.reduce((s, c) => s + Math.max(p.values[c] ?? 0, 0), 0),
  );
  const yMin = 0;
  const yMax = Math.max(1, ...stackedTotals);
  const labels = points.map((p) => p.label);
  const polygons: string[] = [];
  const cumulative: number[] = new Array(points.length).fill(0);
  for (const carrier of order) {
    const lower: string[] = [];
    const upper: string[] = [];
    for (let i = 0; i < points.length; i++) {
      const base = cumulative[i];
      const v = Math.max(points[i].values[carrier] ?? 0, 0);
      const top = base + v;
      lower.push(`${axisX(i, points.length)},${axisY(base, yMin, yMax)}`);
      upper.push(`${axisX(i, points.length)},${axisY(top, yMin, yMax)}`);
      cumulative[i] = top;
    }
    const poly = [...upper, ...lower.reverse()].join(' ');
    polygons.push(
      `<polygon points="${poly}" fill="${carrierColor(carrier)}" opacity="0.85"/>`,
    );
  }
  const legend = order
    .map(
      (c) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${carrierColor(c)}"></span>${esc(c)}</span>`,
    )
    .join('');
  return `
    <div class="chart">
      <h3>${esc(title)}</h3>
      <svg viewBox="${chartViewBox()}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(title)}">
        ${svgAxisFrame(yMin, yMax, labels, unit)}
        ${polygons.join('')}
      </svg>
      <div class="legend">${legend}</div>
    </div>`;
}

// ── Table helpers ────────────────────────────────────────────────────────────

function table(headers: string[], rows: Array<Array<string | number>>): string {
  if (!rows.length) return '<p class="muted">No data.</p>';
  const head = headers.map((h) => `<th>${esc(h)}</th>`).join('');
  const body = rows
    .map((row) => `<tr>${row.map((c) => `<td>${esc(typeof c === 'number' ? fmt(c, 2) : c)}</td>`).join('')}</tr>`)
    .join('');
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// ── Sections ─────────────────────────────────────────────────────────────────

function summaryCards(results: RunResults): string {
  return `
    <div class="cards">
      ${results.summary
        .map(
          (s) => `
        <div class="card">
          <div class="card-label">${esc(s.label)}</div>
          <div class="card-value">${esc(s.value)}</div>
          <div class="card-detail">${esc(s.detail)}</div>
        </div>`,
        )
        .join('')}
    </div>`;
}

function carrierMixSection(results: RunResults): string {
  const total = results.carrierMix.reduce((s, m) => s + m.value, 0) || 1;
  const rows = results.carrierMix.map((m) => [
    m.label,
    m.value,
    `${((m.value / total) * 100).toFixed(1)}%`,
  ]);
  return `<section>
    <h2>Carrier mix</h2>
    ${table(['Carrier', 'Energy (MWh)', 'Share'], rows)}
  </section>`;
}

function costBreakdownSection(results: RunResults, currencySymbol: string): string {
  const rows = results.costBreakdown.map((c) => [c.label, `${currencySymbol}${fmt(c.value)}`]);
  const total = results.costBreakdown.reduce((s, c) => s + c.value, 0);
  rows.push(['Total', `${currencySymbol}${fmt(total)}`]);
  return `<section>
    <h2>Cost breakdown</h2>
    ${table(['Component', 'Cost'], rows)}
  </section>`;
}

function expansionSection(results: RunResults, currencySymbol: string): string {
  if (!results.expansionResults || results.expansionResults.length === 0) return '';
  const rows = results.expansionResults.map((e) => [
    e.name,
    e.component,
    e.carrier || '—',
    e.bus,
    fmt(e.p_nom_mw, 1) + ' ' + (e.unit ?? 'MW'),
    fmt(e.p_nom_opt_mw, 1) + ' ' + (e.unit ?? 'MW'),
    fmt(e.delta_mw, 1) + ' ' + (e.unit ?? 'MW'),
    `${currencySymbol}${fmt(e.capex_annual)}`,
  ]);
  return `<section>
    <h2>Capacity expansion</h2>
    ${table(
      ['Asset', 'Component', 'Carrier', 'Bus', 'Installed', 'Optimised', 'Δ', 'CAPEX / yr'],
      rows,
    )}
  </section>`;
}

function meritOrderSection(results: RunResults, currencySymbol: string): string {
  if (!results.meritOrder || results.meritOrder.length === 0) return '';
  const rows = results.meritOrder.map((m) => [
    m.name, m.carrier, m.bus,
    `${currencySymbol}${fmt(m.marginal_cost, 2)}`,
    fmt(m.p_nom, 1),
    fmt(m.cumulative_mw, 1),
  ]);
  return `<section>
    <h2>Merit order</h2>
    ${table(['Generator', 'Carrier', 'Bus', 'Marginal cost / MWh', 'Capacity (MW)', 'Cumulative (MW)'], rows)}
  </section>`;
}

function lineLoadingSection(results: RunResults): string {
  if (!results.lineLoading.length) return '';
  const rows = [...results.lineLoading]
    .sort((a, b) => b.value - a.value)
    .map((l) => [l.label, `${l.value.toFixed(1)}%`]);
  return `<section>
    <h2>Line / link loading (peak)</h2>
    ${table(['Corridor', 'Peak loading'], rows)}
  </section>`;
}

function nodalBalanceSection(results: RunResults): string {
  if (!results.nodalBalance.length) return '';
  const rows = results.nodalBalance.map((n) => [n.label, n.load, n.generation, n.generation - n.load]);
  return `<section>
    <h2>Nodal balance (averages)</h2>
    ${table(['Bus', 'Avg load (MW)', 'Avg generation (MW)', 'Net (MW)'], rows)}
  </section>`;
}

function emissionsSection(results: RunResults): string {
  const eb = results.emissionsBreakdown;
  if (!eb) return '';
  const byCarrier = eb.byCarrier.map((c) => [
    c.carrier, c.energy_mwh, c.emissions_tco2, c.intensity_kg_mwh,
  ]);
  const byGen = eb.byGenerator.slice(0, 50).map((g) => [
    g.name, g.carrier, g.bus, g.energy_mwh, g.emissions_tco2, g.intensity_kg_mwh,
  ]);
  return `<section>
    <h2>Emissions by carrier</h2>
    ${table(['Carrier', 'Energy (MWh)', 'Emissions (tCO₂e)', 'Intensity (kg/MWh)'], byCarrier)}
    <h2>Emissions by generator (top 50)</h2>
    ${table(['Generator', 'Carrier', 'Bus', 'Energy (MWh)', 'Emissions (tCO₂e)', 'Intensity (kg/MWh)'], byGen)}
  </section>`;
}

function narrativeSection(results: RunResults): string {
  if (!results.narrative.length) return '';
  return `<section>
    <h2>Solver narrative</h2>
    <ul class="narrative">${results.narrative.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
  </section>`;
}

// ── Public entry ─────────────────────────────────────────────────────────────

export function buildReportHtml(
  results: RunResults,
  options: ExportReportOptions = {},
): string {
  const { projectName = 'Ragnarok run', currencySymbol = '$' } = options;
  const generated = new Date().toLocaleString();

  const charts = [
    svgStackedAreaChart('Dispatch by carrier', results.dispatchSeries, 'MW'),
    svgLineChart('System price', results.systemPriceSeries, `${currencySymbol}/MWh`, '#0ea5e9'),
    svgLineChart('System emissions', results.systemEmissionsSeries, 'tCO₂e', '#dc2626'),
  ].filter(Boolean).join('');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>${esc(projectName)} — Ragnarok report</title>
<style>
  :root { color-scheme: light; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #111827; background: #f9fafb; margin: 0; padding: 32px; }
  header { margin-bottom: 24px; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  h2 { margin: 24px 0 12px; font-size: 16px; }
  h3 { margin: 0 0 6px; font-size: 13px; color: #374151; }
  .meta { color: #6b7280; font-size: 12px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 24px; }
  .card { background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }
  .card-label { font-size: 11px; text-transform: uppercase; color: #6b7280; letter-spacing: 0.02em; }
  .card-value { font-size: 18px; font-weight: 600; margin: 4px 0; }
  .card-detail { font-size: 11px; color: #6b7280; }
  section { background: white; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 16px 18px; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  thead th { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb;
    color: #374151; font-weight: 600; }
  tbody td { padding: 6px 8px; border-bottom: 1px solid #f3f4f6; }
  tbody tr:hover { background: #f9fafb; }
  .muted { color: #6b7280; font-size: 12px; }
  .chart { background: white; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 12px 14px; margin-bottom: 16px; }
  .chart svg { width: 100%; height: auto; display: block; }
  .legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
  .legend-item { font-size: 11px; color: #374151; display: inline-flex; align-items: center; gap: 4px; }
  .legend-dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
  ul.narrative { margin: 0; padding-left: 18px; font-size: 12px; color: #374151; }
  ul.narrative li { margin-bottom: 4px; }
  @media print {
    body { background: white; padding: 16px; }
    section, .card, .chart { break-inside: avoid; }
  }
</style>
</head>
<body>
  <header>
    <h1>${esc(projectName)}</h1>
    <div class="meta">Generated ${esc(generated)} · ${results.runMeta.snapshotCount} snapshots · ${results.runMeta.snapshotWeight}h resolution · ${results.runMeta.modeledHours} h modelled</div>
  </header>

  <section>
    <h2>Summary</h2>
    ${summaryCards(results)}
  </section>

  ${charts}

  ${carrierMixSection(results)}
  ${costBreakdownSection(results, currencySymbol)}
  ${expansionSection(results, currencySymbol)}
  ${meritOrderSection(results, currencySymbol)}
  ${nodalBalanceSection(results)}
  ${lineLoadingSection(results)}
  ${emissionsSection(results)}
  ${narrativeSection(results)}
</body>
</html>`;
}

/** Trigger a browser download of the report. */
export function exportReportHtml(
  results: RunResults,
  options: ExportReportOptions = {},
): void {
  const html = buildReportHtml(results, options);
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = (options.filename ?? 'ragnarok_report') + '.html';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
