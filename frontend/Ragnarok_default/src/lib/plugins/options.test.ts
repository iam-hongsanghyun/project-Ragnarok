import { describe, it, expect } from '@jest/globals';
import { resolveOptionsFrom } from './options';
import { WorkbookModel } from 'lib/types';

const model = {
  buses: [
    { name: 'BusA', x: 1 },
    { name: 'BusB', x: 2 },
    { name: 'BusA', x: 3 }, // duplicate value
    { name: '', x: 4 }, // blank → dropped
  ],
  generators: [],
} as unknown as WorkbookModel;

describe('resolveOptionsFrom — source: model', () => {
  it('reads distinct values from a sheet, default column "name"', () => {
    const out = resolveOptionsFrom({ source: 'model', sheet: 'buses' }, { model });
    expect(out).toEqual([
      { value: 'BusA', label: 'BusA' },
      { value: 'BusB', label: 'BusB' },
    ]);
  });

  it('returns [] for a missing or empty sheet (caller falls back to static)', () => {
    expect(resolveOptionsFrom({ source: 'model', sheet: 'nope' }, { model })).toEqual([]);
    expect(resolveOptionsFrom({ source: 'model', sheet: 'generators' }, { model })).toEqual([]);
    expect(resolveOptionsFrom({ source: 'model', sheet: 'buses' }, {})).toEqual([]);
  });

  it('honours a custom column and labelColumn', () => {
    const m = { regions: [{ code: 'KR-11', name: 'Seoul' }, { code: 'KR-26', name: 'Busan' }] } as unknown as WorkbookModel;
    const out = resolveOptionsFrom({ source: 'model', sheet: 'regions', column: 'code', labelColumn: 'name' }, { model: m });
    expect(out).toEqual([
      { value: 'KR-11', label: 'Seoul' },
      { value: 'KR-26', label: 'Busan' },
    ]);
  });
});

describe('resolveOptionsFrom — source: config', () => {
  it('reads distinct values from a sibling table field in formValues', () => {
    const formValues = {
      province_mapping: [
        { province: 'Gyeonggi', bus: 'B1' },
        { province: 'Seoul', bus: 'B2' },
        { province: 'Gyeonggi', bus: 'B3' }, // duplicate
      ],
    };
    const out = resolveOptionsFrom({ source: 'config', field: 'province_mapping', column: 'province' }, { formValues });
    expect(out).toEqual([
      { value: 'Gyeonggi', label: 'Gyeonggi' },
      { value: 'Seoul', label: 'Seoul' },
    ]);
  });

  it('returns [] when the referenced field is absent or not an array', () => {
    expect(resolveOptionsFrom({ source: 'config', field: 'nope', column: 'province' }, { formValues: {} })).toEqual([]);
    expect(resolveOptionsFrom({ source: 'config', field: 'x', column: 'province' }, { formValues: { x: 'scalar' } })).toEqual([]);
  });
});

describe('resolveOptionsFrom — filter + labelSuffix (build_year)', () => {
  const gens = {
    generators: [
      { name: 'old1', build_year: 2018 },
      { name: 'new1', build_year: 2030 },
      { name: 'new2', build_year: 2025 },
      { name: 'nodate' }, // no build_year → excluded by a numeric filter
    ],
  } as unknown as WorkbookModel;

  it('keeps only rows whose column >= a sibling field value, and labels with the year', () => {
    const out = resolveOptionsFrom(
      {
        source: 'model',
        sheet: 'generators',
        column: 'name',
        labelSuffixColumn: 'build_year',
        filter: { column: 'build_year', op: '>=', valueFrom: 'y' },
      },
      { model: gens, formValues: { y: 2025 } },
    );
    expect(out).toEqual([
      { value: 'new1', label: 'new1 (2030)' },
      { value: 'new2', label: 'new2 (2025)' },
    ]);
  });

  it('is a no-op filter when the threshold is blank/non-numeric (keeps all)', () => {
    const out = resolveOptionsFrom(
      { source: 'model', sheet: 'generators', column: 'name', filter: { column: 'build_year', op: '>=', valueFrom: 'y' } },
      { model: gens, formValues: { y: '' } },
    );
    expect(out.map((o) => o.value)).toEqual(['old1', 'new1', 'new2', 'nodate']);
  });
});

describe('resolveOptionsFrom — multiple filters incl. carrier (string ==)', () => {
  const gens = {
    generators: [
      { name: 'coal_2030', build_year: 2030, carrier: 'coal' },
      { name: 'gas_2030', build_year: 2030, carrier: 'gas' },
      { name: 'gas_2020', build_year: 2020, carrier: 'gas' },
      { name: 'wind_2035', build_year: 2035, carrier: 'wind' },
    ],
  } as unknown as WorkbookModel;
  const spec = {
    source: 'model' as const, sheet: 'generators', column: 'name',
    filter: [
      { column: 'build_year', op: '>=' as const, valueFrom: 'y' },
      { column: 'carrier', op: '==' as const, valueFrom: 'c' },
    ],
  };

  it('ANDs build_year >= and carrier ==', () => {
    const out = resolveOptionsFrom(spec, { model: gens, formValues: { y: 2024, c: 'gas' } });
    expect(out.map((o) => o.value)).toEqual(['gas_2030']);
  });

  it('blank carrier → that condition is a no-op', () => {
    const out = resolveOptionsFrom(spec, { model: gens, formValues: { y: 2024, c: '' } });
    expect(out.map((o) => o.value)).toEqual(['coal_2030', 'gas_2030', 'wind_2035']);
  });
});

describe('resolveOptionsFrom — set membership (in) for multi-select carriers', () => {
  const gens = { generators: [
    { name: 'coal_30', build_year: 2030, carrier: 'coal' },
    { name: 'gas_30', build_year: 2030, carrier: 'gas' },
    { name: 'wind_35', build_year: 2035, carrier: 'wind' },
  ] } as unknown as WorkbookModel;
  const spec = { source: 'model' as const, sheet: 'generators', column: 'name',
    filter: [{ column: 'carrier', op: 'in' as const, valueFrom: 'cs' }] };

  it('keeps rows whose carrier is in the checked set', () => {
    const out = resolveOptionsFrom(spec, { model: gens, formValues: { cs: ['gas', 'wind'] } });
    expect(out.map((o) => o.value)).toEqual(['gas_30', 'wind_35']);
  });
  it('empty set → no-op (all rows)', () => {
    const out = resolveOptionsFrom(spec, { model: gens, formValues: { cs: [] } });
    expect(out.map((o) => o.value)).toEqual(['coal_30', 'gas_30', 'wind_35']);
  });
});
