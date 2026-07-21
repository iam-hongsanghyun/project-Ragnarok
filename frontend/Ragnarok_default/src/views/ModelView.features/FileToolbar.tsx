/**
 * File toolbar — every file op for the project, in one row at the top
 * of the Model view. This is the ONLY place these buttons live.
 */
import React from 'react';
import { ViewPaneHeader } from '../../shared/components/primitives';

export interface FileToolbarProps {
  hasResults: boolean;
  onOpen: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onImportProject: () => void;
  onExportProject: () => void;
  onOpenMasterModel: () => void;
  onImportCsvFolder: () => void;
  onExportCsvFolder: () => void;
  onImportNetcdf: () => void;
  onExportNetcdf: () => void;
  onImportHdf5: () => void;
  onExportHdf5: () => void;
}

export function FileToolbar(props: FileToolbarProps) {
  return (
    <ViewPaneHeader variant="toolbar">
      <button className="tb-btn" onClick={props.onOpen}>Open</button>
      <button className="tb-btn" onClick={props.onSave}>Save</button>
      <button className="tb-btn" onClick={props.onSaveAs}>Save As</button>
      <div className="view-toolbar-sep" />
      <button className="tb-btn" onClick={props.onImportProject} title="Open a project workbook (input + solved outputs) into the editor — re-run to add it to History">
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
        </div>
      </details>
    </ViewPaneHeader>
  );
}
