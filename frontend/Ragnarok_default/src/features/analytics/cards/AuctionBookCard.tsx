/**
 * AuctionBookCard — the bid stack at the representative (highest-price) hour.
 *
 * Draws the supply curve as an ascending step function of the sorted offers
 * (width = capacity, height = bid), marks the clearing point, and overlays the
 * demand: a vertical firm-demand line, plus (two-sided) the elastic block at
 * its willingness-to-pay. Shows exactly how the price is set that hour.
 */
import React from 'react';
import { MarketSimulationResult } from 'lib/types';

interface Props {
  data: MarketSimulationResult;
}

const CARRIER_COLORS: Record<string, string> = {
  wind: '#4e79a7', solar: '#edc948', gas: '#e15759', coal: '#59514f',
  nuclear: '#b07aa1', hydro: '#76b7b2', oil: '#9c755f', biomass: '#59a14f',
};
const colorFor = (c: string, i: number) => CARRIER_COLORS[c?.toLowerCase()] ?? ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948'][i % 6];

export function AuctionBookCard({ data }: Props) {
  const cur = data.currency || '';
  const book = data.auctionBook;
  if (!book || !book.offers || book.offers.length === 0) {
    return <p className="dashboard-cell-missing">No auction book for this run.</p>;
  }
  const offers = book.offers;

  const W = 520, H = 280, pad = { l: 52, r: 14, t: 16, b: 40 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
  const maxMW = offers[offers.length - 1].cumulativeMW;
  const wtp = book.wtp ?? 0;
  const maxPrice = Math.max(book.clearingPrice, wtp, ...offers.map((o) => o.bid)) * 1.12 || 1;
  const totalDemand = book.firmDemandMW + book.elasticDemandMW;

  const sx = (mw: number) => pad.l + (mw / (maxMW || 1)) * plotW;
  const sy = (p: number) => pad.t + plotH - (p / maxPrice) * plotH;

  return (
    <div className="econ-card">
      <div style={{ overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="auction-book" role="img" aria-label="Auction bid stack">
          {/* axes */}
          <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + plotH} className="ab-axis" />
          <line x1={pad.l} y1={pad.t + plotH} x2={W - pad.r} y2={pad.t + plotH} className="ab-axis" />
          <text x={4} y={pad.t + 8} className="ab-label">{cur}/MWh</text>
          <text x={W - pad.r} y={H - 6} className="ab-label" textAnchor="end">cumulative MW</text>

          {/* supply offer blocks (width = capacity, height = bid) */}
          {offers.map((o, i) => {
            const x0 = sx(o.cumulativeMW - o.capacityMW);
            const x1 = sx(o.cumulativeMW);
            const y = sy(o.bid);
            const dispW = o.capacityMW > 0 ? (o.dispatchedMW / o.capacityMW) : 0;
            return (
              <g key={o.name}>
                {/* full offer (light) */}
                <rect x={x0} y={y} width={Math.max(0, x1 - x0)} height={pad.t + plotH - y}
                  fill={colorFor(o.carrier, i)} opacity={0.25} stroke="var(--surface)" strokeWidth={0.5} />
                {/* dispatched portion (solid) */}
                {dispW > 0 && (
                  <rect x={x0} y={y} width={Math.max(0, (x1 - x0) * dispW)} height={pad.t + plotH - y}
                    fill={colorFor(o.carrier, i)} opacity={o.marginal ? 0.95 : 0.7} />
                )}
              </g>
            );
          })}

          {/* clearing price line */}
          <line x1={pad.l} y1={sy(book.clearingPrice)} x2={W - pad.r} y2={sy(book.clearingPrice)} className="ab-clearing" />
          <text x={W - pad.r} y={sy(book.clearingPrice) - 4} className="ab-clearing-label" textAnchor="end">
            clears {cur}{Math.round(book.clearingPrice)}
          </text>

          {/* firm-demand vertical line */}
          <line x1={sx(book.firmDemandMW)} y1={pad.t} x2={sx(book.firmDemandMW)} y2={pad.t + plotH} className="ab-demand" />
          <text x={sx(book.firmDemandMW)} y={pad.t + plotH + 14} className="ab-label" textAnchor="middle">firm {Math.round(book.firmDemandMW)}</text>

          {/* two-sided: elastic demand block at its WTP, from firm→total demand */}
          {data.clearingModel === 'twoSided' && book.elasticDemandMW > 0 && (
            <>
              <line x1={sx(book.firmDemandMW)} y1={sy(wtp)} x2={sx(totalDemand)} y2={sy(wtp)} className="ab-wtp" />
              <line x1={sx(totalDemand)} y1={sy(wtp)} x2={sx(totalDemand)} y2={pad.t + plotH} className="ab-wtp" />
              <text x={sx(totalDemand)} y={sy(wtp) - 4} className="ab-label" textAnchor="end">WTP {cur}{Math.round(wtp)}</text>
            </>
          )}

          {/* clearing point marker */}
          <circle cx={sx(book.clearedMW)} cy={sy(book.clearingPrice)} r={4.5} className="ab-point" />
        </svg>
      </div>
      <p className="econ-footnote">
        Bid stack at {book.hourLabel} (the highest-price hour). Bars = supply offers by ascending bid (solid = dispatched);
        the clearing price is set where supply meets demand{data.clearingModel === 'twoSided' ? ', with elastic demand bidding its WTP' : ''}.
        {book.curtailedMW > 0 && ` ${Math.round(book.curtailedMW)} MW of elastic demand was priced out.`}
        {book.unservedMW > 0 && ` ${Math.round(book.unservedMW)} MW of firm demand was unserved (VOLL).`}
      </p>
    </div>
  );
}
