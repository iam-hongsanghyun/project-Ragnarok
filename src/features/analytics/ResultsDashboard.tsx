import React, { useRef, useState } from 'react';
import { RunResults, TimeSeriesRow, TimeSeriesSeries, WorkbookModel } from '../../shared/types';
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
import { CapacityByPeriodCard } from './cards/CapacityByPeriodCard';
import { StochasticScenariosCard } from './cards/StochasticScenariosCard';
import { CarrierAnalysisCard } from './cards/CarrierAnalysisCard';
import { LoadAnalysisCard } from './cards/LoadAnalysisCard';

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
  model: WorkbookModel;
  dispatchRows: TimeSeriesRow[];
  dispatchSeries: TimeSeriesSeries[];
  systemLoadRows: TimeSeriesRow[];
  systemPriceRows: TimeSeriesRow[];
  storageRows: TimeSeriesRow[];
  currencySymbol?: string;
  onExportAll?: () => void;
  selectedPeriod?: number | null;
}

export function ResultsDashboard({
  results,
  model,
  dispatchRows,
  dispatchSeries,
  systemLoadRows,
  systemPriceRows,
  storageRows,
  currencySymbol = '$',
  onExportAll,
  selectedPeriod = null,
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
  const activePathwaySummary = results.pathway?.summaries.find((row) => row.period === selectedPeriod) ?? null;

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

      {results.stochastic?.enabled && (
        <StochasticScenariosCard
          stochastic={results.stochastic}
          currencySymbol={currencySymbol}
        />
      )}

      {results.securityConstrained?.enabled && (
        <div className="stochastic-card" style={{ marginBottom: 16 }}>
          <div className="stochastic-card-header">
            <div>
              <h3>Security-constrained dispatch (N-1)</h3>
              <p>
                Dispatch satisfies the N-1 contingency criterion against{' '}
                <strong>{results.securityConstrained.branchCount}</strong> passive branches.
                The line-loading values shown below are the worst-case loadings consistent
                with any single branch outage.
              </p>
            </div>
          </div>
        </div>
      )}

      {results.pathway?.enabled && (
        <DashboardSection title="Pathway period summary" defaultOpen>
          <div className="kpi-strip">
            <KpiCard
              label="Selected period"
              value={selectedPeriod !== null ? String(selectedPeriod) : '—'}
              unit=""
            />
            <KpiCard
              label="Period dispatch"
              value={Math.round(activePathwaySummary?.totalDispatch ?? 0).toLocaleString()}
              unit="MWh"
            />
            <KpiCard
              label="Period peak load"
              value={Math.round(activePathwaySummary?.peakLoad ?? 0).toLocaleString()}
              unit="MW"
            />
            <KpiCard
              label="Period avg price"
              value={(activePathwaySummary?.averagePrice ?? 0).toFixed(1)}
              unit={`${currencySymbol}/MWh`}
            />
          </div>
          <div style={{ overflowX: 'auto', marginTop: 12 }}>
            <table className="comparison-table">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Snapshots</th>
                  <th>Hours</th>
                  <th>Dispatch</th>
                  <th>Peak load</th>
                  <th>Avg price</th>
                </tr>
              </thead>
              <tbody>
                {results.pathway.summaries.map((row) => (
                  <tr key={row.period} className={row.period === selectedPeriod ? 'is-active' : undefined}>
                    <td>{row.period}</td>
                    <td>{row.snapshotCount}</td>
                    <td>{row.modeledHours.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                    <td>{row.totalDispatch.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td>{row.peakLoad.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td>{row.averagePrice.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DashboardSection>
      )}

      {results.pathway?.enabled && results.pathway.periods.length > 1 && (
        <DashboardSection title="Capacity changes across investment periods" defaultOpen>
          <CapacityByPeriodCard model={model} results={results} />
        </DashboardSection>
      )}

      {/* Dispatch stack */}
      <DashboardSection title="Generation dispatch" defaultOpen onExport={exportDispatch}>
        <div ref={dispatchRef}>
          <InteractiveTimeSeriesCard
            title="Generation dispatch by carrier"
            description="MW"
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

      {/* Carrier performance — capacity factor / curtailment / cost intensity */}
      <DashboardSection title="Carrier performance" defaultOpen={false}>
        <CarrierAnalysisCard results={results} currencySymbol={currencySymbol} />
      </DashboardSection>

      {/* Load analysis — per-bus + system load factor / coincidence */}
      <DashboardSection title="Load analysis" defaultOpen={false}>
        <LoadAnalysisCard results={results} currencySymbol={currencySymbol} />
      </DashboardSection>

      {/* Market analysis row — merit order + CO₂ shadow price */}
      <div className="dashboard-row">
        <DashboardSection title="Merit order (supply stack)" defaultOpen>
          <MeritOrderCard
            entries={results.meritOrder ?? []}
            systemLoad={peakLoad}
            currencySymbol={currencySymbol}
          />
        </DashboardSection>

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
