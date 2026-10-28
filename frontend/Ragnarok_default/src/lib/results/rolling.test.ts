/**
 * Rolling-horizon config: the terminal-SOC penalty is optional (absent = the backend's automatic price) and must survive
 * the normaliser and the workbook sheet, while a blank cell stays "automatic" rather than reading as 0.
 */
import { describe, test, expect } from '@jest/globals';
import {
  defaultRollingConfig,
  normalizeRollingConfig,
  readRollingConfigFromModel,
  writeRollingConfigToModel,
} from './rolling';
import type { WorkbookModel } from 'lib/types';

describe('terminalSocPenalty', () => {
  test('is carried by the normaliser and the sheet round trip', () => {
    const cfg = { ...defaultRollingConfig(), terminalSoc: true, terminalSocPenalty: 12.5 };
    expect(normalizeRollingConfig(cfg).terminalSocPenalty).toBe(12.5);
    const back = readRollingConfigFromModel(writeRollingConfigToModel({} as WorkbookModel, cfg));
    expect(back.terminalSoc).toBe(true);
    expect(back.terminalSocPenalty).toBe(12.5);
  });

  test('absent stays absent, and a blank cell is automatic, not zero', () => {
    const model = writeRollingConfigToModel({} as WorkbookModel, { ...defaultRollingConfig(), terminalSoc: true });
    expect('terminalSocPenalty' in (model.RAGNAROK_Rolling[0] ?? {})).toBe(false);
    expect(readRollingConfigFromModel(model).terminalSocPenalty).toBeUndefined();
    const blank = { RAGNAROK_Rolling: [{ ...model.RAGNAROK_Rolling[0], terminalSocPenalty: '' }] } as unknown as WorkbookModel;
    expect(readRollingConfigFromModel(blank).terminalSocPenalty).toBeUndefined();
  });

  test('zero is a real price (free shortfall), not automatic', () => {
    const cfg = { ...defaultRollingConfig(), terminalSoc: true, terminalSocPenalty: 0 };
    expect(readRollingConfigFromModel(writeRollingConfigToModel({} as WorkbookModel, cfg)).terminalSocPenalty).toBe(0);
  });
});
