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
    // `sessionId` goes AFTER the spread: the request builder always carries the key
    // (as `undefined` when the caller named none), and a spread placed after the
    // default overwrote it - JSON then dropped it and the server fell back to its
    // own `default` session instead of the editor's.
    body: JSON.stringify({ ...req, sessionId: req.sessionId ?? DEFAULT_SESSION_ID }),
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
