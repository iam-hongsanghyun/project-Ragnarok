/**
 * Sampled snapshot blocks config — clamp rules and preview math.
 *
 * computeSamplingPreview must apply the SAME clamp/truncate rules as the
 * backend index builder (backend/pypsa/sampling.py); the fixtures here mirror
 * backend/tests/test_sampling.py so the UI summary matches the solver.
 */
import { describe, test, expect } from '@jest/globals';
import {
  computeSamplingPreview,
  defaultSamplingConfig,
  normalizeSamplingConfig,
  readSamplingConfigFromModel,
  writeSamplingConfigToModel,
} from './sampling';
import type { SamplingConfig, WorkbookModel } from 'lib/types';

const cfg = (patch: Partial<SamplingConfig> = {}): SamplingConfig => ({
  ...defaultSamplingConfig(),
  enabled: true,
  ...patch,
});

describe('computeSamplingPreview (mirrors backend sample_block_indices)', () => {
  test('count mode exact partition: W = N×B', () => {
    const p = computeSamplingPreview(12, 1, cfg({ mode: 'count', blockSize: 6, blockCount: 2 }));
    expect(p).toEqual({ sampledSnapshots: 12, blockCount: 2, scale: 1 });
  });

  test('count mode equally spaced across a larger window', () => {
    const p = computeSamplingPreview(100, 1, cfg({ mode: 'count', blockSize: 10, blockCount: 3 }));
    expect(p.blockCount).toBe(3);
    expect(p.sampledSnapshots).toBe(30);
    expect(p.scale).toBeCloseTo(100 / 30, 6);
  });

  test('count mode clamps block count when N×B > W', () => {
    const p = computeSamplingPreview(20, 1, cfg({ mode: 'count', blockSize: 8, blockCount: 5 }));
    expect(p.blockCount).toBe(2);
    expect(p.sampledSnapshots).toBe(16);
  });

  test('block larger than window degenerates to full window', () => {
    const p = computeSamplingPreview(10, 1, cfg({ mode: 'count', blockSize: 50, blockCount: 3 }));
    expect(p).toEqual({ sampledSnapshots: 10, blockCount: 1, scale: 1 });
  });

  test('gap mode: period B+G with truncated trailing block', () => {
    const p = computeSamplingPreview(25, 1, cfg({ mode: 'gap', blockSize: 4, gapSnapshots: 6 }));
    expect(p.blockCount).toBe(3);
    expect(p.sampledSnapshots).toBe(12);
  });

  test('stride applies inside blocks', () => {
    const p = computeSamplingPreview(24, 3, cfg({ mode: 'count', blockSize: 6, blockCount: 2 }));
    expect(p.sampledSnapshots).toBe(4);
    expect(p.scale).toBeCloseTo(6, 6);
  });

  test('the headline example: 4×168 of 8760', () => {
    const p = computeSamplingPreview(8760, 1, cfg({ mode: 'count', blockSize: 168, blockCount: 4 }));
    expect(p.blockCount).toBe(4);
    expect(p.sampledSnapshots).toBe(672);
    expect(p.scale).toBeCloseTo(8760 / 672, 4);
  });

  test('empty window yields a no-op preview', () => {
    expect(computeSamplingPreview(0, 1, cfg())).toEqual({ sampledSnapshots: 0, blockCount: 0, scale: 1 });
  });
});

describe('normalize + model sheet round-trip', () => {
  test('normalize clamps invalid values', () => {
    const n = normalizeSamplingConfig({
      enabled: true, mode: 'bogus' as any, blockSize: -3, blockCount: 0, gapSnapshots: -1,
    } as SamplingConfig);
    expect(n.mode).toBe('count');
    expect(n.blockSize).toBeGreaterThanOrEqual(1);
    expect(n.blockCount).toBeGreaterThanOrEqual(1);
    expect(n.gapSnapshots).toBe(0);
  });

  test('write then read returns the same config', () => {
    const original = cfg({ mode: 'gap', blockSize: 96, gapSnapshots: 500 });
    const model = writeSamplingConfigToModel({} as WorkbookModel, original);
    const restored = readSamplingConfigFromModel(model);
    expect(restored).toEqual(normalizeSamplingConfig(original));
  });

  test('missing sheet falls back to defaults (disabled)', () => {
    const restored = readSamplingConfigFromModel({} as WorkbookModel);
    expect(restored.enabled).toBe(false);
    expect(restored).toEqual(defaultSamplingConfig());
  });
});

describe('effectiveSpanMs (chart x-label granularity for sparse blocks)', () => {
  const { effectiveSpanMs } = require('./analytics');
  const HOUR = 3_600_000;

  function hourly(start: Date, n: number): Array<{ timestamp: string }> {
    return Array.from({ length: n }, (_, i) => ({
      timestamp: new Date(start.getTime() + i * HOUR).toISOString(),
    }));
  }

  test('contiguous hourly data keeps roughly the raw span', () => {
    const rows = hourly(new Date('2030-01-01T00:00:00Z'), 48);
    const span = effectiveSpanMs(rows);
    expect(span).toBeCloseTo(48 * HOUR, -5);
  });

  test('sampled blocks ignore the gap deltas (median-based)', () => {
    // 4 blocks of 168 hourly rows spread across a year: raw span ~8760 h,
    // effective span must stay near 672 h so labels keep hour granularity.
    const rows: Array<{ timestamp: string }> = [];
    for (let b = 0; b < 4; b++) {
      rows.push(...hourly(new Date(Date.UTC(2030, b * 3, 1)), 168));
    }
    const span = effectiveSpanMs(rows);
    expect(span).toBeCloseTo(672 * HOUR, -7);
    expect(span).toBeLessThan(1000 * HOUR);
  });

  test('fewer than 2 timestamps yields 0', () => {
    expect(effectiveSpanMs([])).toBe(0);
    expect(effectiveSpanMs([{ timestamp: '2030-01-01T00:00:00Z' }])).toBe(0);
  });
});
