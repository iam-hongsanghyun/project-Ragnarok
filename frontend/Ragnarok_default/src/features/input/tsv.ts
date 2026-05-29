/**
 * TSV helpers for grid copy/paste.
 *
 * Excel and Google Sheets both round-trip through TSV on the clipboard.
 * Cells with embedded tab / newline / quote characters get quoted with
 * doubled-quote escapes, mirroring Excel's behaviour.
 */

export function escapeTsvCell(raw: string): string {
  return /[\t\n"]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

export function serializeTsv(matrix: string[][]): string {
  return matrix.map((row) => row.map(escapeTsvCell).join('\t')).join('\n');
}

/**
 * Parse a clipboard TSV payload back into a row × col matrix. Tolerates the
 * trailing newline Excel typically appends.
 */
export function parseTsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"' && text[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        cur += ch;
      }
    } else if (ch === '"' && cur === '') {
      inQuotes = true;
    } else if (ch === '\t') {
      row.push(cur);
      cur = '';
    } else if (ch === '\n') {
      row.push(cur);
      cur = '';
      out.push(row);
      row = [];
    } else if (ch === '\r') {
      // skip
    } else {
      cur += ch;
    }
  }
  if (cur !== '' || row.length > 0) {
    row.push(cur);
    out.push(row);
  }
  while (out.length > 0 && out[out.length - 1].length === 1 && out[out.length - 1][0] === '') {
    out.pop();
  }
  return out;
}
