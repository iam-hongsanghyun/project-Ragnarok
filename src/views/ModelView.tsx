/**
 * Model view — workbook input editor.
 *
 * Owns ALL file ops (open/save/import/export) in a top toolbar, plus
 * a split body with the Table on the left and the Map on the right.
 *
 * The view file is a thin shell: layout only. The toolbar and panes
 * are in `ModelView.features/`.
 */
import React from 'react';
import {
  GridRow,
  Primitive,
  SheetName,
  TsSheetName,
  WorkbookModel,
} from '../shared/types';
import { ModelIssue } from '../features/validation/useModelIssues';
import { DateFormat } from '../features/settings/useSettings';
import { FileToolbar, FileToolbarProps } from './ModelView.features/FileToolbar';
import { MapPane } from '../features/map/MapPane';
import { TablesPane } from '../features/input/TablesPane';

export interface ModelViewProps extends FileToolbarProps {
  model: WorkbookModel;

  // Map
  bounds: ReturnType<typeof import('../shared/utils/helpers').getBounds>;
  busIndex: ReturnType<typeof import('../shared/utils/helpers').getBusIndex>;

  // Table
  onUpdateRow: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: (sheet: SheetName) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onAddColumn: (sheet: SheetName, col: string, defaultValue: string | number | boolean) => void;
  onDeleteColumn: (sheet: SheetName, col: string) => void;
  onRenameColumn: (sheet: SheetName, oldCol: string, newCol: string) => void;
  onImportTsSheet: (sheet: TsSheetName, rows: GridRow[]) => void;
  modelIssues: ModelIssue[];
  jumpTo: { sheet: string; rowIndex: number } | null;
  currencySymbol: string;
  dateFormat: DateFormat;
}

export function ModelView(props: ModelViewProps) {
  return (
    <div className="pane model-pane">
      <FileToolbar {...props} />
      <div className="model-split">
        <section className="model-split-pane model-split-table">
          <TablesPane
            model={props.model}
            onUpdate={props.onUpdateRow}
            onAddRow={props.onAddRow}
            onDeleteRow={props.onDeleteRow}
            onAddColumn={props.onAddColumn}
            onDeleteColumn={props.onDeleteColumn}
            onRenameColumn={props.onRenameColumn}
            onImportTsSheet={props.onImportTsSheet}
            issues={props.modelIssues}
            jumpTo={props.jumpTo}
            currencySymbol={props.currencySymbol}
            dateFormat={props.dateFormat}
          />
        </section>
        <section className="model-split-pane model-split-map">
          <MapPane model={props.model} bounds={props.bounds} busIndex={props.busIndex} />
        </section>
      </div>
    </div>
  );
}
