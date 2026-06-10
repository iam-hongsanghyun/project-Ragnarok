import ExcelJS from 'exceljs';

// ── SVG → PNG (canvas round-trip) ────────────────────────────────────────────

/**
 * Chrome composited around the chart image on export. The on-screen legend and
 * the Y-axis unit live in HTML *outside* the chart's <svg>, so rasterising the
 * SVG alone drops them. We draw them onto the canvas instead so the exported
 * image is self-describing (title + unit at the top, colour legend below).
 */
export interface ChartChrome {
  title?: string;
  /** Y-axis unit, e.g. "MWh" — drawn under the title. */
  unit?: string;
  /** Colour key for the series / slices, drawn below the chart. */
  legend?: { label: string; color: string }[];
}

interface RasterResult {
  base64: string; // PNG base64 (no "data:..." prefix)
  width: number; // CSS px of the composited image
  height: number;
}

const PAD = 14;
const SCALE = 2; // 2× for retina sharpness
const TITLE_FONT = '600 15px -apple-system, system-ui, sans-serif';
const UNIT_FONT = '12px -apple-system, system-ui, sans-serif';
const LEGEND_FONT = '12px -apple-system, system-ui, sans-serif';
const SWATCH = 11;
const SWATCH_GAP = 6;
const ITEM_GAP = 18;
const LINE_H = 19;
const TITLE_H = 20;
const UNIT_H = 16;

/** Wrap legend items into lines that fit `maxWidth`. */
function layoutLegend(
  ctx: CanvasRenderingContext2D,
  items: { label: string; color: string }[],
  maxWidth: number,
): { label: string; color: string }[][] {
  ctx.font = LEGEND_FONT;
  const lines: { label: string; color: string }[][] = [];
  let line: { label: string; color: string }[] = [];
  let x = 0;
  for (const it of items) {
    const w = SWATCH + SWATCH_GAP + ctx.measureText(it.label).width + ITEM_GAP;
    if (x + w > maxWidth && line.length) {
      lines.push(line);
      line = [];
      x = 0;
    }
    line.push(it);
    x += w;
  }
  if (line.length) lines.push(line);
  return lines;
}

/**
 * Serialise an inline SVG element to a PNG (base64 + dimensions) via an
 * off-screen Canvas, compositing the optional title/unit/legend chrome around
 * it. Returns null if anything fails.
 */
export async function svgToPng(svgEl: SVGElement, chrome: ChartChrome = {}): Promise<RasterResult | null> {
  return new Promise((resolve) => {
    try {
      const serializer = new XMLSerializer();
      let svgStr = serializer.serializeToString(svgEl);
      // Ensure the SVG namespace attribute is present (required by browsers)
      if (!svgStr.includes('xmlns=')) {
        svgStr = svgStr.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }
      const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        const baseW = svgEl.clientWidth || 800;
        const baseH = svgEl.clientHeight || 350;

        // Top band: title + unit (each present only if supplied).
        const titleH = chrome.title ? TITLE_H : 0;
        const unitH = chrome.unit ? UNIT_H : 0;
        const topBand = titleH || unitH ? PAD + titleH + unitH : 0;

        // Legend band: wrap onto as many lines as needed (measure off-screen).
        const legendItems = chrome.legend ?? [];
        const measure = document.createElement('canvas').getContext('2d');
        const legendLines = legendItems.length && measure
          ? layoutLegend(measure, legendItems, baseW - PAD * 2)
          : [];
        const legendH = legendLines.length ? PAD + legendLines.length * LINE_H : 0;

        const totalW = baseW;
        const totalH = topBand + baseH + legendH;

        const canvas = document.createElement('canvas');
        canvas.width = totalW * SCALE;
        canvas.height = totalH * SCALE;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          URL.revokeObjectURL(url);
          resolve(null);
          return;
        }
        ctx.scale(SCALE, SCALE);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, totalW, totalH);

        // Title + unit
        ctx.textBaseline = 'alphabetic';
        if (chrome.title) {
          ctx.fillStyle = '#0f172a';
          ctx.font = TITLE_FONT;
          ctx.fillText(chrome.title, PAD, PAD + 13);
        }
        if (chrome.unit) {
          ctx.fillStyle = '#64748b';
          ctx.font = UNIT_FONT;
          ctx.fillText(`Unit: ${chrome.unit}`, PAD, PAD + titleH + 12);
        }

        // The chart itself
        ctx.drawImage(img, 0, topBand, baseW, baseH);

        // Legend
        if (legendLines.length) {
          ctx.font = LEGEND_FONT;
          ctx.textBaseline = 'middle';
          let y = topBand + baseH + PAD + LINE_H / 2;
          for (const ln of legendLines) {
            let x = PAD;
            for (const it of ln) {
              ctx.fillStyle = it.color || '#94a3b8';
              ctx.fillRect(x, y - SWATCH / 2, SWATCH, SWATCH);
              ctx.fillStyle = '#0f172a';
              ctx.fillText(it.label, x + SWATCH + SWATCH_GAP, y);
              x += SWATCH + SWATCH_GAP + ctx.measureText(it.label).width + ITEM_GAP;
            }
            y += LINE_H;
          }
        }

        URL.revokeObjectURL(url);
        const dataUrl = canvas.toDataURL('image/png');
        resolve({ base64: dataUrl.split(',')[1], width: totalW, height: totalH });
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      img.src = url;
    } catch {
      resolve(null);
    }
  });
}

// ── Per-chart export ──────────────────────────────────────────────────────────

/**
 * Export a chart card to an Excel file with two sheets:
 *   "Data"  — tabular rows matching what is displayed
 *   "Chart" — the chart rendered as an embedded PNG image, with the title,
 *             Y-axis unit, and colour legend composited in.
 *
 * @param title        Display name / default filename prefix
 * @param headers      Column names (in order)
 * @param rows         Data rows (each row is a Record keyed by headers)
 * @param containerEl  DOM element that wraps the SVG chart (querySelector('svg') is used)
 * @param filename     Override filename (default: `<title>_<date>.xlsx`)
 * @param chrome       Title/unit/legend to composite onto the exported image
 */
/**
 * Read the chart's ON-SCREEN HTML legend (swatch colour + label) so the export
 * can ALWAYS composite a legend that matches what the user sees — even when the
 * caller passed no `chrome.legend` (or an empty one). Looks for the shared
 * `.legend-swatch` pattern used by every chart card's HTML legend.
 */
function legendFromDom(containerEl: HTMLElement | null): { label: string; color: string }[] {
  if (!containerEl) return [];
  const out: { label: string; color: string }[] = [];
  containerEl.querySelectorAll('.legend-swatch').forEach((sw) => {
    const item = sw.parentElement;
    if (!item) return;
    const label = (item.textContent ?? '').trim();
    if (!label) return;
    const color = window.getComputedStyle(sw).backgroundColor || '#94a3b8';
    out.push({ label, color });
  });
  return out;
}

/** Drop empty/duplicate legend entries and coerce values to plain strings. */
function cleanLegend(items: { label: string; color: string }[] | undefined): { label: string; color: string }[] {
  const seen = new Set<string>();
  const out: { label: string; color: string }[] = [];
  for (const it of items ?? []) {
    const label = String(it?.label ?? '').trim();
    if (!label || seen.has(label)) continue;
    seen.add(label);
    out.push({ label, color: String(it?.color ?? '') || '#94a3b8' });
  }
  return out;
}

export async function exportChartToExcel(
  title: string,
  headers: string[],
  rows: Record<string, unknown>[],
  containerEl: HTMLElement | null,
  filename?: string,
  chrome?: ChartChrome,
): Promise<void> {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = 'Ragnarok';
  workbook.created = new Date();

  // ── Data sheet ─────────────────────────────────────────────────────────────
  const dataSheet = workbook.addWorksheet('Data');

  // Header row — bold
  const headerRow = dataSheet.addRow(headers);
  headerRow.font = { bold: true };
  headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE2E8F0' } };

  // Data rows
  rows.forEach((row) => {
    dataSheet.addRow(headers.map((h) => row[h] ?? ''));
  });

  // Auto-width columns
  headers.forEach((_, i) => {
    const col = dataSheet.getColumn(i + 1);
    col.width = Math.max(
      headers[i].length + 2,
      ...rows.slice(0, 50).map((r) => String(r[headers[i]] ?? '').length + 2),
    );
  });

  // ── Chart image sheet ──────────────────────────────────────────────────────
  const svgEl = containerEl?.querySelector('svg') ?? null;
  if (svgEl) {
    try {
      // The legend must ALWAYS export: prefer the caller's, fall back to the
      // on-screen HTML legend (what the user actually sees next to the chart).
      const legend = (() => {
        const fromChrome = cleanLegend(chrome?.legend);
        return fromChrome.length ? fromChrome : cleanLegend(legendFromDom(containerEl));
      })();
      const effChrome: ChartChrome = { title, ...chrome, legend };
      const raster = await svgToPng(svgEl as SVGElement, effChrome);
      if (raster) {
        const chartSheet = workbook.addWorksheet('Chart');
        const imageId = workbook.addImage({ base64: raster.base64, extension: 'png' });
        chartSheet.addImage(imageId, {
          tl: { col: 0, row: 0 },
          ext: { width: raster.width, height: raster.height },
        });
        // Make the sheet wide / tall enough to show the image
        chartSheet.getColumn(1).width = Math.ceil(raster.width / 8);
        chartSheet.getRow(1).height = raster.height * 0.75;
      }
    } catch (err) {
      console.warn('[exportChart] chart image embed failed:', err);
    }
  }

  // ── Download ───────────────────────────────────────────────────────────────
  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download =
    filename ??
    `${title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_${new Date().toISOString().slice(0, 10)}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
