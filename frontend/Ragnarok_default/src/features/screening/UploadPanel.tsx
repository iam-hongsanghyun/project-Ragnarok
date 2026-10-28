/**
 * Upload panel — per-site (or per-region) series + a site / region table in, validation report out.
 *
 * Two layouts are read (long: site, timestamp, value; wide: one column per
 * site) as CSV or xlsx, with a site table (name, lat, lon, technology, region,
 * unit, capacity_mw). A region dataset is one series per region (a national or
 * zonal CF) with a region table (name, optional lat / lon centroid, optional
 * technology, unit, capacity_mw, optional GeoJSON `geometry`) and an optional
 * GeoJSON FeatureCollection of polygons; the same validation applies. "Validate" reports timestamps, duplicates, gaps, time
 * zone and unit sanity without storing anything; "Upload" stores the dataset
 * server-side for this session (it survives reload). Reference series (model
 * load or a price) are uploaded the same way and used in the correlation step.
 */
import React, { useState } from 'react';
import {
  DatasetKind,
  DatasetSummary,
  GapPolicy,
  Layout,
  ScreeningError,
  UploadForm,
  ValidationReport,
  uploadDataset,
  validateUpload,
} from 'lib/api/screening';
import { gapRows } from 'lib/screening/screening';
import { useToast } from '../../shared/components/Toast';
import { useDialog } from '../../shared/components/Dialog';

const COMMON_ZONES = ['UTC', 'Asia/Seoul', 'Asia/Tokyo', 'Europe/London', 'Europe/Berlin', 'Europe/Madrid', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Australia/Sydney'];

interface Props {
  datasets: DatasetSummary[];
  datasetsError: string | null;
  datasetsLoading: boolean;
  /** Active site dataset. */
  activeId: string | null;
  /** Active region dataset (the region level's source), null when regions are aggregated from sites. */
  activeRegionId: string | null;
  onSelect: (id: string, kind: DatasetKind) => void;
  onChanged: (selectId?: string, kind?: DatasetKind) => void;
  onDelete: (id: string) => Promise<void>;
}

export function ValidationReportView({ report, message }: { report: ValidationReport | undefined; message?: string }) {
  if (!report) return message ? <p className="scr-error">{message}</p> : null;
  const gaps = gapRows(report);
  return (
    <div className="scr-field" data-testid="validation-report">
      {report.errors?.length > 0 && (
        <ul className="scr-list">
          {report.errors.map((e) => <li key={e} className="scr-error">{e}</li>)}
        </ul>
      )}
      {report.warnings?.length > 0 && (
        <ul className="scr-list">
          {report.warnings.map((w) => <li key={w} className="scr-warn">{w}</li>)}
        </ul>
      )}
      {!report.errors?.length && <p className="scr-ok">Valid.</p>}
      <ul className="scr-list">
        {report.resolution && (
          <li>
            {report.resolution.steps.toLocaleString()} steps of {report.resolution.stepMinutes} min,{' '}
            {report.resolution.start.slice(0, 16)} to {report.resolution.end.slice(0, 16)} (UTC)
          </li>
        )}
        {report.timestamps && <li>Time zone: {report.timestamps.interpretation}</li>}
        {report.duplicates && <li>Duplicates: {report.duplicates.count} ({report.duplicates.resolution})</li>}
        {report.gaps && (
          <li>
            Gaps: {report.gaps.sitesWithGaps} site(s), {report.gaps.missingStepsTotal} missing step(s); policy {report.gaps.policy}
            {report.gaps.interpolatedValues !== undefined
              ? `, ${report.gaps.interpolatedValues} interpolated, ${report.gaps.rowsDropped ?? 0} timestamp(s) dropped`
              : ''}
          </li>
        )}
        {report.units && <li>Units: {report.units.basis}</li>}
      </ul>
      {gaps.length > 0 && (
        <div className="scr-table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>Site / region</th><th>Missing</th><th>Runs</th><th>Longest</th><th>First gap</th></tr>
            </thead>
            <tbody>
              {gaps.map((g) => (
                <tr key={g.site}>
                  <td>{g.site}</td><td className="scr-num">{g.missingSteps}</td><td className="scr-num">{g.runs}</td>
                  <td className="scr-num">{g.longestRunSteps}</td><td>{g.firstFrom.slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function UploadPanel({ datasets, datasetsError, datasetsLoading, activeId, activeRegionId, onSelect, onChanged, onDelete }: Props) {
  const { showToast } = useToast();
  const { confirm } = useDialog();
  const [kind, setKind] = useState<DatasetKind>('sites');
  const [geojsonFile, setGeojsonFile] = useState<File | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sitesFile, setSitesFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [layout, setLayout] = useState<Layout>('wide');
  const [timezone, setTimezone] = useState('UTC');
  const [gapPolicy, setGapPolicy] = useState<GapPolicy>('interpolate');
  const [defaultUnit, setDefaultUnit] = useState<'cf' | 'mw'>('cf');
  const [referenceKind, setReferenceKind] = useState<'load' | 'price'>('load');
  const [unitLabel, setUnitLabel] = useState('MW');
  const [busy, setBusy] = useState<'validate' | 'upload' | null>(null);
  const [report, setReport] = useState<ValidationReport | undefined>(undefined);
  const [message, setMessage] = useState<string | undefined>(undefined);

  const form = (): UploadForm | null => {
    if (!file) return null;
    return {
      file, sitesFile: kind === 'reference' ? null : sitesFile, geojsonFile: kind === 'regions' ? geojsonFile : null, name: name.trim() || undefined, layout, timezone: timezone.trim() || 'UTC',
      gapPolicy, kind, referenceKind: kind === 'reference' ? referenceKind : undefined, defaultUnit,
      unit: kind === 'reference' ? unitLabel : undefined,
    };
  };
  const ready = !!file && (kind === 'reference' || !!sitesFile);
  const noun = kind === 'regions' ? 'region' : 'site';

  const run = async (mode: 'validate' | 'upload') => {
    const f = form();
    if (!f) return;
    setBusy(mode);
    setMessage(undefined);
    try {
      if (mode === 'validate') {
        const res = await validateUpload(f);
        setReport(res.report);
        setMessage(res.ok ? undefined : res.message);
      } else {
        const meta = await uploadDataset(f);
        setReport(meta.report);
        showToast(`Stored dataset ${meta.name}.`, 'success');
        onChanged(meta.kind === 'reference' ? undefined : meta.id, meta.kind);
      }
    } catch (error) {
      if (error instanceof ScreeningError) {
        setReport(error.report);
        setMessage(error.message);
      } else {
        setMessage(error instanceof Error ? error.message : 'Upload failed.');
      }
    } finally {
      setBusy(null);
    }
  };

  const remove = async (d: DatasetSummary) => {
    if (!(await confirm(`Delete dataset "${d.name}"? Generators already added to the model stay.`, { danger: true, confirmText: 'Delete' }))) return;
    await onDelete(d.id);
  };

  return (
    <>
      <div className="scr-card">
        <div className="scr-card-head"><h3>1 · Data</h3></div>
        <div className="scr-field-row">
          <button className={`tb-btn${kind === 'sites' ? '' : ' tb-btn--muted'}`} onClick={() => setKind('sites')}>Site series</button>
          <button className={`tb-btn${kind === 'regions' ? '' : ' tb-btn--muted'}`} onClick={() => setKind('regions')}>Region series</button>
          <button className={`tb-btn${kind === 'reference' ? '' : ' tb-btn--muted'}`} onClick={() => setKind('reference')}>Reference series</button>
        </div>
        <div className="scr-field">
          <label className="scr-label" htmlFor="scr-series-file">{kind === 'reference' ? 'Load or price series (CSV or xlsx)' : kind === 'regions' ? 'Region series file (CSV or xlsx; one column per region)' : 'Series file (CSV or xlsx)'}</label>
          <input id="scr-series-file" type="file" accept=".csv,.xlsx,.xls,.txt" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(undefined); setMessage(undefined); }} />
        </div>
        {kind !== 'reference' && (
          <div className="scr-field">
            <label className="scr-label" htmlFor="scr-sites-file">
              {kind === 'regions'
                ? 'Region table (name; optional lat, lon, technology, unit, capacity_mw, geometry)'
                : 'Site table (name, lat, lon, technology, region, unit, capacity_mw)'}
            </label>
            <input id="scr-sites-file" type="file" accept=".csv,.xlsx,.xls,.txt" onChange={(e) => { setSitesFile(e.target.files?.[0] ?? null); setReport(undefined); }} />
          </div>
        )}
        {kind === 'regions' && (
          <div className="scr-field">
            <label className="scr-label" htmlFor="scr-geojson-file">Region polygons (optional GeoJSON FeatureCollection; properties.name = region name)</label>
            <input id="scr-geojson-file" type="file" accept=".geojson,.json" onChange={(e) => { setGeojsonFile(e.target.files?.[0] ?? null); setReport(undefined); }} />
          </div>
        )}
        <div className="scr-field-row">
          <div className="scr-field">
            <span className="scr-label">Layout</span>
            <select className="sg-setting-select" aria-label="Layout" value={layout} onChange={(e) => setLayout(e.target.value as Layout)}>
              <option value="wide">Wide: one column per {noun}</option>
              <option value="long">Long: {noun}, timestamp, value</option>
            </select>
          </div>
          <div className="scr-field">
            <span className="scr-label">Time zone</span>
            <input className="scr-input" list="scr-zones" aria-label="Time zone" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
            <datalist id="scr-zones">{COMMON_ZONES.map((z) => <option key={z} value={z} />)}</datalist>
          </div>
        </div>
        <p className="scr-hint">Timestamps without an offset are read in this zone and stored as UTC. Timestamps that carry an offset are converted as written.</p>
        <div className="scr-field-row">
          <div className="scr-field">
            <span className="scr-label">Gaps</span>
            <select className="sg-setting-select" aria-label="Gap policy" value={gapPolicy} onChange={(e) => setGapPolicy(e.target.value as GapPolicy)}>
              <option value="interpolate">Interpolate short gaps, drop the rest</option>
              <option value="drop">Drop timestamps with gaps</option>
            </select>
          </div>
          {kind !== 'reference' ? (
            <div className="scr-field">
              <span className="scr-label">Default unit</span>
              <select className="sg-setting-select" aria-label="Default unit" value={defaultUnit} onChange={(e) => setDefaultUnit(e.target.value as 'cf' | 'mw')}>
                <option value="cf">Capacity factor (0-1)</option>
                <option value="mw">MW (needs capacity)</option>
              </select>
            </div>
          ) : (
            <>
              <div className="scr-field">
                <span className="scr-label">Series is a</span>
                <select className="sg-setting-select" aria-label="Reference kind" value={referenceKind} onChange={(e) => setReferenceKind(e.target.value as 'load' | 'price')}>
                  <option value="load">Load</option>
                  <option value="price">Price</option>
                </select>
              </div>
              <div className="scr-field">
                <span className="scr-label">Unit</span>
                <input className="scr-input scr-input--short" aria-label="Reference unit" value={unitLabel} onChange={(e) => setUnitLabel(e.target.value)} />
              </div>
            </>
          )}
        </div>
        <div className="scr-field">
          <span className="scr-label">Dataset name</span>
          <input className="scr-input" aria-label="Dataset name" placeholder="defaults to the file name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="scr-field-row">
          <button className="tb-btn" disabled={!ready || busy !== null} onClick={() => run('validate')}>{busy === 'validate' ? 'Validating...' : 'Validate'}</button>
          <button className="tb-btn" disabled={!ready || busy !== null} onClick={() => run('upload')}>{busy === 'upload' ? 'Uploading...' : 'Upload'}</button>
        </div>
        {message && <p className="scr-error">{message}</p>}
        <ValidationReportView report={report} />
      </div>

      <div className="scr-card">
        <div className="scr-card-head"><h3>Datasets</h3><span className="scr-hint">{datasets.length} stored</span></div>
        {datasetsLoading && datasets.length === 0 && <p className="scr-hint">Loading...</p>}
        {datasetsError && <p className="scr-error">{datasetsError}</p>}
        {!datasetsLoading && !datasetsError && datasets.length === 0 && <p className="scr-hint">No dataset yet. Upload a series file and a site table (or a region series and a region table).</p>}
        {datasets.map((d) => (
          <div
            key={d.id}
            role="button"
            tabIndex={0}
            className={`scr-dataset${d.id === activeId || d.id === activeRegionId ? ' scr-dataset--active' : ''}`}
            onClick={() => d.kind !== 'reference' && onSelect(d.id, d.kind)}
            onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && d.kind !== 'reference') onSelect(d.id, d.kind); }}
          >
            <span>
              {d.name}
              <span className="scr-dataset-meta">
                {d.kind === 'sites' ? `${d.siteCount} sites` : d.kind === 'regions' ? `${d.regionCount} regions` : `reference ${d.referenceKind ?? ''} (${d.unit})`} · {d.rows.toLocaleString()} rows · {d.start.slice(0, 10)} to {d.end.slice(0, 10)}
              </span>
            </span>
            <button className="tb-btn tb-btn--muted" aria-label={`Delete ${d.name}`} onClick={(e) => { e.stopPropagation(); void remove(d); }}>Delete</button>
          </div>
        ))}
      </div>
    </>
  );
}
