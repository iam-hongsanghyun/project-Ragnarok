/**
 * CapacityExpansionCard — shows optimised vs. installed capacity for extendable assets.
 *
 * Rendered inside ResultsDashboard only when expansionResults.length > 0.
 */
import React, { useMemo } from 'react';
import { ExpansionAsset } from 'lib/types';
import { carrierColor } from 'lib/utils/helpers';
import { buildExpansionOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

// ── Horizontal installed-vs-optimised bars (ECharts) ──────────────────────────

interface BarRow {
  name: string;
  carrier: string;
  installed: number;
  optimised: number;
}

function ExpansionBarChart({ rows }: { rows: BarRow[] }) {
  const option = useMemo(() => {
    if (!rows.length) return null;
    return buildExpansionOption(
      rows.map((r) => ({
        name: r.name,
        installed: r.installed,
        optimised: r.optimised,
        color: carrierColor(r.carrier),
      })),
      readChartTheme(),
    );
  }, [rows]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!rows.length) return null;

  return (
    <div
      ref={hostRef}
      className="expansion-bar-chart"
      role="img"
      style={{ width: '100%', maxWidth: 560, height: rows.length * 40 + 44 }}
    />
  );
}

// ── Summary table ─────────────────────────────────────────────────────────────

function ExpansionTable({ assets, currencySymbol = '$' }: { assets: ExpansionAsset[]; currencySymbol?: string }) {
  return (
    <div className="expansion-table-wrap">
      <table className="expansion-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Carrier</th>
            <th>Bus</th>
            <th className="num">Installed</th>
            <th className="num">Optimised</th>
            <th className="num">New build</th>
            <th className="num">Annual CAPEX ({currencySymbol})</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => {
            const unit = a.unit ?? 'MW';
            return (
              <tr key={a.name} className={a.delta_mw > 0 ? 'row-new-build' : ''}>
                <td>{a.name}</td>
                <td>{a.component}</td>
                <td>
                  {a.carrier && (
                    <span className="carrier-dot" style={{ backgroundColor: carrierColor(a.carrier) }} />
                  )}
                  {a.carrier || '—'}
                </td>
                <td>{a.bus}</td>
                <td className="num">{a.p_nom_mw.toLocaleString()} {unit}</td>
                <td className="num">{a.p_nom_opt_mw.toLocaleString()} {unit}</td>
                <td className={`num ${a.delta_mw > 0 ? 'delta-positive' : a.delta_mw < 0 ? 'delta-negative' : ''}`}>
                  {a.delta_mw > 0 ? '+' : ''}{a.delta_mw.toLocaleString()} {unit}
                </td>
                <td className="num">{a.capex_annual > 0 ? `${currencySymbol}${Math.round(a.capex_annual).toLocaleString()}` : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface Props {
  assets: ExpansionAsset[];
  currencySymbol?: string;
}

export function CapacityExpansionCard({ assets, currencySymbol = '$' }: Props) {
  if (!assets.length) return null;

  const totalCapex = assets.reduce((s, a) => s + a.capex_annual, 0);
  const totalNewBuild = assets.reduce((s, a) => s + Math.max(0, a.delta_mw), 0);

  const barRows: BarRow[] = assets.map((a) => ({
    name: a.name,
    carrier: a.carrier,
    installed: a.p_nom_mw,
    optimised: a.p_nom_opt_mw,
  }));

  return (
    <div className="expansion-card">
      <div className="expansion-kpi-row">
        <div className="expansion-kpi">
          <div className="expansion-kpi-label">New builds</div>
          <div className="expansion-kpi-value">{assets.filter((a) => a.delta_mw > 0).length}</div>
          <div className="expansion-kpi-unit">assets</div>
        </div>
        <div className="expansion-kpi">
          <div className="expansion-kpi-label">Total new capacity</div>
          <div className="expansion-kpi-value">{Math.round(totalNewBuild).toLocaleString()}</div>
          <div className="expansion-kpi-unit">MW</div>
        </div>
        <div className="expansion-kpi">
          <div className="expansion-kpi-label">Annual CAPEX</div>
          <div className="expansion-kpi-value">{currencySymbol}{Math.round(totalCapex / 1e6).toLocaleString()}M</div>
          <div className="expansion-kpi-unit">{currencySymbol}/yr</div>
        </div>
      </div>

      <div className="expansion-body">
        <div className="expansion-chart-col">
          <p className="expansion-section-label">Capacity (MW) — installed vs. optimised</p>
          <ExpansionBarChart rows={barRows} />
        </div>
        <div className="expansion-table-col">
          <p className="expansion-section-label">Asset detail</p>
          <ExpansionTable assets={assets} currencySymbol={currencySymbol} />
        </div>
      </div>
    </div>
  );
}
