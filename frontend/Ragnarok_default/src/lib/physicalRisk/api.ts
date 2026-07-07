/**
 * Physical Risk — typed client for `/api/physical-risk/*`.
 *
 * Mirrors the fetch/error-handling shape used elsewhere (e.g.
 * `lib/api/session.ts`, `lib/api/procurement.ts`): `API_BASE` prefix, JSON
 * body, and error detail extracted from the FastAPI `{detail}` envelope.
 */
import { API_BASE } from 'lib/constants';
import { Libraries, Portfolio, Run, Scenario } from './types';

/** Same single-session convention as the workbook session (`DEFAULT_SESSION_ID`). */
export const DEFAULT_PHYSICAL_RISK_SESSION_ID = 'default';

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = (body && (body.detail as string)) || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export interface SeedFromModelRequest {
  defaultValuePerMw?: number;
  currency?: string;
  sessionId?: string;
}

/** Build a portfolio from the current Ragnarok model and open a physical-risk session. */
export async function seedFromModel(req: SeedFromModelRequest = {}): Promise<Portfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/seed-from-model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_PHYSICAL_RISK_SESSION_ID, ...req }),
  });
  return asJson<Portfolio>(resp);
}

/** Fetch the portfolio for a physical-risk session. */
export async function getSession(sessionId = DEFAULT_PHYSICAL_RISK_SESSION_ID): Promise<Portfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}`);
  return asJson<Portfolio>(resp);
}

/** Replace the stored portfolio for a session (full-model sync). */
export async function saveSession(
  sessionId: string,
  portfolio: Portfolio,
): Promise<Portfolio> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(portfolio),
  });
  return asJson<Portfolio>(resp);
}

/** The controlled vocabularies (perils + vulnerability classes) to pick from. */
export async function getLibraries(): Promise<Libraries> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/libraries`);
  return asJson<Libraries>(resp);
}

/** Submit a physical-risk analysis run for the session's portfolio. */
export async function submitRun(
  sessionId: string,
  perils: string[],
  scenario: Scenario,
): Promise<Run> {
  const resp = await fetch(`${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ perils, scenario }),
  });
  return asJson<Run>(resp);
}

/** Poll a run; the stub engine finalises it to 'done'/'error' on the first poll. */
export async function getRun(sessionId: string, runId: string): Promise<Run> {
  const resp = await fetch(
    `${API_BASE}/api/physical-risk/session/${encodeURIComponent(sessionId)}/run/${encodeURIComponent(runId)}`,
  );
  return asJson<Run>(resp);
}
