/**
 * World Bank annual electricity consumption → workbook Load row (browser-side).
 *
 * Port of `backend/app/importers/databases/worldbank_demand/importer.py`.
 * Self-contained: slug / dedupe / provenance helpers inlined.
 *
 * The Load row carries the requested year's average MW as `p_set` plus
 * **every year** of the underlying indicators (`kwh_per_capita_*`,
 * `population_*`, `annual_avg_mw_*`) as extra columns — so the user has the
 * full history right next to the value used in the model, without a
 * follow-up fetch.
 *
 * Optional PyPSA attributes (`sign`, `carrier`, `p_set` time-series cols, …)
 * are **not** populated when the upstream is silent — PyPSA's component
 * defaults apply at solve time.
 *
 * No API key; the World Bank Open Data API is public and CORS-enabled.
 */
import type { PreviewSummary, WorkbookFragment } from 'lib/api/databases';
import type { ConvertOptions, DatabaseModule, FetchResult } from '../types';
import { worldbankDemandMeta } from './meta';

const NAME_RE = /[^A-Za-z0-9_]+/g;

function slug(raw: string | null | undefined, fallback: string = 'load'): string {
  if (!raw) return fallback;
  const s = String(raw).trim().replace(NAME_RE, '_').replace(/^_+|_+$/g, '');
  return s || fallback;
}

function apiBase(): string {
  return (
    process.env.REACT_APP_RAGNAROK_WORLDBANK_URL || 'https://api.worldbank.org/v2'
  );
}

interface IndicatorEntry {
  value: number | null;
  date: string | null;
}

async function fetchIndicator(
  countryIso3: string,
  indicator: string,
): Promise<Record<number, number>> {
  const url = `${apiBase()}/country/${countryIso3.toUpperCase()}/indicator/${indicator}?format=json&per_page=200`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`World Bank fetch failed (${resp.status}): ${resp.statusText}`);
  }
  const body = (await resp.json()) as unknown;
  // Response is [metadata, data]; we want the data array.
  if (!Array.isArray(body) || body.length < 2 || !Array.isArray(body[1])) {
    return {};
  }
  const out: Record<number, number> = {};
  for (const entry of body[1] as IndicatorEntry[]) {
    const value = entry?.value;
    const year = entry?.date;
    if (value === null || value === undefined) continue;
    if (year === null || year === undefined) continue;
    const y = parseInt(year, 10);
    const v = Number(value);
    if (Number.isFinite(y) && Number.isFinite(v)) out[y] = v;
  }
  return out;
}

interface Series {
  kwhPerCapita: Record<number, number>;
  population: Record<number, number>;
}

function annualAvgMw(series: Series, year: number): number | null {
  const kwh = series.kwhPerCapita[year];
  const pop = series.population[year];
  if (kwh === undefined || pop === undefined || pop <= 0) return null;
  const totalKwh = kwh * pop;
  // kWh → MWh → MW (averaged over 8760 hours)
  return totalKwh / 8760.0 / 1000.0;
}

function latestYear(series: Series): number {
  const overlap = Object.keys(series.kwhPerCapita)
    .map(Number)
    .filter((y) => y in series.population);
  if (overlap.length) return Math.max(...overlap);
  return new Date().getUTCFullYear() - 3;
}

interface WBPayload {
  series: Series | null;
  notes: string[];
}

export const worldbankDemandModule: DatabaseModule<WBPayload> = {
  meta: worldbankDemandMeta,

  async fetch(region, filters): Promise<FetchResult<WBPayload>> {
    const notes: string[] = [];
    try {
      const kwh = await fetchIndicator(region.countryIso, 'EG.USE.ELEC.KH.PC');
      const pop = await fetchIndicator(region.countryIso, 'SP.POP.TOTL');
      const series: Series = { kwhPerCapita: kwh, population: pop };
      if (!Object.keys(kwh).length) {
        notes.push(
          `No EG.USE.ELEC.KH.PC data for ${region.countryIso}. World Bank coverage stops in 2014 for some countries.`,
        );
      }
      return {
        databaseId: worldbankDemandMeta.id,
        region,
        filters: { ...filters },
        payload: { series, notes },
      };
    } catch (exc) {
      return {
        databaseId: worldbankDemandMeta.id,
        region,
        filters: { ...filters },
        payload: { series: null, notes: [`World Bank fetch failed: ${exc}`] },
        notes: [`World Bank fetch failed: ${exc}`],
      };
    }
  },

  preview(result): PreviewSummary {
    const { series, notes: payloadNotes } = result.payload;
    if (!series || !Object.keys(series.kwhPerCapita).length) {
      return {
        counts: { loads: 0 },
        samples: {},
        notes: payloadNotes.length ? payloadNotes : ['No annual demand data available.'],
      };
    }
    const requestedYear = Number(result.filters.year) || latestYear(series);
    const yearsAvailable = Object.keys(series.kwhPerCapita)
      .map(Number)
      .filter((y) => y in series.population)
      .sort((a, b) => a - b);
    const last15 = yearsAvailable.slice(-15);
    const history = last15.map((y) => {
      const mw = annualAvgMw(series, y);
      return {
        year: y,
        kwh_per_capita: Math.round(series.kwhPerCapita[y] * 10) / 10,
        population: Math.trunc(series.population[y] || 0),
        annual_avg_mw: mw === null ? null : Math.round(mw * 10) / 10,
      };
    });
    const mw = annualAvgMw(series, requestedYear);
    const counts: Record<string, number> = { loads: mw ? 1 : 0 };
    if (mw !== null) counts[`annual_avg_mw_${requestedYear}`] = Math.round(mw);
    const noteText =
      mw !== null
        ? `${requestedYear}: ${Math.round(mw * 10) / 10} MW average load`
        : `No data for ${requestedYear} (latest = ${
            yearsAvailable.length ? yearsAvailable[yearsAvailable.length - 1] : 'n/a'
          })`;
    return {
      counts,
      samples: { history },
      notes: [noteText],
      overlay: { type: 'FeatureCollection', features: [] },
    };
  },

  toSheets(
    result: FetchResult<WBPayload>,
    _options: Required<ConvertOptions>,
  ): WorkbookFragment {
    const { series } = result.payload;
    const ts = new Date().toISOString().slice(0, 19);
    const provenance = (rowCounts: Record<string, number>) => ({
      database_id: worldbankDemandMeta.id,
      country_iso: result.region.countryIso,
      country_name: result.region.countryName,
      filters_json: JSON.stringify(result.filters, Object.keys(result.filters).sort()),
      convert_options_json: JSON.stringify({}),
      fetch_timestamp: ts,
      row_counts_json: JSON.stringify(rowCounts, Object.keys(rowCounts).sort()),
    });

    if (!series || !Object.keys(series.kwhPerCapita).length) {
      return { sheets: {}, provenance: provenance({ loads: 0 }) };
    }

    const requestedYear = Number(result.filters.year) || latestYear(series);
    let chosenYear = requestedYear;
    let mw = annualAvgMw(series, requestedYear);
    if (mw === null) {
      const years = Object.keys(series.kwhPerCapita)
        .map(Number)
        .filter((y) => y in series.population)
        .sort((a, b) => a - b);
      if (years.length) {
        chosenYear = years[years.length - 1];
        mw = annualAvgMw(series, chosenYear);
      }
    }
    if (mw === null) {
      return { sheets: {}, provenance: provenance({ loads: 0 }) };
    }

    const baseName = String(result.filters.load_name || 'national_load');
    const fullName = slug(`${baseName}_${result.region.countryIso}`, 'load');
    const loadRow: Record<string, unknown> = {
      name: fullName,
      // bus, carrier, sign INTENTIONALLY UNSET — PyPSA defaults apply.
      p_set: Math.round(mw * 10000) / 10000,
      country: result.region.countryIso,
      source: 'World Bank',
      year: chosenYear,
    };
    const yearKeys = new Set<number>();
    for (const y of Object.keys(series.kwhPerCapita)) yearKeys.add(Number(y));
    for (const y of Object.keys(series.population)) yearKeys.add(Number(y));
    for (const y of Array.from(yearKeys).sort((a, b) => a - b)) {
      const kwh = series.kwhPerCapita[y];
      const pop = series.population[y];
      const mwY = annualAvgMw(series, y);
      if (kwh !== undefined) loadRow[`kwh_per_capita_${y}`] = Math.round(kwh * 10000) / 10000;
      if (pop !== undefined) loadRow[`population_${y}`] = Math.trunc(pop);
      if (mwY !== null) loadRow[`annual_avg_mw_${y}`] = Math.round(mwY * 10000) / 10000;
    }
    return {
      sheets: { loads: [loadRow] },
      provenance: provenance({ loads: 1, year: chosenYear }),
    };
  },
};
