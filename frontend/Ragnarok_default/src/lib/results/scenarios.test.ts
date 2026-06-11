/**
 * Scenario presets must round-trip the FULL run configuration through the
 * RAGNAROK_Scenarios sheet — including stochasticConfig and
 * securityConstrainedConfig (silently dropped before 2026-06), and stay
 * backward compatible with presets saved without them.
 */
import { expect, test } from '@jest/globals';
import {
  buildScenarioPreset,
  defaultSclopfConfig,
  defaultStochasticConfig,
  readScenarioCatalogFromModel,
  writeScenarioCatalogToModel,
  SCENARIO_SHEET,
} from './scenarios';
import { defaultPathwayConfig } from './pathway';
import { defaultRollingConfig } from './rolling';
import { WorkbookModel } from '../types';

function presetInput() {
  return {
    id: 'scenario-test',
    label: 'Stochastic case',
    notes: '',
    snapshotStart: 0,
    snapshotEnd: 24,
    snapshotWeight: 1,
    carbonPrice: 25,
    carbonPriceSchedule: [{ year: 2030, price: 50 }],
    discountRate: 0.05,
    forceLp: true,
    enableLoadShedding: false,
    loadSheddingCost: 2000,
    pathwayConfig: defaultPathwayConfig(),
    rollingConfig: defaultRollingConfig(),
    stochasticConfig: {
      enabled: true,
      scenarios: [
        {
          id: 'st-1',
          name: 'high fuel',
          weight: 0.4,
          overrides: [
            {
              id: 'ov-1',
              sheet: 'generators',
              attribute: 'marginal_cost',
              scopeType: 'carrier' as const,
              scopeValue: 'gas',
              operation: 'multiply' as const,
              value: 2,
            },
          ],
        },
      ],
    },
    securityConstrainedConfig: { enabled: true },
    constraints: [],
  };
}

test('stochastic + SCLOPF configs round-trip through the scenario sheet', () => {
  const preset = buildScenarioPreset(presetInput() as Parameters<typeof buildScenarioPreset>[0]);
  const model = writeScenarioCatalogToModel({} as WorkbookModel, {
    activeScenarioId: preset.id,
    scenarios: [preset],
  });
  const restored = readScenarioCatalogFromModel(model);

  expect(restored.scenarios).toHaveLength(1);
  const back = restored.scenarios[0];
  expect(back.stochasticConfig.enabled).toBe(true);
  expect(back.stochasticConfig.scenarios).toHaveLength(1);
  expect(back.stochasticConfig.scenarios[0].weight).toBe(0.4);
  expect(back.securityConstrainedConfig.enabled).toBe(true);
});

test('presets saved before the new fields normalize to disabled', () => {
  const preset = buildScenarioPreset(presetInput() as Parameters<typeof buildScenarioPreset>[0]);
  const model = writeScenarioCatalogToModel({} as WorkbookModel, {
    activeScenarioId: preset.id,
    scenarios: [preset],
  });
  // Simulate an OLD sheet row: strip the new fields out of the stored JSON.
  const rows = model[SCENARIO_SHEET] as Array<Record<string, unknown>>;
  const payload = JSON.parse(String(rows[0].json));
  delete payload.stochasticConfig;
  delete payload.securityConstrainedConfig;
  rows[0].json = JSON.stringify(payload);

  const restored = readScenarioCatalogFromModel(model);
  expect(restored.scenarios[0].stochasticConfig).toEqual(defaultStochasticConfig());
  expect(restored.scenarios[0].securityConstrainedConfig).toEqual(defaultSclopfConfig());
});

test('buildScenarioPreset clones configs (no shared references)', () => {
  const input = presetInput();
  const preset = buildScenarioPreset(input as Parameters<typeof buildScenarioPreset>[0]);
  expect(preset.stochasticConfig).not.toBe(input.stochasticConfig);
  expect(preset.stochasticConfig.scenarios[0]).not.toBe(input.stochasticConfig.scenarios[0]);
  expect(preset.securityConstrainedConfig).not.toBe(input.securityConstrainedConfig);
});
