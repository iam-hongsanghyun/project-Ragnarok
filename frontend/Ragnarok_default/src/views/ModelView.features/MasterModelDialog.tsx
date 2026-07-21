/**
 * MasterModelDialog — import a multi-year "master" model and derive a filtered
 * working model from it (Model view → toolbar → Master…).
 *
 * The master lives server-side beside the working model (it is NOT the model
 * being edited). Deriving filters it — calendar years applied to snapshots and
 * every temporal sheet, plus generic attribute filters (component → column →
 * values) — and REPLACES the working model with the result, after an explicit
 * confirm. Excluded components are NOT deleted: they get PyPSA's native
 * `active = false` (the solve skips them, the rows stay editable), and
 * components outside their build_year/lifetime window are deactivated the same
 * way. Uses the RunDialog visual language (modal-card + validation-report).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDialog } from 'shared/components/Dialog';
import { SearchableSelect } from 'shared/components/SearchableSelect';
import { SearchableMultiSelect } from 'shared/components/SearchableMultiSelect';
import {
  clearMasterModel,
  deriveFromMaster,
  getMasterDistinct,
  getMasterMeta,
  importMasterModel,
  MasterFilter,
  MasterMeta,
} from 'lib/api/master';
import type { DeriveReport } from 'lib/api/master';

interface FilterDraft extends MasterFilter {
  /** Distinct values of the picked column (fetched when the column is chosen). */
  options: string[];
}

export interface MasterModelDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful derive — the caller rehydrates the editor. */
  onDerived: (report: DeriveReport, filename?: string) => void | Promise<void>;
  showToast: (message: string, kind?: 'success' | 'error' | 'info') => void;
}

/** Master sheets offered in the filter builder: static component-ish sheets. */
function filterableSheets(meta: MasterMeta): { name: string; columns: string[] }[] {
  return (meta.sheets ?? [])
    .filter((s) => s.kind === 'static' && s.name !== 'snapshots' && s.name !== 'network' && !s.name.startsWith('RAGNAROK_'))
    .map((s) => ({ name: s.name, columns: s.columns }));
}

export function MasterModelDialog({ open, onClose, onDerived, showToast }: MasterModelDialogProps) {
  const { confirm } = useDialog();
  const [meta, setMeta] = useState<MasterMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [years, setYears] = useState<number[]>([]);
  const [filters, setFilters] = useState<FilterDraft[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const hasMaster = !!meta && !!(meta.sheets?.length);

  const refreshMeta = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getMasterMeta();
      setMeta(next);
      setYears(next.years ?? []); // default: every year selected
      setFilters([]);
    } catch {
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void refreshMeta();
  }, [open, refreshMeta]);

  const handleImportFile = async (file: File) => {
    setBusy(`Importing ${file.name}…`);
    try {
      const next = await importMasterModel(file);
      setMeta(next);
      setYears(next.years ?? []);
      setFilters([]);
      showToast(`Master model imported (${file.name})`, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Master import failed.', 'error');
    } finally {
      setBusy(null);
    }
  };

  const handleClearMaster = async () => {
    if (!(await confirm('Remove the stored master model? The working model is untouched.', { title: 'Clear master', danger: true, confirmText: 'Clear' }))) return;
    try {
      await clearMasterModel();
      setMeta(null);
      setYears([]);
      setFilters([]);
      showToast('Master model cleared', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Clear failed.', 'error');
    }
  };

  const setFilter = (i: number, next: Partial<FilterDraft>) => {
    setFilters((prev) => prev.map((f, j) => (j === i ? { ...f, ...next } : f)));
  };

  const handlePickColumn = async (i: number, sheet: string, column: string) => {
    setFilter(i, { column, values: [], options: [] });
    if (!sheet || !column) return;
    try {
      const options = await getMasterDistinct(sheet, column);
      setFilter(i, { options });
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Could not load values.', 'error');
    }
  };

  const handleDerive = async () => {
    if (!meta) return;
    const allYears = meta.years ?? [];
    if (allYears.length > 0 && years.length === 0) {
      showToast('Select at least one year.', 'error');
      return;
    }
    const activeFilters = filters.filter((f) => f.sheet && f.column && f.values.length > 0);
    const ok = await confirm(
      'Deriving replaces the current working model with the filtered result (excluded components are kept but marked active = false). The master itself is untouched, so you can re-derive with different filters at any time.',
      { title: 'Replace working model?', confirmText: 'Derive & replace', danger: true },
    );
    if (!ok) return;
    setBusy('Deriving working model…');
    try {
      const { report } = await deriveFromMaster({
        // Sending no years keeps every year (masters without parseable dates).
        years: allYears.length > 0 ? years : undefined,
        filters: activeFilters.map(({ sheet, column, values }) => ({ sheet, column, values })),
      });
      await onDerived(report, meta.filename);
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Derive failed.', 'error');
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;

  const sheets = meta ? filterableSheets(meta) : [];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card master-model-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="validation-report">
          <div className="validation-report-header">
            <div>
              <p className="eyebrow">Model</p>
              <h2>Master model</h2>
            </div>
            <button className="tb-btn tb-btn--muted" onClick={onClose}>Close</button>
          </div>

          <div className="validation-section">
            <p className="validation-section-title">Source</p>
            {loading ? (
              <p className="master-dialog-note">Loading…</p>
            ) : hasMaster ? (
              <p className="master-dialog-note">
                <strong>{meta?.filename || 'master model'}</strong>
                {' — '}
                {meta?.snapshotCount ?? 0} snapshots
                {meta?.snapshotStart ? ` (${meta.snapshotStart} → ${meta.snapshotEnd})` : ''}
                {(meta?.years?.length ?? 0) > 0 ? `, years ${meta!.years!.join(', ')}` : ''}
              </p>
            ) : (
              <p className="master-dialog-note">
                No master stored yet. Import a project workbook (.xlsx or .zip) with multi-year
                data — it is kept beside the working model, and you derive filtered working
                models from it.
              </p>
            )}
            <div className="master-dialog-row">
              <button className="tb-btn" disabled={!!busy} onClick={() => fileInputRef.current?.click()}>
                {hasMaster ? 'Replace master…' : 'Import master…'}
              </button>
              {hasMaster && (
                <button className="tb-btn tb-btn--muted" disabled={!!busy} onClick={handleClearMaster}>
                  Clear master
                </button>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip,.xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleImportFile(file);
                if (e.target) e.target.value = '';
              }}
            />
          </div>

          {hasMaster && (
            <>
              {(meta?.years?.length ?? 0) > 0 && (
                <div className="validation-section">
                  <p className="validation-section-title">Years</p>
                  <div className="master-dialog-row master-dialog-years">
                    {(meta?.years ?? []).map((y) => {
                      const active = years.includes(y);
                      return (
                        <button
                          key={y}
                          className={`tb-btn ${active ? 'tb-btn--active' : 'tb-btn--muted'}`}
                          onClick={() => setYears((prev) => (active ? prev.filter((v) => v !== y) : [...prev, y].sort((a, b) => a - b)))}
                        >
                          {y}
                        </button>
                      );
                    })}
                  </div>
                  <p className="master-dialog-note">
                    Snapshots and every temporal sheet keep only the selected years. Components
                    whose build_year / lifetime window misses every selected year are marked
                    active = false (kept in the tables, skipped by the solve).
                  </p>
                </div>
              )}

              <div className="validation-section">
                <p className="validation-section-title">Filters</p>
                {filters.map((f, i) => {
                  const sheetCols = sheets.find((s) => s.name === f.sheet)?.columns ?? [];
                  return (
                    <div key={i} className="master-dialog-row master-dialog-filter">
                      <SearchableSelect
                        className="master-dialog-select"
                        value={f.sheet}
                        options={sheets.map((s) => s.name)}
                        placeholder="Component"
                        onChange={(sheet) => setFilter(i, { sheet, column: '', values: [], options: [] })}
                      />
                      <SearchableSelect
                        className="master-dialog-select"
                        value={f.column}
                        options={sheetCols}
                        placeholder="Attribute"
                        disabled={!f.sheet}
                        onChange={(column) => void handlePickColumn(i, f.sheet, column)}
                      />
                      <SearchableMultiSelect
                        className="master-dialog-select master-dialog-select--values"
                        values={f.values}
                        options={f.options}
                        placeholder="Values"
                        disabled={!f.column}
                        onChange={(values) => setFilter(i, { values })}
                      />
                      <button
                        className="tb-btn tb-btn--muted"
                        title="Remove this filter"
                        onClick={() => setFilters((prev) => prev.filter((_, j) => j !== i))}
                      >
                        Remove
                      </button>
                    </div>
                  );
                })}
                <div className="master-dialog-row">
                  <button
                    className="tb-btn"
                    onClick={() => setFilters((prev) => [...prev, { sheet: '', column: '', values: [], options: [] }])}
                  >
                    Add filter
                  </button>
                </div>
                <p className="master-dialog-note">
                  Each filter selects the rows of a sheet whose column value is among the picked
                  values; everything else is marked active = false rather than deleted. Buses and
                  carriers have no active flag in PyPSA, so filtering them deactivates the
                  components attached to them (generators, loads, lines, links, …) instead.
                </p>
              </div>

              <div className="validation-section">
                <div className="master-dialog-row master-dialog-actions">
                  <button className="tb-btn tb-btn--active" disabled={!!busy} onClick={handleDerive}>
                    {busy ?? 'Derive working model'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
