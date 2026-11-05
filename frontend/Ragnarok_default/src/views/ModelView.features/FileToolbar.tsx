/**
 * File toolbar — every file op for the project, in one row at the top
 * of the Model view. This is the ONLY place these buttons live.
 */
import React from 'react';
import { ViewPaneHeader } from '../../shared/components/primitives';
import { API_BASE } from 'lib/constants';

export interface FileToolbarProps {
  hasResults: boolean;
  onOpen: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onImportProject: () => void;
  onExportProject: () => void;
  /** Download the project file (.db): model + every app setting (docs/project-file.md). */
  onExportProjectFile: () => void;
  onOpenMasterModel: () => void;
  onImportCsvFolder: () => void;
  onExportCsvFolder: () => void;
  onImportNetcdf: () => void;
  onExportNetcdf: () => void;
  onImportHdf5: () => void;
  onExportHdf5: () => void;
  /** PyPSA Excel / CSV / MATPOWER / pandapower import and PyPSA Excel / CSV export. */
  onOpenPypsaIo: () => void;
}

export function FileToolbar(props: FileToolbarProps) {
  return (
    <ViewPaneHeader variant="toolbar">
      <button className="tb-btn" onClick={props.onOpen}>Open</button>
      <button className="tb-btn" onClick={props.onSave}>Save</button>
      <button className="tb-btn" onClick={props.onSaveAs}>Save As</button>
      <div className="view-toolbar-sep" />
      <button className="tb-btn" onClick={props.onImportProject} title="Open a project file (.db, model + every setting) or a project workbook (.xlsx / .zip, input + solved outputs) into the editor">
        Import Project
      </button>
      <button
        className="tb-btn"
        onClick={props.onExportProject}
        title={props.hasResults
          ? 'Export the full project: inputs + every solved output sheet'
          : 'Export the project workbook (inputs only — no run yet)'}
      >
        Export Project
      </button>
      <button
        className="tb-btn"
        onClick={props.onExportProjectFile}
        title="Save the project file (.db): the model and every app setting (modules, run controls, plugin settings) in one file"
      >
        Save Project File
      </button>
      <div className="view-toolbar-sep" />
      <button
        className="tb-btn"
        onClick={props.onOpenMasterModel}
        title="Import a multi-year master model and derive a filtered working model from it (years, carriers, buses, …)"
      >
        Master…
      </button>
      <div className="view-toolbar-sep" />
      <details className="view-toolbar-more">
        <summary className="tb-btn tb-btn--muted">More formats…</summary>
        <div className="view-toolbar-more-pop">
          <button className="tb-btn" onClick={props.onImportCsvFolder}>Import CSV folder</button>
          <button className="tb-btn" onClick={props.onImportNetcdf}>Import netCDF</button>
          <button className="tb-btn" onClick={props.onImportHdf5}>Import HDF5</button>
          <div className="view-toolbar-more-sep" />
          <button className="tb-btn" onClick={props.onExportCsvFolder}>Export CSV folder</button>
          <button className="tb-btn" onClick={props.onExportNetcdf}>Export netCDF</button>
          <button className="tb-btn" onClick={props.onExportHdf5}>Export HDF5</button>
          <div className="view-toolbar-more-sep" />
          <button className="tb-btn" onClick={props.onOpenPypsaIo} title="Import PyPSA Excel, PyPSA CSV, MATPOWER or pandapower files; export PyPSA Excel or CSV">PyPSA I/O…</button>
          <div className="view-toolbar-more-sep" />
          <a
            className="tb-btn"
            href={`${API_BASE}/api/project-file/template?format=xlsx`}
            download="ragnarok_template.xlsx"
            title="A small model that runs as it is: fill in your data, run settings (RAGNAROK_RunSettings) and period limits (RAGNAROK_PeriodBudgets), then Import Project and Run"
          >
            Project template (.xlsx)
          </a>
        </div>
      </details>
    </ViewPaneHeader>
  );
}
