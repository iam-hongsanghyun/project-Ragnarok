import { GridRow, WorkbookModel } from '../types';

/**
 * Persistence for the free-text custom-constraint DSL. Stored as a single-row
 * sheet holding the raw multiline text, mirroring the rolling-config pattern.
 */
export const CUSTOM_DSL_SHEET = 'RAGNAROK_CustomDSL';

export function readCustomDslFromModel(model: WorkbookModel): string {
  const row = (model[CUSTOM_DSL_SHEET] ?? [])[0];
  const text = row?.text;
  return typeof text === 'string' ? text : '';
}

export function writeCustomDslToModel(model: WorkbookModel, text: string): WorkbookModel {
  const rows: GridRow[] = [{ text }];
  return { ...model, [CUSTOM_DSL_SHEET]: rows };
}
