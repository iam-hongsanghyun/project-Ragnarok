/**
 * Region map — the regions of the analysis as polygons (when uploaded) and centroids,
 * coloured by region or cluster.
 *
 * Click a region to focus it: every other region then gets a line from the focus centroid
 * and, in the `correlation` colour mode, a fill coloured by its correlation with the focus
 * region (blue positive, orange negative), so how far a region's weather reaches reads off
 * the map. Selected regions (portfolio candidates) get a ring. A region with neither a
 * centroid nor a polygon cannot be drawn; it stays in the table below.
 */
import React, { useMemo } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import type { RegionRow } from 'lib/api/screening';
import { correlationColor, fmt, fmtPct } from 'lib/screening/screening';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';
import type { MapColorMode } from './ScreeningMap';
import { BASEMAP_ATTRIBUTION, BASEMAP_MAX_NATIVE_ZOOM, BASEMAP_URL } from 'lib/map/basemap';

interface Props {
  regions: RegionRow[];
  /** Colour of each region for the `technology` (= by region) and `cluster` modes. */
  baseColors: Record<string, string>;
  mode: MapColorMode;
  focus: string | null;
  /** Correlation of every other region with the focus region (null = constant series). */
  focusCorr: Record<string, number | null>;
  selected: ReadonlySet<string>;
  clusterOf: Record<string, number>;
  onFocus: (name: string) => void;
}

/** Every [lon, lat] position of a GeoJSON polygon / multipolygon, for the map bounds. */
function positions(geometry: RegionRow['geometry']): Array<[number, number]> {
  if (!geometry) return [];
  const out: Array<[number, number]> = [];
  const walk = (node: unknown): void => {
    if (!Array.isArray(node)) return;
    if (node.length >= 2 && typeof node[0] === 'number' && typeof node[1] === 'number') out.push([node[0], node[1]]);
    else node.forEach(walk);
  };
  walk(geometry.coordinates);
  return out;
}

export function RegionMap({ regions, baseColors, mode, focus, focusCorr, selected, clusterOf, onFocus }: Props) {
  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    const pts: Array<[number, number]> = []; // [lat, lon]
    for (const r of regions) {
      if (r.lat !== null && r.lon !== null) pts.push([r.lat, r.lon]);
      for (const [lon, lat] of positions(r.geometry)) pts.push([lat, lon]);
    }
    if (!pts.length) return null;
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
  }, [regions]);
  const focusRegion = regions.find((r) => r.name === focus) ?? null;
  const showCorr = !!focusRegion;
  const unlocated = regions.filter((r) => r.lat === null && !r.geometry).map((r) => r.name);

  const fillOf = (r: RegionRow): string => {
    const isFocus = r.name === focus;
    return mode === 'correlation' && showCorr && !isFocus ? correlationColor(focusCorr[r.name] ?? null) : (baseColors[r.name] ?? '#6b6962');
  };
  const tip = (r: RegionRow) => (
    <Tooltip sticky>
      <strong>{r.name}</strong>
      {r.nSites ? ` · ${r.nSites} site(s)` : ' · region series'}
      {r.capacityMw ? ` · ${Math.round(r.capacityMw).toLocaleString()} MW` : ''}
      <br />
      mean CF {fmtPct(r.meanCf)}
      {clusterOf[r.name] ? ` · cluster ${clusterOf[r.name]}` : ''}
      {showCorr && r.name !== focus ? (<><br />correlation with {focus}: {fmt(focusCorr[r.name] ?? null, 3)}</>) : null}
    </Tooltip>
  );

  return (
    <div className="scr-map">
      <MapContainer
        center={[36.35, 127.9]} zoom={6} className="leaflet-map" scrollWheelZoom zoomAnimation={false}
        zoomSnap={0.25} zoomDelta={0.25} wheelPxPerZoomLevel={120}
      >
        <NoZoomAnimation />
        <TileLayer url={BASEMAP_URL} attribution={BASEMAP_ATTRIBUTION} maxNativeZoom={BASEMAP_MAX_NATIVE_ZOOM} />
        <FitToBounds bounds={bounds} />

        {regions.filter((r) => r.geometry).map((r) => {
          const isFocus = r.name === focus;
          const fill = fillOf(r);
          return (
            <GeoJSON
              key={`poly-${r.name}-${fill}-${isFocus}-${selected.has(r.name)}`}
              data={{ type: 'Feature', properties: { name: r.name }, geometry: r.geometry } as unknown as GeoJSON.Feature}
              style={{ color: isFocus ? '#1c1b17' : selected.has(r.name) ? '#104281' : '#fcfcfb', weight: isFocus ? 3 : 1.5, fillColor: fill, fillOpacity: 0.45, dashArray: selected.has(r.name) ? '4 3' : undefined }}
              eventHandlers={{ click: () => onFocus(r.name) }}
            >
              {tip(r)}
            </GeoJSON>
          );
        })}

        {focusRegion && focusRegion.lat !== null && focusRegion.lon !== null && regions.filter((r) => r.name !== focusRegion.name && r.lat !== null && r.lon !== null).map((r) => {
          const c = focusCorr[r.name] ?? null;
          return (
            <Polyline
              key={`line-${r.name}`}
              positions={[[focusRegion.lat as number, focusRegion.lon as number], [r.lat as number, r.lon as number]]}
              pathOptions={{ color: correlationColor(c), weight: 1 + 4 * Math.abs(c ?? 0), opacity: c === null ? 0.3 : 0.4 + 0.5 * Math.abs(c) }}
              interactive={false}
            />
          );
        })}

        {regions.filter((r) => r.lat !== null && r.lon !== null).map((r) => {
          const isFocus = r.name === focus;
          // Marker area grows with the number of member sites, so a region of one site is not drawn like a nation.
          const radius = (isFocus ? 3 : 0) + 8 + Math.min(10, Math.sqrt(r.nSites ?? 4) * 2);
          return (
            <React.Fragment key={`c-${r.name}`}>
              {selected.has(r.name) && (
                <CircleMarker center={[r.lat as number, r.lon as number]} radius={radius + 5} pathOptions={{ color: '#104281', weight: 2, fillOpacity: 0, dashArray: '3 3' }} interactive={false} />
              )}
              <CircleMarker
                center={[r.lat as number, r.lon as number]} radius={radius}
                pathOptions={{ color: isFocus ? '#1c1b17' : '#fcfcfb', weight: isFocus ? 3 : 1.5, fillColor: fillOf(r), fillOpacity: 0.95 }}
                eventHandlers={{ click: () => onFocus(r.name) }}
              >
                {tip(r)}
              </CircleMarker>
            </React.Fragment>
          );
        })}
      </MapContainer>
      {unlocated.length > 0 && <p className="scr-hint">Not drawn (no centroid or polygon): {unlocated.join(', ')}.</p>}
    </div>
  );
}
