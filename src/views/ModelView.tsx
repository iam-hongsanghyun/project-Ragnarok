/**
 * Model view — workbook input editor.
 *
 * Owns ALL file ops (open/save/import/export) in a top toolbar, and the
 * Map / Table sub-tabs for the workbook itself. No scenarios, no run
 * knobs, no constraints — those live in Settings.
 *
 * The view file is a thin shell: layout + sub-tab routing only. The
 * toolbar and panes are in `ModelView.features/`.
 */
import React from 'react';
import {
  GridRow,
  ModelSubTab,
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
  modelSubTab: ModelSubTab;
  onModelSubTabChange: (s: ModelSubTab) => void;

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
  const subTabs: ModelSubTab[] = ['Map', 'Table'];

  return (
    <div className="pane model-pane">
      <FileToolbar {...props} />
      <div className="pane-header model-pane-header">
        <nav className="subnav">
          {subTabs.map((s) => (
            <button
              key={s}
              className={`subnav-btn${props.modelSubTab === s ? ' subnav-btn--active' : ''}`}
              onClick={() => props.onModelSubTabChange(s)}
            >
              {s}
            </button>
          ))}
        </nav>
      </div>
      {props.modelSubTab === 'Map' && (
        <MapPane model={props.model} bounds={props.bounds} busIndex={props.busIndex} />
      )}
      {props.modelSubTab === 'Table' && (
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
      )}
    </div>
  );
}
