/**
 * Country picker + preview overlay map for the Data view.
 *
 * Renders Natural Earth country polygons (fetched once from the backend).
 * Clicking a country selects it (`onSelect`); selecting also propagates
 * outward so the left rail header updates. A second layer renders the
 * GeoJSON `overlay` returned by the active database's preview, so the user
 * sees substations / lines / plant markers without leaving the Data view.
 */
import React, { useEffect, useMemo, useRef } from 'react';
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from 'react-leaflet';
import L, { LatLngBoundsExpression, Layer } from 'leaflet';
import type { Feature, GeoJsonObject } from 'geojson';
import {
  CountryMeta,
  GeoJSONFeature,
  GeoJSONFeatureCollection,
} from '../../shared/api/databases';
import { CountrySearch } from './CountrySearch';

interface Props {
  countriesGeoJSON: GeoJSONFeatureCollection | null;
  countries: CountryMeta[];
  selectedIso: string | null;
  onSelect: (iso: string) => void;
  overlay: GeoJSONFeatureCollection | null;
}

const COUNTRY_STYLE = {
  default: { color: '#0f766e', weight: 0.7, fillColor: '#94a3b8', fillOpacity: 0.18 },
  hover:   { color: '#0f766e', weight: 1.0, fillColor: '#0f766e', fillOpacity: 0.20 },
  active:  { color: '#0b5e57', weight: 1.5, fillColor: '#0f766e', fillOpacity: 0.36 },
} as const;

function isoOfFeature(feature: Feature | undefined | null): string | null {
  const props = (feature?.properties || {}) as Record<string, unknown>;
  for (const key of ['ADM0_A3', 'ISO_A3_EH', 'ISO_A3', 'SOV_A3', 'iso']) {
    const v = props[key];
    if (typeof v === 'string' && v && v !== '-99') return v.toUpperCase();
  }
  return null;
}

function FitToCountry({ bbox }: { bbox: [number, number, number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (!bbox) return;
    const [minLon, minLat, maxLon, maxLat] = bbox;
    const bounds: LatLngBoundsExpression = [[minLat, minLon], [maxLat, maxLon]];
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
  }, [bbox, map]);
  return null;
}

export function WorldMap({
  countriesGeoJSON,
  countries,
  selectedIso,
  onSelect,
  overlay,
}: Props) {
  const layerRef = useRef<Map<string, Layer>>(new Map());

  // Recompute styles whenever the active country changes, without re-rendering
  // the heavy GeoJSON layer.
  useEffect(() => {
    layerRef.current.forEach((layer, iso) => {
      const path = layer as L.Path;
      const active = iso === selectedIso;
      path.setStyle(active ? COUNTRY_STYLE.active : COUNTRY_STYLE.default);
    });
  }, [selectedIso]);

  const onEachCountry = (feature: Feature, layer: Layer) => {
    const iso = isoOfFeature(feature);
    if (!iso) return;
    layerRef.current.set(iso, layer);
    const path = layer as L.Path;
    path.setStyle(iso === selectedIso ? COUNTRY_STYLE.active : COUNTRY_STYLE.default);
    layer.on('mouseover', () => {
      if (iso !== selectedIso) path.setStyle(COUNTRY_STYLE.hover);
    });
    layer.on('mouseout', () => {
      if (iso !== selectedIso) path.setStyle(COUNTRY_STYLE.default);
    });
    layer.on('click', () => onSelect(iso));
    const props = (feature.properties || {}) as Record<string, unknown>;
    const name = (props.ADMIN || props.NAME || iso) as string;
    layer.bindTooltip(`${name} (${iso})`, { sticky: true, direction: 'top' });
  };

  const selectedCountry = useMemo(
    () => countries.find((c) => c.iso === selectedIso) || null,
    [countries, selectedIso],
  );

  const lineFeatures: GeoJSONFeature[] = [];
  const pointFeatures: GeoJSONFeature[] = [];
  if (overlay && overlay.type === 'FeatureCollection') {
    for (const f of overlay.features) {
      if (f.geometry?.type === 'LineString') lineFeatures.push(f);
      else if (f.geometry?.type === 'Point') pointFeatures.push(f);
    }
  }

  return (
    <div className="data-import-map" style={{ position: 'relative', flex: 1, minHeight: 0 }}>
      <MapContainer
        center={[20, 10]}
        zoom={2}
        className="leaflet-map"
        scrollWheelZoom
        zoomAnimation={false}
        zoomSnap={0.25}
        zoomDelta={0.25}
        worldCopyJump
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
        />
        {countriesGeoJSON && (
          <GeoJSON
            data={countriesGeoJSON as GeoJsonObject}
            onEachFeature={onEachCountry}
          />
        )}
        {selectedCountry && <FitToCountry bbox={selectedCountry.bbox} />}
        {lineFeatures.map((f, idx) => {
          const coords = (f.geometry.coordinates as Array<[number, number]>).map(
            ([lon, lat]) => [lat, lon] as [number, number],
          );
          const v = Number((f.properties || {}).voltage_kv ?? 0);
          const color = v >= 380 ? '#9b1c1c' : v >= 220 ? '#c97a14' : '#0b5e57';
          return (
            <Polyline
              key={`line-${idx}`}
              positions={coords}
              pathOptions={{ color, weight: 1.4, opacity: 0.85 }}
            >
              <Tooltip sticky>
                Line — {Math.round(v)} kV
                {(f.properties || {}).length_km != null
                  ? ` · ${Math.round(Number((f.properties || {}).length_km))} km`
                  : ''}
              </Tooltip>
            </Polyline>
          );
        })}
        {pointFeatures.map((f, idx) => {
          const [lon, lat] = f.geometry.coordinates as [number, number];
          const kind = (f.properties || {}).kind as string | undefined;
          const isGen = kind === 'generator';
          const color = isGen ? '#f97316' : '#0f766e';
          const radius = isGen ? 4 : 5;
          return (
            <CircleMarker
              key={`pt-${idx}`}
              center={[lat, lon]}
              radius={radius}
              pathOptions={{
                color: '#ffffff',
                weight: 1.2,
                fillColor: color,
                fillOpacity: 0.95,
              }}
            >
              <Tooltip sticky>
                {(f.properties || {}).name as string || kind || 'feature'}
                {(f.properties || {}).carrier
                  ? ` · ${(f.properties || {}).carrier}`
                  : ''}
                {(f.properties || {}).capacity_mw != null
                  ? ` · ${Math.round(Number((f.properties || {}).capacity_mw))} MW`
                  : ''}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <div className="data-import-map__search">
        <CountrySearch
          countries={countries}
          selectedIso={selectedIso}
          onSelect={onSelect}
        />
      </div>
    </div>
  );
}
