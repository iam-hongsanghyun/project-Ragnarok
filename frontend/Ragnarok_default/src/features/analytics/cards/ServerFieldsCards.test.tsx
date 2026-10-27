/**
 * The cards render the server's P28 fields rather than recomputing them: carrier-table CF
 * (generatorEconomics.byCarrier[].capacityFactor), the expansion columns, and the
 * Unassigned emissions row so owners + unassigned = system total.
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { describe, test, expect, jest } from '@jest/globals';
import type { CompanyBreakdownResult, CompanyStatementResult, ExpansionAsset, RunResults } from 'lib/types';
import { CompanyBreakdownCard } from './CompanyBreakdownCard';
import { CompanyStatementCard } from './CompanyStatementCard';
import { CapacityExpansionCard } from './CapacityExpansionCard';
import { CarrierAnalysisCard } from './CarrierAnalysisCard';

const toMarkup = (el: React.ReactElement): string => staticMarkup(el);

// echarts ships ESM that jest does not transform; the bar chart is irrelevant here.
jest.mock('../../../shared/echarts/useEChart', () => ({ useEChart: () => ({ current: null }) }));

describe('company views show unassigned emissions', () => {
  test('breakdown: Unassigned row and a system total = owners + unassigned (kt)', () => {
    const data = {
      ownerColumn: 'owner', currency: '$', untaggedCount: 2, unassignedEmissionsTonnes: 3000,
      companies: [{ company: 'A', capacityMW: 10, energyMWh: 1000, revenue: null, emissionsTonnes: 7000, generatorCount: 1, storageCount: 0 }],
    } as CompanyBreakdownResult;
    const html = toMarkup(<CompanyBreakdownCard data={data} />);
    expect(html).toContain('Unassigned');
    expect(html).toContain('System total');
    expect(html).toContain('>10<'); // 7 kt + 3 kt
  });
  test('statement: unassigned and system emissions rows', () => {
    const zero = { revenue: 0, energyMWh: 0, carbonCost: 0, fuelVomCost: 0, variableCost: 0, grossMargin: 0, capexAnnual: 0, ebit: 0, interest: 0, netMargin: 0 };
    const data = {
      ownerColumn: 'owner', currency: '$', carbonPrice: 50, unassignedEmissionsTonnes: 250,
      companies: [{ company: 'A', ...zero, emissionsTonnes: 750 }],
      totals: { ...zero, emissionsTonnes: 750 },
    } as CompanyStatementResult;
    const html = toMarkup(<CompanyStatementCard data={data} />);
    expect(html).toContain('Unassigned emissions');
    expect(html).toContain('System emissions');
    expect(html).toContain('1,000');
  });
});

describe('expansion and carrier cards read server values', () => {
  test('expansion table adds the n.statistics columns only when present', () => {
    const base = { name: 'g', component: 'Generator', carrier: 'gas', bus: 'b', p_nom_mw: 0, p_nom_opt_mw: 5, delta_mw: 5, capital_cost: 1, capex_annual: 100 } as ExpansionAsset;
    expect(toMarkup(<CapacityExpansionCard assets={[base]} />)).not.toContain('Expanded CAPEX');
    const html = toMarkup(
      <CapacityExpansionCard assets={[{ ...base, capex_expanded: 60, capex_installed: 40, overnight_total: 900, fom_total: 7 }]} />,
    );
    for (const label of ['Expanded CAPEX', 'Installed CAPEX', 'Overnight cost', 'Fixed O&amp;M']) expect(html).toContain(label);
    expect(html).toContain('$900');
  });
  test('carrier CF is the server value, not energy / (nameplate x hours)', () => {
    const results = {
      runMeta: { snapshotCount: 10, snapshotWeight: 1, modeledHours: 10, storeWeight: 1 },
      outputs: { static: { generators: { g1: { p_nom_opt: 100 } } }, series: {} },
      generatorEnergy: [{ name: 'g1', value: 500 }],
      generatorEconomics: { byCarrier: [{ carrier: 'wind', capacityFactor: 0.4321 }] },
    } as unknown as RunResults;
    const model = { generators: [{ name: 'g1', carrier: 'wind', p_nom: 100 }] };
    const html = toMarkup(<CarrierAnalysisCard results={results} currencySymbol="$" model={model as never} />);
    expect(html).toContain('43.2%');   // 500 / (100 x 10) would be 50.0%
    expect(html).not.toContain('50.0%');
  });
});
