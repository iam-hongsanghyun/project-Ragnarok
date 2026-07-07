/**
 * AssetRiskMap — leaflet map of a physical-risk portfolio's assets.
 *
 * Ported from climaterisk's `components/ResultsMap.tsx` (risk-colored circle
 * markers sized/colored by EAI) merged with `MapView.tsx`'s facility markers,
 * onto Ragnarok's own map conventions — read from
 * `src/features/map/MapPane.tsx` (tile layer URL/attribution, `NoZoomAnimation`,
 * `FitToBounds`, `.map-frame`/`.leaflet-map`/`.map-legend` classes) rather than
 * climaterisk's maplibre-gl styling. This is its own component (not a MapPane
 * edit) since the data shape (portfolio assets + per-peril EAI) is entirely
 * different from the network model MapPane renders.
 */
import React, { useMemo } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';
import { Asset } from 'lib/physicalRisk/types';
import { AssetTotalEai } from 'lib/physicalRisk/mapAdaptation';

const MIN_RADIUS = 6;
const MAX_RADIUS_ADD = 16;

/** Uniform-color low / mid / high risk bucket, matching climaterisk's ResultsMap thresholds. */
function riskColor(frac: number): string {
  if (frac < 0.33) return '#0f766e';
  if (frac < 0.66) return '#e0a32e';
  return '#dc2626';
}

interface Props {
  assets: Asset[];
  /** Per-asset total EAI (across perils, or for the selected peril), keyed by asset id. */
  eaiByAsset: Map<string, AssetTotalEai> | null;
  /** Which peril's EAI currently drives marker size/color; null = summed across all perils. */
  perilFilter: string | null;
  currency: string;
}

function money(v: number, currency: string): string {
  const symbol = currency === 'USD' ? '$' : `${currency} `;
  return `${symbol}${Math.round(v).toLocaleString()}`;
}

export function AssetRiskMap({ assets, eaiByAsset, perilFilter, currency }: Props) {
  const bounds: LatLngBoundsExpression | null = useMemo(() => {
    if (assets.length === 0) return null;
    return assets.map((a) => [a.lat, a.lon] as [number, number]);
  }, [assets]);

  const eaiOf = (assetId: string): number => {
    if (!eaiByAsset) return 0;
    const entry = eaiByAsset.get(assetId);
    if (!entry) return 0;
    return perilFilter ? (entry.byPeril[perilFilter] ?? 0) : entry.total;
  };
  const maxEai = Math.max(1, ...assets.map((a) => eaiOf(a.id)));
  const hasEai = eaiByAsset !== null;

  return (
    <div className="map-frame" style={{ position: 'relative' }}>
      <MapContainer center={[20, 15]} zoom={2} className="leaflet-map" scrollWheelZoom zoomAnimation={false} zoomSnap={0.25} zoomDelta={0.25} wheelPxPerZoomLevel={120}>
        <NoZoomAnimation />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains="abcd"
        />
        <FitToBounds bounds={bounds} />
        {assets.map((asset) => {
          const eai = eaiOf(asset.id);
          const frac = hasEai ? eai / maxEai : 0;
          const color = hasEai ? riskColor(frac) : '#0f766e';
          const radius = hasEai ? MIN_RADIUS + frac * MAX_RADIUS_ADD : MIN_RADIUS;
          const entry = eaiByAsset?.get(asset.id);
          return (
            <CircleMarker
              key={asset.id}
              center={[asset.lat, asset.lon]}
              radius={radius}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.7, weight: 2 }}
            >
              <Tooltip>
                {asset.name}
                {hasEai ? ` · EAI ${money(eai, currency)}/yr` : ''}
              </Tooltip>
              <Popup>
                <div style={{ fontSize: '0.8rem', lineHeight: 1.5 }}>
                  <strong>{asset.name}</strong>
                  <br />
                  {asset.kind} · {asset.carrier || 'unknown carrier'}
                  <br />
                  Value: {money(asset.value, asset.currency)}
                  {entry && Object.keys(entry.byPeril).length > 0 && (
                    <>
                      <br />
                      <br />
                      <strong>EAI by peril</strong>
                      {Object.entries(entry.byPeril).map(([peril, value]) => (
                        <div key={peril}>
                          {peril.replace(/_/g, ' ')}: {money(value, asset.currency)}/yr
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <div className="map-legend">
        <div className="map-legend-title">{hasEai ? 'Expected annual impact' : 'Assets'}</div>
        {hasEai ? (
          <>
            <div className="map-legend-item">
              <span className="map-legend-dot" style={{ background: '#0f766e' }} />
              <span className="map-legend-label">Low</span>
            </div>
            <div className="map-legend-item">
              <span className="map-legend-dot" style={{ background: '#e0a32e' }} />
              <span className="map-legend-label">Medium</span>
            </div>
            <div className="map-legend-item">
              <span className="map-legend-dot" style={{ background: '#dc2626' }} />
              <span className="map-legend-label">High</span>
            </div>
            <div className="map-legend-item">
              <span className="map-legend-label">Marker size scales with EAI</span>
            </div>
          </>
        ) : (
          <div className="map-legend-item">
            <span className="map-legend-dot" style={{ background: '#0f766e' }} />
            <span className="map-legend-label">Facility (run to size by risk)</span>
          </div>
        )}
      </div>
    </div>
  );
}
