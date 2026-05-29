import * as XLSX from 'xlsx';
import { RunResults, WorkbookModel } from '../types';
import { buildWorkbook } from './workbook';

// ── helpers ───────────────────────────────────────────────────────────────────

function makeAppendSheet(wb: XLSX.WorkBook) {
  return (name: string, data: Record<string, unknown>[]) => {
    if (!data || data.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(data);
    autoFitCols(ws);
    XLSX.utils.book_append_sheet(wb, ws, name);
  };
}

/** Set column widths based on max content length (capped at 40 chars). */
function autoFitCols(ws: XLSX.WorkSheet) {
  const range = XLSX.utils.decode_range(ws['!ref'] ?? 'A1');
  const colWidths: number[] = [];
  for (let R = range.s.r; R <= range.e.r; R++) {
    for (let C = range.s.c; C <= range.e.c; C++) {
      const cell = ws[XLSX.utils.encode_cell({ r: R, c: C })];
      if (!cell) continue;
      const len = String(cell.v ?? '').length;
      colWidths[C] = Math.min(40, Math.max(colWidths[C] ?? 8, len));
    }
  }
  ws['!cols'] = colWidths.map((w) => ({ wch: w }));
}

function pivotSeries(
  rows: Array<{ timestamp?: string; label?: string; period?: number | null; values?: Record<string, number>; total?: number }>,
): Record<string, unknown>[] {
  return rows.map((row) => {
    const { timestamp, label, period, values = {}, total } = row;
    return { ...(period !== undefined && period !== null ? { period } : {}), timestamp: timestamp ?? label, ...values, ...(total !== undefined ? { total } : {}) };
  });
}

// ── main export ───────────────────────────────────────────────────────────────

/**
 * Export the entire model (all input sheets + all result output sheets) to
 * a single .xlsx file.
 */
export function exportFullResults(
  model: WorkbookModel,
  results: RunResults,
  baseFilename = 'ragnarok',
): void {
  // Start from the input workbook so all model sheets are already in.
  const wb = buildWorkbook(model);
  const appendSheet = makeAppendSheet(wb);

  // ── Output sheets ──────────────────────────────────────────────────────────

  appendSheet('OUT_Summary', results.summary as unknown as Record<string, unknown>[]);

  appendSheet('OUT_Dispatch', pivotSeries(results.dispatchSeries));
  appendSheet('OUT_GenDispatch', pivotSeries(results.generatorDispatchSeries));

  appendSheet(
    'OUT_SysPrice',
    results.systemPriceSeries.map((p) => ({
      ...(p.period !== undefined && p.period !== null ? { period: p.period } : {}),
      timestamp: p.timestamp ?? p.label,
      price_per_MWh: p.value,
    })),
  );
  appendSheet(
    'OUT_Emissions',
    results.systemEmissionsSeries.map((p) => ({
      ...(p.period !== undefined && p.period !== null ? { period: p.period } : {}),
      timestamp: p.timestamp ?? p.label,
      emissions_t: p.value,
    })),
  );

  appendSheet(
    'OUT_Storage',
    results.storageSeries.map((s) => ({
      ...(s.period !== undefined && s.period !== null ? { period: s.period } : {}),
      timestamp: s.timestamp ?? s.label,
      charge_MW: s.charge,
      discharge_MW: s.discharge,
      state_MWh: s.state,
    })),
  );

  appendSheet(
    'OUT_CarrierMix',
    results.carrierMix.map(({ label, value }) => ({ carrier: label, energy_MWh: value })),
  );
  appendSheet(
    'OUT_CostBreakdown',
    results.costBreakdown.map(({ label, value }) => ({ category: label, cost: value })),
  );
  appendSheet(
    'OUT_NodalBalance',
    results.nodalBalance.map((n) => ({ bus: n.label, load_MW: n.load, generation_MW: n.generation })),
  );
  appendSheet(
    'OUT_LineLoading',
    results.lineLoading.map((l) => ({ branch: l.label, loading_pct: l.value })),
  );

  // ── Per-asset detail sheets ────────────────────────────────────────────────

  const genRows = Object.values(results.assetDetails.generators).flatMap((g) =>
    g.outputSeries.map((s) => ({
      generator: g.name,
      carrier: g.carrier,
      bus: g.bus,
      timestamp: s.timestamp,
      output_MW: s.output,
    })),
  );
  appendSheet('OUT_GenDetail', genRows);

  const storageRows = Object.values(results.assetDetails.storageUnits).flatMap((u) =>
    u.stateSeries.map((s) => ({
      unit: u.name,
      bus: u.bus,
      timestamp: s.timestamp,
      state_MWh: s.state,
    })),
  );
  appendSheet('OUT_StorageDetail', storageRows);

  const branchRows = Object.values(results.assetDetails.branches).flatMap((b) =>
    b.flowSeries.map((s) => ({
      branch: b.name,
      type: b.component,
      bus0: b.bus0,
      bus1: b.bus1,
      timestamp: s.timestamp,
      p0_MW: s.p0,
      p1_MW: s.p1,
    })),
  );
  appendSheet('OUT_BranchFlow', branchRows);

  // Merit order
  if (results.meritOrder && results.meritOrder.length > 0) {
    appendSheet('OUT_MeritOrder', results.meritOrder.map((e) => ({
      name: e.name,
      carrier: e.carrier,
      bus: e.bus,
      marginal_cost: e.marginal_cost,
      p_nom_MW: e.p_nom,
      cumulative_MW: e.cumulative_mw,
    })));
  }

  // Capacity expansion
  if (results.expansionResults && results.expansionResults.length > 0) {
    appendSheet('OUT_Expansion', results.expansionResults.map((e) => ({
      name: e.name,
      component: e.component,
      carrier: e.carrier,
      bus: e.bus,
      p_nom_MW: e.p_nom_mw,
      p_nom_opt_MW: e.p_nom_opt_mw,
      delta_MW: e.delta_mw,
      capital_cost: e.capital_cost,
      capex_annual: e.capex_annual,
    })));
  }

  // Emissions breakdown
  if (results.emissionsBreakdown) {
    appendSheet('OUT_EmissionsByGen', results.emissionsBreakdown.byGenerator.map((e) => ({
      name: e.name,
      carrier: e.carrier,
      bus: e.bus,
      energy_MWh: e.energy_mwh,
      emissions_tCO2: e.emissions_tco2,
      intensity_kg_MWh: e.intensity_kg_mwh,
    })));
    appendSheet('OUT_EmissionsByCarrier', results.emissionsBreakdown.byCarrier.map((e) => ({
      carrier: e.carrier,
      energy_MWh: e.energy_mwh,
      emissions_tCO2: e.emissions_tco2,
      intensity_kg_MWh: e.intensity_kg_mwh,
    })));
  }

  // CO2 shadow price
  if (results.co2Shadow && results.co2Shadow.found) {
    appendSheet('OUT_CO2Shadow', [{
      constraint_name: results.co2Shadow.constraint_name ?? '',
      shadow_price: results.co2Shadow.shadow_price,
      explicit_price: results.co2Shadow.explicit_price,
      cap_ktco2: results.co2Shadow.cap_ktco2 ?? '',
      status: results.co2Shadow.status,
      note: results.co2Shadow.note,
    }]);
  }

  const ts = new Date().toISOString().slice(0, 19).replace(/[:.]/g, '-');
  XLSX.writeFile(wb, `${baseFilename}_${ts}.xlsx`);
}
