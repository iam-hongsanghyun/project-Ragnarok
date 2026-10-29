/**
 * Run-option editors (CVaR / two-stage, iterative expansion, co-firing, SCLOPF branch outages): each edit lands in the
 * settings object the run payload is built from, and labels / help come from the run-options reference.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { getRunOptionFields } from 'lib/api/runOptions';
import { fetchPlants } from 'lib/api/plants';
import type { SecurityConstrainedConfig, StochasticConfig, WorkbookModel } from 'lib/types';
import type { AdvancedSolveOptions } from 'lib/settings/advancedSolve';
import { RiskTwoStageSection } from './RiskTwoStage';
import { IterativeExpansionSection } from './IterativeExpansion';
import { CofiringSection } from './Cofiring';
import { SclopfSection } from './Sclopf';
import { button, click, mount, setValue, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/runOptions');
jest.mock('lib/api/plants');
const mockFields = jest.mocked(getRunOptionFields);
const mockPlants = jest.mocked(fetchPlants);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });
beforeEach(() => {
  mockFields.mockImplementation(async (key: string) => ({
    [key]: { path: key, type: 'object', meaning: `help for ${key}` },
    [`${key}.alpha`]: { path: `${key}.alpha`, type: 'number', meaning: 'CVaR confidence level.', unit: 'probability 0-1' },
    [`${key}.maxShare`]: { path: `${key}.maxShare`, type: 'number', meaning: 'Maximum H2 share.' },
    [`${key}.msqThreshold`]: { path: `${key}.msqThreshold`, type: 'number', meaning: 'Stop below this change.', unit: 'MVA^2' },
  }));
});

const emptyStochastic = { enabled: false, scenarios: [] } as unknown as StochasticConfig;
const twoScenarios = { enabled: true, scenarios: [{ id: 'a' }, { id: 'b' }] } as unknown as StochasticConfig;

describe('RiskTwoStageSection', () => {
  it('turns CVaR on with the default weights, warns without stochastic mode, and edits alpha', async () => {
    const onChange = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<RiskTwoStageSection advancedSolve={{}} onAdvancedSolveChange={onChange} stochasticConfig={emptyStochastic} />);
    expect(mounted.container.textContent).toContain('help for options.riskPreference');
    await click(button(mounted.container, 'CVaR'));
    expect(onChange).toHaveBeenLastCalledWith({ riskPreference: { alpha: 0.95, omega: 0.5 } });
    await mounted.unmount();

    const onChange2 = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<RiskTwoStageSection advancedSolve={{ riskPreference: { alpha: 0.95, omega: 0.5 } }} onAdvancedSolveChange={onChange2} stochasticConfig={emptyStochastic} />);
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('at least two weighted scenarios');
    expect(mounted.container.textContent).toContain('Confidence level alpha (probability 0-1)');
    await setValue(mounted.container.querySelector('#rs-cvar-alpha'), '0.9');
    expect(onChange2).toHaveBeenLastCalledWith({ riskPreference: { alpha: 0.9, omega: 0.5 } });
    await setValue(mounted.container.querySelector('#rs-cvar-alpha'), '1.5');
    expect(onChange2).toHaveBeenCalledTimes(1);
  });

  it('shows no warning with two weighted scenarios and toggles two-stage', async () => {
    const onChange = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<RiskTwoStageSection advancedSolve={{ riskPreference: { alpha: 0.9, omega: 0.3 } }} onAdvancedSolveChange={onChange} stochasticConfig={twoScenarios} />);
    expect(mounted.container.querySelector('[role="alert"]')).toBeNull();
    const buttons = Array.from(mounted.container.querySelectorAll('button')).filter((b) => b.textContent === 'On');
    await click(buttons[buttons.length - 1]);
    expect(onChange).toHaveBeenLastCalledWith({ riskPreference: { alpha: 0.9, omega: 0.3 }, twoStage: true });
  });
});

describe('IterativeExpansionSection', () => {
  const model = { links: [{ name: 'hvdc1' }, { name: 'hvdc2' }] } as unknown as WorkbookModel;

  it('enables with the PyPSA defaults and edits the unit size, thresholds and a link row', async () => {
    const onChange = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<IterativeExpansionSection advancedSolve={{}} onAdvancedSolveChange={onChange} model={model} />);
    await click(button(mounted.container, 'On'));
    expect(onChange).toHaveBeenLastCalledWith({ iterativeExpansion: { enabled: true, msqThreshold: 0.05, minIterations: 1, maxIterations: 10, fractionalLastUnitSize: false, links: [] } });
    await mounted.unmount();

    const base = { enabled: true, msqThreshold: 0.05, minIterations: 1, maxIterations: 10, fractionalLastUnitSize: false, links: [] };
    const onChange2 = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<IterativeExpansionSection advancedSolve={{ iterativeExpansion: base }} onAdvancedSolveChange={onChange2} model={model} />);
    expect(mounted.container.textContent).toContain('Convergence threshold (MVA^2)');
    expect(mounted.container.textContent).toContain('Stop below this change.');
    await setValue(mounted.container.querySelector('#rs-iter-line-unit'), '500');
    expect(onChange2).toHaveBeenLastCalledWith({ iterativeExpansion: { ...base, lineUnitSize: 500 } });
    await click(button(mounted.container, 'Add link'));
    expect(onChange2).toHaveBeenLastCalledWith({ iterativeExpansion: { ...base, links: [{ link: 'hvdc1', unitSize: 0 }] } });
    await setValue(mounted.container.querySelector('#rs-iter-maxIterations'), '0');
    expect(onChange2).toHaveBeenCalledTimes(2);
  });

  it('flags minimum iterations above the maximum', async () => {
    const it = { enabled: true, msqThreshold: 0.05, minIterations: 12, maxIterations: 10, fractionalLastUnitSize: false, links: [] };
    mounted = await mount(<IterativeExpansionSection advancedSolve={{ iterativeExpansion: it }} onAdvancedSolveChange={() => {}} model={model} />);
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('exceed the maximum');
  });
});

describe('CofiringSection', () => {
  it('sends nothing for Plant data, and Explicit stores shares as fractions from percent inputs', async () => {
    mockPlants.mockResolvedValue([{ plantId: 'ccgt1', type: 'cofiring_network', label: 'CCGT 1' }, { plantId: 'pv1', type: 'solar', label: 'PV' }]);
    const onChange = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<CofiringSection advancedSolve={{}} onAdvancedSolveChange={onChange} />);
    expect(mounted.container.textContent).toContain('help for options.cofiringConfig');
    await click(button(mounted.container, 'Explicit'));
    expect(onChange).toHaveBeenLastCalledWith({ cofiringConfig: { enabled: true, plants: [], minShare: null, maxShare: null, unit: 'energy', scope: 'hourly', perPlant: {} } });
    await mounted.unmount();

    const cfg = { enabled: true, plants: [], minShare: null, maxShare: null, unit: 'energy' as const, scope: 'hourly' as const, perPlant: {} };
    const onChange2 = jest.fn<void, [AdvancedSolveOptions]>();
    mounted = await mount(<CofiringSection advancedSolve={{ cofiringConfig: cfg }} onAdvancedSolveChange={onChange2} />);
    expect(mounted.container.textContent).toContain('Maximum H2 share (% energy (LHV))');
    await setValue(mounted.container.querySelector('#rs-cofire-max'), '30');
    expect(onChange2).toHaveBeenLastCalledWith({ cofiringConfig: { ...cfg, maxShare: 0.3 } });
    await click(button(mounted.container, 'Set own limits'));
    expect(onChange2).toHaveBeenLastCalledWith({ cofiringConfig: { ...cfg, perPlant: { ccgt1: { minShare: null, maxShare: null, unit: 'energy', scope: 'hourly' } } } });
    await click(button(mounted.container, 'Plant data'));
    expect(onChange2).toHaveBeenLastCalledWith({ cofiringConfig: undefined });
  });

  it('warns when minimum exceeds maximum', async () => {
    mockPlants.mockResolvedValue([]);
    const cfg = { enabled: true, plants: [], minShare: 0.5, maxShare: 0.2, unit: 'vol' as const, scope: 'period' as const, perPlant: {} };
    mounted = await mount(<CofiringSection advancedSolve={{ cofiringConfig: cfg }} onAdvancedSolveChange={() => {}} />);
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('minimum share is above the maximum');
    expect(mounted.container.textContent).toContain('no fuel-network co-firing plant');
    expect(mounted.container.textContent).toContain('Minimum H2 share (% vol)');
  });
});

describe('SclopfSection branch outages', () => {
  const model = { lines: [{ name: 'L1' }, { name: 'L2' }], transformers: [{ name: 'T1' }] } as unknown as WorkbookModel;
  const base = {
    rollingConfig: { enabled: false }, stochasticConfig: emptyStochastic, pathwayConfig: { enabled: false },
    lineCount: 2, transformerCount: 1, model,
  } as unknown as React.ComponentProps<typeof SclopfSection>;

  it('keeps the secured branches when toggling the mode and states the coverage', async () => {
    const onChange = jest.fn<void, [SecurityConstrainedConfig]>();
    mounted = await mount(<SclopfSection {...base} sclopfConfig={{ enabled: true, branchOutages: ['L1', 'Transformer:T1'] }} onSclopfConfigChange={onChange} />);
    expect(mounted.container.textContent).toContain('2 of 3 branch(es) secured.');
    await click(button(mounted.container, 'Off'));
    expect(onChange).toHaveBeenLastCalledWith({ enabled: false, branchOutages: ['L1', 'Transformer:T1'] });
  });

  it('says every branch is secured when none is picked', async () => {
    mounted = await mount(<SclopfSection {...base} sclopfConfig={{ enabled: true }} onSclopfConfigChange={() => {}} />);
    expect(mounted.container.textContent).toContain('Every one of the 3 passive branch(es) is secured.');
  });
});
