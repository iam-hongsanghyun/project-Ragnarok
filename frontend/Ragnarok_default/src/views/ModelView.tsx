/**
 * Model view — workbook input editor.
 *
 * Three independent columns side-by-side:
 *   Tree (component → static / temporal sheets) · Table · Map.
 * Each column scrolls on its own. File ops live in the toolbar above.
 *
 * The view file is a thin shell: layout + selection state. The tree,
 * table and map are each their own component.
 */
import React from 'react';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import {
  GridRow,
  Primitive,
  SheetName,
  TableSel,
  TsSheetName,
  WorkbookModel,
} from 'lib/types';
import { ModelIssue } from '../features/validation/useModelIssues';
import { DateFormat } from '../features/settings/useSettings';
import { FileToolbar, FileToolbarProps } from './ModelView.features/FileToolbar';
import { SheetTree } from './ModelView.features/SheetTree';
import { MapPane } from '../features/map/MapPane';
import { TablesPane } from '../features/input/TablesPane';
import { ResizablePanels } from '../layout/ResizablePanels';

export interface ModelViewProps extends FileToolbarProps {
  model: WorkbookModel;

  // Map
  bounds: ReturnType<typeof import('lib/utils/helpers').getBounds>;
  busIndex: ReturnType<typeof import('lib/utils/helpers').getBusIndex>;

  // Table
  onUpdateRow: (sheet: SheetName, rowIndex: number, col: string, val: Primitive) => void;
  onAddRow: (sheet: SheetName) => void;
  onDeleteRow: (sheet: SheetName, rowIndex: number) => void;
  onAddColumn: (sheet: SheetName, col: string, defaultValue: string | number | boolean) => void;
  onDeleteColumn: (sheet: SheetName, col: string) => void;
  onRenameColumn: (sheet: SheetName, oldCol: string, newCol: string) => void;
  onClearTable: (sheet: SheetName) => void;
  onImportTsSheet: (sheet: TsSheetName, rows: GridRow[]) => void;
  onBulkPaste: (
    sheet: SheetName,
    edits: { rowIndex: number; col: string; val: Primitive }[],
    extraRows: number,
  ) => void;
  modelIssues: ModelIssue[];
  jumpTo: { sheet: string; rowIndex: number } | null;
  currencySymbol: string;
  dateFormat: DateFormat;
  /** Session series-sheet row counts (temporal sheets live server-side). */
  seriesSheetCounts?: Record<string, number>;
}

export function ModelView(props: ModelViewProps) {
  const [sel, setSel] = usePersistedState<TableSel>('ui:model-sel', { kind: 'static', sheet: 'buses' });

  return (
    <div className="model-view">
      <FileToolbar {...props} />
      <ResizablePanels id="model" direction="horizontal" className="model-columns" initialSizes={[20, 40, 40]} minSize={160}>
        <section className="model-column model-column-tree">
          <SheetTree
            model={props.model}
            issues={props.modelIssues}
            sel={sel}
            onSelChange={setSel}
            seriesSheetCounts={props.seriesSheetCounts}
          />
        </section>
        <section className="model-column model-column-table">
          <TablesPane
            model={props.model}
            sel={sel}
            onSelChange={setSel}
            onUpdate={props.onUpdateRow}
            onAddRow={props.onAddRow}
            onDeleteRow={props.onDeleteRow}
            onAddColumn={props.onAddColumn}
            onDeleteColumn={props.onDeleteColumn}
            onRenameColumn={props.onRenameColumn}
            onClearTable={props.onClearTable}
            onImportTsSheet={props.onImportTsSheet}
            onBulkPaste={props.onBulkPaste}
            issues={props.modelIssues}
            jumpTo={props.jumpTo}
            currencySymbol={props.currencySymbol}
            dateFormat={props.dateFormat}
            showAttrDoc
          />
        </section>
        <section className="model-column model-column-map">
          <MapPane model={props.model} bounds={props.bounds} busIndex={props.busIndex} />
        </section>
      </ResizablePanels>
    </div>
  );
}
