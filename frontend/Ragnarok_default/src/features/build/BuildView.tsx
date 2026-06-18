/**
 * Build view — guided wizard for constructing a PyPSA model from scratch.
 *
 * Walks the user through the schema in dependency order
 * (Network → Carriers → Buses → ... → Review). Each step focuses one or two
 * schema sheets and writes directly into the shared `WorkbookModel`, so
 * switching to the Model tab at any time shows the same data.
 *
 * Layout: a horizontal step strip at the top, a TablesPane scoped to the
 * step's primary sheet on the left, and a schema/issue detail pane on the
 * right.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  GridRow,
  Primitive,
  SheetName,
  TableSel,
  TsSheetName,
  WorkbookModel,
} from 'lib/types';
import { TablesPane } from '../input/TablesPane';
import { ModelIssue } from '../validation/useModelIssues';
import { DateFormat } from '../settings/useSettings';
import { stringValue } from 'lib/utils/helpers';
import { parseCsvToGridRows } from 'lib/workbook/workbook';
import { TABLE_GROUPS } from 'lib/constants';
import { BUILD_STEPS, BuildStep, getStepIssues } from 'lib/build/steps';
import { BuildDetailPane } from './BuildDetailPane';
import { BuildNetworkMap, BRANCH_SHEETS, isGeoSheet, LinkMode } from './BuildNetworkMap';
import { BuildAttributeForm } from './BuildAttributeForm';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { ViewPaneHeader } from '../../shared/components/primitives';
import { useDialog } from '../../shared/components/Dialog';

export interface BuildViewProps {
  model: WorkbookModel;
  busIndex: Record<string, GridRow>;
  onUpdateRow: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: (sheet: SheetName) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onAddColumn: (sheet: SheetName, col: string, defaultValue: string | number | boolean) => void;
  onDeleteColumn: (sheet: SheetName, col: string) => void;
  onRenameColumn: (sheet: SheetName, oldCol: string, newCol: string) => void;
  onClearTable: (sheet: SheetName) => void;
  onImportTsSheet: (sheet: TsSheetName, rows: GridRow[]) => void;
  onBulkPaste: (
    sheet: SheetName,
    edits: { rowIndex: number; col: string; val: Primitive }[],
    extraRows: number,
  ) => void;
  modelIssues: ModelIssue[];
  currencySymbol: string;
  dateFormat: DateFormat;
  onOpenConstraintsWorkspace?: () => void;
  onOpenRunSetup?: () => void;
}

/** Short, sheet-appropriate base for auto-generated component names. */
const NAME_BASE: Record<string, string> = {
  buses: 'bus',
  generators: 'gen',
  loads: 'load',
  storage_units: 'storage',
  stores: 'store',
  lines: 'line',
  links: 'link',
  transformers: 'transformer',
};

/** First `${base}_${n}` not already used as a name in `rows`. */
function uniqueName(sheet: string, rows: GridRow[]): string {
  const base = NAME_BASE[sheet] ?? 'item';
  const taken = new Set(rows.map((r) => stringValue(r.name)));
  let n = rows.length + 1;
  while (taken.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

const round5 = (v: number): number => Math.round(v * 1e5) / 1e5;

// ── TemporalProfilesPanel ─────────────────────────────────────────────────────
// Right-hand, collapsible panel listing the active step's temporal profiles.
// Each profile can be selected (to show it in the bottom table) and CSV-imported
// in place. There is no manual row/column editing — load a profile from CSV, then
// edit values inline in the table. Clicking the already-active profile (or
// selecting a row on the map) returns the table to the static sheet.
interface TemporalProfilesPanelProps {
  profiles: { sheet: string; label: string }[];
  activeSheet: string | null;
  componentLabel: string;
  rowCountFor: (sheet: string) => number;
  onSelectStatic: () => void;
  onSelectTs: (sheet: string) => void;
  onImport: (sheet: string, rows: GridRow[]) => void;
}

function TemporalProfilesPanel({
  profiles, activeSheet, componentLabel, rowCountFor, onSelectStatic, onSelectTs, onImport,
}: TemporalProfilesPanelProps) {
  const [collapsed, setCollapsed] = useState(true);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pendingSheet = useRef<string | null>(null);
  const { alert: alertDialog } = useDialog();

  const triggerImport = (sheet: string) => {
    pendingSheet.current = sheet;
    inputRef.current?.click();
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    const sheet = pendingSheet.current;
    if (!file || !sheet) { e.target.value = ''; return; }
    try {
      const rows = await parseCsvToGridRows(file);
      if (rows.length === 0) throw new Error('No rows found in the file.');
      onImport(sheet, rows);
      onSelectTs(sheet);
    } catch (err) {
      void alertDialog(`${err instanceof Error ? err.message : String(err)}`, { title: 'CSV import failed' });
    } finally {
      pendingSheet.current = null;
      e.target.value = '';
    }
  };

  return (
    <div className={`build-ts-panel${collapsed ? ' is-collapsed' : ''}`}>
      <input ref={inputRef} type="file" accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain" hidden onChange={handleFile} />
      <button
        type="button"
        className="build-ts-panel-head"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((v) => !v)}
      >
        <span className="build-ts-panel-caret">{collapsed ? '▸' : '▾'}</span>
        <span className="eyebrow">{componentLabel} · time-series</span>
      </button>
      {!collapsed && (
        <div className="build-ts-panel-list">
          {profiles.map((p) => {
            const rowCount = rowCountFor(p.sheet);
            const active = activeSheet === p.sheet;
            return (
              <div key={p.sheet} className={`build-ts-panel-row${active ? ' is-active' : ''}`}>
                <button
                  type="button"
                  className="build-ts-panel-select"
                  onClick={() => (active ? onSelectStatic() : onSelectTs(p.sheet))}
                >
                  <span className="build-ts-panel-name">{p.label}</span>
                  <span className="build-ts-panel-meta">{rowCount > 0 ? `${rowCount} rows` : 'empty'}</span>
                </button>
                <button
                  type="button"
                  className="build-ts-panel-import"
                  title={`Import a CSV for ${p.label}`}
                  onClick={() => triggerImport(p.sheet)}
                >
                  Import
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function BuildView(props: BuildViewProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [focusedRowIndex, setFocusedRowIndex] = useState<number | null>(null);
  // A new object on each map-select flashes + scrolls the matching table row.
  const [jumpTo, setJumpTo] = useState<{ sheet: string; rowIndex: number } | null>(null);
  const [linkMode, setLinkMode] = useState<LinkMode | null>(null);
  const step: BuildStep = BUILD_STEPS[stepIndex];
  const geo = isGeoSheet(step.primarySheet);

  const busNames = useMemo(
    () => props.model.buses.map((b) => stringValue(b.name)).filter(Boolean),
    [props.model.buses],
  );
  const carrierNames = useMemo(
    () => (props.model.carriers ?? []).map((c) => stringValue(c.name)).filter(Boolean),
    [props.model.carriers],
  );

  const stepRows: GridRow[] = (props.model as Record<string, GridRow[]>)[step.primarySheet] ?? [];
  const selectedRow = focusedRowIndex != null ? stepRows[focusedRowIndex] ?? null : null;

  const selectFromMap = (rowIndex: number) => {
    setFocusedRowIndex(rowIndex);
    setJumpTo({ sheet: step.primarySheet, rowIndex });
  };

  // Right-click the map → add a row of the active sheet at that location.
  // Buses and point components (generators/loads/storage/stores) take the exact
  // clicked coordinates (x = lng, y = lat) and are NOT linked to any bus — the
  // user links a bus explicitly afterwards. Branches are defined by their two
  // buses, so a new branch row gets a name only (its buses are picked later).
  // The whole thing is one atomic, undoable mutation via onBulkPaste (grow by
  // 1 row, then set the location columns on it).
  const addAtLocation = (lat: number, lng: number) => {
    const sheet = step.primarySheet as SheetName;
    const newIndex = stepRows.length;
    const name = uniqueName(sheet, stepRows);
    const edits: { rowIndex: number; col: string; val: Primitive }[] = [
      { rowIndex: newIndex, col: 'name', val: name },
    ];

    if (!BRANCH_SHEETS.has(sheet)) {
      edits.push({ rowIndex: newIndex, col: 'x', val: round5(lng) });
      edits.push({ rowIndex: newIndex, col: 'y', val: round5(lat) });
    }

    props.onBulkPaste(sheet, edits, 1);
    setFocusedRowIndex(newIndex);
    setJumpTo({ sheet, rowIndex: newIndex });
  };

  // Click-to-link: a pending "click a bus to set this field" request, started
  // from the map context menu or the attribute form's "pick on map" button.
  const startLink = (rowIndex: number, field: string) => {
    setFocusedRowIndex(rowIndex);
    setJumpTo({ sheet: step.primarySheet, rowIndex });
    setLinkMode({ rowIndex, field });
  };
  const pickBus = (busName: string) => {
    if (!linkMode) return;
    props.onUpdateRow(step.primarySheet as SheetName, linkMode.rowIndex, linkMode.field, busName);
    setLinkMode(null);
  };

  // Drag a node on the map → write its new coordinates (one atomic edit).
  const moveRow = (rowIndex: number, lat: number, lng: number) => {
    props.onBulkPaste(step.primarySheet as SheetName, [
      { rowIndex, col: 'x', val: round5(lng) },
      { rowIndex, col: 'y', val: round5(lat) },
    ], 0);
  };

  // The table can show the step's static sheet or one of its temporal profiles.
  // Defaults to static; resets to static whenever the step changes.
  const [tableSel, setTableSel] = useState<TableSel>({ kind: 'static', sheet: step.primarySheet as SheetName });
  useEffect(() => {
    setTableSel({ kind: 'static', sheet: step.primarySheet as SheetName });
  }, [stepIndex, step.primarySheet]);

  // Temporal profiles the active step's component supports (from the schema).
  const temporalSheets = useMemo(
    () => TABLE_GROUPS.find((g) => g.sheet === step.primarySheet)?.temporalSheets ?? [],
    [step.primarySheet],
  );

  const completionByIndex = useMemo(
    () => BUILD_STEPS.map((s) => s.isComplete(props.model)),
    [props.model],
  );

  const errorCountByIndex = useMemo(
    () =>
      BUILD_STEPS.map(
        (s) => getStepIssues(s, props.modelIssues).filter((i) => i.severity === 'error').length,
      ),
    [props.modelIssues],
  );

  const warningCountByIndex = useMemo(
    () =>
      BUILD_STEPS.map(
        (s) => getStepIssues(s, props.modelIssues).filter((i) => i.severity === 'warning').length,
      ),
    [props.modelIssues],
  );

  const goStep = (i: number) => {
    setStepIndex(i);
    setFocusedRowIndex(null);
    setJumpTo(null);
    setLinkMode(null);
  };

  const buildTable = (
    <TablesPane
      model={props.model}
      sel={tableSel}
      onSelChange={setTableSel}
      onUpdate={props.onUpdateRow}
      onAddRow={props.onAddRow}
      onDeleteRow={props.onDeleteRow}
      onAddColumn={props.onAddColumn}
      onDeleteColumn={props.onDeleteColumn}
      onRenameColumn={props.onRenameColumn}
      onClearTable={props.onClearTable}
      onImportTsSheet={props.onImportTsSheet}
      onBulkPaste={props.onBulkPaste}
      issues={props.modelIssues}
      jumpTo={jumpTo}
      currencySymbol={props.currencySymbol}
      dateFormat={props.dateFormat}
      onFocusRow={setFocusedRowIndex}
      compact
      editableTs
    />
  );

  const attributeForm = (
    <BuildAttributeForm
      sheet={step.primarySheet}
      row={selectedRow}
      rowIndex={focusedRowIndex}
      rowCount={stepRows.length}
      busNames={busNames}
      carrierNames={carrierNames}
      onUpdate={(rowIndex, col, val) => props.onUpdateRow(step.primarySheet as SheetName, rowIndex, col, val)}
      onAddRow={() => { props.onAddRow(step.primarySheet as SheetName); setFocusedRowIndex(stepRows.length); }}
      onDeleteRow={(rowIndex) => { props.onDeleteRow(step.primarySheet as SheetName, rowIndex); setFocusedRowIndex(null); }}
      onPickOnMap={geo ? startLink : undefined}
    />
  );

  // Right column of the top split: the attribute form, plus (for components
  // that support time-series) a panel to pick / CSV-import temporal profiles.
  const rightColumn = (
    <div className="build-top-right">
      {attributeForm}
      {temporalSheets.length > 0 && (
        <TemporalProfilesPanel
          profiles={temporalSheets}
          activeSheet={tableSel.kind === 'ts' ? tableSel.sheet : null}
          componentLabel={step.label}
          rowCountFor={(sheet) => ((props.model as Record<string, GridRow[]>)[sheet] ?? []).length}
          onSelectStatic={() => setTableSel({ kind: 'static', sheet: step.primarySheet as SheetName })}
          onSelectTs={(sheet) => setTableSel({ kind: 'ts', sheet: sheet as TsSheetName })}
          onImport={(sheet, rows) => props.onImportTsSheet(sheet as TsSheetName, rows)}
        />
      )}
    </div>
  );

  // The map always renders the full network as context. Placement / link /
  // drag interactions only apply when the active step's sheet is geo-locatable;
  // for non-geo steps (network, carriers, processes) the map is read-only
  // context and the click-to-add hint is suppressed.
  const geoMap = (
    <BuildNetworkMap
      model={props.model}
      busIndex={props.busIndex}
      activeSheet={step.primarySheet}
      selectedRowIndex={focusedRowIndex}
      onSelectRow={selectFromMap}
      onAddAtLocation={geo ? addAtLocation : undefined}
      onDeleteRow={geo ? (rowIndex) => {
        props.onDeleteRow(step.primarySheet as SheetName, rowIndex);
        setFocusedRowIndex(null);
        setJumpTo(null);
        setLinkMode(null);
      } : undefined}
      onMoveRow={geo ? moveRow : undefined}
      linkMode={linkMode}
      onStartLink={geo ? startLink : undefined}
      onPickBus={geo ? pickBus : undefined}
      onCancelLink={() => setLinkMode(null)}
    />
  );

  return (
    <div className="build-view">
      <ViewPaneHeader>
      <nav className="subnav build-step-strip" aria-label="Build steps">
        {BUILD_STEPS.map((s, i) => {
          const complete = completionByIndex[i];
          const errorCount = errorCountByIndex[i];
          const warningCount = warningCountByIndex[i];
          const active = i === stepIndex;
          const cls = [
            'subnav-btn',
            'build-step-btn',
            active ? 'subnav-btn--active' : '',
            errorCount > 0 ? 'subnav-btn--error' : '',
            errorCount === 0 && warningCount > 0 ? 'subnav-btn--warn' : '',
            errorCount === 0 && warningCount === 0 && complete ? 'subnav-btn--ok' : '',
          ]
            .filter(Boolean)
            .join(' ');
          return (
            <button key={s.id} className={cls} onClick={() => goStep(i)} type="button">
              <span className="build-step-num">{complete && errorCount === 0 ? '✓' : i + 1}</span>
              <span className="build-step-label">{s.label}</span>
              {errorCount > 0 && <span className="tab-badge tab-badge--error">{errorCount}</span>}
              {errorCount === 0 && warningCount > 0 && (
                <span className="tab-badge tab-badge--warn">{warningCount}</span>
              )}
            </button>
          );
        })}
      </nav>
      </ViewPaneHeader>

      {/* Per-step guidance: what this step is for. (Step navigation is the
          strip above; adding components uses the editor's Add button.) */}
      <div className="build-step-guide">
        <p className="build-step-guide__desc">{step.description}</p>
      </div>

      {step.id === 'constraints' ? (
        <ResizablePanels id="build" direction="horizontal" className="build-body" initialSizes={[72, 28]} minSize={220}>
          <section className="build-body-main">
            <ConstraintsStepPanel
              model={props.model}
              onOpenConstraintsWorkspace={props.onOpenConstraintsWorkspace}
            />
          </section>
          <BuildDetailPane step={step} model={props.model} issues={props.modelIssues} focusedRowIndex={focusedRowIndex} />
        </ResizablePanels>
      ) : step.id === 'review' ? (
        <ResizablePanels id="build" direction="horizontal" className="build-body" initialSizes={[72, 28]} minSize={220}>
          <section className="build-body-main">
            <ReviewStepPanel
              model={props.model}
              issues={props.modelIssues}
              onJumpToStep={goStep}
              onOpenRunSetup={props.onOpenRunSetup}
            />
          </section>
          <BuildDetailPane step={step} model={props.model} issues={props.modelIssues} focusedRowIndex={focusedRowIndex} />
        </ResizablePanels>
      ) : (
        <ResizablePanels id="build-v" direction="vertical" className="build-body" initialSizes={[52, 48]} minSize={120}>
          <ResizablePanels id="build-top" direction="horizontal" className="build-top-split" initialSizes={[60, 40]} minSize={160}>
            {geoMap}
            {rightColumn}
          </ResizablePanels>
          <section className="build-table-region">
            {buildTable}
          </section>
        </ResizablePanels>
      )}
    </div>
  );
}

interface ConstraintsStepPanelProps {
  model: WorkbookModel;
  onOpenConstraintsWorkspace?: () => void;
}

function ConstraintsStepPanel({ model, onOpenConstraintsWorkspace }: ConstraintsStepPanelProps) {
  const globalRows: GridRow[] = model.global_constraints ?? [];
  return (
    <div className="build-constraints-panel">
      <p>
        Global constraints (CO₂ caps, expansion limits, primary-energy budgets) are edited
        in the dedicated Constraints workspace. This step is a summary.
      </p>
      <div className="build-constraints-summary">
        <span className="build-constraints-count">
          {globalRows.length} global constraint{globalRows.length === 1 ? '' : 's'} defined
        </span>
        {onOpenConstraintsWorkspace && (
          <button className="ghost-button sm" onClick={onOpenConstraintsWorkspace} type="button">
            Open Constraints workspace →
          </button>
        )}
      </div>
      {globalRows.length > 0 && (
        <ul className="build-constraints-list">
          {globalRows.map((row, idx) => (
            <li key={idx}>
              <strong>{String(row.name ?? `constraint ${idx + 1}`)}</strong>
              {row.type ? <span> · {String(row.type)}</span> : null}
              {row.sense ? <span> {String(row.sense)}</span> : null}
              {row.constant != null ? <span> {String(row.constant)}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface ReviewStepPanelProps {
  model: WorkbookModel;
  issues: ModelIssue[];
  onJumpToStep: (i: number) => void;
  onOpenRunSetup?: () => void;
}

function ReviewStepPanel({ model, issues, onJumpToStep, onOpenRunSetup }: ReviewStepPanelProps) {
  const errorCount = issues.filter((i) => i.severity === 'error').length;
  const warningCount = issues.filter((i) => i.severity === 'warning').length;
  return (
    <div className="build-review-panel">
      <div className="build-review-headline">
        <div className={`build-review-status build-review-status--${errorCount > 0 ? 'error' : warningCount > 0 ? 'warn' : 'ok'}`}>
          <span className="build-review-status-glyph">{errorCount > 0 ? '!' : warningCount > 0 ? '?' : '✓'}</span>
          <div>
            <p className="eyebrow">{errorCount > 0 ? 'Not ready to run' : warningCount > 0 ? 'Review warnings' : 'Ready to run'}</p>
            <h3>
              {errorCount} error{errorCount === 1 ? '' : 's'} · {warningCount} warning{warningCount === 1 ? '' : 's'}
            </h3>
          </div>
        </div>
        {errorCount === 0 && onOpenRunSetup && (
          <button className="primary-button" onClick={onOpenRunSetup} type="button">
            Open Run setup →
          </button>
        )}
      </div>

      <table className="build-review-counts">
        <thead>
          <tr>
            <th>Step</th>
            <th>Sheet</th>
            <th>Rows</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {BUILD_STEPS.slice(0, -1).map((s, i) => {
            const rowCount = Array.isArray(model[s.primarySheet]) ? model[s.primarySheet].length : 0;
            const stepErrors = getStepIssues(s, issues).filter((iss) => iss.severity === 'error').length;
            return (
              <tr key={s.id}>
                <td>
                  <button className="build-review-step-link" onClick={() => onJumpToStep(i)} type="button">
                    {s.label}
                  </button>
                </td>
                <td><code>{s.primarySheet}</code></td>
                <td>{rowCount}</td>
                <td className={stepErrors > 0 ? 'build-review-error-cell' : ''}>{stepErrors}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {issues.length > 0 && (
        <div className="build-review-issues">
          <h4>Top issues</h4>
          <ul>
            {issues.slice(0, 10).map((iss, idx) => (
              <li key={idx} className={`build-issue build-issue--${iss.severity}`}>
                <span className="build-issue-badge">{iss.severity === 'error' ? '!' : '?'}</span>
                <span>
                  <code>{iss.sheet}</code> · row {iss.rowIndex + 1}
                  {iss.col ? ` · ${iss.col}` : ''} — {iss.message}
                </span>
              </li>
            ))}
            {issues.length > 10 && (
              <li className="build-issue build-issue--more">+ {issues.length - 10} more</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
