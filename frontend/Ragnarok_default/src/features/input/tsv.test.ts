import { describe, test, expect } from '@jest/globals';
import { escapeTsvCell, parseTsv, serializeTsv } from './tsv';

describe('TSV helpers', () => {
  test('escapeTsvCell leaves plain values unchanged', () => {
    expect(escapeTsvCell('solar_01')).toBe('solar_01');
    expect(escapeTsvCell('120.5')).toBe('120.5');
  });

  test('escapeTsvCell quotes values containing tab / newline / quote', () => {
    expect(escapeTsvCell('a\tb')).toBe('"a\tb"');
    expect(escapeTsvCell('line1\nline2')).toBe('"line1\nline2"');
    expect(escapeTsvCell('say "hi"')).toBe('"say ""hi"""');
  });

  test('serializeTsv joins rows and columns', () => {
    const matrix = [['name', 'bus'], ['solar_01', 'Bus_01']];
    expect(serializeTsv(matrix)).toBe('name\tbus\nsolar_01\tBus_01');
  });

  test('parseTsv round-trips a plain matrix', () => {
    const text = 'name\tbus\nsolar_01\tBus_01';
    expect(parseTsv(text)).toEqual([['name', 'bus'], ['solar_01', 'Bus_01']]);
  });

  test('parseTsv handles Excel-style trailing newline', () => {
    expect(parseTsv('a\tb\n1\t2\n')).toEqual([['a', 'b'], ['1', '2']]);
  });

  test('parseTsv handles CRLF line endings (Windows Excel)', () => {
    expect(parseTsv('a\tb\r\n1\t2\r\n')).toEqual([['a', 'b'], ['1', '2']]);
  });

  test('parseTsv decodes quoted cells with embedded tab / newline / quote', () => {
    expect(parseTsv('"a\tb"\tc')).toEqual([['a\tb', 'c']]);
    expect(parseTsv('"line1\nline2"\tc')).toEqual([['line1\nline2', 'c']]);
    expect(parseTsv('"say ""hi"""\tc')).toEqual([['say "hi"', 'c']]);
  });

  test('serialize + parse round-trip preserves a matrix with awkward cells', () => {
    const original = [
      ['name', 'note'],
      ['solar_01', 'has\ttab'],
      ['wind_01', 'multi\nline'],
    ];
    expect(parseTsv(serializeTsv(original))).toEqual(original);
  });
});
