/**
 * Co2ShadowCard — CO₂ constraint shadow price display.
 *
 * Shows whether the CO₂ global constraint is binding, its shadow price
 * (dual variable = implied carbon price), and comparison with the
 * explicit carbon price set in the scenario.
 */
import React from 'react';
import { Co2Shadow } from 'lib/types';

interface Props {
  shadow: Co2Shadow;
  currencySymbol?: string;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  binding: { bg: 'rgba(220,38,38,0.08)', text: 'var(--danger)', label: 'Binding' },
  slack:   { bg: 'rgba(22,163,74,0.08)',  text: '#16a34a',      label: 'Not binding (slack)' },
  none:    { bg: 'rgba(100,116,139,0.08)', text: 'var(--muted)', label: 'No constraint' },
};

export function Co2ShadowCard({ shadow, currencySymbol = '$' }: Props) {
  const style = STATUS_STYLES[shadow.status] ?? STATUS_STYLES.none;

  return (
    <div className="co2-shadow-card">
      {/* Status banner */}
      <div className="co2-status-banner" style={{ background: style.bg, borderColor: style.text }}>
        <span className="co2-status-dot" style={{ background: style.text }} />
        <span className="co2-status-label" style={{ color: style.text }}>{style.label}</span>
        {shadow.constraint_name && (
          <span className="co2-constraint-name">({shadow.constraint_name})</span>
        )}
      </div>

      {/* KPI row */}
      <div className="co2-kpi-row">
        <div className="co2-kpi">
          <div className="co2-kpi-label">Shadow price</div>
          <div
            className="co2-kpi-value"
            style={{ color: shadow.status === 'binding' ? 'var(--danger)' : 'var(--muted)' }}
          >
            {shadow.found ? `${currencySymbol}${shadow.shadow_price.toLocaleString()}` : '—'}
          </div>
          <div className="co2-kpi-unit">/tCO₂</div>
        </div>

        <div className="co2-kpi-divider" />

        <div className="co2-kpi">
          <div className="co2-kpi-label">Explicit carbon price</div>
          <div className="co2-kpi-value" style={{ color: 'var(--brand)' }}>
            {shadow.explicit_price > 0 ? `${currencySymbol}${shadow.explicit_price.toLocaleString()}` : '—'}
          </div>
          <div className="co2-kpi-unit">/tCO₂</div>
        </div>

        {shadow.cap_ktco2 != null && (
          <>
            <div className="co2-kpi-divider" />
            <div className="co2-kpi">
              <div className="co2-kpi-label">Emission cap</div>
              <div className="co2-kpi-value">{shadow.cap_ktco2.toLocaleString()}</div>
              <div className="co2-kpi-unit">ktCO₂e</div>
            </div>
          </>
        )}

        {/* Price gap indicator */}
        {shadow.found && shadow.status === 'binding' && shadow.explicit_price > 0 && (
          <>
            <div className="co2-kpi-divider" />
            <div className="co2-kpi">
              <div className="co2-kpi-label">Price gap</div>
              <div
                className="co2-kpi-value"
                style={{ color: shadow.shadow_price > shadow.explicit_price ? 'var(--danger)' : '#16a34a' }}
              >
                {shadow.shadow_price > shadow.explicit_price ? '+' : ''}
                {(shadow.shadow_price - shadow.explicit_price).toFixed(0)}
              </div>
              <div className="co2-kpi-unit">{currencySymbol}/tCO₂ vs explicit</div>
            </div>
          </>
        )}
      </div>

      {/* Explanation */}
      <p className="co2-note">{shadow.note}</p>

      {/* Interpretation guide */}
      {shadow.status === 'binding' && (
        <div className="co2-interpretation">
          <h4>What the shadow price means</h4>
          <ul>
            <li>
              The optimizer had to limit emissions to meet the CO₂ cap.
              The shadow price of <strong>{currencySymbol}{shadow.shadow_price}/tCO₂</strong> is the
              marginal cost of tightening the cap by 1 tonne — i.e. the implied
              carbon price the system is effectively paying.
            </li>
            {shadow.explicit_price > 0 && shadow.shadow_price > shadow.explicit_price && (
              <li>
                Shadow price exceeds the explicit carbon price — the CO₂ cap is
                the <em>binding</em> decarbonisation driver, not the carbon tax.
              </li>
            )}
            {shadow.explicit_price > 0 && shadow.shadow_price <= shadow.explicit_price && (
              <li>
                Shadow price is at or below the explicit carbon price — the carbon
                tax alone would achieve the same emission level; the cap adds no
                extra cost.
              </li>
            )}
          </ul>
        </div>
      )}

      {shadow.status === 'slack' && (
        <div className="co2-interpretation">
          <p>
            Actual emissions are below the cap — the constraint has spare headroom
            and does not influence the dispatch. Increase the carbon price or tighten
            the cap to make it binding.
          </p>
        </div>
      )}
    </div>
  );
}
