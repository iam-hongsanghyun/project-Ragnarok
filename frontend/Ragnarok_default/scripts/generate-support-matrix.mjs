/**
 * Build `docs/SUPPORT_MATRIX.md`.
 *
 * Inputs
 * - Component inventory (sheets, attribute counts, outputs, piecewise curves) and the
 *   standard line / transformer catalogues come from the backend's runtime schema
 *   builder, the same functions that serve `GET /api/config`
 *   (`backend/app/pypsa_schema_builder.py`). They are read from the installed PyPSA
 *   package by a Python subprocess. No checked-in JSON copy is used.
 * - Detail-card / map-marker flags, feature rows and format rows are declared in this
 *   file (FEATURES, IO_FORMATS, COMPONENT_UI). They are the only hand-maintained facts
 *   behind the matrix. Edit them here, then re-run.
 *
 * Interpreter: `$RAGNAROK_PYTHON` if set, else `<repo>/.venv-pypsa/bin/python`
 * (the venv `run.command` / `serve.command` build). It must have PyPSA installed.
 *
 * Run from `frontend/Ragnarok_default`: `npm run generate:support-matrix`
 */
import fs from 'fs/promises';
import path from 'path';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { fileURLToPath } from 'url';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// ROOT is the frontend package (frontend/Ragnarok_default); REPO_ROOT is two levels up.
const ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(ROOT, '..', '..');

const OUT_PATH = path.join(REPO_ROOT, 'docs/SUPPORT_MATRIX.md');
const DEFAULT_PYTHON = path.join(REPO_ROOT, '.venv-pypsa/bin/python');

// Hand-declared UI facts per component sheet. Carried over from the last committed
// capabilities.json (removed in 1c66198). Keys are PyPSA sheet names.
const COMPONENT_UI = {
  buses:              { detailCard: true,  mapMarker: true,  notes: '' },
  carriers:           { detailCard: false, mapMarker: false, notes: 'Surfaced via carrier-color picker and emissions factors; no per-asset card.' },
  generators:         { detailCard: true,  mapMarker: true,  notes: '' },
  global_constraints: { detailCard: false, mapMarker: false, notes: 'Native PyPSA constraints editable in the Constraints workspace.' },
  lines:              { detailCard: true,  mapMarker: true,  notes: '' },
  links:              { detailCard: true,  mapMarker: true,  notes: '' },
  loads:              { detailCard: false, mapMarker: false, notes: 'Aggregated in the bus detail card.' },
  network:            { detailCard: false, mapMarker: false, notes: 'Top-level Network attrs; runtime-import policy limits which fields are applied.' },
  processes:          { detailCard: true,  mapMarker: false, notes: '' },
  shapes:             { detailCard: false, mapMarker: false, notes: 'Optional geo metadata; not user-edited.' },
  shunt_impedances:   { detailCard: true,  mapMarker: false, notes: '' },
  storage_units:      { detailCard: true,  mapMarker: true,  notes: '' },
  stores:             { detailCard: true,  mapMarker: true,  notes: '' },
  sub_networks:       { detailCard: false, mapMarker: false, notes: 'Computed by PyPSA; not user-editable.' },
  line_types:         { detailCard: false, mapMarker: false, notes: '__LINE_TYPES__' },
  transformer_types:  { detailCard: false, mapMarker: false, notes: '__TRANSFORMER_TYPES__' },
  transformers:       { detailCard: true,  mapMarker: true,  notes: '' },
  snapshots:          { detailCard: false, mapMarker: false, notes: 'Snapshot index; controls modelled time window.' },
};

// Optimisation / scenario features. Status is as shipped (see docs/TODO.md PyPSA 1.4 section for IDs).
const FEATURES = [
  { name: 'Single-period LOPF', status: 'supported' },
  { name: 'Multi-period (pathway) capacity expansion', status: 'supported' },
  { name: 'Rolling-horizon dispatch', status: 'supported' },
  { name: 'Two-stage stochastic planning (CVaR via `options.riskPreference`)', status: 'supported' },
  { name: 'Stochastic guard: scenario-invariant attributes refused (HTTP 400)', status: 'supported' },
  { name: 'Security-constrained LOPF (N-1, branch-outage subset)', status: 'supported' },
  { name: 'Piecewise-linear cost and efficiency curves (PyPSA 1.3+)', status: 'supported' },
  { name: 'Iterative transmission expansion (`options.iterativeExpansion`)', status: 'supported' },
  { name: 'Transmission losses (secants / tangents)', status: 'supported' },
  { name: 'Solver choice (HiGHS default; installed linopy solvers)', status: 'supported' },
  { name: 'Temporal clustering (resample / downsample / segment)', status: 'supported' },
  { name: 'Spatial clustering (k-means, modularity, HAC)', status: 'supported' },
  { name: 'Network analysis: PTDF, BODF, cycles, incidence (no solve)', status: 'supported' },
  { name: 'Scheduled maintenance (`maintainable`, `maintenance_*`)', status: 'partial' },
  { name: 'Phase-shifting transformers (`phase_shift_min` / `_max`)', status: 'partial' },
  { name: 'Unit commitment (MIP; Force-LP override)', status: 'partial' },
  { name: 'Load shedding (VOLL backstop)', status: 'supported' },
  { name: 'Carbon price (per-generator marginal cost adder)', status: 'supported' },
  { name: 'Annuitised CAPEX for extendable assets', status: 'supported' },
  { name: 'UI-authored linopy constraints', status: 'supported' },
  { name: 'Native PyPSA global_constraints editor', status: 'supported' },
  { name: 'Scenario presets (deterministic alternatives)', status: 'supported' },
];

// Input / output formats.
const IO_FORMATS = [
  { name: 'Save / Save As (inputs)', status: 'supported' },
  { name: 'Project workbook (inputs + outputs round-trip)', status: 'supported' },
  { name: 'PyPSA-native Excel workbook import / export (`/api/import/pypsa-excel`, `/api/export/pypsa-excel`)', status: 'supported' },
  { name: 'PyPSA-native CSV folder import / export, zipped (`/api/import/pypsa-csv`, `/api/export/pypsa-csv`)', status: 'supported' },
  { name: 'MATPOWER `.m` / `.mat` import (`/api/import/matpower`)', status: 'supported' },
  { name: 'pandapower import (`/api/import/pandapower`; 501 until pandapower is installed)', status: 'partial' },
  { name: 'PyPSA-native netCDF (.nc) import / export via backend', status: 'supported' },
  { name: 'PyPSA-native HDF5 (.h5) import / export via backend', status: 'supported' },
];

function tick(b) { return b ? '✓' : '—'; }

function statusBadge(status) {
  switch (status) {
    case 'supported': return '✓ supported';
    case 'partial':   return '◐ partial';
    case 'planned':   return '○ planned';
    case 'unsupported': return '✗ not supported';
    default:          return status;
  }
}

/** Run the backend schema builder in the backend venv; returns {schema, standardTypes}. */
async function loadRuntimeBundle() {
  const python = process.env.RAGNAROK_PYTHON || DEFAULT_PYTHON;
  const code = [
    'import json, sys',
    'from backend.app.pypsa_schema_builder import build_pypsa_schema, build_standard_types',
    'json.dump({"schema": build_pypsa_schema(), "standardTypes": build_standard_types()}, sys.stdout)',
  ].join('\n');
  try {
    const { stdout } = await execFileAsync(python, ['-c', code], {
      cwd: REPO_ROOT,
      maxBuffer: 64 * 1024 * 1024,
    });
    return JSON.parse(stdout);
  } catch (error) {
    const hint = `Could not run the backend schema builder with ${python}. `
      + 'Build the backend venv (run.command / serve.command) or set RAGNAROK_PYTHON to an interpreter with PyPSA installed.';
    throw new Error(`${hint}\n${error.stderr || error.message}`);
  }
}

async function main() {
  const { schema, standardTypes } = await loadRuntimeBundle();
  const pypsaVersion = schema.meta?.pypsa_version ?? 'unknown';
  const lineTypeCount = standardTypes.line_types?.length ?? 0;
  const transformerTypeCount = standardTypes.transformer_types?.length ?? 0;

  const componentRows = Object.entries(schema.components).map(([sheet, comp]) => {
    const ui = COMPONENT_UI[sheet] ?? { detailCard: false, mapMarker: false, notes: '' };
    let notes = ui.notes;
    if (notes === '__LINE_TYPES__') notes = `Picker exposes ${lineTypeCount} PyPSA standard types in the lines.type cell.`;
    if (notes === '__TRANSFORMER_TYPES__') notes = `Picker exposes ${transformerTypeCount} PyPSA standard types in the transformers.type cell.`;
    return {
      sheet,
      label: comp.label || comp.sheet_name || sheet,
      inputStatic: comp.input_static_attributes?.length ?? 0,
      inputTemporal: comp.input_temporal_attributes?.length ?? 0,
      outputAttrs: comp.output_attributes?.length ?? 0,
      piecewise: comp.piecewise_attributes?.length ?? 0,
      detailCard: ui.detailCard,
      mapMarker: ui.mapMarker,
      notes,
    };
  });

  const lines = [];
  lines.push('# Ragnarok — PyPSA support matrix');
  lines.push('');
  lines.push('> Auto-generated by `frontend/Ragnarok_default/scripts/generate-support-matrix.mjs` (`npm run generate:support-matrix`).');
  lines.push(`> Component data is the backend runtime schema (\`backend/app/pypsa_schema_builder.py\`, PyPSA ${pypsaVersion}, the same data as \`GET /api/config\`).`);
  lines.push('> Feature, format and UI-flag rows are declared in the script.');
  lines.push('> **Do not edit by hand** — edit the script and re-run it.');
  lines.push('');
  lines.push('## Components');
  lines.push('');
  lines.push('| Component | Sheet | Input static | Input time-series | Outputs | Piecewise curves | Detail card | Map marker | Notes |');
  lines.push('|---|---|---:|---:|---:|---:|:---:|:---:|---|');
  for (const row of componentRows) {
    lines.push(`| ${row.label} | \`${row.sheet}\` | ${row.inputStatic} | ${row.inputTemporal} | ${row.outputAttrs} | ${row.piecewise || '—'} | ${tick(row.detailCard)} | ${tick(row.mapMarker)} | ${row.notes} |`);
  }
  lines.push('');
  lines.push('Every component listed above is imported through the generic schema-driven path in `backend/pypsa/network/__init__.py`. `network` (runtime-import allow-list) and `snapshots` (index special case) are the only exceptions. See [`backend/pypsa/network/README.md`](../backend/pypsa/network/README.md).');
  lines.push('');
  lines.push('Counts are the backend schema as shipped: "Input static" and "Input time-series" are the attributes a user can enter, "Outputs" are the attributes PyPSA solves, and "Piecewise curves" are the `<list>-<attr>-pw` curves (see [`docs/backend.md`](backend.md) §5.7).');
  lines.push('');

  lines.push('## Optimisation / scenario features');
  lines.push('');
  lines.push('| Feature | Status |');
  lines.push('|---|---|');
  for (const feat of FEATURES) lines.push(`| ${feat.name} | ${statusBadge(feat.status)} |`);
  lines.push('');

  lines.push('## Input / output formats');
  lines.push('');
  lines.push('| Format | Status |');
  lines.push('|---|---|');
  for (const fmt of IO_FORMATS) lines.push(`| ${fmt.name} | ${statusBadge(fmt.status)} |`);
  lines.push('');

  await fs.writeFile(OUT_PATH, lines.join('\n') + '\n', 'utf8');
  process.stdout.write(`Wrote ${OUT_PATH} (PyPSA ${pypsaVersion}, ${componentRows.length} components)\n`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
