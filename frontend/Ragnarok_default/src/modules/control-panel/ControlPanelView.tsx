/**
 * ControlPanelView — the Control Panel tab: switch rules for constraints that PyPSA applies when a value is stated (ramp
 * limits, UC times, committable, minimum load). A rule selects rows of a component sheet by one column and its values;
 * switched off, the run solves its own copy of the model without those attributes. The workbook keeps every value.
 *
 * The rules are a project setting (`CONTROL_PANEL_KEY` in localStorage, saved in the project's `_app_state`); the backend
 * applies them at submit time (backend/app/control_panel). This view only edits the list and previews it.
 */
import React from 'react';
import { usePersistedState } from '../../shared/hooks/usePersistedState';
import { ViewPaneHeader, ViewPanel } from '../../shared/components/primitives';
import {
  CONTROL_PANEL_KEY, getColumnValues, getControlPanel, previewControlPanel,
  type ColumnValue, type ControlPanelInfo, type ControlPanelPreview, type ControlPanelState, type RulePreview, type SwitchRule,
} from 'lib/api/controlPanel';
import './control-panel.css';

const EMPTY: ControlPanelState = { version: 1, rules: [] };

/** Groups offered as checkboxes, in this order, with their labels. */
const GROUP_LABELS: [string, string][] = [
  ['ramp_up_down', 'Ramp up / down'],
  ['ramp_start_shut', 'Start-up / shut-down ramp'],
  ['uc_times', 'Min up / down times'],
  ['unit_commitment', 'Unit commitment (committable)'],
  ['min_load', 'Minimum load (p_min_pu)'],
];

function newId(rules: SwitchRule[]): string {
  const taken = new Set(rules.map((r) => r.id));
  let n = rules.length + 1;
  while (taken.has(`r${n}`)) n += 1;
  return `r${n}`;
}

function blankRule(rules: SwitchRule[], info: ControlPanelInfo | null): SwitchRule {
  const component = info?.components.some((c) => c.component === 'generators') ? 'generators' : (info?.components[0]?.component ?? 'generators');
  return { id: newId(rules), component, attributes: ['ramp_up_down'], column: 'carrier', values: [], on: false, label: '' };
}

/** Attribute list as the user reads it: group names by their label. */
function attributeText(attrs: string[]): string {
  const labels = new Map(GROUP_LABELS);
  return attrs.map((a) => labels.get(a) ?? a).join(', ');
}

function filterText(rule: SwitchRule): string {
  return rule.values.length ? `${rule.column} ∈ ${rule.values.map((v) => v || '(blank)').join(', ')}` : 'all rows';
}

interface EditorProps {
  rule: SwitchRule;
  info: ControlPanelInfo | null;
  onSave: (rule: SwitchRule) => void;
  onCancel: () => void;
}

function RuleEditor({ rule, info, onSave, onCancel }: EditorProps) {
  const [draft, setDraft] = React.useState<SwitchRule>(rule);
  const [values, setValues] = React.useState<ColumnValue[]>([]);
  const [valuesError, setValuesError] = React.useState<string | null>(null);
  const [extraAttr, setExtraAttr] = React.useState('');
  const comp = info?.components.find((c) => c.component === draft.component);
  const groups = info?.groups ?? {};
  const groupAttrs = new Set(GROUP_LABELS.flatMap(([g]) => groups[g] ?? []));

  React.useEffect(() => {
    let live = true;
    if (!draft.component || !draft.column) { setValues([]); return undefined; }
    getColumnValues(draft.component, draft.column)
      .then((v) => { if (live) { setValues(v); setValuesError(null); } })
      .catch((e: Error) => { if (live) { setValues([]); setValuesError(e.message); } });
    return () => { live = false; };
  }, [draft.component, draft.column]);

  const toggleIn = (list: string[], item: string) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  const set = (patch: Partial<SwitchRule>) => setDraft((d) => ({ ...d, ...patch }));
  const groupAvailable = (g: string) => !comp || (groups[g] ?? []).some((a) => comp.attributes.includes(a));
  const extras = draft.attributes.filter((a) => !GROUP_LABELS.some(([g]) => g === a));
  const otherAttrs = (comp?.attributes ?? []).filter((a) => !groupAttrs.has(a) && !draft.attributes.includes(a));

  return (
    <div className="cp-editor">
      <div className="cp-grid">
        <label className="cp-field">
          <span>Label</span>
          <input value={draft.label ?? ''} placeholder="e.g. no ramps on coal and gas" onChange={(e) => set({ label: e.target.value })} />
        </label>
        <label className="cp-field">
          <span>Component</span>
          <select value={draft.component} onChange={(e) => set({ component: e.target.value, values: [], column: 'carrier' })}>
            {(info?.components ?? []).map((c) => <option key={c.component} value={c.component}>{c.component} ({c.rows})</option>)}
            {!info?.components.some((c) => c.component === draft.component) && <option value={draft.component}>{draft.component}</option>}
          </select>
        </label>
        <label className="cp-field">
          <span>Filter column</span>
          <select value={draft.column} onChange={(e) => set({ column: e.target.value, values: [] })}>
            {(comp?.columns ?? [draft.column]).map((c) => <option key={c} value={c}>{c}</option>)}
            {comp && !comp.columns.includes(draft.column) && <option value={draft.column}>{draft.column}</option>}
          </select>
        </label>
      </div>

      <fieldset className="cp-fieldset">
        <legend>Constraints to switch</legend>
        <div className="cp-checks">
          {GROUP_LABELS.map(([g, label]) => (
            <label key={g} className={`cp-check${groupAvailable(g) ? '' : ' cp-check--na'}`} title={(groups[g] ?? []).join(', ')}>
              <input type="checkbox" checked={draft.attributes.includes(g)} disabled={!groupAvailable(g)}
                onChange={() => set({ attributes: toggleIn(draft.attributes, g) })} />
              {label}
            </label>
          ))}
          {extras.map((a) => (
            <label key={a} className="cp-check">
              <input type="checkbox" checked onChange={() => set({ attributes: draft.attributes.filter((x) => x !== a) })} />
              <code>{a}</code>
            </label>
          ))}
        </div>
        {otherAttrs.length > 0 && (
          <div className="cp-inline">
            <select value={extraAttr} onChange={(e) => setExtraAttr(e.target.value)} aria-label="Another attribute">
              <option value="">Another attribute…</option>
              {otherAttrs.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <button type="button" className="ghost-button sm" disabled={!extraAttr}
              onClick={() => { set({ attributes: [...draft.attributes, extraAttr] }); setExtraAttr(''); }}>Add</button>
          </div>
        )}
      </fieldset>

      <fieldset className="cp-fieldset">
        <legend>Rows where <code>{draft.column}</code> is {draft.values.length ? 'one of' : '(none ticked = every row)'}</legend>
        {valuesError && <p className="cp-error">{valuesError}</p>}
        <div className="cp-values">
          {values.map((v) => (
            <label key={v.value} className="cp-check">
              <input type="checkbox" checked={draft.values.includes(v.value)} onChange={() => set({ values: toggleIn(draft.values, v.value) })} />
              {v.value || <em>(blank)</em>} <span className="cp-count">{v.count}</span>
            </label>
          ))}
          {!values.length && !valuesError && <p className="cp-note">No rows in this sheet.</p>}
        </div>
      </fieldset>

      <div className="cp-actions">
        <button type="button" className="primary-button sm" disabled={!draft.attributes.length || !draft.column} onClick={() => onSave(draft)}>Save rule</button>
        <button type="button" className="ghost-button sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function Switch({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className={`cp-switch${on ? ' cp-switch--on' : ''}`}
      onClick={() => onChange(!on)}>
      <span className="cp-switch__knob" />
      <span className="cp-switch__text">{on ? 'On' : 'Off'}</span>
    </button>
  );
}

function effectText(p: RulePreview | undefined): string {
  if (!p) return '';
  const parts = [`${p.matched} row${p.matched === 1 ? '' : 's'}`];
  const changes = [p.cells && `${p.cells} cell${p.cells === 1 ? '' : 's'}`, p.seriesColumns && `${p.seriesColumns} series`,
    p.timeUnitRows && `${p.timeUnitRows} time-unit row${p.timeUnitRows === 1 ? '' : 's'}`].filter(Boolean);
  parts.push(changes.length ? `off clears ${changes.join(', ')}` : 'nothing stated to clear');
  return parts.join(' · ');
}

export function ControlPanelView() {
  const [state, setState] = usePersistedState<ControlPanelState>(CONTROL_PANEL_KEY, EMPTY);
  const rules = Array.isArray(state?.rules) ? state.rules : [];
  const [info, setInfo] = React.useState<ControlPanelInfo | null>(null);
  const [infoError, setInfoError] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<ControlPanelPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<SwitchRule | null>(null);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    let live = true;
    getControlPanel()
      .then((i) => { if (live) { setInfo(i); setInfoError(null); } })
      .catch((e: Error) => { if (live) setInfoError(e.message); });
    return () => { live = false; };
  }, [tick]);

  React.useEffect(() => {
    let live = true;
    const t = window.setTimeout(() => {
      previewControlPanel(rules)
        .then((p) => { if (live) { setPreview(p); setPreviewError(null); } })
        .catch((e: Error) => { if (live) { setPreview(null); setPreviewError(e.message); } });
    }, 250);
    return () => { live = false; window.clearTimeout(t); };
  }, [JSON.stringify(rules), tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = (next: SwitchRule[]) => setState({ version: 1, rules: next });
  const upsert = (rule: SwitchRule) => {
    const i = rules.findIndex((r) => r.id === rule.id);
    save(i < 0 ? [...rules, rule] : rules.map((r) => (r.id === rule.id ? rule : r)));
    setEditing(null);
  };
  const byId = new Map((preview?.rules ?? []).map((p) => [p.id, p]));
  const offRules = rules.filter((r) => !r.on);

  return (
    <ViewPanel name="control-panel">
      <ViewPaneHeader variant="analytics">
        <div className="cp-header">
          <strong>Control Panel</strong>
          <span className="cp-header__sum">{offRules.length ? `${offRules.length} rule${offRules.length === 1 ? '' : 's'} switched off for the next run` : 'Every constraint as the workbook states it'}</span>
        </div>
      </ViewPaneHeader>
      <div className="cp-scroll">
        <p className="cp-note">
          A PyPSA constraint such as a ramp limit is on when its value is stated and off when blank. A rule here switches it off
          for the rows it selects without deleting the value: the run solves its own copy with PyPSA&apos;s default for those
          attributes (blank ramp, <code>committable</code> false, <code>p_min_pu</code> 0), drops their time-series column and
          their RAGNAROK_TimeUnits rows, and lists each switched-off rule in its notes. Rules are saved in the project.
        </p>
        {infoError && <p className="cp-error">{infoError}</p>}

        <div className="cp-toolbar">
          <button type="button" className="primary-button sm" disabled={!!editing} onClick={() => setEditing(blankRule(rules, info))}>Add rule</button>
          <button type="button" className="ghost-button sm" disabled={!rules.length} onClick={() => save(rules.map((r) => ({ ...r, on: true })))}>All on</button>
          <button type="button" className="ghost-button sm" disabled={!rules.length} onClick={() => save(rules.map((r) => ({ ...r, on: false })))}>All off</button>
          <button type="button" className="ghost-button sm" onClick={() => setTick((t) => t + 1)} title="Re-read the model (after editing the workbook)">Refresh</button>
        </div>

        {editing && !rules.some((r) => r.id === editing.id) && (
          <RuleEditor key={editing.id} rule={editing} info={info} onSave={upsert} onCancel={() => setEditing(null)} />
        )}

        {rules.length ? (
          <table className="cp-table">
            <thead>
              <tr><th>Switch</th><th>Rule</th><th>Component</th><th>Constraints</th><th>Rows</th><th>Effect</th><th /></tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <React.Fragment key={r.id}>
                  <tr className={r.on ? '' : 'cp-row--off'}>
                    <td><Switch on={r.on} label={`Constraint switch ${r.label || r.id}`} onChange={(on) => save(rules.map((x) => (x.id === r.id ? { ...x, on } : x)))} /></td>
                    <td>{r.label || <span className="cp-muted">{r.id}</span>}</td>
                    <td><code>{r.component}</code></td>
                    <td>{attributeText(r.attributes)}</td>
                    <td>{filterText(r)}</td>
                    <td className="cp-muted" title={byId.get(r.id)?.names.join(', ')}>{effectText(byId.get(r.id))}</td>
                    <td className="cp-row-actions">
                      <button type="button" className="ghost-button sm" disabled={!!editing} onClick={() => setEditing(r)}>Edit</button>
                      <button type="button" className="ghost-button sm" onClick={() => save(rules.filter((x) => x.id !== r.id))}>Delete</button>
                    </td>
                  </tr>
                  {editing?.id === r.id && (
                    <tr className="cp-row--edit"><td colSpan={7}>
                      <RuleEditor key={r.id} rule={editing} info={info} onSave={upsert} onCancel={() => setEditing(null)} />
                    </td></tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        ) : (!editing && <p className="cp-note">No rules yet. Add one, e.g. ramp up / down for generators whose carrier is coal or gas.</p>)}

        {previewError && <p className="cp-error">{previewError}</p>}
        {preview && preview.notes.length > 0 && (
          <section className="cp-section">
            <h4>The next run will note</h4>
            <ul className="cp-notes">{preview.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </section>
        )}
      </div>
    </ViewPanel>
  );
}
