import React, { useRef, useState } from 'react';
import { ModuleConfigField, ModuleDescriptor, ModuleHostInventory, PluginDisplayMode } from '../../shared/types';

interface ModuleManagerSectionProps {
  inventory: ModuleHostInventory | null;
  loading: boolean;
  error: string | null;
  enabledIds: string[];
  isEnabled: (moduleId: string) => boolean;
  isEnableEligible: (module: ModuleDescriptor) => boolean;
  onToggleEnabled: (moduleId: string, enabled: boolean) => void;
  moduleConfigs: Record<string, Record<string, unknown>>;
  onModuleConfigChange: (moduleId: string, key: string, value: unknown) => void;
  onInstall: (file: File) => void;
  onUninstall: (module: ModuleDescriptor) => void;
  /** Carrier names from the current workbook, used by carrier-select fields. */
  carriers?: string[];
  pluginDisplayModes?: Record<string, PluginDisplayMode>;
  onPluginDisplayModeChange?: (moduleId: string, mode: PluginDisplayMode) => void;
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
}

export function ConfigFieldRow({ fieldKey, field, value, onChange, carriers }: ConfigFieldProps) {
  const resolved = value !== undefined ? value : field.default;
  const label = field.label ?? fieldKey;

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

  if (field.type === 'select' && field.options) {
    return (
      <label className="sg-module-config-row">
        <span className="sg-module-config-label">{label}</span>
        <select
          className="sg-module-config-select"
          value={String(resolved ?? '')}
          onChange={(e) => onChange(e.target.value)}
        >
          {field.options.map((opt) => (
            <option key={String(opt.value)} value={String(opt.value)}>{opt.label}</option>
          ))}
        </select>
      </label>
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

// ── Module card ───────────────────────────────────────────────────────────────

interface ModuleCardProps {
  module: ModuleDescriptor;
  enabled: boolean;
  eligible: boolean;
  config: Record<string, unknown>;
  onToggleEnabled: () => void;
  onModuleConfigChange: (key: string, value: unknown) => void;
  onUninstall: () => void;
  carriers?: string[];
  displayMode?: PluginDisplayMode;
  onDisplayModeChange?: (mode: PluginDisplayMode) => void;
}

function ModuleCard({
  module, enabled, eligible, config, carriers,
  onToggleEnabled, onModuleConfigChange, onUninstall,
  displayMode = 'sidebar', onDisplayModeChange,
}: ModuleCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasConfig = module.config && Object.keys(module.config).length > 0;

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
          <strong>{module.name || module.id}</strong>
          <span className={`sg-module-status sg-module-status--${module.status}`}>
            {statusLabel(module)}
          </span>
        </div>
        <p className="sg-module-meta">
          {module.id} · v{module.version || '—'} · sdk {module.sdkVersion || '—'}
        </p>
        <span className="sg-module-card-chevron">{expanded ? '▲' : '▼'}</span>
      </button>

      {/* ── Body (expanded only) ────────────────────────────────────── */}
      {expanded && (
        <div className="sg-module-card-body">
          {module.description && (
            <p className="sg-setting-hint" style={{ marginBottom: 8 }}>{module.description}</p>
          )}

          <p className="sg-module-meta">
            Capabilities: {module.capabilities.length > 0 ? module.capabilities.join(', ') : '—'}
          </p>

          {/* Config form — hidden when plugin is set to main panel mode */}
          {hasConfig && displayMode === 'sidebar' && (
            <div className="sg-module-config-form">
              {Object.entries(module.config!).map(([key, field]) => (
                <ConfigFieldRow
                  key={key}
                  fieldKey={key}
                  field={field}
                  value={config[key]}
                  onChange={(v) => onModuleConfigChange(key, v)}
                  carriers={carriers}
                />
              ))}
            </div>
          )}
          {hasConfig && displayMode === 'panel' && (
            <p className="sg-setting-hint" style={{ margin: '6px 0' }}>
              Config and results are shown in the <strong>Plugins</strong> tab.
            </p>
          )}

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
              {/* Location toggle */}
              {onDisplayModeChange && (
                <div className="sg-module-location-row">
                  <span className="sg-module-location-label">Location</span>
                  <div className="sg-module-location-btns">
                    {(['sidebar', 'panel'] as PluginDisplayMode[]).map((m) => (
                      <button
                        key={m}
                        className={`tb-btn sg-location-btn${displayMode === m ? '' : ' tb-btn--muted'}`}
                        onClick={() => onDisplayModeChange(m)}
                      >
                        {m === 'sidebar' ? 'Sidebar' : 'Main panel'}
                      </button>
                    ))}
                  </div>
                </div>
              )}
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
  onToggleEnabled, moduleConfigs, onModuleConfigChange,
  onInstall, onUninstall, carriers,
  pluginDisplayModes, onPluginDisplayModeChange,
}: ModuleManagerSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modules = inventory?.modules ?? [];

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) { onInstall(file); e.target.value = ''; }
  }

  return (
    <div className="sg-setting-row">
      <div className="sg-module-head">
        <div>
          <p className="sg-setting-section-title">Local module host</p>
          <p className="sg-setting-hint">
            {inventory
              ? `SDK ${inventory.host.sdkVersion} · ${enabledIds.length} enabled`
              : 'Install trusted local modules to extend Ragnarok.'}
          </p>
        </div>
        <div className="sg-btn-row">
          <button className="tb-btn" onClick={() => fileInputRef.current?.click()} disabled={loading}>
            {loading ? 'Installing…' : 'Install'}
          </button>
          <input ref={fileInputRef} type="file" accept=".zip"
            style={{ display: 'none' }} onChange={handleFileChange} />
        </div>
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
              config={moduleConfigs[module.id] ?? {}}
              carriers={carriers}
              displayMode={pluginDisplayModes?.[module.id] ?? 'sidebar'}
              onDisplayModeChange={onPluginDisplayModeChange
                ? (mode) => onPluginDisplayModeChange(module.id, mode)
                : undefined}
              onToggleEnabled={() => {
                const enabled = isEnabled(module.id) && isEnableEligible(module);
                onToggleEnabled(module.id, !enabled);
              }}
              onModuleConfigChange={(key, value) => onModuleConfigChange(module.id, key, value)}
              onUninstall={() => onUninstall(module)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
