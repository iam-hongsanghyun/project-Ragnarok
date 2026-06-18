/**
 * Welcome view — first-time landing page.
 *
 *  1. A start chooser: "Start from scratch" or "Start with an example"
 *     (examples are bundled SQLite starter projects loaded via the backend).
 *  2. A short paragraph of what Ragnarok is.
 *  3. A quick manual (numbered steps the user reads top-to-bottom).
 *  4. A grid of tiles, one per workspace view, that double as navigation.
 *
 * Click the "Ragnarok" word in the top-bar to return here from anywhere.
 */
import React, { useEffect, useState } from 'react';
import { WorkspaceTab } from 'lib/types';
import { RagnarokLogo } from 'shared/components/RagnarokLogo';
import { ExampleMeta, listExamples } from 'lib/api/examples';

interface Props {
  onNavigate: (tab: WorkspaceTab) => void;
  /** Start a brand-new empty model (and jump into the guided builder). */
  onStartScratch?: () => void;
  /** Load a bundled example into the session by id. */
  onLoadExample?: (id: string) => void | Promise<void>;
}

interface Tile {
  id: WorkspaceTab;
  title: string;
  blurb: string;
}

const TILES: Tile[] = [
  {
    id: 'Data',
    title: 'Data',
    blurb:
      'Country-first importers: pick a region on the map, pull the network, plants, demand, and renewable profiles from open databases (OSM, WRI GPPD, OPSD, World Bank).',
  },
  {
    id: 'Build',
    title: 'Build',
    blurb:
      'Map-driven editor for the network: click to place buses, drag to link them, edit component attributes in the right rail.',
  },
  {
    id: 'Model',
    title: 'Model',
    blurb:
      'The full workbook view: every sheet, every column, every snapshot. Edit cells directly, paste from spreadsheets, manage time-series.',
  },
  {
    id: 'Forge',
    title: 'Forge',
    blurb:
      'Shape the imported data: round / ceil / floor numeric attributes in bulk, and snap components to their nearest bus by distance (within a km buffer).',
  },
  {
    id: 'Settings',
    title: 'Settings',
    blurb:
      'Solver options, currency, date format, scenarios, pathway / rolling / stochastic / N-1 run modes.',
  },
  {
    id: 'Analytics',
    title: 'Analytics',
    blurb:
      'Validation, results, comparison across scenarios, per-asset drill-downs, custom charts, run history, solver logs.',
  },
  {
    id: 'Plugins',
    title: 'Plugins',
    blurb:
      'Local plugins for data import, custom analytics, and workbook transforms. Drop a folder under your plugins root and Ragnarok picks it up.',
  },
];

function StartChooser({ onStartScratch, onLoadExample }: { onStartScratch?: () => void; onLoadExample?: (id: string) => void | Promise<void> }) {
  const [picking, setPicking] = useState(false);
  const [examples, setExamples] = useState<ExampleMeta[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  useEffect(() => {
    if (!picking || examples) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listExamples()
      .then((list) => { if (!cancelled) setExamples(list); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load examples.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [picking, examples]);

  const pick = async (id: string) => {
    if (!onLoadExample) return;
    setLoadingId(id);
    try { await onLoadExample(id); } finally { setLoadingId(null); }
  };

  return (
    <section className="welcome-section welcome-start">
      <h2>Get started</h2>
      {!picking ? (
        <div className="welcome-start-choices">
          <button type="button" className="welcome-start-card" onClick={onStartScratch}>
            <span className="welcome-start-card__title">Start from scratch</span>
            <span className="welcome-start-card__blurb">Begin with an empty model and build it up step by step in the guided builder.</span>
          </button>
          <button type="button" className="welcome-start-card" onClick={() => setPicking(true)}>
            <span className="welcome-start-card__title">Start with an example</span>
            <span className="welcome-start-card__blurb">Open a ready-made network that already solves — the fastest way to learn the workflow.</span>
          </button>
        </div>
      ) : (
        <div className="welcome-examples">
          <button type="button" className="welcome-back" onClick={() => setPicking(false)}>← Back</button>
          {loading && <p className="welcome-examples-note">Loading examples…</p>}
          {error && <p className="welcome-examples-note welcome-examples-note--error">{error}</p>}
          {!loading && !error && examples && examples.length === 0 && (
            <p className="welcome-examples-note">No examples available.</p>
          )}
          <div className="welcome-examples-list">
            {(examples ?? []).map((ex) => (
              <button
                key={ex.id}
                type="button"
                className="welcome-example-card"
                disabled={loadingId !== null}
                onClick={() => void pick(ex.id)}
              >
                <span className="welcome-example-card__title">
                  {ex.label}{loadingId === ex.id ? ' · loading…' : ''}
                </span>
                {ex.description && <span className="welcome-example-card__blurb">{ex.description}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export function WelcomeView({ onNavigate, onStartScratch, onLoadExample }: Props) {
  return (
    <div className="view welcome-view">
      <div className="welcome-content">
        <header className="welcome-header">
          <RagnarokLogo size={68} title="" className="welcome-logo" />
          <h1>Ragnarok</h1>
          <p className="welcome-tagline">
            Open-source energy-system modelling for the rest of us.
            Build a PyPSA model from public data, run it, analyse it, share it —
            no Python required.
          </p>
        </header>

        {(onStartScratch || onLoadExample) && (
          <StartChooser onStartScratch={onStartScratch} onLoadExample={onLoadExample} />
        )}

        <section className="welcome-section">
          <h2>Quick start</h2>
          <ol className="welcome-steps">
            <li>
              Pick <b>Start with an example</b> above to open a ready-made network,
              or <b>Start from scratch</b> for an empty model. You can also import
              your own data from <b>Data</b> (pick a country on the map).
            </li>
            <li>
              Refine the network in <b>Build</b> (map-driven) or <b>Model</b>
              (edit any sheet / cell / snapshot directly).
            </li>
            <li>
              In <b>Settings</b>, pick the run mode (single-period, pathway,
              rolling-horizon, stochastic, N-1) and any scenario presets.
            </li>
            <li>
              Hit <b>Run</b> in the top-bar. Watch progress in the live
              solver log; results land in <b>Analytics</b>.
            </li>
            <li>
              Export the project (`.xlsx`) or the run results to share. Import
              the same file later to restore the full state.
            </li>
          </ol>
        </section>

        <section className="welcome-section">
          <h2>Where to go</h2>
          <div className="welcome-tiles">
            {TILES.map((t) => (
              <button
                key={t.id}
                type="button"
                className="welcome-tile"
                onClick={() => onNavigate(t.id)}
              >
                <span className="welcome-tile__title">{t.title}</span>
                <span className="welcome-tile__blurb">{t.blurb}</span>
              </button>
            ))}
          </div>
        </section>

        <footer className="welcome-footer">
          <p>
            Built on <a href="https://pypsa.readthedocs.io" target="_blank" rel="noreferrer">PyPSA</a>.
            Click the <b>Ragnarok</b> wordmark in the top-bar any time to come back here.
          </p>
        </footer>
      </div>
    </div>
  );
}
