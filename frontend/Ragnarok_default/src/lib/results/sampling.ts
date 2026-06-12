/**
 * Sampled snapshot blocks ("test run") config — persistence + preview math.
 *
 * Mirrors lib/results/rolling.ts: a single config row in the
 * RAGNAROK_Sampling workbook sheet, normalize/clone helpers, and a pure
 * preview that applies the SAME clamp/truncate rules as the backend index
 * builder (backend/pypsa/sampling.py sample_block_indices) so the UI summary
 * matches what the solver will actually do.
 */
import { GridRow, Primitive, SamplingConfig, WorkbookModel } from '../types';

export const SAMPLING_CONFIG_SHEET = 'RAGNAROK_Sampling';

function primitiveBoolean(value: Primitive, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'yes') return true;
    if (normalized === 'false' || normalized === '0' || normalized === 'no') return false;
  }
  return fallback;
}

function primitiveNumber(value: Primitive, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function defaultSamplingConfig(): SamplingConfig {
  return {
    enabled: false,
    mode: 'count',
    blockSize: 168,
    blockCount: 4,
    gapSnapshots: 672,
  };
}

export function normalizeSamplingConfig(config: SamplingConfig): SamplingConfig {
  return {
    enabled: Boolean(config.enabled),
    mode: config.mode === 'gap' ? 'gap' : 'count',
    blockSize: Math.max(1, Math.floor(Number(config.blockSize) || 168)),
    blockCount: Math.max(1, Math.floor(Number(config.blockCount) || 4)),
    gapSnapshots: Math.max(0, Math.floor(Number(config.gapSnapshots) || 0)),
  };
}

export function cloneSamplingConfig(config: SamplingConfig): SamplingConfig {
  return { ...normalizeSamplingConfig(config) };
}

export function readSamplingConfigFromModel(model: WorkbookModel): SamplingConfig {
  const row = (model[SAMPLING_CONFIG_SHEET] ?? [])[0] ?? {};
  return normalizeSamplingConfig({
    enabled: primitiveBoolean(row.enabled as Primitive, false),
    mode: (String(row.mode ?? 'count') === 'gap' ? 'gap' : 'count'),
    blockSize: primitiveNumber(row.blockSize as Primitive, 168),
    blockCount: primitiveNumber(row.blockCount as Primitive, 4),
    gapSnapshots: primitiveNumber(row.gapSnapshots as Primitive, 672),
  });
}

export function writeSamplingConfigToModel(
  model: WorkbookModel,
  config: SamplingConfig,
): WorkbookModel {
  const normalized = normalizeSamplingConfig(config);
  const configRows: GridRow[] = [{
    enabled: normalized.enabled,
    mode: normalized.mode,
    blockSize: normalized.blockSize,
    blockCount: normalized.blockCount,
    gapSnapshots: normalized.gapSnapshots,
  }];
  return { ...model, [SAMPLING_CONFIG_SHEET]: configRows };
}

export function sameSamplingConfig(left: SamplingConfig, right: SamplingConfig): boolean {
  return JSON.stringify(normalizeSamplingConfig(left)) === JSON.stringify(normalizeSamplingConfig(right));
}

export interface SamplingPreview {
  /** Modelled snapshots M (after blocks + in-block stride). */
  sampledSnapshots: number;
  /** Actual block count after clamping/truncation. */
  blockCount: number;
  /** Weight multiplier W / M applied to objective/generators. */
  scale: number;
}

/** Preview of what the backend will sample over a window of `windowSteps`
 *  rows at stride `step` — same clamp/truncate rules as sample_block_indices. */
export function computeSamplingPreview(
  windowSteps: number,
  step: number,
  config: SamplingConfig,
): SamplingPreview {
  const cfg = normalizeSamplingConfig(config);
  const W = Math.max(0, Math.floor(windowSteps));
  const stride = Math.max(1, Math.floor(step) || 1);
  if (W <= 0) return { sampledSnapshots: 0, blockCount: 0, scale: 1 };
  const B = Math.min(cfg.blockSize, W);

  const blocks: Array<[number, number]> = [];
  if (cfg.mode === 'gap') {
    const period = B + cfg.gapSnapshots;
    for (let s = 0; s < W; s += period) blocks.push([s, Math.min(s + B, W)]);
  } else {
    const N = Math.max(1, Math.min(cfg.blockCount, Math.floor(W / B)));
    if (N === 1) {
      blocks.push([0, B]);
    } else {
      const spacing = (W - B) / (N - 1);
      let prevEnd = 0;
      for (let i = 0; i < N; i++) {
        const s = Math.max(Math.round(i * spacing), prevEnd);
        const e = Math.min(s + B, W);
        blocks.push([s, e]);
        prevEnd = e;
      }
    }
  }

  let sampled = 0;
  for (const [s, e] of blocks) sampled += Math.ceil((e - s) / stride);
  return {
    sampledSnapshots: sampled,
    blockCount: blocks.length,
    scale: sampled > 0 ? W / sampled : 1,
  };
}
