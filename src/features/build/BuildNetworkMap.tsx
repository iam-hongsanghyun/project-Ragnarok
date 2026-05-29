/**
 * Build-mode network map.
 *
 * Renders the model's buses/branches as geographic context and makes the
 * active step's component layer clickable: clicking a node/line selects that
 * row, which drives the attribute form on the right and highlights the row in
 * the table below. Editing the model live re-draws the map.
 *
 * Components are placed where the user clicks (own `x`/`y` on the row) and are
 * never auto-attached to a bus — the user links a bus explicitly, either in the
 * attribute form or by entering "link mode" and clicking a bus on the map. A
 * dashed connector is drawn from a component to its bus only once a bus is set.
 *
 * Unlike the analytics map this is results-agnostic — it only knows the
 * `WorkbookModel` and the sheet the current Build step is editing.
 */
import React, { useEffect, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { GridRow, WorkbookModel } from '../../shared/types';
import { numberValue, stringValue, resolvedColor } from '../../shared/utils/helpers';

const POINT_SHEETS = new Set(['generators', 'loads', 'storage_units', 'stores']);
export const BRANCH_SHEETS = new Set(['lines', 'links', 'transformers']);

/** Singular, human label per sheet for the right-click hint. */
const SHEET_SINGULAR: Record<string, string> = {
  buses: 'bus',
  generators: 'generator',
  loads: 'load',
  storage_units: 'storage unit',
  stores: 'store',
  lines: 'line',
  links: 'link',
  transformers: 'transformer',
};

/** Distinct default fill per component type so layers read apart on the map.
 *  Generators are coloured by carrier instead (see `pointFill`). */
const POINT_FILL: Record<string, string> = {
  loads: '#ef4444',
  storage_units: '#0ea5e9',
  stores: '#eab308',
};

/** Distinct stroke per branch type. */
const BRANCH_COLOR: Record<string, string> = {
  lines: '#0f766e',
  links: '#8b5cf6',
  transformers: '#f97316',
};

const SELECT_COLOR = '#f59e0b';

/** Fill for a point component: explicit `color` wins, else carrier (generators)
 *  or the per-sheet default. */
function pointFill(sheet: string, row: GridRow): string {
  if (sheet === 'generators') return resolvedColor(row.color, row.carrier);
  const explicit = stringValue(row.color).trim();
  if (explicit.startsWith('#')) return explicit;
  return POINT_FILL[sheet] ?? '#14b8a6';
}

/** Sheets the map can geo-locate; other steps render no map. */
export function isGeoSheet(sheet: string): boolean {
  return sheet === 'buses' || POINT_SHEETS.has(sheet) || BRANCH_SHEETS.has(sheet);
}

function ownCoords(row: GridRow): [number, number] | null {
  const x = row.x;
  const y = row.y;
  if (x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
  return [numberValue(y), numberValue(x)];
}

/** Where a point component draws: its own coordinates if it has them, else
 *  (for models imported without coordinates) offset from its bus. */
function pointCoords(row: GridRow, busIndex: Record<string, GridRow>): [number, number] | null {
  const own = ownCoords(row);
  if (own) return own;
  const bus = busIndex[stringValue(row.bus)];
  if (!bus) return null;
  const c = ownCoords(bus);
  return c ? [c[0] + 0.07, c[1] + 0.07] : null;
}

function branchPositions(
  row: GridRow,
  busIndex: Record<string, GridRow>,
): [number, number][] | null {
  const b0 = busIndex[stringValue(row.bus0)];
  const b1 = busIndex[stringValue(row.bus1)];
  if (!b0 || !b1) return null;
  const c0 = ownCoords(b0);
  const c1 = ownCoords(b1);
  if (!c0 || !c1) return null;
  return [c0, c1];
}

/** A clickable map target used to hit-test right-clicks against existing rows. */
interface ClickTarget {
  rowIndex: number;
  latlng: [number, number];
}

/** Right-click anywhere on the map → open a context menu. Hit-tests the click
 *  against the active layer's targets (within HIT_PX) so the menu can offer a
 *  Delete for the component under the cursor. Suppresses the browser menu. */
function MapContextMenu({
  targets,
  onContext,
}: {
  targets: ClickTarget[];
  onContext: (clientX: number, clientY: number, lat: number, lng: number, rowIndex: number | null) => void;
}) {
  const HIT_PX = 14;
  const map = useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      const cp = map.latLngToContainerPoint(e.latlng);
      let hit: number | null = null;
      let bestD = HIT_PX * HIT_PX;
      for (const t of targets) {
        const p = map.latLngToContainerPoint(t.latlng);
        const d = (p.x - cp.x) ** 2 + (p.y - cp.y) ** 2;
        if (d < bestD) { bestD = d; hit = t.rowIndex; }
      }
      onContext(e.originalEvent.clientX, e.originalEvent.clientY, e.latlng.lat, e.latlng.lng, hit);
    },
  });
  return null;
}

/** Leaflet measures its container once on mount; the Build panel resolves its
 *  flex height after that, so remeasure on every container resize. */
function InvalidateOnResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el);
    const t = window.setTimeout(() => map.invalidateSize(), 0);
    return () => { ro.disconnect(); window.clearTimeout(t); };
  }, [map]);
  return null;
}

/** A pending "click a bus to set this field" request. */
export interface LinkMode {
  rowIndex: number;
  field: string;
}

interface Props {
  model: WorkbookModel;
  busIndex: Record<string, GridRow>;
  /** Sheet the current step edits — its rows are the clickable layer. */
  activeSheet: string;
  selectedRowIndex: number | null;
  onSelectRow: (rowIndex: number) => void;
  /** Add a row of the active sheet at this point (from the context menu). */
  onAddAtLocation?: (lat: number, lng: number) => void;
  /** Delete a row of the active sheet (from the context menu). */
  onDeleteRow?: (rowIndex: number) => void;
  /** Active "click a bus" request, if any. */
  linkMode?: LinkMode | null;
  /** Begin linking a bus to the given row's field (from the context menu). */
  onStartLink?: (rowIndex: number, field: string) => void;
  /** A bus was clicked while in link mode. */
  onPickBus?: (busName: string) => void;
  /** Abandon the current link request. */
  onCancelLink?: () => void;
}

interface ContextMenuState {
  x: number;
  y: number;
  lat: number;
  lng: number;
  rowIndex: number | null;
}

export function BuildNetworkMap({
  model, busIndex, activeSheet, selectedRowIndex, onSelectRow, onAddAtLocation, onDeleteRow,
  linkMode, onStartLink, onPickBus, onCancelLink,
}: Props) {
  const rows: GridRow[] = (model as Record<string, GridRow[]>)[activeSheet] ?? [];
  const busActive = activeSheet === 'buses';
  const pointActive = POINT_SHEETS.has(activeSheet);
  const branchActive = BRANCH_SHEETS.has(activeSheet);
  const linking = !!linkMode;

  const [menu, setMenu] = useState<ContextMenuState | null>(null);

  // Close the menu on any outside click, scroll, or Escape.
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null); };
    // Defer binding so the opening right-click doesn't immediately close it.
    const t = window.setTimeout(() => {
      window.addEventListener('click', close);
      window.addEventListener('scroll', close, true);
      window.addEventListener('keydown', onKey);
    }, 0);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('click', close);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  // Escape cancels an in-progress link request.
  useEffect(() => {
    if (!linking) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancelLink?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [linking, onCancelLink]);

  // Targets the context menu hit-tests against to offer a Delete / Link.
  const clickTargets: ClickTarget[] = [];
  if (busActive) {
    model.buses.forEach((b, i) => { const c = ownCoords(b); if (c) clickTargets.push({ rowIndex: i, latlng: c }); });
  } else if (pointActive) {
    rows.forEach((r, i) => { const c = pointCoords(r, busIndex); if (c) clickTargets.push({ rowIndex: i, latlng: c }); });
  } else if (branchActive) {
    rows.forEach((r, i) => {
      const p = branchPositions(r, busIndex);
      if (p) clickTargets.push({ rowIndex: i, latlng: [(p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2] });
    });
  }

  const openMenu = (x: number, y: number, lat: number, lng: number, rowIndex: number | null) => {
    if (rowIndex != null) onSelectRow(rowIndex); // highlight the targeted component
    setMenu({ x, y, lat, lng, rowIndex });
  };

  const singular = SHEET_SINGULAR[activeSheet] ?? 'component';
  const menuTargetName = menu?.rowIndex != null
    ? (stringValue(rows[menu.rowIndex]?.name) || `row ${menu.rowIndex + 1}`)
    : '';
  const linkTargetName = linkMode != null
    ? (stringValue(rows[linkMode.rowIndex]?.name) || `row ${linkMode.rowIndex + 1}`)
    : '';

  // Faint geographic context: lines as thin grey links (non-branch steps).
  const contextLines = model.lines
    .map((line) => branchPositions(line, busIndex))
    .filter(Boolean) as [number, number][][];

  return (
    <div className={`build-map-frame${linking ? ' build-map-frame--linking' : ''}`}>
      <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" scrollWheelZoom>
        <InvalidateOnResize />
        {onAddAtLocation && <MapContextMenu targets={clickTargets} onContext={openMenu} />}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
        />

        {/* Context lines (non-branch steps) */}
        {!branchActive && contextLines.map((positions, i) => (
          <Polyline key={`ctx-line-${i}`} positions={positions} pathOptions={{ color: '#cbd5e1', weight: 2, opacity: 0.7 }} />
        ))}

        {/* Dashed connectors: active point component → its linked bus. */}
        {pointActive && rows.map((row, index) => {
          const own = ownCoords(row);
          const bus = busIndex[stringValue(row.bus)];
          const busC = bus ? ownCoords(bus) : null;
          if (!own || !busC) return null;
          return (
            <Polyline
              key={`conn-${index}`}
              positions={[own, busC]}
              pathOptions={{ color: '#94a3b8', weight: 1.5, opacity: 0.8, dashArray: '4 4' }}
            />
          );
        })}

        {/* Active branch layer — clickable */}
        {branchActive && rows.map((row, index) => {
          const positions = branchPositions(row, busIndex);
          if (!positions) return null;
          const sel = index === selectedRowIndex;
          return (
            <Polyline
              key={`branch-${index}`}
              positions={positions}
              pathOptions={{
                color: sel ? SELECT_COLOR : (BRANCH_COLOR[activeSheet] ?? '#0f766e'),
                weight: sel ? 7 : 3,
                opacity: sel ? 1 : 0.85,
              }}
              eventHandlers={{ click: () => onSelectRow(index) }}
            >
              <Tooltip>{stringValue(row.name) || `row ${index + 1}`}</Tooltip>
            </Polyline>
          );
        })}

        {/* Buses — context, the active+clickable layer, or pickable in link mode */}
        {model.buses.map((bus, index) => {
          const coords = ownCoords(bus);
          if (!coords) return null;
          const sel = busActive && index === selectedRowIndex;
          const name = stringValue(bus.name);
          let handlers: { click: () => void } | undefined;
          if (linking) handlers = { click: () => onPickBus?.(name) };
          else if (busActive) handlers = { click: () => onSelectRow(index) };
          return (
            <CircleMarker
              key={`bus-${index}`}
              center={coords}
              radius={sel ? 11 : linking ? 9 : busActive ? 8 : 6}
              pathOptions={{
                color: sel ? SELECT_COLOR : linking ? '#0f766e' : '#ffffff',
                weight: sel ? 3 : linking ? 3 : 2,
                fillColor: '#0f766e',
                fillOpacity: linking ? 0.95 : busActive ? 0.95 : 0.5,
              }}
              eventHandlers={handlers}
            >
              <Tooltip>
                <strong>{name}</strong><br />
                {linking ? 'Click to link this bus' : `${numberValue(bus.v_nom)} kV · ${stringValue(bus.carrier)}`}
              </Tooltip>
            </CircleMarker>
          );
        })}

        {/* Active point layer (generators / loads / storage / stores) — clickable */}
        {pointActive && rows.map((row, index) => {
          const coords = pointCoords(row, busIndex);
          if (!coords) return null;
          const sel = index === selectedRowIndex;
          const fill = pointFill(activeSheet, row);
          const bus = stringValue(row.bus);
          return (
            <CircleMarker
              key={`pt-${index}`}
              center={coords}
              radius={sel ? 10 : 6}
              pathOptions={{ color: sel ? SELECT_COLOR : '#ffffff', weight: sel ? 3 : 1.5, fillColor: fill, fillOpacity: 0.95 }}
              eventHandlers={{ click: () => onSelectRow(index) }}
            >
              <Tooltip>{stringValue(row.name) || `row ${index + 1}`}{bus ? ` · ${bus}` : ' · (no bus)'}</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {linking && (
        <div className="build-map-linkbar">
          <span>
            Click a bus to set <strong>{linkMode?.field}</strong> of {linkTargetName}
          </span>
          <button type="button" className="ghost-button sm" onClick={() => onCancelLink?.()}>Cancel</button>
        </div>
      )}

      {onAddAtLocation && !menu && !linking && (
        <div className="build-map-hint">
          Right-click the map to add a {singular} here
        </div>
      )}

      {menu && (
        <div
          className="build-map-menu"
          style={{ position: 'fixed', left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
          role="menu"
        >
          {onAddAtLocation && (
            <button
              type="button"
              className="build-map-menu-item"
              onClick={() => { onAddAtLocation(menu.lat, menu.lng); setMenu(null); }}
            >
              Add {singular} here
            </button>
          )}
          {onStartLink && menu.rowIndex != null && pointActive && (
            <button
              type="button"
              className="build-map-menu-item"
              onClick={() => { onStartLink(menu.rowIndex as number, 'bus'); setMenu(null); }}
            >
              Link {menuTargetName} to a bus…
            </button>
          )}
          {onStartLink && menu.rowIndex != null && branchActive && (
            <>
              <button
                type="button"
                className="build-map-menu-item"
                onClick={() => { onStartLink(menu.rowIndex as number, 'bus0'); setMenu(null); }}
              >
                Set bus 0 by clicking…
              </button>
              <button
                type="button"
                className="build-map-menu-item"
                onClick={() => { onStartLink(menu.rowIndex as number, 'bus1'); setMenu(null); }}
              >
                Set bus 1 by clicking…
              </button>
            </>
          )}
          {onDeleteRow && menu.rowIndex != null && (
            <button
              type="button"
              className="build-map-menu-item build-map-menu-item--danger"
              onClick={() => { onDeleteRow(menu.rowIndex as number); setMenu(null); }}
            >
              Delete {menuTargetName}
            </button>
          )}
          <button
            type="button"
            className="build-map-menu-item build-map-menu-item--muted"
            onClick={() => setMenu(null)}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
