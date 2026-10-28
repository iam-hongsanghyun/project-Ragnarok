/**
 * Screening map — the dataset's sites coloured by technology or cluster.
 *
 * Click a site to focus it: every other site is then drawn with a line (and a
 * fill) coloured by its correlation with the focus site, so the spatial decay
 * of correlation reads straight off the map. Selected sites (the portfolio
 * candidates) get a ring.
 */
import React, { useMemo } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import type { ScreeningSite } from 'lib/api/screening';
import { correlationColor, fmt, fmtPct } from 'lib/screening/screening';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';

export type MapColorMode = 'technology' | 'cluster' | 'correlation';

interface Props {
  sites: ScreeningSite[];
  /** Colour of each site for the `technology` / `cluster` modes. */
  baseColors: Record<string, string>;
  mode: MapColorMode;
  focus: string | null;
  /** Correlation of every other site with the focus site (null = constant series). */
  focusCorr: Record<string, number | null>;
  selected: ReadonlySet<string>;
  clusterOf: Record<string, number>;
  onFocus: (name: string) => void;
}

export function ScreeningMap({ sites, baseColors, mode, focus, focusCorr, selected, clusterOf, onFocus }: Props) {
  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    if (!sites.length) return null;
    const lats = sites.map((s) => s.lat);
    const lons = sites.map((s) => s.lon);
    return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
  }, [sites]);
  const focusSite = sites.find((s) => s.name === focus) ?? null;
  const showCorr = !!focusSite;

  return (
    <div className="scr-map">
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

        {showCorr && focusSite && sites.filter((s) => s.name !== focusSite.name).map((s) => {
          const r = focusCorr[s.name] ?? null;
          return (
            <Polyline
              key={`line-${s.name}`}
              positions={[[focusSite.lat, focusSite.lon], [s.lat, s.lon]]}
              pathOptions={{
                color: correlationColor(r),
                weight: 1 + 4 * Math.abs(r ?? 0),
                opacity: r === null ? 0.3 : 0.4 + 0.5 * Math.abs(r),
              }}
            />
          );
        })}

        {sites.map((s) => {
          const r = focusCorr[s.name];
          const isFocus = s.name === focus;
          const fill = mode === 'correlation' && showCorr && !isFocus
            ? correlationColor(r ?? null)
            : (baseColors[s.name] ?? '#6b6962');
          return (
            <React.Fragment key={`site-${s.name}`}>
              {selected.has(s.name) && (
                <CircleMarker
                  center={[s.lat, s.lon]}
                  radius={13}
                  pathOptions={{ color: '#104281', weight: 2, fillOpacity: 0, dashArray: '3 3' }}
                  interactive={false}
                />
              )}
              <CircleMarker
                center={[s.lat, s.lon]}
                radius={isFocus ? 10 : 7}
                pathOptions={{ color: isFocus ? '#1c1b17' : '#fcfcfb', weight: isFocus ? 3 : 1.5, fillColor: fill, fillOpacity: 0.95 }}
                eventHandlers={{ click: () => onFocus(s.name) }}
              >
                <Tooltip>
                  <strong>{s.name}</strong> · {s.technology}
                  {s.region ? ` · ${s.region}` : ''}
                  <br />
                  mean CF {fmtPct(s.meanCf ?? null)}
                  {clusterOf[s.name] ? ` · cluster ${clusterOf[s.name]}` : ''}
                  {showCorr && !isFocus ? (
                    <>
                      <br />
                      correlation with {focus}: {fmt(r ?? null, 3)}
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
