import React, { useMemo, useState } from 'react';
import {
  ModuleConfigField,
  ModuleDescriptor,
  ModulePanelConfig,
  PluginAnalyticsEntry,
  PluginFieldHint,
  PluginPanelLayout,
  WorkbookModel,
} from 'lib/types';
import { ConfigFieldRow } from '../modules/ModuleManagerSection';
import { PluginChart } from './PluginChart';
import { isPluginChartSpec } from 'lib/plugins/chartSpec';

type PluginInnerTab = 'description' | 'input' | 'output';

interface DescriptionSection {
  id: string;
  title?: string;
  body: string;
}

interface InputSection {
  id: string;
  title: string;
  description?: string;
  fields: Array<[string, ModuleConfigField]>;
}

interface OutputSection {
  id: string;
  title: string;
  data: Record<string, unknown>;
  ui: Record<string, PluginFieldHint>;
}

function layoutClass(layout: PluginPanelLayout | undefined): string {
  switch (layout) {
    case '2x1':
      return 'plugin-panel-grid plugin-panel-grid--2x1';
    case '1x2':
      return 'plugin-panel-grid plugin-panel-grid--1x2';
    case '2x2':
      return 'plugin-panel-grid plugin-panel-grid--2x2';
    default:
      return 'plugin-panel-grid plugin-panel-grid--single';
  }
}

const TWO_COLUMN_LAYOUTS = new Set<PluginPanelLayout>(['2x1', '2x2']);

/**
 * Plugin-panel grid whose middle divider is draggable to rebalance the two
 * columns (so wide tables on one side aren't clipped). Two-column layouts get a
 * splitter; other layouts render a plain grid. Sections keep `min-width: 0`, so
 * content reflows / scrolls to fit whatever width the user sets.
 */
function PanelGrid({ layout, children }: { layout: PluginPanelLayout | undefined; children: React.ReactNode }) {
  const cls = layoutClass(layout);
  const ref = React.useRef<HTMLDivElement>(null);
  const [leftFr, setLeftFr] = useState(1); // left:right column ratio (right pinned at 1)

  if (!layout || !TWO_COLUMN_LAYOUTS.has(layout)) {
    return <div className={cls}>{children}</div>;
  }

  const frac = leftFr / (leftFr + 1); // left column's fraction of the width
  const onPointerDown = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const width = el.getBoundingClientRect().width;
    const startX = e.clientX;
    const startFrac = frac;
    const move = (ev: PointerEvent) => {
      let f = startFrac + (ev.clientX - startX) / Math.max(width, 1);
      f = Math.min(0.85, Math.max(0.15, f));
      setLeftFr(f / (1 - f));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.style.cursor = '';
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    document.body.style.cursor = 'col-resize';
    e.preventDefault();
  };

  return (
    <div className="plugin-panel-resizable">
      <div ref={ref} className={cls} style={{ gridTemplateColumns: `minmax(0, ${leftFr}fr) minmax(0, 1fr)` }}>
        {children}
      </div>
      <div
        className="plugin-panel-splitter"
        style={{ left: `calc(${frac * 100}% - 4px)` }}
        onPointerDown={onPointerDown}
        onDoubleClick={() => setLeftFr(1)}
        role="separator"
        aria-orientation="vertical"
        aria-label="Drag to resize columns (double-click to reset)"
        title="Drag to resize · double-click to reset"
      />
    </div>
  );
}

function formatPluginValue(value: unknown, hint: PluginFieldHint | undefined): string {
  if (value === null || value === undefined) return '—';
  if (hint?.format === 'currency' || hint?.format === 'number') {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

function renderTableContent(value: unknown, hint: PluginFieldHint | undefined): React.ReactNode | null {
  if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'object' && value[0] !== null) {
    const cols = Object.keys(value[0] as Record<string, unknown>);
    return (
      <table className="plugin-result-subtable">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {(value as Record<string, unknown>[]).map((row, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>
                  {formatPluginValue(row[c], hint)}
                  {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (typeof value === 'object' && !Array.isArray(value) && value !== null) {
    return (
      <table className="plugin-result-subtable">
        <tbody>
          {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td>
                {formatPluginValue(v, hint)}
                {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return null;
}

function buildDescriptionSections(module: ModuleDescriptor): DescriptionSection[] {
  const manifestSections = module.panel?.descriptionSections ?? [];
  if (manifestSections.length > 0) {
    return manifestSections.map((section, index) => ({
      id: `description-${index}`,
      title: section.title,
      body: section.body,
    }));
  }
  if (module.description) {
    return [{ id: 'description-main', title: 'Description', body: module.description }];
  }
  return [];
}

function buildInputSections(module: ModuleDescriptor): InputSection[] {
  const schema = module.config ?? {};
  const entries = Object.entries(schema);
  if (entries.length === 0) return [];

  const sections: InputSection[] = [];
  let current: InputSection = { id: 'input-general', title: 'General', fields: [] };

  entries.forEach(([key, field], index) => {
    if (field.type === 'group') {
      if (current.fields.length > 0) sections.push(current);
      current = {
        id: `input-group-${index}`,
        title: field.label ?? 'Section',
        description: field.description,
        fields: [],
      };
      return;
    }
    current.fields.push([key, field]);
  });

  if (current.fields.length > 0) sections.push(current);
  return sections;
}

function buildOutputSections(entry: PluginAnalyticsEntry | null): OutputSection[] {
  if (!entry || !entry.data || Object.keys(entry.data).length === 0) return [];
  const groups = new Map<string, OutputSection>();

  Object.entries(entry.data).forEach(([key, value]) => {
    const hint = entry.ui?.[key];
    const sectionTitle = hint?.section || 'Results';
    const existing = groups.get(sectionTitle) ?? {
      id: `output-${sectionTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
      title: sectionTitle,
      data: {},
      ui: {},
    };
    existing.data[key] = value;
    existing.ui[key] = hint ?? {};
    groups.set(sectionTitle, existing);
  });

  return Array.from(groups.values());
}

function PluginResults({ data, ui }: { data: Record<string, unknown>; ui: Record<string, PluginFieldHint> }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="sg-setting-hint">No results yet — run the model first.</p>;
  }
  return (
    <table className="plugin-result-table">
      <tbody>
        {Object.entries(data).map(([key, value]) => {
          const hint = ui?.[key];

          if (key === 'error') {
            return (
              <tr key={key}>
                <td colSpan={2} style={{ color: 'var(--danger, #dc2626)', fontSize: '0.82rem' }}>
                  Plugin error: {String(value)}
                </td>
              </tr>
            );
          }

          if (hint?.format === 'chart' && isPluginChartSpec(value)) {
            return (
              <tr key={key}>
                <td className="plugin-result-chart-cell" colSpan={2}>
                  <PluginChart spec={value} title={hint?.label} />
                </td>
              </tr>
            );
          }

          if (hint?.format === 'table') {
            const tableContent = renderTableContent(value, hint);
            if (tableContent) {
              return (
                <tr key={key}>
                  <td className="plugin-result-label" style={{ verticalAlign: 'top' }}>{hint?.label ?? key}</td>
                  <td className="plugin-result-value">{tableContent}</td>
                </tr>
              );
            }
          }

          return (
            <tr key={key}>
              <td className="plugin-result-label">{hint?.label ?? key}</td>
              <td className="plugin-result-value">
                {formatPluginValue(value, hint)}
                {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function DescriptionView({ module }: { module: ModuleDescriptor }) {
  const sections = buildDescriptionSections(module);
  const panel = module.panel as ModulePanelConfig | undefined;
  if (sections.length === 0) {
    return <p className="sg-setting-hint">No plugin description provided.</p>;
  }
  return (
    <div className={layoutClass(panel?.descriptionLayout)}>
      {sections.map((section) => (
        <section key={section.id} className="plugin-panel-section">
          {section.title && <h3 className="plugin-panel-section-title">{section.title}</h3>}
          <p className="plugin-panel-description">{section.body}</p>
        </section>
      ))}
    </div>
  );
}

interface InputViewProps {
  module: ModuleDescriptor;
  config: Record<string, unknown>;
  onConfigChange: (key: string, value: unknown) => void;
  carriers?: string[];
  model?: WorkbookModel;
  onModuleAction?: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

function InputView({ module, config, onConfigChange, carriers, model, onModuleAction }: InputViewProps) {
  const sections = buildInputSections(module);
  const panel = module.panel as ModulePanelConfig | undefined;
  if (sections.length === 0) {
    return <p className="sg-setting-hint">This plugin does not define any input fields.</p>;
  }
  return (
    <PanelGrid layout={panel?.inputLayout}>
      {sections.map((section) => (
        <section key={section.id} className="plugin-panel-section">
          <h3 className="plugin-panel-section-title">{section.title}</h3>
          {section.description && <p className="sg-setting-hint">{section.description}</p>}
          <div className="sg-module-config-form">
            {section.fields.map(([key, field]) => (
              <ConfigFieldRow
                key={key}
                fieldKey={key}
                field={field}
                value={config[key]}
                onChange={(value) => onConfigChange(key, value)}
                carriers={carriers}
                model={model}
                formValues={config}
                onAction={onModuleAction ? (fk, f) => onModuleAction(module.id, fk, f) : undefined}
              />
            ))}
          </div>
        </section>
      ))}
    </PanelGrid>
  );
}

function OutputView({ module, analytics }: { module: ModuleDescriptor; analytics: PluginAnalyticsEntry | null }) {
  const sections = buildOutputSections(analytics);
  const panel = module.panel as ModulePanelConfig | undefined;
  if (sections.length === 0) {
    return <p className="sg-setting-hint">No results yet — run the model first.</p>;
  }
  return (
    <PanelGrid layout={panel?.outputLayout}>
      {sections.map((section) => (
        <section key={section.id} className="plugin-panel-section">
          <h3 className="plugin-panel-section-title">{section.title}</h3>
          <PluginResults data={section.data} ui={section.ui} />
        </section>
      ))}
    </PanelGrid>
  );
}

interface PluginTabContentProps {
  module: ModuleDescriptor;
  config: Record<string, unknown>;
  onConfigChange: (key: string, value: unknown) => void;
  carriers?: string[];
  model?: WorkbookModel;
  analytics: PluginAnalyticsEntry | null;
  onModuleAction?: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

function PluginTabContent({ module, config, onConfigChange, carriers, model, analytics, onModuleAction }: PluginTabContentProps) {
  const [activeInnerTab, setActiveInnerTab] = useState<PluginInnerTab>('description');
  const innerTabs: Array<{ key: PluginInnerTab; label: string }> = [
    { key: 'description', label: 'Description' },
    { key: 'input', label: 'Input' },
    { key: 'output', label: 'Output' },
  ];

  return (
    <div className="plugin-panel-content">
      <div className="plugin-panel-subtabs">
        {innerTabs.map((tab) => (
          <button
            key={tab.key}
            className={`analytics-subtab${activeInnerTab === tab.key ? ' analytics-subtab--active' : ''}`}
            onClick={() => setActiveInnerTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeInnerTab === 'description' && <DescriptionView module={module} />}
      {activeInnerTab === 'input' && (
        <InputView
          module={module}
          config={config}
          onConfigChange={onConfigChange}
          carriers={carriers}
          model={model}
          onModuleAction={onModuleAction}
        />
      )}
      {activeInnerTab === 'output' && <OutputView module={module} analytics={analytics} />}
    </div>
  );
}

interface PluginPanelProps {
  modules: ModuleDescriptor[];
  moduleConfigs: Record<string, Record<string, unknown>>;
  onModuleConfigChange: (moduleId: string, key: string, value: unknown) => void;
  carriers?: string[];
  model?: WorkbookModel;
  pluginAnalytics: Record<string, PluginAnalyticsEntry>;
  onModuleAction?: (moduleId: string, fieldKey: string, field: ModuleConfigField) => Promise<void>;
}

export function PluginPanel({
  modules, moduleConfigs, onModuleConfigChange, carriers, model, pluginAnalytics, onModuleAction,
}: PluginPanelProps) {
  const [activeId, setActiveId] = useState<string>(modules[0]?.id ?? '');
  const activeModules = useMemo(() => modules, [modules]);

  if (activeModules.length === 0) {
    return (
      <div className="analytics-empty">
        <h3>No enabled plugins</h3>
        <p>Install and enable a plugin from the sidebar to use the Plugins workspace.</p>
      </div>
    );
  }

  const fallbackId = activeModules[0].id;
  const active = activeModules.find((m) => m.id === activeId) ?? activeModules[0];

  const onlyOne = activeModules.length === 1;

  return (
    <div className="plugin-panel-root">
      <div className="plugin-panel-header">
        {onlyOne ? (
          <h2 className="plugin-panel-title">
            {active.name || active.id}
            <span className="plugin-panel-title-meta">v{active.version || '—'} · {active.id}</span>
          </h2>
        ) : (
          <nav className="plugin-module-tabs" aria-label="Active plugin">
            {activeModules.map((m) => (
            <button
              key={m.id}
              className={`plugin-module-tab${(activeId || fallbackId) === m.id ? ' is-active' : ''}`}
              onClick={() => setActiveId(m.id)}
            >
              {m.name || m.id}
              {pluginAnalytics[m.id] && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: 'var(--brand, #0f766e)',
                    marginLeft: 6,
                    verticalAlign: 'middle',
                  }}
                  title="Has results"
                />
              )}
            </button>
          ))}
          </nav>
        )}
      </div>

      <PluginTabContent
        key={active.id}
        module={active}
        config={moduleConfigs[active.id] ?? {}}
        onConfigChange={(key, value) => onModuleConfigChange(active.id, key, value)}
        carriers={carriers}
        model={model}
        analytics={pluginAnalytics[active.id] ?? null}
        onModuleAction={onModuleAction}
      />
    </div>
  );
}
