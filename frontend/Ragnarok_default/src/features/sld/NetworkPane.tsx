/**
 * NetworkPane — the Model tab's right pane: a segmented switch between the geographic map and the single-line diagram.
 * The choice is remembered per viewer in localStorage (a bad or missing value falls back to the map).
 */
import React, { useState } from 'react';
import type { LatLngBoundsExpression } from 'leaflet';
import type { GridRow, WorkbookModel } from 'lib/types';
import { MapPane } from '../map/MapPane';
import { SingleLineDiagram } from './SingleLineDiagram';
import './sld.css';

export type NetworkView = 'map' | 'sld';
const STORAGE_KEY = 'ui:model-network-view';

export function readNetworkView(): NetworkView {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'sld' ? 'sld' : 'map';
  } catch {
    return 'map';
  }
}

interface Props {
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
  onSelect?: (sheet: string, name: string) => void;
}

export function NetworkPane({ model, bounds, busIndex, onSelect }: Props) {
  const [view, setView] = useState<NetworkView>(readNetworkView);
  const choose = (next: NetworkView) => {
    setView(next);
    try { window.localStorage.setItem(STORAGE_KEY, next); } catch { /* private mode: the choice just is not remembered */ }
  };
  return (
    <div className="network-switch">
      <div className="network-switch-bar">
        <div className="network-switch-group" role="group" aria-label="Network view">
          <button type="button" className="network-switch-btn" aria-pressed={view === 'map'} onClick={() => choose('map')}>Map</button>
          <button type="button" className="network-switch-btn" aria-pressed={view === 'sld'} onClick={() => choose('sld')}>Single-line diagram</button>
        </div>
      </div>
      <div className="network-switch-body">
        {view === 'map'
          ? <MapPane model={model} bounds={bounds} busIndex={busIndex} />
          : <SingleLineDiagram model={model} onSelect={onSelect} />}
      </div>
    </div>
  );
}
