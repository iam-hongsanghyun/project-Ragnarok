import React, { useState } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import { GridRow, WorkbookModel } from '../../shared/types';
import { numberValue, stringValue, resolvedColor } from '../../shared/utils/helpers';
import { FitToBounds } from './FitToBounds';
import { MapLegend } from './MapLegend';

type LayerKey = 'buses' | 'generators' | 'lines' | 'links' | 'transformers';

interface Props {
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
}

/** Return [lat, lng] from a row's own x/y if present, else null. */
function ownCoords(row: GridRow): [number, number] | null {
  const x = row.x;
  const y = row.y;
  if (x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
  const lng = numberValue(x);
  const lat = numberValue(y);
  // Treat 0,0 as valid (prime meridian / equator is a real location)
  return [lat, lng];
}

/** Return [lat, lng] for a component: own coords first, then bus coords + small offset. */
function resolveCoords(
  row: GridRow,
  bus: GridRow | undefined,
  offset = 0.07,
): [number, number] | null {
  const own = ownCoords(row);
  if (own) return own;
  if (!bus) return null;
  const busCoords = ownCoords(bus);
  if (!busCoords) return null;
  return [busCoords[0] + offset, busCoords[1] + offset];
}

export function MapPane({ model, bounds, busIndex }: Props) {
  const [visibleLayers, setVisibleLayers] = useState<Record<LayerKey, boolean>>({
    buses: true, generators: true, lines: true, links: true, transformers: true,
  });
  const toggleLayer = (key: LayerKey) =>
    setVisibleLayers((prev) => ({ ...prev, [key]: !prev[key] }));

  const uniqueCarriers = Array.from(
    new Set(model.generators.map((g) => stringValue(g.carrier)).filter(Boolean)),
  );
  const lineGeometries = model.lines
    .map((line) => {
      const bus0 = busIndex[stringValue(line.bus0)];
      const bus1 = busIndex[stringValue(line.bus1)];
      if (!bus0 || !bus1) return null;
      return {
        name: stringValue(line.name),
        positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][],
        sNom: numberValue(line.s_nom),
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][]; sNom: number }>;

  const linkGeometries = model.links
    .map((link) => {
      const bus0 = busIndex[stringValue(link.bus0)];
      const bus1 = busIndex[stringValue(link.bus1)];
      if (!bus0 || !bus1) return null;
      return {
        name: stringValue(link.name),
        positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][],
        pNom: numberValue(link.p_nom),
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][]; pNom: number }>;

  const transformerGeometries = model.transformers
    .map((transformer) => {
      const bus0 = busIndex[stringValue(transformer.bus0)];
      const bus1 = busIndex[stringValue(transformer.bus1)];
      if (!bus0 || !bus1) return null;
      return {
        name: stringValue(transformer.name),
        positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][],
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <p className="eyebrow">Network</p>
          <h2>Interactive grid map</h2>
        </div>
        <div className="inline-stats">
          <span>{model.buses.length} buses</span>
          <span>{model.lines.length} lines</span>
          <span>{model.links.length} links</span>
          <span>{model.transformers.length} transformers</span>
        </div>
      </div>
      <div className="map-frame" style={{ position: 'relative' }}>
        <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" scrollWheelZoom>
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            subdomains="abcd"
          />
          <FitToBounds bounds={bounds} />
          {visibleLayers.lines && lineGeometries.map((line) => (
            <Polyline key={line.name} positions={line.positions} pathOptions={{ color: '#0f766e', weight: 2, opacity: 0.72 }}>
              <Tooltip>{line.name} · {Math.round(line.sNom)} MVA</Tooltip>
            </Polyline>
          ))}
          {visibleLayers.links && linkGeometries.map((link) => (
            <Polyline key={link.name} positions={link.positions} pathOptions={{ color: '#0f766e', weight: 2, opacity: 0.84, dashArray: '10 8' }}>
              <Tooltip>{link.name} · {Math.round(link.pNom)} MW link</Tooltip>
            </Polyline>
          ))}
          {visibleLayers.transformers && transformerGeometries.map((transformer) => (
            <Polyline key={transformer.name} positions={transformer.positions} pathOptions={{ color: '#f97316', weight: 2, opacity: 0.78, dashArray: '8 6' }}>
              <Tooltip>{transformer.name} · Transformer</Tooltip>
            </Polyline>
          ))}
          {visibleLayers.buses && model.buses.map((bus, index) => {
            const coords = ownCoords(bus);
            if (!coords) return null;
            return (
              <CircleMarker
                key={`${stringValue(bus.name)}-${index}`}
                center={coords}
                radius={8}
                pathOptions={{ color: '#ffffff', weight: 2, fillColor: '#0f766e', fillOpacity: 0.95 }}
              >
                <Tooltip sticky>
                  <strong>{stringValue(bus.name)}</strong><br />
                  {numberValue(bus.v_nom)} kV · {stringValue(bus.carrier)}
                </Tooltip>
              </CircleMarker>
            );
          })}
          {visibleLayers.generators && model.generators.map((generator, index) => {
            const bus = busIndex[stringValue(generator.bus)];
            const coords = resolveCoords(generator, bus, 0.07);
            if (!coords) return null;
            return (
              <CircleMarker
                key={`${stringValue(generator.name)}-${index}`}
                center={coords}
                radius={5}
                pathOptions={{ color: '#ffffff', weight: 1.5, fillColor: resolvedColor(generator.color, generator.carrier), fillOpacity: 0.95 }}
              >
                <Tooltip>{stringValue(generator.name)} · {stringValue(generator.carrier)} · {Math.round(numberValue(generator.p_nom))} MW</Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
        <MapLegend carriers={uniqueCarriers} showLines />
        <div className="map-layer-controls">
          {[
            { key: 'buses',        label: 'Buses' },
            { key: 'generators',   label: 'Generators' },
            { key: 'lines',        label: 'Lines' },
            { key: 'links',        label: 'Links' },
            { key: 'transformers', label: 'Transformers' },
          ].map(({ key, label }) => (
            <label key={key} className="map-layer-toggle">
              <input
                type="checkbox"
                checked={visibleLayers[key as LayerKey]}
                onChange={() => toggleLayer(key as LayerKey)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
