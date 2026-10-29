/**
 * RunDialog: "Export LP" sits next to the run controls, calls the handler and is disabled while an export runs.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { RunDialog, type RunDialogProps } from './RunDialog';
import { button, click, mount, type Mounted } from '../../shared/testing/dom';

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; });

const props = (over: Partial<RunDialogProps> = {}): RunDialogProps => ({
  open: true, onClose: () => {}, forceLp: false, dryRun: false, activeScenarioLabel: 'Base', activeConstraintCount: 0,
  snapshotStart: 0, snapshotEnd: 24,
  pathwayConfig: { enabled: false, periods: [] } as unknown as RunDialogProps['pathwayConfig'],
  rollingConfig: { enabled: false } as unknown as RunDialogProps['rollingConfig'],
  samplingConfig: { enabled: false } as unknown as RunDialogProps['samplingConfig'],
  onForceLpChange: () => {}, onDryRunChange: () => {}, onRun: () => {}, onQueueNext: () => {}, onAddScenario: () => {},
  ...over,
});

describe('RunDialog Export LP', () => {
  it('calls onExportLp and is absent when no handler is given', async () => {
    const onExportLp = jest.fn();
    mounted = await mount(<RunDialog {...props({ onExportLp })} />);
    await click(button(mounted.container, 'Export LP'));
    expect(onExportLp).toHaveBeenCalledTimes(1);
    await mounted.unmount();
    mounted = await mount(<RunDialog {...props()} />);
    expect(button(mounted.container, 'Export LP')).toBeNull();
  });

  it('disables the button while an export is running', async () => {
    mounted = await mount(<RunDialog {...props({ onExportLp: () => {}, exportLpBusy: true })} />);
    expect(button(mounted.container, 'Export LP')?.disabled).toBe(true);
  });
});
