/**
 * P28: the load-analysis, carrier-performance and transition-risk cards print the server's
 * `analysis/{topic}` values and compute nothing; the totals cards print `analysis/totals`.
 * `useAsync` is stubbed so the cards render the response synchronously.
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import type { CompanyStatementResult } from 'lib/types';
import { LoadAnalysisCard } from './LoadAnalysisCard';
import { CarrierAnalysisCard } from './CarrierAnalysisCard';
import { TransitionRiskCard } from './TransitionRiskCard';
import { EmissionsBreakdownCard } from './EmissionsBreakdownCard';
import { CapacityExpansionCard } from './CapacityExpansionCard';
import { MeritOrderCard } from './MeritOrderCard';

const mockAsyncState: { current: { data: unknown; loading: boolean; error: string | null } } = {
  current: { data: null, loading: false, error: null },
};
jest.mock('../../../shared/hooks/useAsync', () => ({ useAsync: () => mockAsyncState.current }));
jest.mock('../../../shared/echarts/useEChart', () => ({ useEChart: () => ({ current: null }) }));

const toMarkup = (el: React.ReactElement): string => staticMarkup(el);
const respond = (data: unknown): void => { mockAsyncState.current = { data, loading: false, error: null }; };

describe('server-driven analysis cards', () => {
  beforeEach(() => { mockAsyncState.current = { data: null, loading: false, error: null }; });

  test('load analysis prints the server ratios and per-bus rows in the given order', () => {
    respond({
      systemPeakMw: 1000, systemEnergyMwh: 5000, systemLoadFactor: 0.625, coincidenceFactor: 0.8,
      buses: [
        { name: 'north', peakMw: 600, energyMwh: 3000, loadFactor: 0.5, share: 0.6 },
        { name: 'south', peakMw: 400, energyMwh: 2000, loadFactor: null, share: 0.4 },
      ],
    });
    const html = toMarkup(<LoadAnalysisCard runName="r" currencySymbol="$" />);
    expect(html).toContain('62.5%');
    expect(html).toContain('80.0%');
    expect(html).toContain('60.0%');
    expect(html.indexOf('north')).toBeLessThan(html.indexOf('south'));
    expect(html).toContain('—'); // south has no load factor
  });

  test('load analysis without a run, while loading, or on error says so', () => {
    expect(toMarkup(<LoadAnalysisCard currencySymbol="$" />)).toContain('needs a stored run');
    mockAsyncState.current = { data: null, loading: true, error: null };
    expect(toMarkup(<LoadAnalysisCard runName="r" currencySymbol="$" />)).toContain('Loading load analysis');
    mockAsyncState.current = { data: null, loading: false, error: 'boom' };
    expect(toMarkup(<LoadAnalysisCard runName="r" currencySymbol="$" />)).toContain('boom');
  });

  test('carrier performance prints rows, the server CF and the totals row', () => {
    respond({
      rows: [{
        carrier: 'wind', color: '#112233', generatorCount: 2, nameplateMw: 300, capacityShare: 0.75, generatedMw: 300,
        energyMwh: 4321, generationShare: 1, capacityFactor: 0.4321, curtailmentMwh: 12,
      }],
      totals: { generatorCount: 2, nameplateMw: 300, generatedMw: 300, energyMwh: 4321, curtailmentMwh: 12 },
    });
    const html = toMarkup(<CarrierAnalysisCard runName="r" currencySymbol="$" />);
    expect(html).toContain('43.2%');
    expect(html).toContain('4,321');
    expect(html).toContain('75.0%');
    expect(html).toContain('Total');
  });

  test('transition risk prints the server summary and every company row', () => {
    respond({
      baseYear: 2030, strandedThreshold: 0, currency: '$',
      trajectory: [{ year: 2030, price: 50 }, { year: 2031, price: 100 }],
      companies: [
        { company: 'Acme', baseNetMargin: 350, emissionsTonnes: 2, strandedYear: 2031, marginErosion: 400,
          byYear: [{ year: 2030, price: 50, carbonCost: 100, netMargin: 350, stranded: false }, { year: 2031, price: 100, carbonCost: 200, netMargin: -50, stranded: true }] },
      ],
      summary: { companyCount: 1, strandedCount: 1, earliestStrandedYear: 2031, totalMarginAtRisk: 400 },
    });
    const statement = { currency: '$', carbonPrice: 50, companies: [] } as unknown as CompanyStatementResult;
    const html = toMarkup(<TransitionRiskCard data={statement} runName="r" />);
    expect(html).toContain('1 / 1');
    expect(html).toContain('2031');
    expect(html).toContain('$400');
    expect(html).toContain('Acme');
  });
});

describe('cards that show a total print the server value', () => {
  test('emissions breakdown: totals and carrier share come from the server', () => {
    const data = {
      byCarrier: [{ carrier: 'gas', emissions_tco2: 300, energy_mwh: 600, intensity_kg_mwh: 500 }],
      byGenerator: [],
    };
    const totals = { totalTco2: 300, totalEnergyMwh: 600, averageIntensityKgPerMwh: 500, byCarrier: [{ carrier: 'gas', sharePct: 42.5 }] };
    const html = toMarkup(<EmissionsBreakdownCard data={data as never} totals={totals} />);
    expect(html).toContain('42.5%');
    expect(html).toContain('500 kg CO₂e/MWh');
    expect(toMarkup(<EmissionsBreakdownCard data={data as never} />)).not.toContain('42.5%');
  });

  test('capacity expansion KPIs are the server sums', () => {
    const asset = { name: 'g', component: 'Generator', carrier: 'gas', bus: 'b', p_nom_mw: 0, p_nom_opt_mw: 5, delta_mw: 5, capital_cost: 1, capex_annual: 100 };
    const html = toMarkup(
      <CapacityExpansionCard assets={[asset as never]} totals={{ newBuildCount: 7, totalCapexAnnual: 3_000_000, totalNewBuildMw: 123 }} />,
    );
    expect(html).toContain('>7<');
    expect(html).toContain('$3M');
    expect(html).toContain('>123<');
  });

  test('merit order shows the server total MW and marginal cost range', () => {
    const entries = [{ name: 'g', carrier: 'gas', p_nom: 10, marginal_cost: 40, color: '#000' }];
    const html = toMarkup(<MeritOrderCard entries={entries as never} totalMw={77} marginalCostRange={{ min: 12, max: 40 }} />);
    expect(html).toContain('77 MW');
    expect(html).toContain('$12 – $40 /MWh');
  });
});
