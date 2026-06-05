import React, { useMemo } from 'react';
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression, divIcon } from 'leaflet';
import { PluginChartSpec } from 'lib/types';
import { chartSpecToMapEdges, chartSpecToMapNodes, MapNodePoint } from 'lib/plugins/chartSpec';
import { carrierColor } from 'lib/utils/helpers';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';

/** Build an inline SVG pie for a node's mix (full circle when one/zero slices). */
function piePieSvg(node: MapNodePoint, r: number): string {
  const size = r * 2;
  const total = node.mix.reduce((s, x) => s + Math.max(x.value, 0), 0);
  if (node.mix.length === 0 || total <= 0) {
    const fill = node.color || '#0f766e';
    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${r}" cy="${r}" r="${r - 1}" fill="${fill}" stroke="#fff" stroke-width="1.5"/></svg>`;
  }
  let a0 = -Math.PI / 2;
  let paths = '';
  for (const s of node.mix) {
    const frac = Math.max(s.value, 0) / total;
    if (frac <= 0) continue;
    const fill = s.color || carrierColor(s.label);
    if (frac >= 0.9999) {
      paths += `<circle cx="${r}" cy="${r}" r="${r}" fill="${fill}" stroke="#fff" stroke-width="0.8"/>`;
      break;
    }
    const a1 = a0 + frac * 2 * Math.PI;
    const x0 = (r + r * Math.cos(a0)).toFixed(2);
    const y0 = (r + r * Math.sin(a0)).toFixed(2);
    const x1 = (r + r * Math.cos(a1)).toFixed(2);
    const y1 = (r + r * Math.sin(a1)).toFixed(2);
    const large = frac > 0.5 ? 1 : 0;
    paths += `<path d="M${r},${r} L${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1} Z" fill="${fill}" stroke="#fff" stroke-width="0.8"/>`;
    a0 = a1;
  }
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${paths}</svg>`;
}

function MixTooltip({ node }: { node: MapNodePoint }) {
  return (
    <Tooltip sticky>
      <strong>{node.label}</strong>
      {node.mix.length > 0 && (
        <>
          <br />
          {node.mix.map((s) => (
            <span key={s.label}>{s.label}: {s.value}<br /></span>
          ))}
        </>
      )}
    </Tooltip>
  );
}

/**
 * Renders a plugin `kind: 'map'` spec: nodes (e.g. region centroids) sized by
 * `value`, drawn as a pie of `mix` (e.g. generation by carrier) when supplied,
 * else a plain circle; edges (e.g. inter-region flows) as lines weighted by
 * `value`. Reuses the app's react-leaflet stack — the plugin supplies data only.
 */
export function PluginMap({ spec, title }: { spec: PluginChartSpec; title?: string }) {
  const nodes = useMemo(() => chartSpecToMapNodes(spec), [spec]);
  const edges = useMemo(() => chartSpecToMapEdges(spec, nodes), [spec, nodes]);

  if (nodes.length === 0) {
    return <p className="sg-setting-hint" style={{ margin: 0 }}>Map has no located nodes.</p>;
  }

  const bounds: LatLngBoundsExpression = nodes.map((n) => [n.lat, n.lon]) as [number, number][];
  const maxNodeVal = Math.max(1, ...nodes.map((n) => Math.abs(n.value)));
  const maxEdgeVal = Math.max(1, ...edges.map((e) => Math.abs(e.value)));
  const radius = (v: number) => 10 + 20 * Math.sqrt(Math.abs(v) / maxNodeVal);
  const weight = (v: number) => 1.5 + 7 * (Math.abs(v) / maxEdgeVal);

  return (
    <section className="chart-card">
      {title && (
        <div className="chart-card-header"><div><h3>{title}</h3></div></div>
      )}
      {spec.description && <p className="sg-setting-hint" style={{ margin: '0 0 6px' }}>{spec.description}</p>}
      <div style={{ height: 360, width: '100%', overflow: 'hidden' }}>
        <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" style={{ height: '100%', width: '100%' }} scrollWheelZoom zoomAnimation={false} zoomSnap={0.25} zoomDelta={0.25} wheelPxPerZoomLevel={120}>
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
          {nodes.map((n) => {
            const r = radius(n.value);
            if (n.mix.length === 0) {
              return (
                <CircleMarker
                  key={n.id}
                  center={[n.lat, n.lon]}
                  radius={r}
                  pathOptions={{ color: '#ffffff', weight: 2, fillColor: n.color || '#0f766e', fillOpacity: 0.9 }}
                >
                  <MixTooltip node={n} />
                </CircleMarker>
              );
            }
            const icon = divIcon({
              html: piePieSvg(n, r),
              className: 'plugin-map-pie',
              iconSize: [r * 2, r * 2],
              iconAnchor: [r, r],
            });
            return (
              <Marker key={n.id} position={[n.lat, n.lon]} icon={icon}>
                <MixTooltip node={n} />
              </Marker>
            );
          })}
        </MapContainer>
      </div>
    </section>
  );
}
