/**
 * Siting HTTP client — `/api/siting/scan`.
 *
 * One-trip scan matching the importer pattern: POST the candidate region,
 * technologies, cost assumptions, and the grid buses the workbook already
 * holds; the backend samples a candidate grid, fetches cached keyless weather
 * per point, and returns the candidate list + preview + a WorkbookFragment of
 * extendable candidate assets. The caller holds the fragment in React state
 * until the user clicks "Add candidates to model" (the same client-side merge
 * the Data view uses); the ordinary capacity-expansion solve then picks the
 * winning sites.
 */
import { API_BASE } from 'lib/constants';
import { PreviewSummary, WorkbookFragment } from './databases';

export interface SitingCandidate {
  id: number;
  lat: number;
  lon: number;
  /** Name of the candidate's own bus in the fragment (`siting_site_<id>`). */
  siteBus: string;
  /** Nearest existing grid bus the connection Link lands on. */
  gridBus: string;
  distanceKm: number;
  /** Connection capex written to the Link (`rate × distance`, currency/MW). */
  connectionCostPerMw: number;
  /** Mean capacity factor per technology over the scanned window. */
  meanCf: Record<string, number>;
}

export interface SitingScanRequest {
  /** Candidate region [minLon, minLat, maxLon, maxLat] (WGS84). */
  bbox: [number, number, number, number];
  technologies: string[];
  gridPoints: number;
  dateFrom: string;
  dateTo: string;
  utcOffset: number;
  weatherSource: string;
  performanceRatio: number;
  buses: Array<{ name: string; x: number; y: number }>;
  siteCapacityMw: number;
  capitalCostPerMw: Record<string, number>;
  connectionCostPerMwKm: number;
  marginalCost: number;
  /**
   * The model's existing snapshot labels. When given, CF series are tiled
   * onto these labels and no new snapshots are introduced — the solve window
   * keeps its demand data. Omit to land the weather window as new snapshots.
   */
  targetSnapshots?: string[];
}

export interface SitingScanResponse {
  candidates: SitingCandidate[];
  preview: PreviewSummary;
  fragment: WorkbookFragment;
}

export async function runSitingScan(req: SitingScanRequest): Promise<SitingScanResponse> {
  const resp = await fetch(`${API_BASE}/api/siting/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`siting scan failed (${resp.status}): ${detail}`);
  }
  return (await resp.json()) as SitingScanResponse;
}
