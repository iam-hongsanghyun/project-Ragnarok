import { describe, test, expect } from '@jest/globals';
import { BUILD_STEPS, getStepIssues } from './steps';
import { createEmptyWorkbook } from '../../shared/utils/workbook';
import { ModelIssue } from '../validation/useModelIssues';

describe('BUILD_STEPS registry', () => {
  test('every step has a recognised primary sheet', () => {
    const empty = createEmptyWorkbook();
    for (const step of BUILD_STEPS) {
      // Either the primary sheet is in the workbook (schema-defined) or the
      // step is one of the synthetic steps (constraints / review) — both fall
      // back to a known sheet for the schema pane.
      expect(empty).toHaveProperty(step.primarySheet);
    }
  });

  test('isComplete returns false when the schema requires a row and there are none', () => {
    const empty = createEmptyWorkbook();
    const network = BUILD_STEPS.find((s) => s.id === 'network')!;
    const carriers = BUILD_STEPS.find((s) => s.id === 'carriers')!;
    const buses = BUILD_STEPS.find((s) => s.id === 'buses')!;
    const generators = BUILD_STEPS.find((s) => s.id === 'generators')!;
    expect(network.isComplete(empty)).toBe(false);
    expect(carriers.isComplete(empty)).toBe(false);
    expect(buses.isComplete(empty)).toBe(false);
    expect(generators.isComplete(empty)).toBe(false);
  });

  test('isComplete returns true once rows exist for the step', () => {
    const model = createEmptyWorkbook();
    model.buses = [{ name: 'b1' }];
    const buses = BUILD_STEPS.find((s) => s.id === 'buses')!;
    expect(buses.isComplete(model)).toBe(true);
  });

  test('optional steps (processes, review) are complete on an empty model', () => {
    const empty = createEmptyWorkbook();
    expect(BUILD_STEPS.find((s) => s.id === 'processes')!.isComplete(empty)).toBe(true);
    expect(BUILD_STEPS.find((s) => s.id === 'review')!.isComplete(empty)).toBe(true);
    expect(BUILD_STEPS.find((s) => s.id === 'constraints')!.isComplete(empty)).toBe(true);
  });

  test('getStepIssues filters by primary + extra sheets', () => {
    const generators = BUILD_STEPS.find((s) => s.id === 'generators')!;
    const issues: ModelIssue[] = [
      { sheet: 'generators', rowIndex: 0, severity: 'error', message: 'missing bus' },
      { sheet: 'buses', rowIndex: 0, severity: 'warning', message: 'orphan bus' },
      { sheet: 'generators-p_max_pu', rowIndex: 0, severity: 'warning', message: 'short profile' },
    ];
    const filtered = getStepIssues(generators, issues);
    expect(filtered).toHaveLength(2);
    expect(filtered.map((i) => i.sheet).sort()).toEqual(['generators', 'generators-p_max_pu']);
  });

  test('step order matches the PyPSA dependency chain (carriers before generators, buses before lines)', () => {
    const order = BUILD_STEPS.map((s) => s.id);
    expect(order.indexOf('carriers')).toBeLessThan(order.indexOf('generators'));
    expect(order.indexOf('buses')).toBeLessThan(order.indexOf('generators'));
    expect(order.indexOf('buses')).toBeLessThan(order.indexOf('transport'));
    expect(order.indexOf('generators')).toBeLessThan(order.indexOf('review'));
  });
});
