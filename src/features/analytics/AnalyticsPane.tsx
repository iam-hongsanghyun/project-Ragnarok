import React, { useMemo } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { LatLngBoundsExpression } from 'leaflet';
import {
  AnalyticsFocus, AnalyticsSubTab, ChartSectionConfig, GridRow, RunHistoryEntry, RunResults, TimeSeriesRow, TimeSeriesSeries, WorkbookModel,
} from '../../shared/types';
import { EMPTY_METRIC_KEY } from '../../constants';
import { numberValue, stringValue, carrierColor, loadingColor, priceColor, resolvedColor } from '../../shared/utils/helpers';
import { FitToBounds } from '../map/FitToBounds';
import { MapLegend, SmpLegend } from '../map/MapLegend';
import { SummaryCards } from '../../shared/components/SummaryCards';
import { UserDefinedChartCard } from './cards/UserDefinedChartCard';
import { ResultsDashboard } from './ResultsDashboard';
import { MapDetailCard } from './MapDetailCard';

interface Props {
  results: RunResults;
  filename: string;
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  busIndex: Record<string, GridRow>;
  analyticsFocus: AnalyticsFocus;
  setAnalyticsFocus: (focus: AnalyticsFocus) => void;
  chartSections: ChartSectionConfig[];
  setChartSections: React.Dispatch<React.SetStateAction<ChartSectionConfig[]>>;
  dispatchRows: TimeSeriesRow[];
  dispatchSeries: TimeSeriesSeries[];
  systemLoadRows: TimeSeriesRow[];
  systemPriceRows: TimeSeriesRow[];
  storageRows: TimeSeriesRow[];
  runHistory: RunHistoryEntry[];
  subTab: AnalyticsSubTab;
  currencySymbol: string;
  onExportAll?: () => void;
  panelModeModuleIds?: Set<string>;
}

function EmptyAnalytics() {
  return (
    <div className="analytics-empty">
      <h3>Analytics is empty until you run the model</h3>
      <p>
        Open the run dialog, set the number of snapshots and snapshot weight, then execute the case. The dashboard will populate after a successful backend run.
      </p>
    </div>
  );
}

export { EmptyAnalytics };

export function AnalyticsPane({
  results, filename, model, bounds, busIndex,
  analyticsFocus, setAnalyticsFocus,
  chartSections, setChartSections,
  dispatchRows, dispatchSeries,
  systemLoadRows, systemPriceRows, storageRows,
  runHistory,
  subTab,
  currencySymbol,
  onExportAll,
  panelModeModuleIds,
}: Props) {
  const focusTitle =
    analyticsFocus.type === 'system' ? 'System analytics' : analyticsFocus.key;

  const lineGeometries = model.lines
    .map((line) => {
      const bus0 = busIndex[stringValue(line.bus0)];
      const bus1 = busIndex[stringValue(line.bus1)];
      if (!bus0 || !bus1) return null;
      return { name: stringValue(line.name), positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][] };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  const linkGeometries = model.links
    .map((link) => {
      const bus0 = busIndex[stringValue(link.bus0)];
      const bus1 = busIndex[stringValue(link.bus1)];
      if (!bus0 || !bus1) return null;
      return { name: stringValue(link.name), positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][] };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  const transformerGeometries = model.transformers
    .map((transformer) => {
      const bus0 = busIndex[stringValue(transformer.bus0)];
      const bus1 = busIndex[stringValue(transformer.bus1)];
      if (!bus0 || !bus1) return null;
      return { name: stringValue(transformer.name), positions: [[numberValue(bus0.y), numberValue(bus0.x)], [numberValue(bus1.y), numberValue(bus1.x)]] as [number, number][] };
    })
    .filter(Boolean) as Array<{ name: string; positions: [number, number][] }>;

  // Build line loading lookup for QW-2 colour scale
  const loadingMap = Object.fromEntries(
    results.lineLoading.map((l) => [l.label, l.value]),
  );
  const hasLineLoading = results.lineLoading.length > 0;

  // Per-bus average SMP for nodal price colouring
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
    const base = Math.max(4, Math.round(4 + normalized * 13)); // 4–17
    return selected ? base + 4 : base;
  };

  // Unique generator carriers for legend
  const uniqueCarriers = Array.from(
    new Set(model.generators.map((g) => stringValue(g.carrier)).filter(Boolean)),
  );

  const focusSummary =
    analyticsFocus.type === 'generator' ? results.assetDetails.generators[analyticsFocus.key]?.summary || []
    : analyticsFocus.type === 'bus' ? results.assetDetails.buses[analyticsFocus.key]?.summary || []
    : analyticsFocus.type === 'storageUnit' ? results.assetDetails.storageUnits[analyticsFocus.key]?.summary || []
    : analyticsFocus.type === 'store' ? results.assetDetails.stores[analyticsFocus.key]?.summary || []
    : analyticsFocus.type === 'branch' ? results.assetDetails.branches[analyticsFocus.key]?.summary || []
    : results.summary;

  return (
    <div className="pane analytics-pane">
      {/* ── Result sub-tab — predefined charts ───────────────────────── */}
      {subTab === 'Result' && (
        <ResultsDashboard
          results={results}
          dispatchRows={dispatchRows}
          dispatchSeries={dispatchSeries}
          systemLoadRows={systemLoadRows}
          systemPriceRows={systemPriceRows}
          storageRows={storageRows}
          currencySymbol={currencySymbol}
          onExportAll={onExportAll}
          panelModeModuleIds={panelModeModuleIds}
        />
      )}

      {/* ── Analytics sub-tab — map + user-defined charts ───────────── */}
      {subTab === 'Analytics' && <>

      {/* Map section */}
      <section className="chart-card analytics-map-card">
        <div className="chart-card-header">
          <div>
            <h3>Map section</h3>
            <p>Click any asset for KPIs and a preview chart. Generator bubble size scales with capacity.</p>
          </div>
          <div className="focus-chip">
            <span>Focus</span>
            <strong>{focusTitle}</strong>
          </div>
        </div>
        <div className="analytics-map-frame" style={{ position: 'relative' }}>
          <MapContainer center={[36.35, 127.9]} zoom={7} className="leaflet-map" scrollWheelZoom>
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            />
            <FitToBounds bounds={bounds} />
            {lineGeometries.map((line) => {
              const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === line.name;
              const pct = loadingMap[line.name] ?? 0;
              const lineCol = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#2563eb');
              return (
                <Polyline key={line.name} positions={line.positions}
                  pathOptions={{ color: lineCol, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85 }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'branch', key: line.name }) }}>
                  <Tooltip>{line.name} · Line · {pct.toFixed(1)}% loaded</Tooltip>
                </Polyline>
              );
            })}
            {linkGeometries.map((link) => {
              const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === link.name;
              const pct = loadingMap[link.name] ?? 0;
              const linkCol = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#0f766e');
              return (
                <Polyline key={link.name} positions={link.positions}
                  pathOptions={{ color: linkCol, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85, dashArray: sel ? undefined : '10 8' }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'branch', key: link.name }) }}>
                  <Tooltip>{link.name} · Link · {pct.toFixed(1)}% loaded</Tooltip>
                </Polyline>
              );
            })}
            {transformerGeometries.map((transformer) => {
              const sel = analyticsFocus.type === 'branch' && analyticsFocus.key === transformer.name;
              const pct = loadingMap[transformer.name] ?? 0;
              const txCol = sel ? '#f59e0b' : (hasLineLoading ? loadingColor(pct) : '#f97316');
              return (
                <Polyline key={transformer.name} positions={transformer.positions}
                  pathOptions={{ color: txCol, weight: sel ? 8 : 3, opacity: sel ? 1 : 0.85, dashArray: sel ? undefined : '8 6' }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'branch', key: transformer.name }) }}>
                  <Tooltip>{transformer.name} · Transformer · {pct.toFixed(1)}% loaded</Tooltip>
                </Polyline>
              );
            })}
            {model.buses.map((bus, index) => {
              const busName = stringValue(bus.name);
              const sel = analyticsFocus.type === 'bus' && analyticsFocus.key === busName;
              const avgSmp = busAvgSmp[busName];
              const busFill = hasSmp && avgSmp !== undefined
                ? priceColor(avgSmp, smpMin, smpMax)
                : '#2563eb';
              return (
                <CircleMarker key={`${busName}-analytics-${index}`}
                  center={[numberValue(bus.y), numberValue(bus.x)]}
                  radius={sel ? 12 : 8}
                  pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 2, fillColor: busFill, fillOpacity: 0.96 }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'bus', key: busName }) }}>
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
                <CircleMarker key={`${name}-analytics-${index}`}
                  center={[numberValue(bus.y) + 0.07, numberValue(bus.x) + 0.07]}
                  radius={genRadius(pNom, sel)}
                  pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 1.5, fillColor: resolvedColor(generator.color, carrier), fillOpacity: 0.96 }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'generator', key: name }) }}>
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
                <CircleMarker key={`${name}-analytics-storage-${index}`}
                  center={[numberValue(bus.y) - 0.07, numberValue(bus.x) + 0.05]}
                  radius={genRadius(pNom, sel)}
                  pathOptions={{ color: sel ? '#f59e0b' : '#ffffff', weight: sel ? 3 : 1.5, fillColor: '#14b8a6', fillOpacity: 0.96 }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'storageUnit', key: name }) }}>
                  <Tooltip>{name} · Storage Unit · {pNom.toLocaleString(undefined, { maximumFractionDigits: 0 })} MW</Tooltip>
                </CircleMarker>
              );
            })}
            {model.stores.map((store, index) => {
              const bus = busIndex[stringValue(store.bus)];
              if (!bus) return null;
              const name = stringValue(store.name);
              return (
                <CircleMarker key={`${name}-analytics-store-${index}`}
                  center={[numberValue(bus.y) - 0.08, numberValue(bus.x) - 0.06]}
                  radius={analyticsFocus.type === 'store' && analyticsFocus.key === name ? 7 : 4}
                  pathOptions={{ color: '#ffffff', weight: 1.5, fillColor: '#7c3aed', fillOpacity: analyticsFocus.type === 'store' && analyticsFocus.key === name ? 1 : 0.92 }}
                  eventHandlers={{ click: () => setAnalyticsFocus({ type: 'store', key: name }) }}>
                  <Tooltip>{name} · Store</Tooltip>
                </CircleMarker>
              );
            })}
          </MapContainer>
          <MapLegend carriers={uniqueCarriers} showLines={!hasLineLoading} />
          <SmpLegend show={hasSmp} min={smpMin} max={smpMax} />
          <MapDetailCard
            focus={analyticsFocus}
            results={results}
            onClose={() => setAnalyticsFocus({ type: 'system' })}
            currencySymbol={currencySymbol}
          />
        </div>
      </section>

      {/* Charts section */}
      <section className="analytics-charts-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Chart Section</p>
            <h2>User-defined outputs</h2>
          </div>
          <div className="chart-section-actions">
            <button className="ghost-button" onClick={() => setAnalyticsFocus({ type: 'system' })}>Reset Focus</button>
            <button className="ghost-button" onClick={() => {
              setChartSections((current) => [
                ...current,
                { id: Date.now(), focusType: 'system', focusKeys: [], groupBy: 'carrier', metricKey: EMPTY_METRIC_KEY, chartType: 'line', timeframe: 'hourly', startIndex: 0, endIndex: 0, stacked: false },
              ]);
            }}>Add Chart</button>
          </div>
        </div>

        <SummaryCards items={focusSummary} />

        <div className="analytics-grid">
          {chartSections.map((section) => (
            <UserDefinedChartCard
              key={section.id}
              section={section}
              results={results}
              model={model}
              currencySymbol={currencySymbol}
              onChange={(next) => setChartSections((current) => current.map((item) => (item.id === section.id ? next : item)))}
              onClean={() => setChartSections((current) => current.map((item) =>
                item.id === section.id
                  ? { ...item, focusType: 'system', focusKeys: [], groupBy: 'carrier' as const, metricKey: EMPTY_METRIC_KEY, chartType: 'line', timeframe: 'hourly', startIndex: 0, endIndex: 0, stacked: false }
                  : item,
              ))}
              onRemove={() => setChartSections((current) => current.filter((item) => item.id !== section.id))}
            />
          ))}
        </div>

        <div className="narrative-panel">
          <h3>Run notes</h3>
          <ul>
            {results.narrative.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </section>

      </>}
    </div>
  );
}
