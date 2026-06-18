/**
 * Client for backend-stored RUN analytics series.
 *
 * "View result" loads the LIGHT analytics bundle, which strips the heavy
 * per-component output series (`outputs.series = null`) and lists their sheet
 * names in `outputs.seriesSheets`. Per-asset analytics — the generator /
 * storage / bus / branch charts and the map asset-detail popups — all derive
 * from those series (`deriveAssetDetails`), so they stay blank until the series
 * are fetched back. This module pulls them from the run db on demand; the
 * caller splices them into `outputs.series` and re-derives `assetDetails`.
 *
 * Mirror of the session-series client in `session.ts`, but scoped to a stored
 * run (`/api/runs/{name}/series/{sheet}`) instead of the live editor session.
 */
import { API_BASE } from 'lib/constants';
import type { GridRow } from 'lib/types';
import type { DownsampleAgg, SeriesWindow } from './session';

// Above any realistic snapshot count (≈ 100 years hourly) so the backend's
// `downsample` no-ops and we get the series at FULL resolution. Downsampling
// here would be incorrect: the donut + sum-reducer charts integrate each row
// over `snapshotWeight` hours, so a mean-bucketed series undercounts energy /
// emissions totals. Per-snapshot fidelity is required, not optional.
const FULL_RESOLUTION = 100_000_000;

/**
 * Default per-chart temporal window (hours) for a per-asset chart. Bounds how
 * much per-asset series a chart loads + renders by default; a long run with one
 * series per asset froze the tab when loading every snapshot. Each chart's gear
 * settings can override this (incl. "Full run" = null). One week.
 */
export const DEFAULT_CHART_WINDOW_HOURS = 168;

/** Window-length options offered in each chart's gear (hours; null = full run). */
export const CHART_WINDOW_OPTIONS: Array<{ value: number | null; label: string }> = [
  { value: 168, label: '1 week' },
  { value: 744, label: '1 month' },
  { value: 2208, label: '3 months' },
  { value: 8760, label: '1 year' },
  { value: null, label: 'Full run' },
];

/**
 * Output series sheets `deriveAssetDetails` reads for a given non-`system`
 * focus type. Used to scope on-demand hydration to ONLY the sheets the
 * displayed per-asset charts need — fetching (and client-deriving) the whole
 * bundle on every result view froze the tab on large runs. Keys mirror
 * `AnalyticsFocus['type']`; system charts read inline aggregates and need none.
 */
export const OUTPUT_SHEETS_FOR_FOCUS: Record<string, string[]> = {
  generator:      ['generators-p'],
  bus:            ['generators-p', 'buses-marginal_price', 'buses-v_mag_pu', 'buses-v_ang'],
  storageUnit:    ['storage_units-p', 'storage_units-state_of_charge'],
  store:          ['stores-e', 'stores-p'],
  branch:         ['lines-p0', 'lines-p1', 'links-p0', 'links-p1', 'transformers-p0', 'transformers-p1'],
  process:        ['processes-p0', 'processes-p1'],
  shuntImpedance: ['shunt_impedances-p', 'shunt_impedances-q'],
};

/** A windowed slice of a stored run's output time-series sheet. Same wire shape
 *  as the session window — both are served by `run_store.run_series_window`. */
export async function getRunSeriesWindow(
  runName: string,
  sheet: string,
  opts: { start?: number; end?: number; columns?: string[]; maxPoints?: number; agg?: DownsampleAgg } = {},
): Promise<SeriesWindow> {
  const params = new URLSearchParams();
  if (opts.start != null) params.set('start', String(opts.start));
  if (opts.end != null) params.set('end', String(opts.end));
  if (opts.columns?.length) params.set('columns', opts.columns.join(','));
  if (opts.maxPoints != null) params.set('maxPoints', String(opts.maxPoints));
  if (opts.agg) params.set('agg', opts.agg);
  const qs = params.toString();
  const resp = await fetch(
    `${API_BASE}/api/runs/${encodeURIComponent(runName)}/series/${encodeURIComponent(sheet)}${qs ? `?${qs}` : ''}`,
  );
  if (!resp.ok) throw new Error(`Run series fetch failed (HTTP ${resp.status})`);
  return resp.json() as Promise<SeriesWindow>;
}

/**
 * Normalise a series window's rows for `deriveAssetDetails`, which reads each
 * row's `snapshot` index. Canonical runs already use `snapshot`; remap
 * defensively when the stored index column is named differently (older
 * `name` / `datetime` indices).
 */
export function seriesRowsFromWindow(window: Pick<SeriesWindow, 'indexCol' | 'rows'>): GridRow[] {
  if (!Array.isArray(window.rows)) return [];
  if (window.indexCol === 'snapshot') return window.rows;
  return window.rows.map((row) => {
    const { [window.indexCol]: idx, ...rest } = row as Record<string, unknown>;
    return { snapshot: idx, ...rest } as GridRow;
  });
}

/**
 * Fetch a set of output series sheets, each windowed to its own first-`end`
 * snapshots (`end` null = whole run), and assemble the `outputs.series` map
 * `deriveAssetDetails` expects: sheet name → rows, each keyed by component name
 * plus a `snapshot` index. FULL resolution WITHIN each window so donut/sum
 * totals stay exact. Per-sheet windows let different charts pull different
 * lengths of the same sheet (the caller requests the max each sheet needs).
 *
 * Sheets that fail to load are skipped (their charts stay empty) rather than
 * failing the whole hydration.
 */
export async function fetchRunOutputSeriesWindows(
  runName: string,
  items: Array<{ sheet: string; end: number | null }>,
): Promise<Record<string, GridRow[]>> {
  const windows = await Promise.all(
    items.map(({ sheet, end }) =>
      getRunSeriesWindow(runName, sheet, { end: end ?? undefined, maxPoints: FULL_RESOLUTION }).catch(() => null),
    ),
  );
  const series: Record<string, GridRow[]> = {};
  items.forEach(({ sheet }, i) => {
    const w = windows[i];
    if (!w) return;
    series[sheet] = seriesRowsFromWindow(w);
  });
  return series;
}
