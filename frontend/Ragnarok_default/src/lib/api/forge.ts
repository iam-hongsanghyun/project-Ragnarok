/**
 * Client for the Forge "Query & Edit" engine (`/api/forge/query`). Preview is a
 * dry run (match count + before/after sample); apply writes through the session
 * store. Both take the full query spec built by `lib/forge/queryEdit`.
 */
import { API_BASE } from 'lib/constants';
import type {
  QueryApplyResult,
  QueryEditRequest,
  QueryPreview,
} from 'lib/forge/queryEdit';
import { DEFAULT_SESSION_ID } from './session';

async function post<T>(path: string, req: QueryEditRequest): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, ...req }),
  });
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

export const forgeQueryPreview = (req: QueryEditRequest): Promise<QueryPreview> =>
  post<QueryPreview>('/api/forge/query/preview', req);

export const forgeQueryApply = (req: QueryEditRequest): Promise<QueryApplyResult> =>
  post<QueryApplyResult>('/api/forge/query/apply', req);
