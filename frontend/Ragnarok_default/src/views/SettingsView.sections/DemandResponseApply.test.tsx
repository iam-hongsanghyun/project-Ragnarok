/**
 * DemandResponseApply: preview the server's dr_* rows, write them only through Apply, and never apply a stale preview.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { applyDemandResponse, previewDemandResponse } from 'lib/api/operationsModules';
import type { DemandResponseConfig } from 'lib/types';
import { DemandResponseApply } from './DemandResponseApply';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/operationsModules');
const mockPreview = jest.mocked(previewDemandResponse);
const mockApply = jest.mocked(applyDemandResponse);

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

const config: DemandResponseConfig = {
  enabled: true, loads: [], shiftFraction: 0.2, maxShiftHours: 4, elasticEnabled: false, elasticFraction: 0.1, wtpMax: 200,
};
const preview = {
  existing: {},
  rows: { buses: [{ name: 'dr_load_north', carrier: 'AC' }], stores: [{ name: 'drstore_load_north', e_nom: 159.888101, e_cyclic: true }] },
  removed: { links: ['drlink_old'] },
  sheets: ['buses', 'stores'],
  notes: ['Demand response: 1 load(s) made shiftable (buffer 20% of peak x 4 h).'],
};

describe('DemandResponseApply', () => {
  it('previews rows and notes, then applies the previewed config and reloads the session model', async () => {
    mockPreview.mockResolvedValueOnce(preview);
    mockApply.mockResolvedValueOnce({ rows: preview.rows, removed: preview.removed, sheetsWritten: ['buses', 'stores'], notes: [] });
    const onSessionSync = jest.fn(async () => {});
    const onSessionReload = jest.fn(async () => {});
    mounted = await mount(<DemandResponseApply config={config} onSessionSync={onSessionSync} onSessionReload={onSessionReload} />);
    const root = mounted.container;
    expect(button(root, 'Apply rows')?.disabled).toBe(true);
    await click(button(root, 'Preview rows'));
    expect(mockPreview).toHaveBeenCalledWith(config);
    expect(root.textContent).toContain('buses: 1 row(s)');
    expect(root.textContent).toContain('dr_load_north');
    expect(root.textContent).toContain('159.888');
    expect(root.textContent).toContain('Remove from links: drlink_old');
    expect(mockApply).not.toHaveBeenCalled();
    await click(button(root, 'Apply rows'));
    expect(mockApply).toHaveBeenCalledWith(config);
    expect(onSessionReload).toHaveBeenCalled();
    expect(root.textContent).toContain('Written to buses, stores: 2 row(s) added, 1 removed.');
  });

  it('disables Apply when the settings changed after the preview, and when the workbook already holds the rows', async () => {
    mockPreview.mockResolvedValueOnce(preview).mockResolvedValueOnce({ ...preview, sheets: [] });
    mounted = await mount(<DemandResponseApply config={config} onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await click(button(mounted.container, 'Preview rows'));
    expect(button(mounted.container, 'Apply rows')?.disabled).toBe(false);
    await mounted.unmount();
    mounted = await mount(<DemandResponseApply config={config} onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await click(button(mounted.container, 'Preview rows'));
    expect(mounted.container.textContent).toContain('already holds exactly these rows');
    expect(button(mounted.container, 'Apply rows')?.disabled).toBe(true);
  });

  it('shows the server error', async () => {
    mockPreview.mockRejectedValueOnce(new Error('No model loaded in session'));
    mounted = await mount(<DemandResponseApply config={config} onSessionSync={async () => {}} onSessionReload={async () => {}} />);
    await click(button(mounted.container, 'Preview rows'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe('No model loaded in session');
  });
});
