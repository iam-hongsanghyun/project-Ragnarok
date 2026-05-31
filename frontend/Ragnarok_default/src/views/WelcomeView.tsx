/**
 * Welcome view — first-time landing page.
 *
 * Three blocks:
 *  1. A short paragraph of what Ragnarok is.
 *  2. A quick manual (numbered steps the user reads top-to-bottom).
 *  3. A 2x3 grid of tiles, one per workspace view, that double as
 *     navigation shortcuts.
 *
 * Click the "Ragnarok" word in the top-bar to return here from anywhere.
 */
import React from 'react';
import { WorkspaceTab } from 'lib/types';

interface Props {
  onNavigate: (tab: WorkspaceTab) => void;
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

export function WelcomeView({ onNavigate }: Props) {
  return (
    <div className="view welcome-view">
      <div className="welcome-content">
        <header className="welcome-header">
          <h1>Ragnarok</h1>
          <p className="welcome-tagline">
            Open-source energy-system modelling for the rest of us.
            Build a PyPSA model from public data, run it, analyse it, share it —
            no Python required.
          </p>
        </header>

        <section className="welcome-section">
          <h2>Quick start</h2>
          <ol className="welcome-steps">
            <li>
              Open <b>Data</b> and pick a country on the map. Pull the grid
              from OSM, the power-plant fleet from WRI, demand from World
              Bank or OPSD.
            </li>
            <li>
              Switch to <b>Build</b> to refine the network on the map, or
              <b> Model</b> to edit any sheet / cell / snapshot directly.
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
