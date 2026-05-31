import { describe, test, expect } from '@jest/globals';
import { exportModelAsCsvFolderBytes, importCsvFolderZip } from './csvFolder';
import { createEmptyWorkbook } from './workbook';

describe('PyPSA CSV folder I/O', () => {
  test('static + temporal sheets round-trip through the zip archive', async () => {
    const model = createEmptyWorkbook();
    model.buses = [
      { name: 'b0', v_nom: 380, x: 0, y: 0 },
      { name: 'b1', v_nom: 380, x: 0.1, y: 0.1 },
    ];
    model.carriers = [{ name: 'wind', co2_emissions: 0 }];
    model.generators = [
      { name: 'g_wind', bus: 'b0', carrier: 'wind', p_nom: 50, marginal_cost: 0.01 },
    ];
    model['generators-p_max_pu'] = [
      { snapshot: '2025-01-01T00:00:00', g_wind: 0.5 },
      { snapshot: '2025-01-01T01:00:00', g_wind: 0.8 },
    ];

    const buffer = exportModelAsCsvFolderBytes(model, 'test_export');
    expect(buffer.byteLength).toBeGreaterThan(0);

    const { model: imported, importedSheets, unknownFiles } = await importCsvFolderZip(buffer);

    expect(unknownFiles).toEqual([]);
    expect(importedSheets.sort()).toContain('buses');
    expect(importedSheets.sort()).toContain('generators');
    expect(importedSheets.sort()).toContain('generators-p_max_pu');

    expect(imported.buses.length).toBe(2);
    expect(imported.buses[0].name).toBe('b0');
    expect(Number(imported.buses[0].v_nom)).toBe(380);

    expect(imported.generators.length).toBe(1);
    expect(imported.generators[0].name).toBe('g_wind');
    expect(Number(imported.generators[0].p_nom)).toBe(50);

    expect(imported['generators-p_max_pu'].length).toBe(2);
    expect(Number(imported['generators-p_max_pu'][0].g_wind)).toBe(0.5);
    expect(Number(imported['generators-p_max_pu'][1].g_wind)).toBe(0.8);
  });

  test('empty sheets are not written to the archive', async () => {
    const model = createEmptyWorkbook();
    model.buses = [{ name: 'b0' }];
    // All other sheets stay empty (createEmptyWorkbook populates them as []).

    const buffer = exportModelAsCsvFolderBytes(model, 'minimal');
    const { importedSheets } = await importCsvFolderZip(buffer);

    expect(importedSheets).toEqual(['buses']);
  });

  test('unknown files in the zip are reported but not loaded', async () => {
    const { zipSync, strToU8 } = await import('fflate');
    const archive = zipSync({
      'pkg/buses.csv': strToU8('name,v_nom\nb0,380\n'),
      'pkg/notes.txt': strToU8('this is not a sheet'),
      'pkg/junk.csv': strToU8('a,b,c\n1,2,3\n'),
    });
    const { importedSheets, unknownFiles } = await importCsvFolderZip(archive);

    expect(importedSheets).toEqual(['buses']);
    expect(unknownFiles).toEqual(expect.arrayContaining(['pkg/junk.csv']));
    // notes.txt is not a .csv so it doesn't even get listed
  });
});
