/**
 * PypsaIoDialog: formats come from the capabilities, an import is previewed before it replaces anything, and a
 * pandapower 202 is retried.
 */
import React, { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { getPypsaIoCapabilities, postPypsaImport, summariseModel, type PypsaIoCapabilities } from 'lib/api/pypsaIo';
import { PypsaIoDialog } from './PypsaIoDialog';
import { button, chooseFile, click, mount, setValue, settle, type Mounted } from '../../shared/testing/dom';

jest.mock('lib/api/pypsaIo');
const mockCaps = jest.mocked(getPypsaIoCapabilities);
const mockImport = jest.mocked(postPypsaImport);
const mockSummary = jest.mocked(summariseModel);

const caps: PypsaIoCapabilities = {
  import: ['pypsa-excel', 'pypsa-csv', 'matpower'],
  export: ['netcdf', 'hdf5', 'pypsa-excel', 'pypsa-csv'],
  pandapowerInstalled: false,
  pandapowerSetup: { state: 'failed', error: 'no network' },
  exportOptions: ['exportStandardTypes'],
};

let mounted: Mounted | null = null;
beforeEach(() => {
  jest.useFakeTimers();
  mockSummary.mockImplementation((m) => Object.entries(m as Record<string, unknown[]>).filter(([, r]) => r.length > 0).map(([sheet, r]) => ({ sheet, rows: r.length })));
});
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.useRealTimers(); jest.resetAllMocks(); });

function props() {
  return {
    open: true,
    onClose: jest.fn(() => {}),
    onImported: jest.fn(async () => {}),
    onExport: jest.fn(async () => {}),
    showToast: jest.fn(() => {}),
  };
}

describe('PypsaIoDialog', () => {
  it('disables a format the backend does not offer and a failed pandapower environment', async () => {
    mockCaps.mockResolvedValue({ ...caps, import: ['pypsa-excel', 'matpower', 'pandapower'] });
    mounted = await mount(<PypsaIoDialog {...props()} />);
    await settle();
    const options = Array.from(mounted.container.querySelectorAll('option'));
    const byLabel = (t: string) => options.find((o) => (o.textContent ?? '').includes(t));
    expect(byLabel('PyPSA Excel')?.disabled).toBe(false);
    expect(byLabel('PyPSA CSV')?.disabled).toBe(true);        // not in capabilities.import
    expect(byLabel('pandapower')?.disabled).toBe(true);       // environment setup failed
  });

  it('previews what an import creates and replaces the model only on confirm', async () => {
    mockCaps.mockResolvedValue(caps);
    mockImport.mockResolvedValue({ status: 'ok', model: { buses: [{ name: 'a' }, { name: 'b' }], lines: [{ name: 'l' }], loads: [] } as never });
    const p = props();
    mounted = await mount(<PypsaIoDialog {...p} />);
    await settle();
    const root = mounted.container;
    await setValue(root.querySelector('#pypsa-io-format'), 'matpower');
    expect(button(root, 'Read file')?.disabled).toBe(true);   // no file yet
    await chooseFile(root.querySelector('#pypsa-io-file'), new File(['x'], 'case3.m'));
    await setValue(root.querySelector('#pypsa-io-snom'), '500');
    await click(button(root, 'Read file'));
    expect(mockImport).toHaveBeenCalledWith('matpower', expect.any(File), expect.objectContaining({ overwriteZeroSNom: 500 }));
    const preview = root.querySelector('[aria-label="Import preview"]');
    expect(preview?.textContent).toContain('buses');
    expect(preview?.textContent).not.toContain('loads');      // empty sheets are not listed
    expect(p.onImported).not.toHaveBeenCalled();
    await click(button(root, 'Replace working model'));
    expect(p.onImported).toHaveBeenCalledWith(expect.objectContaining({ buses: expect.any(Array) }), 'case3.m');
    expect(p.onClose).toHaveBeenCalled();
  });

  it('shows the backend reason when an import fails and keeps the model untouched', async () => {
    mockCaps.mockResolvedValue(caps);
    mockImport.mockRejectedValue(new Error('MATPOWER import failed: not a case'));
    const p = props();
    mounted = await mount(<PypsaIoDialog {...p} />);
    await settle();
    await chooseFile(mounted.container.querySelector('#pypsa-io-file'), new File(['x'], 'a.xlsx'));
    await click(button(mounted.container, 'Read file'));
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('not a case');
    expect(p.onImported).not.toHaveBeenCalled();
  });

  it('retries the same request after a pandapower 202', async () => {
    mockCaps.mockResolvedValue({ ...caps, import: ['pandapower'], pandapowerSetup: { state: 'absent' } });
    mockImport
      .mockResolvedValueOnce({ status: 'setting_up', detail: 'Building the pandapower environment.', retryAfterSeconds: 5 })
      .mockResolvedValueOnce({ status: 'ok', model: { buses: [{ name: 'b' }] } as never });
    mounted = await mount(<PypsaIoDialog {...props()} />);
    await settle();
    const root = mounted.container;
    await setValue(root.querySelector('#pypsa-io-format'), 'pandapower');
    await chooseFile(root.querySelector('#pypsa-io-file'), new File(['{}'], 'net.json'));
    await click(button(root, 'Read file'));
    expect(root.textContent).toContain('Retrying in 5 s');
    await act(async () => { jest.advanceTimersByTime(5100); });
    await settle();
    expect(mockImport).toHaveBeenCalledTimes(2);
    expect(root.querySelector('[aria-label="Import preview"]')).not.toBeNull();
  });

  it('exports with the standard-types option when ticked', async () => {
    mockCaps.mockResolvedValue(caps);
    const p = props();
    mounted = await mount(<PypsaIoDialog {...p} />);
    await settle();
    await click(button(mounted.container, 'Export PyPSA Excel'));
    expect(p.onExport).toHaveBeenLastCalledWith('pypsa-excel', {});
    await click(Array.from(mounted.container.querySelectorAll('input[type="checkbox"]')).pop() ?? null);
    await click(button(mounted.container, 'Export PyPSA CSV (zip)'));
    expect(p.onExport).toHaveBeenLastCalledWith('pypsa-csv', { exportStandardTypes: true });
  });
});
