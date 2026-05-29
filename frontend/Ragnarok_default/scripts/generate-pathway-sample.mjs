import XLSX from 'xlsx';

const SOURCE = 'sample-networks/capacity_expansion.xlsx';
const TARGET = 'sample-networks/pathway_capacity_expansion.xlsx';

function rows(ws) {
  return XLSX.utils.sheet_to_json(ws, { defval: null });
}

function solarProfile(hour) {
  if (hour < 6 || hour > 18) return 0;
  const x = (hour - 6) / 12;
  return Number(Math.sin(Math.PI * x).toFixed(4));
}

const wb = XLSX.readFile(SOURCE);

const baseSnapshots = rows(wb.Sheets.snapshots);
const periods = [
  { period: 2030, objectiveWeight: 1, yearsWeight: 10 },
  { period: 2040, objectiveWeight: 1, yearsWeight: 10 },
];

const expandedSnapshots = periods.flatMap(({ period }) =>
  baseSnapshots.map((row) => ({
    ...row,
    period,
  })),
);
wb.Sheets.snapshots = XLSX.utils.json_to_sheet(expandedSnapshots);

const generatorRows = rows(wb.Sheets.generators)
  .filter((row) => row.name !== 'NewWind_West');
generatorRows.forEach((row) => {
  if (row.name === 'OldCoal_Hub' || row.name === 'OldGas_Hub') {
    row.build_year = 2020;
    row.lifetime = 35;
  }
});
generatorRows.push(
  {
    name: 'NewWind_West_2030',
    bus: 'West',
    control: 'PQ',
    carrier: 'Wind',
    p_nom: 0,
    p_nom_min: 0,
    p_min_pu: 0,
    p_max_pu: 1,
    marginal_cost: 0,
    capital_cost: 95000,
    committable: false,
    p_nom_extendable: true,
    p_nom_max: 3000,
    build_year: 2030,
    lifetime: 25,
  },
  {
    name: 'NewWind_West_2040',
    bus: 'West',
    control: 'PQ',
    carrier: 'Wind',
    p_nom: 0,
    p_nom_min: 0,
    p_min_pu: 0,
    p_max_pu: 1,
    marginal_cost: 0,
    capital_cost: 76000,
    committable: false,
    p_nom_extendable: true,
    p_nom_max: 4000,
    build_year: 2040,
    lifetime: 25,
  },
  {
    name: 'NewSolar_East_2030',
    bus: 'East',
    control: 'PQ',
    carrier: 'Solar',
    p_nom: 0,
    p_nom_min: 0,
    p_min_pu: 0,
    p_max_pu: 1,
    marginal_cost: 0,
    capital_cost: 70000,
    committable: false,
    p_nom_extendable: true,
    p_nom_max: 2600,
    build_year: 2030,
    lifetime: 25,
  },
  {
    name: 'NewSolar_East_2040',
    bus: 'East',
    control: 'PQ',
    carrier: 'Solar',
    p_nom: 0,
    p_nom_min: 0,
    p_min_pu: 0,
    p_max_pu: 1,
    marginal_cost: 0,
    capital_cost: 52000,
    committable: false,
    p_nom_extendable: true,
    p_nom_max: 3200,
    build_year: 2040,
    lifetime: 25,
  },
);
wb.Sheets.generators = XLSX.utils.json_to_sheet(generatorRows);

const carrierRows = rows(wb.Sheets.carriers);
if (!carrierRows.some((row) => row.name === 'Solar')) {
  carrierRows.push({ name: 'Solar', co2_emissions: 0, color: '#facc15' });
}
wb.Sheets.carriers = XLSX.utils.json_to_sheet(carrierRows);

const loadRows = rows(wb.Sheets['loads-p_set']);
const expandedLoadRows = periods.flatMap(({ period }) => {
  const scale = period === 2040 ? 1.35 : 1.0;
  return loadRows.map((row, index) => {
    const next = { ...row };
    Object.keys(next).forEach((key) => {
      if (typeof next[key] === 'number') {
        next[key] = Number((next[key] * scale).toFixed(4));
      }
    });
    return next;
  });
});
wb.Sheets['loads-p_set'] = XLSX.utils.json_to_sheet(expandedLoadRows);

const pMaxRows = rows(wb.Sheets['generators-p_max_pu']);
const sourceWindColumn = Object.keys(pMaxRows[0] || {}).find((key) => key === 'NewWind_West') || 'NewWind_West';
const expandedPMaxRows = periods.flatMap(({ period }) =>
  pMaxRows.map((row, index) => {
    const hour = index % 24;
    const windBase = Number(row[sourceWindColumn] ?? 0);
    const windFactor = period === 2040 ? 1.08 : 1.0;
    return {
      snapshot: row.snapshot ?? row.name ?? row.datetime,
      NewWind_West_2030: Number((windBase * windFactor).toFixed(4)),
      NewWind_West_2040: Number((windBase * (windFactor + 0.08)).toFixed(4)),
      NewSolar_East_2030: solarProfile(hour),
      NewSolar_East_2040: Number((solarProfile(hour) * 1.05).toFixed(4)),
    };
  }),
);
wb.Sheets['generators-p_max_pu'] = XLSX.utils.json_to_sheet(expandedPMaxRows);

const networkRows = rows(wb.Sheets.network);
if (networkRows[0]) networkRows[0]._multi_invest = true;
wb.Sheets.network = XLSX.utils.json_to_sheet(networkRows);

wb.Sheets.RAGNAROK_Pathway = XLSX.utils.json_to_sheet([
  {
    enabled: true,
    planningMode: 'pathway',
    snapshotMappingMode: 'explicit_period_column',
    overridePolicy: 'reuse_base_inputs',
    selectedPeriod: 2030,
  },
]);
wb.Sheets.RAGNAROK_PathwayPeriods = XLSX.utils.json_to_sheet(periods);

if (!wb.SheetNames.includes('RAGNAROK_Pathway')) wb.SheetNames.push('RAGNAROK_Pathway');
if (!wb.SheetNames.includes('RAGNAROK_PathwayPeriods')) wb.SheetNames.push('RAGNAROK_PathwayPeriods');

XLSX.writeFile(wb, TARGET);
console.log(`Wrote ${TARGET}`);
