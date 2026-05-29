/**
 * CapacityExpansionCard — shows optimised vs. installed capacity for extendable assets.
 *
 * Rendered inside ResultsDashboard only when expansionResults.length > 0.
 */
import React from 'react';
import { ExpansionAsset } from '../../../shared/types';
import { carrierColor } from '../../../shared/utils/helpers';

// ── Simple horizontal bar chart ───────────────────────────────────────────────

interface BarRow {
  name: string;
  carrier: string;
  installed: number;
  optimised: number;
}

function ExpansionBarChart({ rows }: { rows: BarRow[] }) {
  if (!rows.length) return null;

  const maxMW = Math.max(1, ...rows.map((r) => r.optimised));
  const barWidth = 340;

  return (
    <svg
      viewBox={`0 0 ${barWidth + 180} ${rows.length * 44 + 28}`}
      className="expansion-bar-chart"
      style={{ width: '100%', maxWidth: 560, display: 'block' }}
    >
      {/* Y-axis labels */}
      {rows.map((row, i) => (
        <g key={row.name} transform={`translate(0,${i * 44 + 10})`}>
          <text x={0} y={14} className="chart-axis-title">
            {row.name.length > 20 ? row.name.slice(0, 18) + '…' : row.name}
          </text>
          {/* installed capacity bar (grey, dimmed) */}
          <rect
            x={0} y={18}
            width={Math.max(2, (row.installed / maxMW) * barWidth)}
            height={8}
            fill="#cbd5e1"
            rx={2}
          />
          {/* optimised capacity bar (carrier colour) */}
          <rect
            x={0} y={28}
            width={Math.max(2, (row.optimised / maxMW) * barWidth)}
            height={10}
            fill={carrierColor(row.carrier)}
            fillOpacity={0.85}
            rx={2}
          />
          {/* value labels */}
          <text
            x={(row.optimised / maxMW) * barWidth + 6}
            y={36}
            className="chart-bar-value"
          >
            {Math.round(row.optimised).toLocaleString()} MW
          </text>
        </g>
      ))}
      {/* Legend */}
      <g transform={`translate(0,${rows.length * 44 + 12})`}>
        <rect x={0} y={0} width={12} height={8} fill="#cbd5e1" rx={2} />
        <text x={16} y={8} className="chart-tick">Installed</text>
        <rect x={68} y={0} width={12} height={8} fill="#6366f1" fillOpacity={0.85} rx={2} />
        <text x={84} y={8} className="chart-tick">Optimised</text>
      </g>
    </svg>
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
