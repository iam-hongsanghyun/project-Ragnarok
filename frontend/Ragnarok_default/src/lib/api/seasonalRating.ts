/** P18 — `POST /api/transform/seasonal-rating` (PyPSA `Lines.apply_seasonal_rating`). */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from './session';
import type { GridRow } from 'lib/types';

export interface SeasonalRatingResponse {
  model: Record<string, GridRow[]>;
  lines: string[];
  summerMonths: number[];
  compose: boolean;
  snapshots: number;
}

export async function postSeasonalRating(
  ratings: Record<string, { summer: number; winter: number }>,
  summerMonths: number[],
  compose: boolean,
  sessionId: string = DEFAULT_SESSION_ID,
): Promise<SeasonalRatingResponse> {
  const resp = await fetch(`${API_BASE}/api/transform/seasonal-rating`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, ratings, summerMonths, compose }),
  });
  if (!resp.ok) {
    let detail = '';
    try { detail = (await resp.json()).detail ?? ''; } catch { /* non-JSON body */ }
    throw new Error(detail || `Seasonal rating failed (HTTP ${resp.status})`);
  }
  return resp.json();
}
