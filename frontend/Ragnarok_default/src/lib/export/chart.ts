import ExcelJS from 'exceljs';

// ── SVG → PNG (canvas round-trip) ────────────────────────────────────────────

/**
 * Serialise an inline SVG element to a PNG base64 string (no "data:..." prefix)
 * via an off-screen Canvas.  Returns null if anything fails.
 */
export async function svgToPng(svgEl: SVGElement): Promise<string | null> {
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
        const w = svgEl.clientWidth || 800;
        const h = svgEl.clientHeight || 350;
        const canvas = document.createElement('canvas');
        canvas.width = w * 2;  // 2× for retina sharpness
        canvas.height = h * 2;
        const ctx = canvas.getContext('2d');
        if (!ctx) { URL.revokeObjectURL(url); resolve(null); return; }
        ctx.scale(2, 2);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        const dataUrl = canvas.toDataURL('image/png');
        resolve(dataUrl.split(',')[1]); // base64 only
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
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
 *   "Chart" — the chart rendered as an embedded PNG image
 *
 * @param title        Display name / default filename prefix
 * @param headers      Column names (in order)
 * @param rows         Data rows (each row is a Record keyed by headers)
 * @param containerEl  DOM element that wraps the SVG chart (querySelector('svg') is used)
 * @param filename     Override filename (default: `<title>_<date>.xlsx`)
 */
export async function exportChartToExcel(
  title: string,
  headers: string[],
  rows: Record<string, unknown>[],
  containerEl: HTMLElement | null,
  filename?: string,
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
      const pngBase64 = await svgToPng(svgEl as SVGElement);
      if (pngBase64) {
        const chartSheet = workbook.addWorksheet('Chart');
        const imageId = workbook.addImage({ base64: pngBase64, extension: 'png' });
        const svgW = (svgEl as SVGElement).clientWidth || 800;
        const svgH = (svgEl as SVGElement).clientHeight || 350;
        chartSheet.addImage(imageId, {
          tl: { col: 0, row: 0 },
          ext: { width: svgW, height: svgH },
        });
        // Make the sheet wide enough to show the image
        chartSheet.getColumn(1).width = Math.ceil(svgW / 8);
        chartSheet.getRow(1).height = svgH * 0.75;
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
