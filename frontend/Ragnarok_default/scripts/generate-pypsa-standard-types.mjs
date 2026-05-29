/**
 * Regenerate `src/config/pypsa_standard_types.json` from the PyPSA GitHub
 * tree.
 *
 * PyPSA ships standard `line_types` and `transformer_types` catalogues as
 * CSV files under `pypsa/data/standard_types/`. They are exactly what
 * populates `pypsa.Network().line_types` / `.transformer_types` by default.
 *
 * Mirrors the pattern of `generate-pypsa-schema.mjs`: fetches from master,
 * records the commit SHA, and writes a JSON file that the frontend reads
 * without bundling a CSV parser.
 *
 * Run via: `node scripts/generate-pypsa-standard-types.mjs`
 */
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import https from 'https';

const REPO = 'PyPSA/PyPSA';
const REF = 'master';
const RAW_BASE = `https://raw.githubusercontent.com/${REPO}/${REF}/pypsa/data/standard_types`;
const REF_API = `https://api.github.com/repos/${REPO}/git/ref/heads/${REF}`;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const OUTPUT_PATH = path.join(ROOT, 'src/config/pypsa_standard_types.json');

const CATALOGUES = [
  { sheet: 'line_types', file: 'line_types.csv' },
  { sheet: 'transformer_types', file: 'transformer_types.csv' },
];

function request(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          'User-Agent': 'ragnarok-standard-types-generator',
          Accept: 'application/vnd.github+json',
        },
      },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => {
          if ((res.statusCode ?? 500) >= 400) {
            reject(new Error(`Request failed (${res.statusCode}) for ${url}`));
            return;
          }
          resolve({ headers: res.headers, body });
        });
      },
    ).on('error', reject);
  });
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === '"') {
      if (inQuotes && next === '"') {
        cell += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      row.push(cell);
      cell = '';
    } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
      if (ch === '\r' && next === '\n') i += 1;
      row.push(cell);
      if (row.some((value) => value !== '')) rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += ch;
    }
  }

  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

/** Coerce a CSV cell to number, boolean, or string (matching PyPSA's CSV
 *  semantics — blank = absent; numeric strings → numbers). */
function coerce(value) {
  if (value === '' || value === undefined || value === null) return '';
  if (/^-?\d+$/.test(value)) return parseInt(value, 10);
  // Matches "1.2", "1.", ".5", and scientific notation. Trailing-dot forms
  // like "50." appear in PyPSA's CSVs and must coerce to numbers.
  if (/^-?(\d+\.?\d*|\.\d+)([eE]-?\d+)?$/.test(value)) return parseFloat(value);
  return value;
}

function csvToRecords(csv) {
  const rows = parseCsv(csv);
  if (rows.length === 0) return [];
  const [header, ...body] = rows;
  return body.map((row) => {
    const record = {};
    header.forEach((column, index) => {
      record[column] = coerce(row[index] ?? '');
    });
    return record;
  });
}

async function main() {
  const refResp = await request(REF_API);
  const refInfo = JSON.parse(refResp.body);

  const catalogues = {};
  for (const { sheet, file } of CATALOGUES) {
    const url = `${RAW_BASE}/${file}`;
    const { body } = await request(url);
    catalogues[sheet] = csvToRecords(body);
    process.stdout.write(`  ${sheet}: ${catalogues[sheet].length} rows\n`);
  }

  const payload = {
    source: {
      repo: REPO,
      ref: REF,
      commit: refInfo.object?.sha ?? null,
      generated_at: new Date().toISOString(),
      note: 'Built-in PyPSA standard component-type catalogues. Regenerate with `node scripts/generate-pypsa-standard-types.mjs`.',
    },
    ...catalogues,
  };

  await fs.writeFile(OUTPUT_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  process.stdout.write(`Wrote ${OUTPUT_PATH}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
