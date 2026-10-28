/**
 * ChainDesigner renders from props alone (static markup): the controls the brief asks for are present, the parameter
 * table shows value, unit, source flag from the catalogue, and the product-dependent sections follow the form.
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { describe, expect, it, jest } from '@jest/globals';
import type { TechCatalogue } from 'lib/api/p2x';
import type { WorkbookModel } from 'lib/types';
import { ChainDesigner } from './ChainDesigner';
import { defaultForm } from './spec';

const catalogue: TechCatalogue = {
  basis: { currency: 'EUR', costYear: 2025, technologyYear: 2030 },
  sources: { 'technology-data': { repository: 'https://github.com/PyPSA/technology-data', version: 'v0.15.0' } },
  technologies: {
    electrolyser_aec: {
      label: 'Alkaline electrolyser (AEC), 100 MW plant, 2030',
      parameters: {
        capex: { value: 691.5, default: 691.5, unit: 'EUR/kW_el', source: { document: 'DEA', locator: 'sheet 86 AEC 100 MW row 26', year: 2030 }, costYear: 2025, currency: 'EUR', verified: 'file' },
        min_load: { value: 15, default: 15, unit: '% of nominal input', source: { document: 'Buttler', locator: 'Table', year: 2018 }, costYear: null, currency: null, verified: 'literature-recalled' },
      },
    },
    water: { label: 'Process water', parameters: {} },
    h2_storage_tank: { label: 'Compressed H2 tank', parameters: {} },
  },
};
const model: WorkbookModel = {
  buses: [{ name: 'grid', carrier: 'AC' }],
  generators: [{ name: 'wind1', carrier: 'wind', bus: 'grid', build_year: 2030 }, { name: 'gas1', carrier: 'gas', bus: 'grid', build_year: 0 }],
};
const markupOf = (form = defaultForm(0.05, 'grid')) => staticMarkup(
  <ChainDesigner model={model} form={form} onChange={jest.fn()} catalogue={catalogue} catalogueError={null} onApplyFragment={jest.fn()} existingChainIds={['old']} />,
);

describe('ChainDesigner', () => {
  it('offers the products, electrolyser, storage, offtake and designated RES controls', () => {
    const html = markupOf();
    for (const text of ['Hydrogen', 'Ammonia', 'Methanol', 'E-fuel', 'Alkaline (AEC)', 'Extendable', 'Compressed tank', 'Salt cavern', 'Offtake', 'Designated renewable generators']) {
      expect(html).toContain(text);
    }
    expect(html).toContain('wind1');
    expect(html).toContain('Chains already in this model: old.');
    expect(html).toContain('Apply to model');
  });

  it('shows the technology parameters with unit, provenance flag and source in the tooltip', () => {
    const html = markupOf();
    expect(html).toContain('EUR/kW_el');
    expect(html).toContain('p2x-chip--file');
    expect(html).toContain('p2x-chip--literature-recalled');
    expect(html).toContain('sheet 86 AEC 100 MW row 26');
  });

  it('adds the synthesis and CO2 sections only for the ticked derivatives', () => {
    expect(markupOf()).not.toContain('CO2 supply');
    const f = defaultForm(0.05, 'grid');
    f.products.MeOH = true;
    const html = markupOf(f);
    expect(html).toContain('Synthesis');
    expect(html).toContain('CO2 supply');
    expect(html).toContain('Product tank');
  });
});
