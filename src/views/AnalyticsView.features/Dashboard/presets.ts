/**
 * Built-in preset layouts for the Analytics dashboard.
 *
 * Each preset is a named DashboardLayout that the user can load with
 * a single click. Use these as starting points; the user can then
 * resize / rearrange / save under a new name.
 *
 * Presets only contain `chart` and `notes` cards (the kinds the
 * dashboard supports today). Each chart card sets a sensible default
 * focus + metric so it shows real data the moment the layout loads.
 */
import { ChartSectionConfig } from '../../../shared/types';
import { EMPTY_METRIC_KEY } from '../../../constants';
import { DashboardLayout } from './types';

let _id = 0;
const id = (p: string) => `${p}-${Date.now().toString(36)}-${(_id++).toString(36)}`;

function chartConfig(patch: Partial<ChartSectionConfig>): ChartSectionConfig {
  return {
    id: Date.now() + Math.random(),
    focusType: 'system',
    focusKeys: [],
    groupBy: 'carrier',
    busFilter: [],
    carrierFilter: [],
    metricKey: EMPTY_METRIC_KEY,
    chartType: 'line',
    timeframe: 'hourly',
    startIndex: 0,
    endIndex: 0,
    stacked: false,
    ...patch,
  };
}

export interface Preset {
  key: string;
  label: string;
  description: string;
  build: () => DashboardLayout;
}

export const PRESETS: Preset[] = [
  {
    key: 'overview',
    label: 'System overview',
    description: 'KPIs at a glance: system dispatch, load and price in three stacked charts plus run notes.',
    build: () => {
      const dispatchCardId = id('chart');
      const loadCardId = id('chart');
      const priceCardId = id('chart');
      const notesId = id('notes');
      return {
        cards: [
          { id: dispatchCardId, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', stacked: true, metricKey: 'gen_mw' }) },
          { id: loadCardId,     kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', metricKey: 'load_mw' }) },
          { id: priceCardId,    kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', metricKey: 'price' }) },
          { id: notesId,        kind: 'notes' },
        ],
        rows: [
          { id: id('row'), height: 320, cells: [{ id: id('cell'), flex: 1, cardId: dispatchCardId }] },
          { id: id('row'), height: 240, cells: [
            { id: id('cell'), flex: 1, cardId: loadCardId },
            { id: id('cell'), flex: 1, cardId: priceCardId },
          ]},
          { id: id('row'), height: 160, cells: [{ id: id('cell'), flex: 1, cardId: notesId }] },
        ],
      };
    },
  },
  {
    key: 'dispatch-deep-dive',
    label: 'Dispatch deep-dive',
    description: 'Three system-level dispatch views side-by-side, plus a system-load reference below.',
    build: () => {
      const a = id('chart'); const b = id('chart'); const c = id('chart'); const d = id('chart');
      return {
        cards: [
          { id: a, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', stacked: true, metricKey: 'gen_mw' }) },
          { id: b, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'area', stacked: true, metricKey: 'gen_mw' }) },
          { id: c, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'bar', metricKey: 'gen_mw', timeframe: 'daily' }) },
          { id: d, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', metricKey: 'load_mw' }) },
        ],
        rows: [
          { id: id('row'), height: 280, cells: [
            { id: id('cell'), flex: 1, cardId: a },
            { id: id('cell'), flex: 1, cardId: b },
            { id: id('cell'), flex: 1, cardId: c },
          ]},
          { id: id('row'), height: 200, cells: [{ id: id('cell'), flex: 1, cardId: d }] },
        ],
      };
    },
  },
  {
    key: 'storage-focus',
    label: 'Storage focus',
    description: 'System dispatch on top, two storage charts below for state-of-charge and inflow/outflow.',
    build: () => {
      const a = id('chart'); const b = id('chart'); const c = id('chart');
      return {
        cards: [
          { id: a, kind: 'chart', config: chartConfig({ focusType: 'system', chartType: 'line', stacked: true, metricKey: 'gen_mw' }) },
          { id: b, kind: 'chart', config: chartConfig({ focusType: 'storageUnit', chartType: 'line', metricKey: 'state_of_charge_mwh' }) },
          { id: c, kind: 'chart', config: chartConfig({ focusType: 'storageUnit', chartType: 'line', metricKey: 'dispatch_mw' }) },
        ],
        rows: [
          { id: id('row'), height: 280, cells: [{ id: id('cell'), flex: 1, cardId: a }] },
          { id: id('row'), height: 240, cells: [
            { id: id('cell'), flex: 1, cardId: b },
            { id: id('cell'), flex: 1, cardId: c },
          ]},
        ],
      };
    },
  },
  {
    key: 'minimal',
    label: 'Blank minimal',
    description: 'One empty chart card. Build the rest yourself.',
    build: () => {
      const a = id('chart');
      return {
        cards: [{ id: a, kind: 'chart', config: chartConfig({}) }],
        rows: [{ id: id('row'), height: 320, cells: [{ id: id('cell'), flex: 1, cardId: a }] }],
      };
    },
  },
];
