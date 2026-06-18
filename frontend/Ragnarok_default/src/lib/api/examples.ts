/**
 * Client for bundled starter projects ("Start with Examples" on the welcome
 * screen). Each example is a SQLite `project.db` the backend copies into the
 * active session; loading one is therefore just a POST + a session rehydrate —
 * no client-side workbook parsing. See backend `app/routers/examples.py`.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from './session';

export interface ExampleMeta {
  id: string;
  label: string;
  description: string;
}

/** List the bundled examples (newest/curated order from the backend). */
export async function listExamples(): Promise<ExampleMeta[]> {
  const resp = await fetch(`${API_BASE}/api/examples`);
  if (!resp.ok) throw new Error(`Failed to list examples (HTTP ${resp.status})`);
  const data = (await resp.json()) as { examples?: ExampleMeta[] };
  return data.examples ?? [];
}

/** Load an example into the active session; returns its label. */
export async function loadExample(id: string): Promise<{ label: string }> {
  const resp = await fetch(
    `${API_BASE}/api/examples/${encodeURIComponent(id)}/load?session_id=${encodeURIComponent(DEFAULT_SESSION_ID)}`,
    { method: 'POST' },
  );
  if (!resp.ok) throw new Error((await resp.text()) || `Failed to load example (HTTP ${resp.status})`);
  return resp.json() as Promise<{ label: string }>;
}
