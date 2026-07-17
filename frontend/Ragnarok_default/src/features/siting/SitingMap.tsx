/**
 * Siting map — the spatial half of the Siting surface.
 *
 * Renders the existing grid (buses as small anchors), the candidate region
 * rectangle (drawn with two clicks: corner, then opposite corner), and — after
 * a scan — the candidate sites colored by mean capacity factor with their
 * connection line to the nearest grid bus. After a solve, sites the expansion
 * LP actually built get a ring sized by built MW, so winners and rejected
 * locations read directly off the map.
 */
import React, { useMemo, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, Rectangle, TileLayer, Tooltip, useMapEvents } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import { GridRow } from 'lib/types';
import { numberValue, stringValue } from 'lib/utils/helpers';
import { SitingCandidate } from 'lib/api/siting';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';

export type Bbox = [number, number, number, number]; // [minLon, minLat, maxLon, maxLat]

interface Props {
  buses: GridRow[];
  bounds: LatLngBoundsExpression | null;
  bbox: Bbox | null;
  onBboxChange: (bbox: Bbox | null) => void;
  candidates: SitingCandidate[] | null;
  /** Built MW per candidate site bus (from expansionResults), post-solve. */
  builtMwBySiteBus: Record<string, number>;
  currencySymbol: string;
}

/** Mean-CF color ramp: muted slate at 0 to saturated green at 0.5+. */
function cfColor(cf: number): string {
  const t = Math.max(0, Math.min(1, cf / 0.5));
  const hue = 150;
  const light = 78 - t * 43; // 78% (pale) → 35% (deep)
  const sat = 25 + t * 55;
  return `hsl(${hue} ${sat}% ${light}%)`;
}

function RegionDraw({ pending, onCorner }: {
  pending: [number, number] | null;
  onCorner: (latlng: [number, number]) => void;
}) {
  useMapEvents({
    click(e) {
      onCorner([e.latlng.lat, e.latlng.lng]);
    },
  });
  if (!pending) return null;
  return (
    <CircleMarker
      center={pending}
      radius={5}
      pathOptions={{ color: '#b45309', fillColor: '#b45309', fillOpacity: 0.9 }}
    >
      <Tooltip permanent direction="top">click the opposite corner</Tooltip>
    </CircleMarker>
  );
}

export function SitingMap({
  buses, bounds, bbox, onBboxChange, candidates, builtMwBySiteBus, currencySymbol,
}: Props) {
  const [pendingCorner, setPendingCorner] = useState<[number, number] | null>(null);

  const busPoints = useMemo(
    () =>
      buses
        .map((b) => {
          const x = b.x;
          const y = b.y;
          if (x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
          return { name: stringValue(b.name), lat: numberValue(y), lon: numberValue(x) };
        })
        .filter(Boolean) as Array<{ name: string; lat: number; lon: number }>,
    [buses],
  );
  const busByName = useMemo(() => {
    const out: Record<string, { lat: number; lon: number }> = {};
    for (const b of busPoints) out[b.name] = b;
    return out;
  }, [busPoints]);

  const handleCorner = (latlng: [number, number]) => {
    if (!pendingCorner) {
      setPendingCorner(latlng);
      return;
    }
    const [lat1, lon1] = pendingCorner;
    const [lat2, lon2] = latlng;
    setPendingCorner(null);
    onBboxChange([
      Math.min(lon1, lon2), Math.min(lat1, lat2),
      Math.max(lon1, lon2), Math.max(lat1, lat2),
    ]);
  };

  const rectBounds: LatLngBoundsExpression | null = bbox
    ? [[bbox[1], bbox[0]], [bbox[3], bbox[2]]]
    : null;
  const maxBuilt = Math.max(1, ...Object.values(builtMwBySiteBus));

  return (
    <div className="map-frame" style={{ position: 'relative', flex: 1, minHeight: 320 }}>
      <MapContainer
        center={[36.35, 127.9]}
        zoom={6}
        className="leaflet-map"
        scrollWheelZoom
        zoomAnimation={false}
        zoomSnap={0.25}
        zoomDelta={0.25}
        wheelPxPerZoomLevel={120}
      >
        <NoZoomAnimation />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
        />
        <FitToBounds bounds={bounds} />
        <RegionDraw pending={pendingCorner} onCorner={handleCorner} />

        {rectBounds && (
          <Rectangle
            bounds={rectBounds}
            pathOptions={{ color: '#b45309', weight: 1.5, fillOpacity: 0.04, dashArray: '6 5' }}
          />
        )}

        {busPoints.map((b) => (
          <CircleMarker
            key={`bus-${b.name}`}
            center={[b.lat, b.lon]}
            radius={3.5}
            pathOptions={{ color: '#475569', fillColor: '#475569', fillOpacity: 0.85, weight: 1 }}
          >
            <Tooltip>{b.name}</Tooltip>
          </CircleMarker>
        ))}

        {(candidates ?? []).map((c) => {
          const grid = busByName[c.gridBus];
          const bestCf = Math.max(0, ...Object.values(c.meanCf));
          const built = builtMwBySiteBus[c.siteBus] ?? 0;
          const cfLines = Object.entries(c.meanCf)
            .map(([tech, cf]) => `${tech} CF ${(cf * 100).toFixed(0)}%`)
            .join(' · ');
          return (
            <React.Fragment key={`cand-${c.id}`}>
              {grid && (
                <Polyline
                  positions={[[c.lat, c.lon], [grid.lat, grid.lon]]}
                  pathOptions={{
                    color: built > 0 ? '#b45309' : '#94a3b8',
                    weight: built > 0 ? 2 : 1,
                    opacity: built > 0 ? 0.9 : 0.5,
                    dashArray: built > 0 ? undefined : '4 5',
                  }}
                />
              )}
              {built > 0 && (
                <CircleMarker
                  center={[c.lat, c.lon]}
                  radius={8 + 10 * Math.sqrt(built / maxBuilt)}
                  pathOptions={{ color: '#b45309', weight: 2, fillOpacity: 0, dashArray: undefined }}
                />
              )}
              <CircleMarker
                center={[c.lat, c.lon]}
                radius={6}
                pathOptions={{
                  color: cfColor(bestCf),
                  fillColor: cfColor(bestCf),
                  fillOpacity: 0.9,
                  weight: 1,
                }}
              >
                <Tooltip>
                  site {c.id} · {cfLines}
                  <br />
                  {c.distanceKm} km to {c.gridBus} · connection {currencySymbol}
                  {Math.round(c.connectionCostPerMw).toLocaleString()}/MW
                  {built > 0 ? (
                    <>
                      <br />
                      built {built.toFixed(1)} MW
                    </>
                  ) : null}
                </Tooltip>
              </CircleMarker>
            </React.Fragment>
          );
        })}
      </MapContainer>
    </div>
  );
}
