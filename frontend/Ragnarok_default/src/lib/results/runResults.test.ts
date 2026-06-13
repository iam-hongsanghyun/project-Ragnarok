import { describe, it, expect } from '@jest/globals';
import { deriveRunResults } from './runResults';
import { createEmptyWorkbook } from 'lib/workbook/workbook';
import type { RunResults } from 'lib/types';

// Regression: an imported external result (or any run with no server-derived
// summary) is opened via the LIGHT analytics view, which ships `series: null`
// (the heavy per-component output series are stripped and fetched on demand).
// `deriveRunResults` must tolerate that — derive to empty, never throw
// `Object.values(null)` / `null['lines-p0']`. See History import (H2).
describe('deriveRunResults — light-view (stripped series) safety', () => {
  const model = createEmptyWorkbook();

  it('does not throw when outputs.series is null', () => {
    const outputs = { static: {}, series: null } as unknown as NonNullable<RunResults['outputs']>;
    expect(() => deriveRunResults(model, outputs)).not.toThrow();
  });

  it('does not throw when both series and static are null', () => {
    const outputs = { static: null, series: null } as unknown as NonNullable<RunResults['outputs']>;
    expect(() => deriveRunResults(model, outputs)).not.toThrow();
  });

  it('derives empty dispatch / line-loading from a null series', () => {
    const outputs = { static: {}, series: null } as unknown as NonNullable<RunResults['outputs']>;
    const derived = deriveRunResults(model, outputs);
    // Empty, well-formed structures — the cards render "no data", not a crash.
    expect(Array.isArray(derived.dispatchSeries)).toBe(true);
    expect(derived.dispatchSeries).toHaveLength(0);
    expect(Array.isArray(derived.lineLoading)).toBe(true);
    expect(derived.lineLoading).toHaveLength(0);
  });
});
