import React, { useMemo, useRef, useState } from 'react';
import { ModuleConfigField, ModuleConfigTableColumn, ModuleConfigVisibleWhen, ModuleDescriptor, ModuleHostInventory, PluginFileValue, WorkbookModel } from 'lib/types';
import { resolveOptionsFrom, ResolvedOption } from 'lib/plugins/options';
import { SearchableSelect } from '../../shared/components/SearchableSelect';

/** Resolved option list for a field/column: dynamic source wins, static is the fallback. */
function resolveStaticOrDynamic(
  optionsFrom: ModuleConfigField['optionsFrom'],
  staticOptions: ResolvedOption[],
  ctx: { model?: WorkbookModel; formValues?: Record<string, unknown> },
): ResolvedOption[] {
  if (!optionsFrom) return staticOptions;
  const dynamic = resolveOptionsFrom(optionsFrom, ctx);
  return dynamic.length > 0 ? dynamic : staticOptions;
}

interface ModuleManagerSectionProps {
  inventory: ModuleHostInventory | null;
  loading: boolean;
  error: string | null;
  enabledIds: string[];
  isEnabled: (moduleId: string) => boolean;
  isEnableEligible: (module: ModuleDescriptor) => boolean;
  onToggleEnabled: (moduleId: string, enabled: boolean) => void;
  onInstall: (file: File) => void;
  onUninstall: (module: ModuleDescriptor) => void;
}

function statusLabel(module: ModuleDescriptor): string {
  if (module.status === 'ready' && module.entryExists) return 'Ready';
  if (module.status === 'incompatible') return 'Incompatible';
  return 'Invalid';
}

// ── Generic config field renderer ─────────────────────────────────────────────

interface ConfigFieldProps {
  fieldKey: string;
  field: ModuleConfigField;
  value: unknown;
  onChange: (value: unknown) => void;
  carriers?: string[];
  /** Current workbook model, for `optionsFrom: { source: 'model' }`. */
  model?: WorkbookModel;
  /** Sibling field values, used to evaluate `visibleWhen` gates and `optionsFrom: { source: 'config' }`. */
  formValues?: Record<string, unknown>;
  /**
   * Called when an `action`-typed field's button is clicked. Async — the
   * button shows a spinner while the promise is pending.
   */
  onAction?: (fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

function evaluateVisibleWhen(
  gate: ModuleConfigVisibleWhen | undefined,
  formValues: Record<string, unknown> | undefined,
  schema?: Record<string, ModuleConfigField>,
): boolean {
  if (!gate) return true;
  if (!formValues) return true;
  const raw = formValues[gate.field];
  const resolved = raw !== undefined ? raw : schema?.[gate.field]?.default;
  // Strict equality after a tolerant coercion: matches numeric/string parity
  // the way most config form values arrive (numbers from sliders, strings
  // from selects, booleans from checkboxes).
  if (typeof gate.equals === 'boolean') return Boolean(resolved) === gate.equals;
  if (typeof gate.equals === 'number')  return Number(resolved) === gate.equals;
  return String(resolved ?? '') === String(gate.equals);
}

interface ActionFieldRowProps {
  fieldKey: string;
  field: ModuleConfigField;
  label: string;
  onAction?: (fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

function ActionFieldRow({ fieldKey, field, label, onAction }: ActionFieldRowProps) {
  const [pending, setPending] = useState(false);
  const variant = field.variant ?? 'primary';
  const cls = variant === 'primary'
    ? 'primary-button sg-module-action-btn'
    : 'tb-btn sg-module-action-btn';
  const handleClick = async () => {
    if (!onAction || pending) return;
    setPending(true);
    try { await onAction(fieldKey, field); }
    finally { setPending(false); }
  };
  return (
    <div className="sg-module-config-row sg-module-config-row--action">
      <button
        type="button"
        className={cls}
        onClick={handleClick}
        disabled={pending || !onAction}
        title={!onAction ? 'Action handler not available in this context.' : undefined}
      >
        {pending
          ? <><span className="sg-module-action-spinner" aria-hidden="true" />Working…</>
          : label}
      </button>
      {field.description && (
        <p className="sg-setting-hint sg-module-action-hint">{field.description}</p>
      )}
    </div>
  );
}

export function ConfigFieldRow({ fieldKey, field, value, onChange, carriers, model, formValues, onAction }: ConfigFieldProps) {
  if (!evaluateVisibleWhen(field.visibleWhen, formValues)) {
    return null;
  }

  const resolved = value !== undefined ? value : field.default;
  const label = field.label ?? fieldKey;

  if (field.type === 'group') {
    return (
      <div className="sg-module-config-group" role="separator" aria-label={label}>
        <span className="sg-module-config-group-label">{label}</span>
      </div>
    );
  }

  if (field.type === 'action') {
    return (
      <ActionFieldRow
        fieldKey={fieldKey}
        field={field}
        label={label}
        onAction={onAction}
      />
    );
  }

  if (field.type === 'boolean') {
    return (
      <label className="sg-module-config-row">
        <span className="sg-module-config-label">{label}</span>
        <input
          type="checkbox"
          checked={Boolean(resolved)}
          onChange={(e) => onChange(e.target.checked)}
          style={{ width: 16, height: 16, cursor: 'pointer' }}
        />
        {field.unit && <span className="sg-module-config-unit">{field.unit}</span>}
      </label>
    );
  }

  if (field.type === 'select' && (field.options || field.optionsFrom)) {
    const opts = resolveStaticOrDynamic(
      field.optionsFrom,
      (field.options ?? []).map((opt) => ({ value: String(opt.value), label: String(opt.label) })),
      { model, formValues },
    );
    return (
      <label className="sg-module-config-row">
        <span className="sg-module-config-label">{label}</span>
        <SearchableSelect
          className="sg-module-config-select"
          value={String(resolved ?? '')}
          options={opts}
          onChange={(v) => onChange(v)}
        />
      </label>
    );
  }

  if (field.type === 'multi-select' && (field.options || field.optionsFrom)) {
    // General multi-select: pick several from an option list (static or a
    // dynamic `optionsFrom` source). Returns a string[]. Generalises
    // `carrier-select` (which is fixed to workbook carriers).
    const options = resolveStaticOrDynamic(
      field.optionsFrom,
      (field.options ?? []).map((opt) => ({ value: String(opt.value), label: String(opt.label) })),
      { model, formValues },
    );
    const selected: string[] = Array.isArray(resolved)
      ? (resolved as unknown[]).map(String)
      : Array.isArray(field.default) ? (field.default as unknown[]).map(String) : [];

    const toggle = (val: string, checked: boolean) => {
      const next = checked
        ? [...selected, val]
        : selected.filter((v) => v !== val);
      onChange(next);
    };

    return (
      <div className="sg-module-config-row sg-module-config-row--carrier">
        <span className="sg-module-config-label">{label}</span>
        {options.length > 0 ? (
          <div className="sg-carrier-select-list">
            {options.map((opt) => (
              <label key={opt.value} className="sg-carrier-select-item">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={(e) => toggle(opt.value, e.target.checked)}
                />
                <span className="sg-carrier-select-name">{opt.label}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="sg-setting-hint" style={{ margin: 0 }}>No options available.</p>
        )}
        {options.length > 0 && (
          <p className="sg-setting-hint" style={{ margin: '4px 0 0' }}>
            {selected.length} of {options.length} selected.
          </p>
        )}
      </div>
    );
  }

  if (field.type === 'carrier-select') {
    // Current selection: value from store, else field default, else empty array
    const selected: string[] = Array.isArray(resolved)
      ? (resolved as string[])
      : Array.isArray(field.default) ? (field.default as string[]) : [];

    // Available options: workbook carriers if present, otherwise fall back to
    // the defaults so the card is usable before any workbook is loaded.
    const options: string[] = carriers && carriers.length > 0
      ? carriers
      : (Array.isArray(field.default) ? (field.default as string[]) : []);

    const toggle = (carrier: string, checked: boolean) => {
      const next = checked
        ? [...selected, carrier]
        : selected.filter((c) => c !== carrier);
      onChange(next);
    };

    return (
      <div className="sg-module-config-row sg-module-config-row--carrier">
        <span className="sg-module-config-label">{label}</span>
        {options.length > 0 ? (
          <div className="sg-carrier-select-list">
            {options.map((carrier) => (
              <label key={carrier} className="sg-carrier-select-item">
                <input
                  type="checkbox"
                  checked={selected.includes(carrier)}
                  onChange={(e) => toggle(carrier, e.target.checked)}
                />
                <span className="sg-carrier-select-name">{carrier}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="sg-setting-hint" style={{ margin: 0 }}>
            No carriers defined in this workbook yet.
          </p>
        )}
        {carriers && carriers.length > 0 && (
          <p className="sg-setting-hint" style={{ margin: '4px 0 0' }}>
            {selected.length} of {options.length} selected as renewable.
          </p>
        )}
      </div>
    );
  }

  if (field.type === 'number' && field.min !== undefined && field.max !== undefined) {
    const num = Number(resolved ?? field.default ?? field.min);
    return (
      <div className="sg-module-config-row sg-module-config-row--slider">
        <span className="sg-module-config-label">{label}</span>
        <div className="sg-module-config-slider-row">
          <input
            type="range"
            min={field.min}
            max={field.max}
            step={field.step ?? 1}
            value={num}
            onChange={(e) => onChange(Number(e.target.value))}
            className="sg-module-config-slider"
          />
          <span className="sg-module-config-value">
            {num}{field.unit ? <span className="sg-module-config-unit">{field.unit}</span> : null}
          </span>
        </div>
      </div>
    );
  }

  if (field.type === 'file') {
    const fileVal = resolved as PluginFileValue | undefined | null;
    const binary = field.binary === true;
    return (
      <div className="sg-module-config-row sg-module-config-row--file">
        <span className="sg-module-config-label">{label}</span>
        <div className="sg-module-file-row">
          <label className="tb-btn sg-module-file-btn">
            {fileVal ? 'Change' : 'Select file'}
            <input
              type="file"
              accept={field.accept}
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                  // For binary fields, result is a `data:<mime>;base64,<payload>`
                  // string from readAsDataURL — the plugin decodes the base64.
                  // For text fields, result is the UTF-8 decoded text.
                  onChange({ name: file.name, content: reader.result as string, mime: file.type } as PluginFileValue);
                };
                if (binary) {
                  reader.readAsDataURL(file);
                } else {
                  reader.readAsText(file);
                }
              }}
            />
          </label>
          {fileVal
            ? <span className="sg-module-file-name">{fileVal.name}</span>
            : <span className="sg-setting-hint" style={{ margin: 0 }}>No file selected</span>
          }
        </div>
      </div>
    );
  }

  if (field.type === 'table' && field.columns && field.columns.length > 0) {
    const rows: Array<Record<string, unknown>> = Array.isArray(resolved)
      ? (resolved as Array<Record<string, unknown>>)
      : (Array.isArray(field.default) ? (field.default as Array<Record<string, unknown>>) : []);
    return (
      <div className="sg-module-config-row sg-module-config-row--table">
        <span className="sg-module-config-label">{label}</span>
        <TableEditor
          columns={field.columns}
          rows={rows}
          onChange={(next) => onChange(next)}
          maxHeight={field.maxHeight}
          model={model}
          formValues={formValues}
        />
      </div>
    );
  }

  // string / bare number
  return (
    <label className="sg-module-config-row">
      <span className="sg-module-config-label">{label}</span>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        className="sg-module-config-input"
        value={String(resolved ?? '')}
        step={field.step}
        min={field.min}
        max={field.max}
        onChange={(e) => onChange(field.type === 'number' ? Number(e.target.value) : e.target.value)}
      />
      {field.unit && <span className="sg-module-config-unit">{field.unit}</span>}
    </label>
  );
}

// ── Table editor (config field type 'table') ─────────────────────────────────

interface TableEditorProps {
  columns: ModuleConfigTableColumn[];
  rows: Array<Record<string, unknown>>;
  onChange: (rows: Array<Record<string, unknown>>) => void;
  maxHeight?: number;
  model?: WorkbookModel;
  formValues?: Record<string, unknown>;
}

function emptyRow(columns: ModuleConfigTableColumn[]): Record<string, unknown> {
  const row: Record<string, unknown> = {};
  for (const c of columns) row[c.key] = c.type === 'number' ? 0 : '';
  return row;
}

function cellInput(
  column: ModuleConfigTableColumn,
  cell: unknown,
  onCellChange: (v: unknown) => void,
  selectOptions: ResolvedOption[],
): React.ReactNode {
  if (column.type === 'select' && (column.options || column.optionsFrom)) {
    return (
      <SearchableSelect
        className="constraints-cell-input"
        value={String(cell ?? '')}
        options={[{ value: '', label: '—' }, ...selectOptions]}
        onChange={(v) => onCellChange(v)}
      />
    );
  }
  if (column.type === 'number') {
    return (
      <input
        type="number"
        className="constraints-cell-input constraints-cell-input--num"
        value={cell === null || cell === undefined ? '' : String(cell)}
        onChange={(e) => onCellChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
    );
  }
  return (
    <input
      type="text"
      className="constraints-cell-input"
      value={cell === null || cell === undefined ? '' : String(cell)}
      onChange={(e) => onCellChange(e.target.value)}
    />
  );
}

function TableEditor({ columns, rows, onChange, maxHeight, model, formValues }: TableEditorProps) {
  // Per-column 'select' options are the same for every row, so resolve once.
  // Dynamic `optionsFrom` (model sheet / sibling config table) wins; the
  // static `options` array is the fallback when it resolves to nothing.
  const columnOptions = useMemo(() => {
    const map: Record<string, ResolvedOption[]> = {};
    for (const c of columns) {
      if (c.type !== 'select') continue;
      const staticOpts = (c.options ?? []).map((opt) => ({ value: String(opt.value), label: String(opt.label ?? opt.value) }));
      map[c.key] = resolveStaticOrDynamic(c.optionsFrom, staticOpts, { model, formValues });
    }
    return map;
  }, [columns, model, formValues]);

  const updateCell = (rowIdx: number, key: string, val: unknown) => {
    const next = rows.map((r, i) => (i === rowIdx ? { ...r, [key]: val } : r));
    onChange(next);
  };
  const addRow = () => onChange([...rows, emptyRow(columns)]);
  const deleteRow = (rowIdx: number) => {
    const next = rows.filter((_, i) => i !== rowIdx);
    onChange(next);
  };

  return (
    <div className="sg-module-table-editor">
      <div
        className="constraints-table-wrap"
        style={maxHeight !== undefined ? { maxHeight, overflowY: 'auto' } : undefined}
      >
      <table className="constraints-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                style={c.width ? { width: typeof c.width === 'number' ? `${c.width}px` : c.width } : undefined}
              >
                {c.label ?? c.key}
              </th>
            ))}
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length + 1} className="constraints-cell-placeholder" style={{ textAlign: 'center', padding: '8px 0' }}>
                No rows — click “+ Add row” to start.
              </td>
            </tr>
          ) : (
            rows.map((row, rowIdx) => (
              <tr key={rowIdx}>
                {columns.map((c) => (
                  <td key={c.key}>{cellInput(c, row[c.key], (v) => updateCell(rowIdx, c.key, v), columnOptions[c.key] ?? [])}</td>
                ))}
                <td>
                  <button
                    type="button"
                    className="gcc-del"
                    onClick={() => deleteRow(rowIdx)}
                    aria-label={`Delete row ${rowIdx + 1}`}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>
      <button type="button" className="tb-btn" style={{ marginTop: 8 }} onClick={addRow}>
        + Add row
      </button>
    </div>
  );
}

// ── Module card ───────────────────────────────────────────────────────────────

interface ModuleCardProps {
  module: ModuleDescriptor;
  enabled: boolean;
  eligible: boolean;
  onToggleEnabled: () => void;
  onUninstall: () => void;
}

function ModuleCard({
  module, enabled, eligible, onToggleEnabled, onUninstall,
}: ModuleCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`sg-module-card${expanded ? ' sg-module-card--open' : ''}`}>
      {/* ── Header (always visible) ─────────────────────────────────── */}
      <button
        type="button"
        className="sg-module-card-header"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <div className="sg-module-name-row">
          <strong className="sg-module-name">{module.name || module.id}</strong>
          <span className={`sg-module-status sg-module-status--${module.status}`}>
            {statusLabel(module)}
          </span>
          <span className="sg-module-card-chevron" aria-hidden>{expanded ? '▴' : '▾'}</span>
        </div>
        <p className="sg-module-meta">
          {module.id} · v{module.version || '—'} · sdk {module.sdkVersion || '—'}
        </p>
      </button>

      {/* ── Body (expanded only) ────────────────────────────────────── */}
      {expanded && (
        <div className="sg-module-card-body">
          <p className="sg-module-meta">
            Capabilities: {module.capabilities.length > 0 ? module.capabilities.join(', ') : '—'}
          </p>

          {module.diagnostics.length > 0 && (
            <div className="sg-module-diag-list">
              {module.diagnostics.map((item, i) => (
                <p key={i} className="sg-error-text">{item}</p>
              ))}
            </div>
          )}

          <div className="sg-module-action-row">
            <code className="sg-module-root-path">{module.modulePath}</code>
            <div className="sg-module-action-bottom">
              <div className="sg-module-btn-row">
                <button
                  className={`tb-btn sg-module-toggle-btn${enabled ? '' : ' tb-btn--muted'}`}
                  disabled={!eligible}
                  onClick={onToggleEnabled}
                  title={eligible ? 'Enable for future runs.' : 'Only ready modules can be enabled.'}
                >
                  {enabled ? 'Enabled' : 'Enable'}
                </button>
                <button
                  className="tb-btn tb-btn--muted"
                  onClick={onUninstall}
                  title="Remove this module completely."
                >
                  Uninstall
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Section ───────────────────────────────────────────────────────────────────

export function ModuleManagerSection({
  inventory, loading, error,
  enabledIds, isEnabled, isEnableEligible,
  onToggleEnabled, onInstall, onUninstall,
}: ModuleManagerSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modules = inventory?.modules ?? [];

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) { onInstall(file); e.target.value = ''; }
  }

  return (
    <div className="sg-module-rail">
      <div className="sg-module-head">
        <span className="sg-module-meta">
          {inventory
            ? `SDK ${inventory.host.sdkVersion} · ${enabledIds.length} enabled`
            : 'No host'}
        </span>
        <button className="tb-btn" onClick={() => fileInputRef.current?.click()} disabled={loading}>
          {loading ? 'Installing…' : 'Install'}
        </button>
        <input ref={fileInputRef} type="file" accept=".zip"
          style={{ display: 'none' }} onChange={handleFileChange} />
      </div>

      {error && <p className="sg-error-text">{error}</p>}

      {modules.length === 0 ? (
        <p className="sg-setting-hint" style={{ marginTop: 8 }}>
          No modules installed yet. Click Install to select a <code>.zip</code> module package.
        </p>
      ) : (
        <div className="sg-module-list">
          {modules.map((module) => (
            <ModuleCard
              key={module.id}
              module={module}
              enabled={isEnabled(module.id) && isEnableEligible(module)}
              eligible={isEnableEligible(module)}
              onToggleEnabled={() => {
                const enabled = isEnabled(module.id) && isEnableEligible(module);
                onToggleEnabled(module.id, !enabled);
              }}
              onUninstall={() => onUninstall(module)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
