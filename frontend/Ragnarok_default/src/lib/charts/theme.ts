/**
 * Chart theme — the design tokens (styles/_tokens.css) resolved to concrete
 * values for ECharts, which themes via JS options rather than CSS.
 *
 * `readChartTheme()` resolves the CSS variables off :root at call time, so
 * charts always match the stylesheet; the fallbacks mirror _tokens.css for
 * non-DOM contexts (tests).
 */

export interface ChartTheme {
  text: string;
  muted: string;
  border: string;
  borderStrong: string;
  bgHover: string;
  danger: string;
  /** Grid line colour — matches `--chart-grid` (recessive chrome). */
  gridLine: string;
  /** Tooltip surface — matches `--chart-tooltip-bg`. */
  tooltipBg: string;
  fontSans: string;
  fontMono: string;
  /** Validated categorical series order (`--series-1`..`--series-8`) — assign
   *  to generic series IN THIS ORDER, never cycle. Charts that colour by a
   *  domain dimension (energy carrier, etc.) keep whatever colour the data
   *  already carries; this palette is only for otherwise-uncoloured series. */
  seriesPalette: string[];
  /** Grid line colour — `--chart-grid`. Same value as `gridLine`; both names
   *  are kept so existing call sites and the new builders can each use the
   *  one that reads clearly. */
  grid: string;
  /** Axis line colour — `--chart-axis`. Recessive chrome, one step darker
   *  than `grid` so axis baselines stay legible without competing with data. */
  axis: string;
  /** Tooltip text colour — `--chart-tooltip-text`. */
  tooltipText: string;
}

export const FALLBACK_CHART_THEME: ChartTheme = {
  text: '#1c1b17',
  muted: '#6b6962',
  border: '#e2e8f0',
  borderStrong: '#cbd5e1',
  bgHover: '#f1f5f9',
  danger: '#dc2626',
  gridLine: '#e7e5dd',
  tooltipBg: '#232219',
  fontSans: '"IBM Plex Sans", "Inter", "Segoe UI", system-ui, sans-serif',
  fontMono: '"JetBrains Mono", "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  seriesPalette: [
    '#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#4a3aa7', '#e34948',
  ],
  grid: '#e7e5dd',
  axis: '#c3c2b7',
  tooltipText: '#f5f4ef',
};

let cached: ChartTheme | null = null;

/** Resolve the chart theme from the :root CSS variables (cached). */
export function readChartTheme(): ChartTheme {
  if (cached) return cached;
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return FALLBACK_CHART_THEME;
  }
  const style = window.getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string =>
    style.getPropertyValue(name).trim() || fallback;
  const grid = read('--chart-grid', FALLBACK_CHART_THEME.grid);
  cached = {
    text: read('--text', FALLBACK_CHART_THEME.text),
    muted: read('--muted', FALLBACK_CHART_THEME.muted),
    border: read('--border', FALLBACK_CHART_THEME.border),
    borderStrong: read('--border-strong', FALLBACK_CHART_THEME.borderStrong),
    bgHover: read('--bg-hover', FALLBACK_CHART_THEME.bgHover),
    danger: read('--danger', FALLBACK_CHART_THEME.danger),
    gridLine: grid,
    tooltipBg: read('--chart-tooltip-bg', FALLBACK_CHART_THEME.tooltipBg),
    fontSans: read('--font-sans', FALLBACK_CHART_THEME.fontSans),
    fontMono: read('--font-mono', FALLBACK_CHART_THEME.fontMono),
    seriesPalette: FALLBACK_CHART_THEME.seriesPalette.map((fallback, i) =>
      read(`--series-${i + 1}`, fallback)),
    grid,
    axis: read('--chart-axis', FALLBACK_CHART_THEME.axis),
    tooltipText: read('--chart-tooltip-text', FALLBACK_CHART_THEME.tooltipText),
  };
  return cached;
}
