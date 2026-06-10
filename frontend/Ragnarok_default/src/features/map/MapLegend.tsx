import React from 'react';
import { carrierColor } from 'lib/utils/helpers';

// ── Generator carrier legend ──────────────────────────────────────────────────

interface MapLegendProps {
  /** Unique carrier names present in the model's generators */
  carriers: string[];
  /** Whether to show the transmission line type legend */
  showLines?: boolean;
}

const LINE_TYPES = [
  { label: 'Line', color: '#0f766e', dash: false },
  { label: 'Link', color: '#0f766e', dash: true },
  { label: 'Transformer', color: '#f97316', dash: true },
];

export function MapLegend({ carriers, showLines = true }: MapLegendProps) {
  if (carriers.length === 0 && !showLines) return null;

  return (
    <div className="map-legend">
      {carriers.length > 0 && (
        <div className="map-legend-section">
          <div className="map-legend-title">Generators</div>
          {carriers.map((c) => (
            <div key={c} className="map-legend-item">
              <span
                className="map-legend-dot"
                style={{ background: carrierColor(c) }}
              />
              <span className="map-legend-label">{c}</span>
            </div>
          ))}
        </div>
      )}
      {showLines && (
        <div className="map-legend-section">
          <div className="map-legend-title">Transmission</div>
          {LINE_TYPES.map(({ label, color, dash }) => (
            <div key={label} className="map-legend-item">
              <svg width="22" height="10" className="map-legend-line-svg">
                <line
                  x1="0" y1="5" x2="22" y2="5"
                  stroke={color}
                  strokeWidth="2.5"
                  strokeDasharray={dash ? '5 3' : undefined}
                />
              </svg>
              <span className="map-legend-label">{label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Loading colour scale legend (Analytics map) ───────────────────────────────

interface LoadingLegendProps {
  show: boolean;
}

export function LoadingLegend({ show }: LoadingLegendProps) {
  if (!show) return null;
  return (
    <div className="map-legend loading-legend">
      <div className="map-legend-title">Line loading</div>
      <div className="loading-gradient-bar" />
      <div className="loading-gradient-labels">
        <span>0%</span>
        <span>50%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

// ── Nodal SMP colour scale legend ─────────────────────────────────────────────

interface SmpLegendProps {
  show: boolean;
  min: number;
  max: number;
  /** Currency unit symbol from Settings (defaults to $ for back-compat). */
  currencySymbol?: string;
}

export function SmpLegend({ show, min, max, currencySymbol = '$' }: SmpLegendProps) {
  if (!show) return null;
  return (
    <div className="map-legend loading-legend">
      <div className="map-legend-title">Avg SMP ({currencySymbol}/MWh)</div>
      <div className="smp-gradient-bar" />
      <div className="loading-gradient-labels">
        <span>{min.toFixed(0)}</span>
        <span>{((min + max) / 2).toFixed(0)}</span>
        <span>{max.toFixed(0)}</span>
      </div>
    </div>
  );
}
