/**
 * Analytics dashboard — wires PyPSA-specific cards into the generic
 * Dashboard grid plus a toolbar for layout edit / save / load.
 *
 * Card kinds supported in this iteration:
 *   - chart  : a user-defined chart (UserDefinedChartCard)
 *   - notes  : run narrative bullet list
 *
 * A map card is intentionally omitted from the palette here — the
 * Model view already owns the network map, and the analytics map's
 * focus / line-loading / SMP-color logic isn't yet extracted into a
 * self-contained card. Slated for a follow-up.
 */
import React, { useState } from 'react';
import { ChartSectionConfig, RunResults, WorkbookModel } from '../../../shared/types';
import { EMPTY_METRIC_KEY } from '../../../constants';
import { UserDefinedChartCard } from '../../../features/analytics/cards/UserDefinedChartCard';
import { Dashboard, addCard, newId } from './Dashboard';
import { Card, DashboardLayout } from './types';
import { useDashboardLayout } from './useDashboardLayout';
import { PRESETS } from './presets';

const DEFAULT_LAYOUT: DashboardLayout = { rows: [], cards: [] };

function newChartCard(): Card {
  return {
    id: newId('chart'),
    kind: 'chart',
    config: {
      id: Date.now(),
      focusType: 'system',
      focusKeys: [],
      groupBy: 'carrier',
      busFilter: [],
      carrierFilter: [],
      metricKey: EMPTY_METRIC_KEY,
      chartType: 'line',
      timeframe: 'hourly',
      startIndex: 0,
      endIndex: 0,
      stacked: false,
    },
  };
}

function newNotesCard(): Card {
  return { id: newId('notes'), kind: 'notes' };
}

interface Props {
  results: RunResults;
  model: WorkbookModel;
  currencySymbol: string;
}

export function AnalyticsDashboard({ results, model, currencySymbol }: Props) {
  const { layout, setLayout, editing, setEditing, savedLayouts, saveAs, load, remove, resetToDefault } =
    useDashboardLayout(DEFAULT_LAYOUT);
  const [openMenu, setOpenMenu] = useState<'add' | 'layouts' | 'presets' | null>(null);

  const updateChartConfig = (cardId: string, next: ChartSectionConfig) =>
    setLayout({
      ...layout,
      cards: layout.cards.map((c) =>
        c.id === cardId && c.kind === 'chart' ? { ...c, config: next } : c,
      ),
    });

  const handleAdd = (kind: 'chart' | 'notes') => {
    const card = kind === 'chart' ? newChartCard() : newNotesCard();
    const targetRow = layout.rows[layout.rows.length - 1]?.id ?? null;
    setLayout(addCard(layout, targetRow, card));
    setOpenMenu(null);
  };

  const handleSave = () => {
    const name = window.prompt('Save layout as:', `layout-${savedLayouts.length + 1}`);
    if (name) saveAs(name);
    setOpenMenu(null);
  };

  const handleLoad = (name: string) => {
    load(name);
    setOpenMenu(null);
  };

  const handleDelete = (name: string) => {
    if (!window.confirm(`Delete saved layout "${name}"?`)) return;
    remove(name);
  };

  const handleLoadPreset = (key: string) => {
    const preset = PRESETS.find((p) => p.key === key);
    if (preset) setLayout(preset.build());
    setOpenMenu(null);
  };

  const renderCard = (card: Card): React.ReactNode => {
    if (card.kind === 'chart') {
      return (
        <UserDefinedChartCard
          section={card.config}
          results={results}
          model={model}
          currencySymbol={currencySymbol}
          onChange={(next) => updateChartConfig(card.id, next)}
          onClean={() => updateChartConfig(card.id, {
            ...card.config,
            focusType: 'system',
            focusKeys: [],
            groupBy: 'carrier',
            busFilter: [],
            carrierFilter: [],
            metricKey: EMPTY_METRIC_KEY,
            chartType: 'line',
            timeframe: 'hourly',
            startIndex: 0,
            endIndex: 0,
            stacked: false,
          })}
          onRemove={() => {
            // The dashboard cell delete button is the canonical way to remove
            // a card from the layout. Here we collapse to no-op so the chart
            // card's own internal remove control stays inert in dashboard mode.
          }}
        />
      );
    }
    if (card.kind === 'notes') {
      return (
        <ul className="dashboard-notes">
          {results.narrative.length === 0 && <li className="dashboard-notes-empty">No notes from this run.</li>}
          {results.narrative.map((item) => <li key={item}>{item}</li>)}
        </ul>
      );
    }
    return null;
  };

  const cardTitle = (card: Card): string => {
    if (card.kind === 'chart') {
      const f = card.config.focusType;
      return f === 'system' ? 'System chart' : `${f} · chart`;
    }
    if (card.kind === 'notes') return 'Run notes';
    return 'Card';
  };

  return (
    <div className="analytics-dashboard">
      <div className="dashboard-toolbar">
        <button
          className={`tb-btn${editing ? ' tb-btn--active' : ''}`}
          onClick={() => setEditing(!editing)}
        >
          {editing ? 'Done editing' : 'Edit layout'}
        </button>

        <div className="dashboard-toolbar-sep" />

        <div className="dashboard-toolbar-menu">
          <button className="tb-btn" onClick={() => setOpenMenu(openMenu === 'presets' ? null : 'presets')}>
            Presets ▾
          </button>
          {openMenu === 'presets' && (
            <div className="dashboard-toolbar-pop dashboard-toolbar-pop--wide">
              {PRESETS.map((p) => (
                <button
                  key={p.key}
                  className="dashboard-preset-row"
                  onClick={() => handleLoadPreset(p.key)}
                  title={p.description}
                >
                  <span className="dashboard-preset-label">{p.label}</span>
                  <span className="dashboard-preset-desc">{p.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {editing && (
          <>
            <div className="dashboard-toolbar-menu">
              <button className="tb-btn" onClick={() => setOpenMenu(openMenu === 'add' ? null : 'add')}>
                + Add card
              </button>
              {openMenu === 'add' && (
                <div className="dashboard-toolbar-pop">
                  <button className="tb-btn" onClick={() => handleAdd('chart')}>Chart</button>
                  <button className="tb-btn" onClick={() => handleAdd('notes')}>Run notes</button>
                </div>
              )}
            </div>
            <div className="dashboard-toolbar-sep" />
            <button className="tb-btn" onClick={handleSave}>Save layout…</button>
            <div className="dashboard-toolbar-menu">
              <button
                className="tb-btn"
                onClick={() => setOpenMenu(openMenu === 'layouts' ? null : 'layouts')}
                disabled={savedLayouts.length === 0}
              >
                Load…
              </button>
              {openMenu === 'layouts' && savedLayouts.length > 0 && (
                <div className="dashboard-toolbar-pop">
                  {savedLayouts.map((s) => (
                    <div key={s.name} className="dashboard-saved-row">
                      <button className="tb-btn" onClick={() => handleLoad(s.name)} title={`Saved ${new Date(s.updatedAt).toLocaleString()}`}>
                        {s.name}
                      </button>
                      <button className="tb-btn tb-btn--muted" onClick={() => handleDelete(s.name)} title="Delete">
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="dashboard-toolbar-sep" />
            <button className="tb-btn tb-btn--muted" onClick={resetToDefault} title="Reset to empty layout">
              Reset
            </button>
          </>
        )}
      </div>

      <Dashboard
        layout={layout}
        onLayoutChange={setLayout}
        editing={editing}
        renderCard={renderCard}
        cardTitle={cardTitle}
      />
    </div>
  );
}
