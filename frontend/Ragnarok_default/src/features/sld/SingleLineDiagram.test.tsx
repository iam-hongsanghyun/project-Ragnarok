/** SLD rendering (static markup) and selection (click on a delegated target). */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import type { WorkbookModel } from 'lib/types';
import { buildSldLayout, DEFAULT_OPTIONS } from './layout';
import { SldDrawing, SingleLineDiagram } from './SingleLineDiagram';
import { NetworkPane } from './NetworkPane';
import { mount, type Mounted } from '../../shared/testing/dom';
import { act } from 'react';

jest.mock('../map/MapPane', () => ({ MapPane: () => <div data-testid="map-pane" /> }));

const model = {
  buses: [{ name: 'N400', v_nom: 400, carrier: 'AC' }, { name: 'N220', v_nom: 220, carrier: 'AC' }],
  generators: [{ name: 'w1', bus: 'N400', carrier: 'wind', p_nom: 100 }],
  loads: [{ name: 'l1', bus: 'N220', p_set: 5 }],
  transformers: [{ name: 'T1', bus0: 'N400', bus1: 'N220', s_nom: 300 }],
  lines: [], links: [], storage_units: [], stores: [],
} as unknown as WorkbookModel;

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; window.localStorage.clear(); });

describe('SldDrawing', () => {
  it('renders band labels, bus names and one selectable element per component', () => {
    const view = renderToStaticMarkup(<svg><SldDrawing layout={buildSldLayout(model, DEFAULT_OPTIONS)} selected={null} /></svg>);
    expect(view).toContain('400 kV');
    expect(view).toContain('220 kV');
    expect(view).toContain('data-sld-name="N400"');
    expect(view).toContain('data-sld-sheet="transformers"');
    expect(view).toContain('data-sld-sheet="generators"');
    expect(view).toContain('data-sld-sheet="loads"');
  });
});

describe('SingleLineDiagram', () => {
  it('emits onSelect(sheet, name) when an element is clicked', async () => {
    const onSelect = jest.fn();
    mounted = await mount(<SingleLineDiagram model={model} onSelect={onSelect} />);
    const frame = mounted.container.querySelector('.sld-frame') as HTMLElement;
    const gen = mounted.container.querySelector('[data-sld-sheet="generators"] rect') as Element;
    await act(async () => { gen.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true })); gen.dispatchEvent(new MouseEvent('pointerup', { bubbles: true })); });
    expect(frame).not.toBeNull();
    expect(onSelect).toHaveBeenCalledWith('generators', 'w1');
  });

  it('opens a composite through RAGNAROK_Composites', async () => {
    const withComposite = { ...model,
      generators: [{ name: 'c_g', bus: 'N400', carrier: 'gas', p_nom: 1, plant: 'c1' }],
      RAGNAROK_PLANTS: [{ name: 'c1', json: JSON.stringify({ plantId: 'c1', type: 'CCGT cofire', bus: 'N400' }) }],
    } as unknown as WorkbookModel;
    const onSelect = jest.fn();
    mounted = await mount(<SingleLineDiagram model={withComposite} onSelect={onSelect} />);
    expect(mounted.container.textContent).toContain('CCGT cofire');
    const box = mounted.container.querySelector('[data-sld-sheet="RAGNAROK_Composites"] rect') as Element;
    await act(async () => { box.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true })); box.dispatchEvent(new MouseEvent('pointerup', { bubbles: true })); });
    expect(onSelect).toHaveBeenCalledWith('RAGNAROK_Composites', 'c1');
  });
});

describe('NetworkPane', () => {
  it('defaults to the map and remembers the diagram choice', async () => {
    mounted = await mount(<NetworkPane model={model} bounds={null} busIndex={{}} />);
    expect(mounted.container.querySelector('[data-testid="map-pane"]')).not.toBeNull();
    const diagramButton = Array.from(mounted.container.querySelectorAll('button')).find((b) => b.textContent === 'Single-line diagram') as HTMLButtonElement;
    await act(async () => { diagramButton.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(mounted.container.querySelector('[data-testid="sld"]')).not.toBeNull();
    expect(window.localStorage.getItem('ui:model-network-view')).toBe('sld');
  });
});
