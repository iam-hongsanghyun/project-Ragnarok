/**
 * Analytics map card — Bloomberg dashboard cell that renders the
 * network with results overlays (line loadings, per-bus average SMP,
 * generator size by p_nom) and propagates click events as analytics
 * focus changes.
 *
 * Adapted from the pre-rebuild map JSX that used to live inline in
 * `AnalyticsPane.tsx`. Self-contained so the dashboard can mount it
 * via its `renderCard` callback.
 */
import React, { useEffect, useMemo } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus,
  GridRow,
  RunResults,
  WorkbookModel,
} from 'lib/types';
import {
  loadingColor,
  numberValue,
  priceColor,
  resolvedColor,
  stringValue,
} from 'lib/utils/helpers';
import { FitToBounds } from '../map/FitToBounds';
import { NoZoomAnimation } from '../map/NoZoomAnimation';
import { MapLegend, SmpLegend } from '../map/MapLegend';
import { MapDetailCard } from './MapDetailCard';

/**
 * Leaflet measures its container once on mount. Inside a dashboard cell the
 * cell often resolves its flex/auto height *after* the map mounts, leaving the
 * map blank until told to remeasure. This observes the container and calls
 * invalidateSize() on every resize (plus once shortly after mount).
 */
function InvalidateOnResize() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    // Skip while the container has no area (collapsed/hidden panel): invalidating
    // then corrupts Leaflet's pane positions and crashes a later zoom transition
    // (`Cannot read properties of undefined (reading '_leaflet_pos')`).
    const safeInvalidate = () => {
      if (el.offsetWidth === 0 || el.offsetHeight === 0) return;
      try { map.invalidateSize(); } catch { /* map removed during resize */ }
    };
    const ro = new ResizeObserver(safeInvalidate);
    ro.observe(el);
    const t = window.setTimeout(safeInvalidate, 0);
    return () => { ro.disconnect(); window.clearTimeout(t); };
  }, [map]);
  return null;
}

interface Props {
  results: RunResults;
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
  analyticsFocus: AnalyticsFocus;
  onFocusChange: (focus: AnalyticsFocus) => void;
  currencySymbol: string;
}

export function AnalyticsMapCard({
  results, model, bounds, busIndex,
  analyticsFocus, onFocusChange,
  currencySymbol,
}: Props) {
  // ── Geometry pre-builds ──────────────────────────────────────────────────
  const lineGeometries = model.lines
    .map((line) => {
      const b0 = busIndex[stringValue(line.bus0)];
      const b1 = busIndex[stringValue(line.bus1)];
      if (!b0 || !b1) return null;
      return {
        name: stringValue(line.name),
        positions: [[numberValue(b0.y), numberValue(b0.x)], [numberValue(b1.y), numberValue(b1.x)]] as [number, number][],
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  const linkGeometries = model.links
    .map((link) => {
      const b0 = busIndex[stringValue(link.bus0)];
      const b1 = busIndex[stringValue(link.bus1)];
      if (!b0 || !b1) return null;
      return {
        name: stringValue(link.name),
        positions: [[numberValue(b0.y), numberValue(b0.x)], [numberValue(b1.y), numberValue(b1.x)]] as [number, number][],
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  const transformerGeometries = model.transformers
    .map((tx) => {
      const b0 = busIndex[stringValue(tx.bus0)];
      const b1 = busIndex[stringValue(tx.bus1)];
      if (!b0 || !b1) return null;
      return {
        name: stringValue(tx.name),
        positions: [[numberValue(b0.y), numberValue(b0.x)], [numberValue(b1.y), numberValue(b1.x)]] as [number, number][],
      };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  // ── Loading + SMP lookups ───────────────────────────────────────────────
  const loadingMap = useMemo(
    () => Object.fromEntries(results.lineLoading.map((l) => [l.label, l.value])),
    [results.lineLoading],
  );
  const hasLineLoading = results.lineLoading.length > 0;

  const busAvgSmp = useMemo(() => {
    const out: Record<string, number> = {};
    for (const [name, detail] of Object.entries(results.assetDetails.buses)) {
      const pts = detail.netSeries;
      if (pts.length === 0) continue;
      out[name] = pts.reduce((s, p) => s + p.smp, 0) / pts.length;
    }
    return out;
  }, [results.assetDetails.buses]);

  const smpValues = Object.values(busAvgSmp);
  const smpMin = smpValues.length > 0 ? Math.min(...smpValues) : 0;
  const smpMax = smpValues.length > 0 ? Math.max(...smpValues) : 1;
  const hasSmp = smpValues.some((v) => Math.abs(v) > 0.01);

  // Generator p_nom scaling — sqrt so large/small coexist
  const maxPnom = useMemo(() => {
    const vals = model.generators.map((g) => numberValue(g.p_nom)).filter((v) => v > 0);
    return vals.length > 0 ? Math.max(...vals) : 1;
  }, [model.generators]);

  const genRadius = (pNom: number, selected: boolean): number => {
    const normalized = Math.sqrt(Math.max(pNom, 0) / maxPnom);
    const base = Math.max(4, Math.round(4 + normalized * 13));
    return selected ? base + 4 : base;
  };

  const uniqueCarriers = Array.from(
    new Set(model.generators.map((g) => stringValue(g.carrier)).filter(Boolean)),
  );

  return (
    <div className="analytics-map-card-inner" style={{ position: 'relative', width: '100%', height: '100%' }}>
      <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" scrollWheelZoom zoomAnimation={false} zoomSnap={0.25} zoomDelta={0.25} wheelPxPerZoomLevel={120}>
        <NoZoomAnimation />
        <InvalidateOnResize />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        <FitToBounds bounds={bounds} />

        {lineGeometries.map((line) => {
          const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === line.name;
          const pct = loadingMap[line.name] ?? 0;
          const col = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#0f766e');
          return (
            <Polyline
              key={line.name}
              positions={line.positions}
              pathOptions={{ color: col, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85 }}
              eventHandlers={{ click: () => onFocusChange({ type: 'branch', key: line.name }) }}
            >
              <Tooltip>{line.name} · Line · {pct.toFixed(1)}% loaded</Tooltip>
            </Polyline>
          );
        })}

        {linkGeometries.map((link) => {
          const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === link.name;
          const pct = loadingMap[link.name] ?? 0;
          const col = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#0f766e');
          return (
            <Polyline
              key={link.name}
              positions={link.positions}
              pathOptions={{ color: col, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85, dashArray: sel ? undefined : '10 8' }}
              eventHandlers={{ click: () => onFocusChange({ type: 'branch', key: link.name }) }}
            >
              <Tooltip>{link.name} · Link · {pct.toFixed(1)}% loaded</Tooltip>
            </Polyline>
          );
        })}

        {transformerGeometries.map((tx) => {
          const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === tx.name;
          const pct = loadingMap[tx.name] ?? 0;
          const col = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#f97316');
          return (
            <Polyline
              key={tx.name}
              positions={tx.positions}
              pathOptions={{ color: col, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85, dashArray: sel ? undefined : '8 6' }}
              eventHandlers={{ click: () => onFocusChange({ type: 'branch', key: tx.name }) }}
            >
              <Tooltip>{tx.name} · Transformer · {pct.toFixed(1)}% loaded</Tooltip>
            </Polyline>
          );
        })}

        {model.buses.map((bus, index) => {
          const busName = stringValue(bus.name);
          const sel = analyticsFocus.type === 'bus' && analyticsFocus.key === busName;
          const avgSmp = busAvgSmp[busName];
          const fill = hasSmp && avgSmp !== undefined
            ? priceColor(avgSmp, smpMin, smpMax)
            : '#0f766e';
          return (
            <CircleMarker
              key={`${busName}-am-${index}`}
              center={[numberValue(bus.y), numberValue(bus.x)]}
              radius={sel ? 12 : 8}
              pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 2, fillColor: fill, fillOpacity: 0.96 }}
              eventHandlers={{ click: () => onFocusChange({ type: 'bus', key: busName }) }}
            >
              <Tooltip>{busName} · Bus{hasSmp && avgSmp !== undefined ? ` · Avg SMP ${avgSmp.toFixed(1)} ${currencySymbol}/MWh` : ''}</Tooltip>
            </CircleMarker>
          );
        })}

        {model.generators.map((generator, index) => {
          const bus = busIndex[stringValue(generator.bus)];
          if (!bus) return null;
          const name = stringValue(generator.name);
          const sel = analyticsFocus.type === 'generator' && analyticsFocus.key === name;
          const pNom = numberValue(generator.p_nom);
          const carrier = stringValue(generator.carrier);
          return (
            <CircleMarker
              key={`${name}-am-${index}`}
              center={[numberValue(bus.y) + 0.07, numberValue(bus.x) + 0.07]}
              radius={genRadius(pNom, sel)}
              pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 1.5, fillColor: resolvedColor(generator.color, carrier), fillOpacity: 0.96 }}
              eventHandlers={{ click: () => onFocusChange({ type: 'generator', key: name }) }}
            >
              <Tooltip>{name} · {carrier} · {pNom.toLocaleString(undefined, { maximumFractionDigits: 0 })} MW</Tooltip>
            </CircleMarker>
          );
        })}

        {model.storage_units.map((unit, index) => {
          const bus = busIndex[stringValue(unit.bus)];
          if (!bus) return null;
          const name = stringValue(unit.name);
          const sel = analyticsFocus.type === 'storageUnit' && analyticsFocus.key === name;
          const pNom = numberValue(unit.p_nom);
          return (
            <CircleMarker
              key={`${name}-am-storage-${index}`}
              center={[numberValue(bus.y) - 0.07, numberValue(bus.x) + 0.05]}
              radius={genRadius(pNom, sel)}
              pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 1.5, fillColor: '#14b8a6', fillOpacity: 0.96 }}
              eventHandlers={{ click: () => onFocusChange({ type: 'storageUnit', key: name }) }}
            >
              <Tooltip>{name} · Storage Unit · {pNom.toLocaleString(undefined, { maximumFractionDigits: 0 })} MW</Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <MapLegend carriers={uniqueCarriers} showLines={!hasLineLoading} />
      <SmpLegend show={hasSmp} min={smpMin} max={smpMax} currencySymbol={currencySymbol} />
      <MapDetailCard
        focus={analyticsFocus}
        results={results}
        onClose={() => onFocusChange({ type: 'system' })}
        currencySymbol={currencySymbol}
      />
    </div>
  );
}
