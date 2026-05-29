import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import https from 'https';

const REPO = 'PyPSA/PyPSA';
const REF = 'master';
const RAW_BASE = `https://raw.githubusercontent.com/${REPO}/${REF}/pypsa/data`;
const API_BASE = `https://api.github.com/repos/${REPO}/contents/pypsa/data/component_attrs?ref=${REF}`;
const REF_API = `https://api.github.com/repos/${REPO}/git/ref/heads/${REF}`;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const OUTPUT_PATH = path.join(ROOT, 'src/config/pypsa_schema.json');

const SHEET_NAME_OVERRIDES = {
  networks: 'network',
};

function request(url) {
  return new Promise((resolve, reject) => {
    https.get(
      url,
      {
        headers: {
          'User-Agent': 'ragnarok-schema-generator',
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

function titleCase(value) {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function normalizeStatus(status) {
  if (status.startsWith('Input')) return 'input';
  return 'output';
}

function normalizeStorage(type) {
  const lowered = String(type || '').toLowerCase();
  if (lowered.includes('static or series')) return 'static_or_series';
  if (lowered.includes('series')) return 'series';
  return 'static';
}

function toRecord(header, row) {
  return Object.fromEntries(header.map((key, index) => [key, row[index] ?? '']));
}

async function main() {
  const [{ body: componentsCsv }, { body: dirListingJson }, { body: refJson }] = await Promise.all([
    request(`${RAW_BASE}/components.csv`),
    request(API_BASE),
    request(REF_API),
  ]);
  const refInfo = JSON.parse(refJson);

  const componentRows = parseCsv(componentsCsv);
  const [componentHeader, ...componentBody] = componentRows;
  const componentsByListName = Object.fromEntries(
    componentBody.map((row) => {
      const record = toRecord(componentHeader, row);
      return [record.list_name, record];
    }),
  );

  const directoryListing = JSON.parse(dirListingJson);
  const attrsFiles = directoryListing
    .filter((entry) => entry.type === 'file' && entry.name.endsWith('.csv'))
    .sort((a, b) => a.name.localeCompare(b.name));

  const attrFiles = await Promise.all(
    attrsFiles.map(async (entry) => {
      const response = await request(entry.download_url);
      return { name: entry.name.replace(/\.csv$/i, ''), csv: response.body };
    }),
  );

  const components = {};

  for (const file of attrFiles) {
    const rows = parseCsv(file.csv);
    const [header, ...body] = rows;
    const componentMeta = componentsByListName[file.name] ?? {};
    const componentName = componentMeta.component || titleCase(file.name);
    const listName = file.name;
    const sheetName = SHEET_NAME_OVERRIDES[listName] ?? listName;
    const attributes = body.map((row) => {
      const record = toRecord(header, row);
      const normalizedStatus = normalizeStatus(record.status || '');
      const storage = normalizeStorage(record.type);
      return {
        attribute: record.attribute,
        type: record.type,
        unit: record.unit,
        default: record.default,
        description: record.description,
        status: normalizedStatus,
        raw_status: record.status,
        required: (record.status || '').includes('(required)'),
        storage,
      };
    });

    components[sheetName] = {
      unique_id: sheetName,
      component_name: componentName,
      list_name: listName,
      sheet_name: sheetName,
      label: componentName,
      category: componentMeta.category || '',
      source_file: `${RAW_BASE}/component_attrs/${file.name}.csv`,
      attributes,
      input_attributes: attributes.filter((attr) => attr.status === 'input').map((attr) => attr.attribute),
      output_attributes: attributes.filter((attr) => attr.status === 'output').map((attr) => attr.attribute),
      // `static_or_series` attributes belong to BOTH lists — they can be entered
      // as a static scalar in the component sheet, or as a column in the matching
      // time-series sheet. Examples: marginal_cost, efficiency, p_max_pu.
      temporal_attributes: attributes.filter((attr) => attr.storage !== 'static').map((attr) => attr.attribute),
      static_attributes: attributes.filter((attr) => attr.storage !== 'series').map((attr) => attr.attribute),
      input_temporal_attributes: attributes.filter((attr) => attr.status === 'input' && attr.storage !== 'static').map((attr) => attr.attribute),
      input_static_attributes: attributes.filter((attr) => attr.status === 'input' && attr.storage !== 'series').map((attr) => attr.attribute),
      order: componentBody.findIndex((row) => row[componentHeader.indexOf('list_name')] === listName),
    };
  }

  components.snapshots = {
    unique_id: 'snapshots',
    component_name: 'Snapshots',
    list_name: 'snapshots',
    sheet_name: 'snapshots',
    label: 'Snapshots',
    category: 'system',
    source_file: `${RAW_BASE}/component_attrs/networks.csv`,
    attributes: [
      {
        attribute: 'snapshot',
        type: 'string',
        unit: 'n/a',
        default: 'now',
        description: 'Snapshot label or timestamp used by the workbook snapshot index.',
        status: 'input',
        raw_status: 'Input (required)',
        required: true,
        storage: 'static',
      },
    ],
    input_attributes: ['snapshot'],
    output_attributes: [],
    temporal_attributes: [],
    static_attributes: ['snapshot'],
    input_temporal_attributes: [],
    input_static_attributes: ['snapshot'],
    order: -1,
  };

  const schema = {
    meta: {
      repo: `https://github.com/${REPO}`,
      ref: REF,
      commit_sha: refInfo?.object?.sha ?? '',
      generated_at: new Date().toISOString(),
      generator: 'scripts/generate-pypsa-schema.mjs',
      note: 'Generated from PyPSA GitHub component metadata.',
      // PyPSA "sheets" that are NOT user-editable component tables.
      // `network` is the top-level Network attribute row (single record),
      // `snapshots` is the time index, `shapes` is optional geo metadata
      // and `sub_networks` is computed by PyPSA itself.
      // Consumers (Python backend + TS frontend) skip these in the
      // component iteration loop and handle them via dedicated codepaths.
      non_component_sheets: ['network', 'snapshots', 'shapes', 'sub_networks'],
    },
    components,
  };

  await fs.writeFile(OUTPUT_PATH, `${JSON.stringify(schema, null, 2)}\n`, 'utf8');
  process.stdout.write(`Wrote ${OUTPUT_PATH}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
