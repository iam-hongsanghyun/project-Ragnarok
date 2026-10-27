/**
 * Parity with the Python port in `backend/app/scenario_presets.py` (WA6).
 *
 * Both sides run the SAME golden fixture, `backend/tests/fixtures/scenario_parity.json`
 * (model sheets in; catalog, carbon library, DSL specs, run bodies out). The Python
 * test (`backend/tests/test_scenario_presets.py`) asserts its port equals the file; this
 * test asserts the browser code equals the file. If either side changes behaviour the
 * other test fails until both agree.
 */
import { describe, it, expect } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';
import { readScenarioCatalogFromModel } from 'lib/results/scenarios';
import { readCarbonLibraryFromModel } from 'lib/results/carbonLibrary';
import { generatorCarriers, readCustomDslFromModel } from 'lib/constraints/custom';
import { parseConstraintDsl } from 'lib/constraints/dsl';
import type { ConstraintSpec, WorkbookModel } from 'lib/types';
import type { RunUiOptions } from './buildRunPayload';
import { buildRunPayload } from './buildRunPayload';

// JSON round trip drops `undefined` exactly like the backend's JSON does.
const plain = (value: unknown) => JSON.parse(JSON.stringify(value));

interface ParityCase {
  name: string;
  model: WorkbookModel;
  uiOptions: Partial<RunUiOptions>;
  expected: {
    catalog: { activeScenarioId: string | null; scenarios: unknown[] };
    carbon: unknown[];
    dsl: { text: string; lines: { lineNo: number; raw: string; error?: string; spec?: unknown }[]; specs: unknown[] };
    generatorCarriers: string[];
    runBodies: Record<string, unknown>;
  };
}

const fixturePath = path.resolve(process.cwd(), '../../backend/tests/fixtures/scenario_parity.json');
const cases: ParityCase[] = JSON.parse(fs.readFileSync(fixturePath, 'utf8')).cases;

describe.each(cases)('backend parity: $name', (c) => {
  it('reads the same scenario catalog', () => {
    const catalog = readScenarioCatalogFromModel(c.model);
    expect(plain({ activeScenarioId: catalog.activeScenarioId, scenarios: catalog.scenarios })).toEqual(c.expected.catalog);
  });

  it('reads the same carbon library', () => {
    expect(plain(readCarbonLibraryFromModel(c.model))).toEqual(c.expected.carbon);
  });

  it('reads and parses the DSL sheet the same way', () => {
    const text = readCustomDslFromModel(c.model);
    expect(text).toBe(c.expected.dsl.text);
    const lines = parseConstraintDsl(text);
    expect(plain(lines.map(({ lineNo, raw, error, spec }) => ({ lineNo, raw, error, spec })))).toEqual(c.expected.dsl.lines);
    expect(plain(lines.map((l) => l.spec).filter((s): s is ConstraintSpec => !!s))).toEqual(c.expected.dsl.specs);
  });

  it('lists the same generator carriers', () => {
    expect(generatorCarriers(c.model)).toEqual(c.expected.generatorCarriers);
  });

  it('builds the same run body for every scenario', () => {
    const catalog = readScenarioCatalogFromModel(c.model);
    const specs = parseConstraintDsl(readCustomDslFromModel(c.model))
      .map((l) => l.spec).filter((s): s is ConstraintSpec => !!s);
    const bodies: Record<string, unknown> = {};
    for (const preset of catalog.scenarios) {
      bodies[preset.id] = buildRunPayload(
        preset,
        { backend: 'pypsa', ...c.uiOptions, scenarioLabel: preset.label } as RunUiOptions,
        specs,
      );
    }
    expect(plain(bodies)).toEqual(c.expected.runBodies);
  });
});
