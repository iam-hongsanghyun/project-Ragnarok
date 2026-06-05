import React, { useMemo } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import { PluginChartSpec } from 'lib/types';
import { chartSpecToMapEdges, chartSpecToMapNodes } from 'lib/plugins/chartSpec';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';

/**
 * Renders a plugin `kind: 'map'` spec: nodes (e.g. region centroids) as
 * circle markers sized by `value`, and edges (e.g. inter-region flows) as
 * lines weighted by `value`. Reuses the app's react-leaflet stack so the
 * plugin only supplies coordinates + magnitudes — the host owns rendering.
 */
export function PluginMap({ spec, title }: { spec: PluginChartSpec; title?: string }) {
  const nodes = useMemo(() => chartSpecToMapNodes(spec), [spec]);
  const edges = useMemo(() => chartSpecToMapEdges(spec, nodes), [spec, nodes]);

  if (nodes.length === 0) {
    return <p className="sg-setting-hint" style={{ margin: 0 }}>Map has no located nodes.</p>;
  }

  const bounds: LatLngBoundsExpression = nodes.map((n) => [n.lat, n.lon]) as [number, number][];

  // Marker radius ∝ sqrt(value) (area-proportional); line weight ∝ |value|.
  const maxNodeVal = Math.max(1, ...nodes.map((n) => Math.abs(n.value)));
  const maxEdgeVal = Math.max(1, ...edges.map((e) => Math.abs(e.value)));
  const radius = (v: number) => 6 + 18 * Math.sqrt(Math.abs(v) / maxNodeVal);
  const weight = (v: number) => 1.5 + 7 * (Math.abs(v) / maxEdgeVal);

  return (
    <section className="chart-card">
      {title && (
        <div className="chart-card-header"><div><h3>{title}</h3></div></div>
      )}
      {spec.description && <p className="sg-setting-hint" style={{ margin: '0 0 6px' }}>{spec.description}</p>}
      <div style={{ height: 360, width: '100%' }}>
        <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" scrollWheelZoom zoomAnimation={false} zoomSnap={0.25} zoomDelta={0.25} wheelPxPerZoomLevel={120}>
          <NoZoomAnimation />
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            subdomains="abcd"
          />
          <FitToBounds bounds={bounds} />
          {edges.map((e) => (
            <Polyline
              key={`${e.from}->${e.to}`}
              positions={e.positions}
              pathOptions={{ color: e.color || '#2563eb', weight: weight(e.value), opacity: 0.7 }}
            >
              <Tooltip sticky>{e.label}</Tooltip>
            </Polyline>
          ))}
          {nodes.map((n) => (
            <CircleMarker
              key={n.id}
              center={[n.lat, n.lon]}
              radius={radius(n.value)}
              pathOptions={{ color: '#ffffff', weight: 2, fillColor: n.color || '#0f766e', fillOpacity: 0.9 }}
            >
              <Tooltip sticky>
                <strong>{n.label}</strong>
                {Number.isFinite(n.value) && n.value !== 0 ? <><br />{n.value}</> : null}
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
    </section>
  );
}
