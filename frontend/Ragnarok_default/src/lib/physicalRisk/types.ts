/**
 * Physical Risk — shared TS types.
 *
 * Mirrors the backend contract byte-for-byte (`backend/app/physical_risk/
 * entities.py` + `backend/app/routers/physical_risk.py`). Field names and
 * casing MUST match the Python Pydantic models exactly (FastAPI serialises
 * them camelCase-as-written, not snake_case) — do not rename on this side.
 */

export type AssetKind = 'generator' | 'storage';

export interface Asset {
  id: string;
  name: string;
  kind: AssetKind;
  lat: number;
  lon: number;
  value: number;
  currency: string;
  vulnerabilityClass: string;
  carrier: string;
}

export interface Portfolio {
  sessionId: string;
  assets: Asset[];
}

export type RunStatus = 'queued' | 'running' | 'done' | 'error';

export interface AssetImpact {
  assetId: string;
  eai: number;
}

export interface FreqCurve {
  returnPeriods: number[];
  losses: number[];
}

export interface PhysicalRunResult {
  peril: string;
  perAsset: AssetImpact[];
  aaiAgg: number;
  freqCurve: FreqCurve;
  deltaPct: number | null;
}

export interface PhysicalRunOutput {
  currency: string;
  perils: PhysicalRunResult[];
}

export interface Scenario {
  rcp: string;
  horizon: number;
}

export interface Run {
  id: string;
  status: RunStatus;
  result?: PhysicalRunOutput | null;
  error?: string | null;
}

export interface LibraryEntry {
  id: string;
  label: string;
}

export interface Libraries {
  perils: LibraryEntry[];
  vulnerabilityClasses: LibraryEntry[];
}
