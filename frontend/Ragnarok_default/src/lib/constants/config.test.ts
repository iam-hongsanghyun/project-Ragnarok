import { describe, it, expect, afterEach } from '@jest/globals';
import { RUN_WINDOW, applySimulationDefaults } from './config';

const shipped = { end: RUN_WINDOW.defaultSnapshotEnd, weight: RUN_WINDOW.defaultSnapshotWeight };
afterEach(() => {
  RUN_WINDOW.defaultSnapshotEnd = shipped.end;
  RUN_WINDOW.defaultSnapshotWeight = shipped.weight;
});

describe('applySimulationDefaults', () => {
  it('lets the server defaults win over the shipped run window', () => {
    applySimulationDefaults({ defaultSnapshotCount: 48, defaultSnapshotWeight: 2 });
    expect(RUN_WINDOW.defaultSnapshotEnd).toBe(48);
    expect(RUN_WINDOW.defaultSnapshotWeight).toBe(2);
  });

  it('ignores missing or non-positive values', () => {
    applySimulationDefaults(undefined);
    applySimulationDefaults({ defaultSnapshotCount: 0, defaultSnapshotWeight: Number.NaN });
    expect(RUN_WINDOW.defaultSnapshotEnd).toBe(shipped.end);
    expect(RUN_WINDOW.defaultSnapshotWeight).toBe(shipped.weight);
  });
});
