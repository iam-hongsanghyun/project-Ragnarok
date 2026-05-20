import React, { useRef, useState } from 'react';
import { PluginAnalyticsEntry, PluginFieldHint, RunResults, TimeSeriesRow, TimeSeriesSeries } from '../../shared/types';
import { numberValue } from '../../shared/utils/helpers';
import { exportChartToExcel } from '../../shared/utils/exportChart';
import { useToast } from '../../shared/components/Toast';
import { InteractiveTimeSeriesCard } from './cards/InteractiveTimeSeriesCard';
import { DonutChart } from './cards/DonutChart';
import { DurationCurveCard } from './cards/DurationCurveCard';
import { CapacityExpansionCard } from './cards/CapacityExpansionCard';
import { MeritOrderCard } from './cards/MeritOrderCard';
import { Co2ShadowCard } from './cards/Co2ShadowCard';
import { EmissionsBreakdownCard } from './cards/EmissionsBreakdownCard';

// ── KPI card ──────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string;
  unit: string;
  green?: boolean;
}

function KpiCard({ label, value, unit, green }: KpiCardProps) {
  return (
    <div className={`kpi-card${green ? ' kpi-card--green' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-unit">{unit}</div>
    </div>
  );
}

// ── Collapsible section with optional export ───────────────────────────────────

interface SectionProps {
  title: string;
  defaultOpen?: boolean;
  onExport?: () => void;
  children: React.ReactNode;
}

function DashboardSection({ title, defaultOpen = true, onExport, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="dashboard-section">
      <div className="dashboard-section-header-row">
        <button
          type="button"
          className="dashboard-section-header"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          <h3>{title}</h3>
          <span style={{ fontSize: '0.75rem', color: 'var(--muted)', userSelect: 'none' }}>
            {open ? '-' : '+'}
          </span>
        </button>
        {onExport && (
          <button
            type="button"
            className="chart-export-btn"
            title="Export data and chart to Excel"
            onClick={(e) => { e.stopPropagation(); onExport(); }}
          >
            Export
          </button>
        )}
      </div>
      {open && <div className="dashboard-section-body">{children}</div>}
    </div>
  );
}

// ── Generic plugin result card ────────────────────────────────────────────────

function formatPluginValue(value: unknown, hint: PluginFieldHint | undefined): string {
  if (value === null || value === undefined) return '—';
  if (hint?.format === 'currency' || hint?.format === 'number') {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

function PluginResultCard({ moduleId, entry }: { moduleId: string; entry: PluginAnalyticsEntry }) {
  const { name, ui, data } = entry;
  if (!data || Object.keys(data).length === 0) return null;

  return (
    <div className="plugin-result-card">
      <p className="plugin-result-card-title">{name}</p>
      <table className="plugin-result-table">
        <tbody>
          {Object.entries(data).map(([key, value]) => {
            const hint = ui?.[key];
            if (hint?.format === 'table' && value && typeof value === 'object' && !Array.isArray(value)) {
              return (
                <tr key={key}>
                  <td className="plugin-result-label">{hint?.label ?? key}</td>
                  <td className="plugin-result-value">
                    <table className="plugin-result-subtable">
                      <tbody>
                        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
                          <tr key={k}>
                            <td>{k}</td>
                            <td>{formatPluginValue(v, hint)}{hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              );
            }
            if (key === 'error') {
              return (
                <tr key={key}>
                  <td colSpan={2} style={{ color: 'var(--danger, #dc2626)', fontSize: '0.82rem' }}>
                    Plugin error: {String(value)}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={key}>
                <td className="plugin-result-label">{hint?.label ?? key}</td>
                <td className="plugin-result-value">
                  {formatPluginValue(value, hint)}
                  {hint?.unit ? <span className="plugin-result-unit"> {hint.unit}</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Cost breakdown color palette ──────────────────────────────────────────────

const COST_COLORS: Record<string, string> = {
  'Fuel cost': '#f97316',
  'Carbon cost': '#16a34a',
  'Load shedding': '#dc2626',
  'Capital cost': '#6366f1',
};

// ── Main dashboard ────────────────────────────────────────────────────────────

interface Props {
  results: RunResults;
  dispatchRows: TimeSeriesRow[];
  dispatchSeries: TimeSeriesSeries[];
  systemLoadRows: TimeSeriesRow[];
  systemPriceRows: TimeSeriesRow[];
  storageRows: TimeSeriesRow[];
  currencySymbol?: string;
  onExportAll?: () => void;
  /** Module IDs that are in 'panel' mode — their analytics are shown in the Plugins tab, not here. */
  panelModeModuleIds?: Set<string>;
}

export function ResultsDashboard({
  results,
  dispatchRows,
  dispatchSeries,
  systemLoadRows,
  systemPriceRows,
  storageRows,
  currencySymbol = '$',
  onExportAll,
  panelModeModuleIds,
}: Props) {
  const { showToast } = useToast();

  // Refs for chart containers (used to grab the SVG for export)
  const dispatchRef = useRef<HTMLDivElement>(null);
  const energyMixRef = useRef<HTMLDivElement>(null);
  const costRef = useRef<HTMLDivElement>(null);
  const loadDurRef = useRef<HTMLDivElement>(null);
  const priceDurRef = useRef<HTMLDivElement>(null);
  const storageRef = useRef<HTMLDivElement>(null);

  // KPI calculations
  const totalDispatch = results.carrierMix.reduce((s, m) => s + m.value, 0);

  const avgPrice = systemPriceRows.length
    ? systemPriceRows.reduce((s, r) => s + numberValue(r['price'] as number | string | undefined), 0) / systemPriceRows.length
    : 0;

  const emissionsSummary = results.summary.find((s) => s.label === 'System emissions');
  const emissionsDisplay = emissionsSummary ? emissionsSummary.value : '—';

  const sortedLoad: number[] = systemLoadRows
    .map((r) => numberValue(r['load'] as number | string | undefined))
    .filter((v) => v > 0)
    .sort((a, b) => b - a);

  const peakLoad = sortedLoad.length > 0 ? sortedLoad[0] : undefined;

  const sortedPrice: number[] = systemPriceRows
    .map((r) => numberValue(r['price'] as number | string | undefined))
    .sort((a, b) => b - a);

  const costMix = results.costBreakdown
    .filter((item) => item.value > 0)
    .map((item) => ({
      label: item.label,
      value: item.value,
      color: COST_COLORS[item.label] ?? '#94a3b8',
    }));

  const storageStateSeries: TimeSeriesSeries[] = [{ key: 'state', label: 'State of charge', color: '#14b8a6' }];
  const hasStorage = storageRows.length > 0 && storageRows.some((r) => numberValue(r['state'] as number | string | undefined) > 0);

  // ── Export helpers ────────────────────────────────────────────────────────

  const doExport = (fn: () => Promise<void> | void, label: string) => {
    Promise.resolve(fn()).then(() => showToast(`Exported ${label}`, 'success')).catch(() => showToast(`Export failed`, 'error'));
  };

  const exportDispatch = () => doExport(() => {
    const carriers = dispatchSeries.map((s) => s.key);
    const headers = ['timestamp', ...carriers];
    const rows = dispatchRows.map((r) => {
      const row: Record<string, unknown> = { timestamp: r.timestamp ?? r.label };
      carriers.forEach((c) => { row[c] = numberValue(r[c] as number | string | undefined); });
      return row;
    });
    return exportChartToExcel('generation_dispatch', headers, rows, dispatchRef.current);
  }, 'Generation Dispatch');

  const exportEnergyMix = () => doExport(() =>
    exportChartToExcel('energy_mix', ['carrier', 'energy_MWh'],
      results.carrierMix.map((m) => ({ carrier: m.label, energy_MWh: m.value })),
      energyMixRef.current), 'Energy Mix');

  const exportCostBreakdown = () => doExport(() =>
    exportChartToExcel('cost_breakdown', ['category', 'cost'],
      results.costBreakdown.map((c) => ({ category: c.label, cost: c.value })),
      costRef.current), 'Cost Breakdown');

  const exportLoadDuration = () => doExport(() =>
    exportChartToExcel('load_duration_curve', ['rank', 'load_MW'],
      sortedLoad.map((v, i) => ({ rank: i + 1, load_MW: v })),
      loadDurRef.current), 'Load Duration Curve');

  const exportPriceDuration = () => doExport(() =>
    exportChartToExcel('price_duration_curve', ['rank', 'price_per_MWh'],
      sortedPrice.map((v, i) => ({ rank: i + 1, price_per_MWh: v })),
      priceDurRef.current), 'Price Duration Curve');

  const exportStorage = () => doExport(() =>
    exportChartToExcel('storage_state_of_charge', ['timestamp', 'state_MWh'],
      storageRows.map((r) => ({
        timestamp: r.timestamp ?? r.label,
        state_MWh: numberValue(r['state'] as number | string | undefined),
      })),
      storageRef.current), 'Storage SoC');

  return (
    <div className="results-dashboard">
      {onExportAll && (
        <div className="dashboard-export-header">
          <span className="dashboard-export-title">Results dashboard</span>
          <button className="ghost-button" onClick={onExportAll} title="Download all results as Excel">
            Export all results
          </button>
        </div>
      )}
      {/* KPI strip */}
      <div className="kpi-strip">
        <KpiCard label="Total dispatch" value={Math.round(totalDispatch).toLocaleString()} unit="MWh" />
        <KpiCard label="Avg price" value={`${avgPrice.toFixed(1)}`} unit={`${currencySymbol}/MWh`} />
        <KpiCard label="Emissions" value={emissionsDisplay} unit="" />
      </div>

      {/* Dispatch stack */}
      <DashboardSection title="Generation dispatch" defaultOpen onExport={exportDispatch}>
        <div ref={dispatchRef}>
          <InteractiveTimeSeriesCard
            title="Generation dispatch by carrier"
            description="Stacked area of generation over all snapshots"
            data={dispatchRows}
            series={dispatchSeries}
            mode="area"
            stacked
          />
        </div>
      </DashboardSection>

      {/* System load time series */}
      {systemLoadRows.length > 0 && (
        <DashboardSection title="System load">
          <InteractiveTimeSeriesCard
            title="Total system load"
            description="Load (MW) over all snapshots"
            data={systemLoadRows}
            series={[{ key: 'load', label: 'Load MW', color: '#f97316' }]}
            mode="area"
            stacked={false}
          />
        </DashboardSection>
      )}

      {/* System marginal price time series */}
      {systemPriceRows.length > 0 && (
        <DashboardSection title="System marginal price">
          <InteractiveTimeSeriesCard
            title="System marginal price"
            description={`${currencySymbol}/MWh over all snapshots`}
            data={systemPriceRows}
            series={[{ key: 'price', label: `SMP ${currencySymbol}/MWh`, color: '#111827' }]}
            mode="line"
            stacked={false}
          />
        </DashboardSection>
      )}

      {/* Energy mix + Cost breakdown side by side */}
      <div className="dashboard-row">
        <DashboardSection title="Energy mix" onExport={exportEnergyMix}>
          <div ref={energyMixRef}>
            <DonutChart data={results.carrierMix} />
          </div>
        </DashboardSection>
        <DashboardSection title="Cost breakdown" onExport={exportCostBreakdown}>
          <div ref={costRef}>
            {costMix.length > 0 ? (
              <DonutChart data={costMix} />
            ) : (
              <p className="empty-text" style={{ padding: '16px' }}>
                No cost data available — set a carbon price or run with marginal costs to see breakdown.
              </p>
            )}
          </div>
        </DashboardSection>
      </div>

      {/* Duration curves side by side */}
      <div className="dashboard-row">
        <DashboardSection title="Load duration curve" onExport={exportLoadDuration}>
          <div ref={loadDurRef}>
            <DurationCurveCard title="Load (MW)" data={sortedLoad} unit="MW" color="#f97316" />
          </div>
        </DashboardSection>
        <DashboardSection title="Price duration curve" onExport={exportPriceDuration}>
          <div ref={priceDurRef}>
            <DurationCurveCard title={`Marginal price (${currencySymbol}/MWh)`} data={sortedPrice} unit={`${currencySymbol}/MWh`} color="#111827" />
          </div>
        </DashboardSection>
      </div>

      {/* Storage SoC */}
      {hasStorage && (
        <DashboardSection title="Storage state of charge" onExport={exportStorage}>
          <div ref={storageRef}>
            <InteractiveTimeSeriesCard
              title="Storage state of charge"
              description="State of charge (MWh) over all snapshots"
              data={storageRows}
              series={storageStateSeries}
              mode="area"
              stacked={false}
            />
          </div>
        </DashboardSection>
      )}

      {/* Capacity expansion */}
      {results.expansionResults && results.expansionResults.length > 0 && (
        <DashboardSection title="Capacity expansion results" defaultOpen>
          <CapacityExpansionCard assets={results.expansionResults} currencySymbol={currencySymbol} />
        </DashboardSection>
      )}

      {/* Emissions breakdown */}
      {results.emissionsBreakdown && (
        results.emissionsBreakdown.byCarrier.length > 0 || results.emissionsBreakdown.byGenerator.length > 0
      ) && (
        <DashboardSection title="Emissions by generator / carrier" defaultOpen>
          <EmissionsBreakdownCard data={results.emissionsBreakdown} />
        </DashboardSection>
      )}

      {/* Market analysis row — merit order + CO₂ shadow price */}
      <div className="dashboard-row">
        <DashboardSection title="Merit order (supply stack)" defaultOpen>
          <MeritOrderCard
            entries={results.meritOrder ?? []}
            systemLoad={peakLoad}
            currencySymbol={currencySymbol}
          />
        </DashboardSection>
        {results.pluginAnalytics && Object.entries(results.pluginAnalytics).some(
          ([id]) => !panelModeModuleIds?.has(id)
        ) && (
          <DashboardSection title="Plugin results" defaultOpen>
            <div className="plugin-result-list">
              {Object.entries(results.pluginAnalytics)
                .filter(([id]) => !panelModeModuleIds?.has(id))
                .map(([moduleId, entry]) => (
                  <PluginResultCard key={moduleId} moduleId={moduleId} entry={entry} />
                ))}
            </div>
          </DashboardSection>
        )}

        <DashboardSection title="CO₂ constraint shadow price">
          <Co2ShadowCard currencySymbol={currencySymbol} shadow={results.co2Shadow ?? {
            found: false,
            constraint_name: null,
            shadow_price: 0,
            explicit_price: 0,
            cap_ktco2: null,
            status: 'none',
            note: 'Run the model to see CO₂ shadow price.',
          }} />
        </DashboardSection>
      </div>

    </div>
  );
}
