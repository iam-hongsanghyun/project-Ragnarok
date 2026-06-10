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
  /** Grid line colour — matches the old `.chart-grid` stroke. */
  gridLine: string;
  /** Tooltip surface — matches the old dark rgba(15,23,42,0.88) tooltips. */
  tooltipBg: string;
  fontSans: string;
  fontMono: string;
}

export const FALLBACK_CHART_THEME: ChartTheme = {
  text: '#0f172a',
  muted: '#64748b',
  border: '#e2e8f0',
  borderStrong: '#cbd5e1',
  bgHover: '#f1f5f9',
  danger: '#dc2626',
  gridLine: 'rgba(148, 163, 184, 0.28)',
  tooltipBg: 'rgba(15, 23, 42, 0.88)',
  fontSans: '"IBM Plex Sans", "Inter", "Segoe UI", system-ui, sans-serif',
  fontMono: '"JetBrains Mono", "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
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
  cached = {
    text: read('--text', FALLBACK_CHART_THEME.text),
    muted: read('--muted', FALLBACK_CHART_THEME.muted),
    border: read('--border', FALLBACK_CHART_THEME.border),
    borderStrong: read('--border-strong', FALLBACK_CHART_THEME.borderStrong),
    bgHover: read('--bg-hover', FALLBACK_CHART_THEME.bgHover),
    danger: read('--danger', FALLBACK_CHART_THEME.danger),
    gridLine: FALLBACK_CHART_THEME.gridLine,
    tooltipBg: FALLBACK_CHART_THEME.tooltipBg,
    fontSans: read('--font-sans', FALLBACK_CHART_THEME.fontSans),
    fontMono: read('--font-mono', FALLBACK_CHART_THEME.fontMono),
  };
  return cached;
}
