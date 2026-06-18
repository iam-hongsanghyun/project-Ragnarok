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
 * Fetch every named output series sheet for a run at full resolution and
 * assemble the `outputs.series` map that `deriveAssetDetails` expects: sheet
 * name → rows, each row keyed by component name plus a `snapshot` index column.
 *
 * Sheets that fail to load are skipped (per-asset charts for those components
 * stay empty) rather than failing the whole hydration.
 */
export async function fetchRunOutputSeries(
  runName: string,
  sheets: string[],
): Promise<Record<string, GridRow[]>> {
  const windows = await Promise.all(
    sheets.map((sheet) =>
      getRunSeriesWindow(runName, sheet, { maxPoints: FULL_RESOLUTION }).catch(() => null),
    ),
  );
  const series: Record<string, GridRow[]> = {};
  sheets.forEach((sheet, i) => {
    const w = windows[i];
    if (!w) return;
    series[sheet] = seriesRowsFromWindow(w);
  });
  return series;
}
