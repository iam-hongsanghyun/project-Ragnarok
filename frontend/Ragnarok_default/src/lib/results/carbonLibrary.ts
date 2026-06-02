/**
 * Carbon-schedule library — a named set of reusable carbon-price curves saved
 * with the project (in the `RAGNAROK_CarbonSchedules` model sheet, so it
 * travels with project export/import). Mirrors the scenario-catalog pattern.
 */
import {
  CarbonPriceScheduleEntry,
  CarbonScheduleProfile,
  GridRow,
  Primitive,
  WorkbookModel,
} from '../types';

export const CARBON_LIBRARY_SHEET = 'RAGNAROK_CarbonSchedules';

export function createCarbonProfileId(): string {
  return `carbon-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function str(value: Primitive | undefined): string {
  return typeof value === 'string' ? value : '';
}

/** Sanitised, year-sorted copy of a schedule (drops non-numeric entries). */
export function cloneSchedule(schedule: CarbonPriceScheduleEntry[]): CarbonPriceScheduleEntry[] {
  return (schedule ?? [])
    .map((row) => ({ year: Number(row.year), price: Number(row.price) }))
    .filter((row) => Number.isFinite(row.year) && Number.isFinite(row.price))
    .sort((a, b) => a.year - b.year);
}

export function readCarbonLibraryFromModel(model: WorkbookModel): CarbonScheduleProfile[] {
  const rows = model[CARBON_LIBRARY_SHEET] ?? [];
  return rows
    .map((row): CarbonScheduleProfile | null => {
      const id = str(row.id as Primitive).trim();
      if (!id) return null;
      let schedule: CarbonPriceScheduleEntry[] = [];
      try {
        const parsed = typeof row.json === 'string' && row.json.trim() ? JSON.parse(row.json) : [];
        if (Array.isArray(parsed)) schedule = cloneSchedule(parsed);
      } catch {
        /* malformed row — empty schedule */
      }
      return { id, name: str(row.name as Primitive).trim() || 'Carbon schedule', schedule };
    })
    .filter((profile): profile is CarbonScheduleProfile => !!profile);
}

export function writeCarbonLibraryToModel(
  model: WorkbookModel,
  library: CarbonScheduleProfile[],
): WorkbookModel {
  const rows: GridRow[] = library.map((profile) => ({
    id: profile.id,
    name: profile.name,
    json: JSON.stringify(cloneSchedule(profile.schedule)),
  }));
  return { ...model, [CARBON_LIBRARY_SHEET]: rows };
}

export function sameCarbonLibrary(a: CarbonScheduleProfile[], b: CarbonScheduleProfile[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
