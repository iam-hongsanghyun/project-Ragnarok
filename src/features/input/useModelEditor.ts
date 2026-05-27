import { useCallback, useState } from 'react';

import { getDefaultRowForSheet } from '../../constants';
import { createEmptyWorkbook } from '../../shared/utils/workbook';
import { GridRow, Primitive, SheetName, WorkbookModel } from '../../shared/types';

/**
 * Workbook model state and its row/column mutation helpers. Each mutation
 * reports a human-readable status line via the supplied ``setStatus`` callback,
 * keeping the status surface in the parent.
 */
export function useModelEditor(setStatus: (message: string) => void) {
  const [model, setModel] = useState<WorkbookModel>(() => createEmptyWorkbook());

  const updateRowValue = useCallback((sheet: SheetName, rowIndex: number, key: string, value: Primitive) => {
    setModel((current) => {
      const nextRows = current[sheet].map((row, index) => (index === rowIndex ? { ...row, [key]: value } : row));
      return { ...current, [sheet]: nextRows };
    });
  }, []);

  const addRow = useCallback((sheet: SheetName) => {
    setModel((current) => {
      const nextRows = [...(current[sheet] ?? []), { ...getDefaultRowForSheet(sheet) }];
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Added a new row to ${sheet}.`);
  }, [setStatus]);

  const deleteRow = useCallback((sheet: SheetName, rowIndex: number) => {
    setModel((current) => {
      const nextRows = current[sheet].filter((_, i) => i !== rowIndex);
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Removed row ${rowIndex + 1} from ${sheet}.`);
  }, [setStatus]);

  const moveRow = useCallback((sheet: SheetName, rowIndex: number, direction: -1 | 1) => {
    setModel((current) => {
      const nextIndex = rowIndex + direction;
      if (nextIndex < 0 || nextIndex >= current[sheet].length) return current;
      const nextRows = [...current[sheet]];
      const [row] = nextRows.splice(rowIndex, 1);
      nextRows.splice(nextIndex, 0, row);
      return { ...current, [sheet]: nextRows };
    });
  }, []);

  const addColumn = useCallback((sheet: SheetName, col: string, defaultValue: string | number | boolean) => {
    setModel((current) => {
      const nextRows = current[sheet].map((row) =>
        col in row ? row : { ...row, [col]: defaultValue },
      );
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Added column "${col}" to ${sheet}.`);
  }, [setStatus]);

  const deleteColumn = useCallback((sheet: SheetName, col: string) => {
    setModel((current) => {
      const nextRows = current[sheet].map((row) => {
        const { [col]: _removed, ...rest } = row as Record<string, Primitive>;
        return rest as GridRow;
      });
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Removed column "${col}" from ${sheet}.`);
  }, [setStatus]);

  const renameColumn = useCallback((sheet: SheetName, oldCol: string, newCol: string) => {
    if (!newCol || newCol === oldCol) return;
    setModel((current) => {
      const nextRows = current[sheet].map((row) => {
        const r = row as Record<string, Primitive>;
        if (!(oldCol in r)) return row;
        const { [oldCol]: val, ...rest } = r;
        return { ...rest, [newCol]: val } as GridRow;
      });
      return { ...current, [sheet]: nextRows };
    });
    setStatus(`Renamed column "${oldCol}" to "${newCol}" in ${sheet}.`);
  }, [setStatus]);

  return {
    model,
    setModel,
    updateRowValue,
    addRow,
    deleteRow,
    moveRow,
    addColumn,
    deleteColumn,
    renameColumn,
  };
}
