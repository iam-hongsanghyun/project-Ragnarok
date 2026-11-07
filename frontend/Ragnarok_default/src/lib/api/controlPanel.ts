/**
 * Control-panel module (backend/app/routers/control_panel.py): switch rules that turn PyPSA attributes off for a
 * filtered set of components while the workbook keeps its values.
 *
 * The rules are a project setting: the tab keeps them in `localStorage` under `CONTROL_PANEL_KEY`, which travels with
 * the project (`_app_state`). The backend reads that key at submit time and applies the switched-off rules to the run's
 * own copy of the model. These calls only read the SESSION workbook to preview what a rule selects.
 */
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';

/** The app-state key the rules live under (mirrors `backend/app/control_panel.STATE_KEY`). */
export const CONTROL_PANEL_KEY = 'ragnarok:control-panel:rules';

export interface SwitchRule {
  id: string;
  /** A PyPSA component sheet: generators, links, processes, storage_units, ... */
  component: string;
  /** Input attributes of the component, or group names (`ramps`, `uc_times`, ...). */
  attributes: string[];
  /** The filter column, e.g. `carrier`. */
  column: string;
  /** The column values the rule selects; empty = every row. */
  values: string[];
  /** true = constraint as the workbook states it; false = switched off for the selected rows in the run. */
  on: boolean;
  label?: string;
}

export interface ControlPanelState {
  version: 1;
  rules: SwitchRule[];
}

export interface RulePreview {
  id: string;
  label: string;
  component: string;
  attributes: string[];
  column: string;
  values: string[];
  matched: number;
  names: string[];
  cells: number;
  seriesColumns: number;
  timeUnitRows: number;
  on: boolean;
}

export interface ControlPanelPreview {
  rules: RulePreview[];
  offCount: number;
  notes: string[];
  error?: string;
}

export interface ComponentInfo {
  component: string;
  rows: number;
  columns: string[];
  attributes: string[];
}

export interface ControlPanelInfo {
  stateKey: string;
  rules: SwitchRule[];
  groups: Record<string, string[]>;
  components: ComponentInfo[];
  preview: ControlPanelPreview;
}

export interface ColumnValue {
  value: string;
  count: number;
}

async function request<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const resp = body
    ? await fetch(`${API_BASE}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: DEFAULT_SESSION_ID, ...body }),
    })
    : await fetch(`${API_BASE}${path}?session_id=${encodeURIComponent(DEFAULT_SESSION_ID)}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json())?.detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return resp.json() as Promise<T>;
}

export const getControlPanel = () => request<ControlPanelInfo>('/api/control-panel');

export const previewControlPanel = (rules: SwitchRule[]) =>
  request<ControlPanelPreview>('/api/control-panel/preview', { rules });

export const getColumnValues = (component: string, column: string) =>
  request<{ values: ColumnValue[] }>('/api/control-panel/values', { component, column }).then((r) => r.values);
