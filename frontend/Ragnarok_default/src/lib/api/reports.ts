/**
 * Reports API client — `/api/reports/*` plus the run list the picker needs.
 *
 * Same conventions as `lib/api/session.ts`: raw fetch, `API_BASE` prefix,
 * FastAPI `{detail}` error envelope surfaced as an Error message.
 */
import { API_BASE } from 'lib/constants';
import type {
  ReportDocumentPayload,
  ReportPerspective,
  ReportRunOption,
} from 'lib/reporting/types';

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

export async function fetchReportPerspectives(): Promise<ReportPerspective[]> {
  const resp = await fetch(`${API_BASE}/api/reports/perspectives`);
  const body = await asJson<{ perspectives: ReportPerspective[] }>(resp);
  return body.perspectives;
}

export async function fetchReport(
  runName: string,
  perspective: string,
): Promise<ReportDocumentPayload> {
  const resp = await fetch(
    `${API_BASE}/api/reports/${encodeURIComponent(runName)}/${encodeURIComponent(perspective)}`,
  );
  return asJson<ReportDocumentPayload>(resp);
}

export async function fetchReportRuns(): Promise<ReportRunOption[]> {
  const resp = await fetch(`${API_BASE}/api/runs`);
  const body = await asJson<{ runs: ReportRunOption[] }>(resp);
  return body.runs;
}
