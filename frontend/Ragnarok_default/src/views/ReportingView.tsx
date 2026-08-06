/**
 * ReportingView — perspective-based report documents from stored runs.
 *
 * Deterministic by design: the backend assembles every figure from the stored
 * solve payload (`/api/reports/{run}/{perspective}`); this view only picks a
 * run, a perspective, and a layout (document or slides), then renders and
 * prints. No number is computed client-side.
 */
import React from 'react';
import { TopTab, ViewPaneHeader, ViewPanel } from '../shared/components/primitives';
import type { TopTabItem } from '../shared/components/primitives';
import {
  fetchReport,
  fetchReportPerspectives,
  fetchReportRuns,
} from 'lib/api/reports';
import type {
  ReportDocumentPayload,
  ReportPerspective,
  ReportRunOption,
} from 'lib/reporting/types';
import { ReportDocument } from './ReportingView.features/ReportDocument';

type ReportLayout = 'document' | 'slides';

/** Session cache so switching perspective/run back and forth doesn't flash. */
const reportCache = new Map<string, ReportDocumentPayload>();

export function ReportingView() {
  const [perspectives, setPerspectives] = React.useState<ReportPerspective[]>([]);
  const [runs, setRuns] = React.useState<ReportRunOption[]>([]);
  const [runName, setRunName] = React.useState<string>('');
  const [perspective, setPerspective] = React.useState<string>('policy-maker');
  const [layout, setLayout] = React.useState<ReportLayout>('document');
  const [doc, setDoc] = React.useState<ReportDocumentPayload | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    fetchReportPerspectives()
      .then((list) => {
        if (!live) return;
        setPerspectives(list);
        if (list.length && !list.some((p) => p.id === 'policy-maker')) {
          setPerspective(list[0].id);
        }
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    fetchReportRuns()
      .then((list) => {
        if (!live) return;
        setRuns(list);
        if (list.length) setRunName((current) => current || list[0].name);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  React.useEffect(() => {
    if (!runName || !perspective) return;
    const key = `${runName}::${perspective}`;
    const cached = reportCache.get(key);
    if (cached) {
      setDoc(cached);
      return;
    }
    let live = true;
    setBusy(true);
    setError(null);
    fetchReport(runName, perspective)
      .then((payload) => {
        if (!live) return;
        reportCache.set(key, payload);
        setDoc(payload);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [runName, perspective]);

  const tabs: TopTabItem<string>[] = perspectives.map((p) => ({ id: p.id, label: p.label }));
  const active = perspectives.find((p) => p.id === perspective);

  return (
    <ViewPanel name="reporting">
      <ViewPaneHeader variant="analytics">
        {tabs.length > 0 && (
          <TopTab
            items={tabs}
            active={perspective}
            onChange={setPerspective}
            ariaLabel="Report perspective"
          />
        )}
        <div className="reporting-controls">
          <select
            className="reporting-run-select"
            value={runName}
            onChange={(e) => setRunName(e.target.value)}
            aria-label="Stored run"
            disabled={runs.length === 0}
          >
            {runs.map((r) => (
              <option key={r.name} value={r.name}>
                {r.label || r.name}
              </option>
            ))}
          </select>
          <div className="subnav" role="group" aria-label="Report layout">
            <button
              type="button"
              className={'subnav-btn' + (layout === 'document' ? ' subnav-btn--active' : '')}
              onClick={() => setLayout('document')}
            >
              <span className="subnav-btn-label">Document</span>
            </button>
            <button
              type="button"
              className={'subnav-btn' + (layout === 'slides' ? ' subnav-btn--active' : '')}
              onClick={() => setLayout('slides')}
            >
              <span className="subnav-btn-label">Slides</span>
            </button>
          </div>
          <button
            type="button"
            className="reporting-print-btn"
            onClick={() => window.print()}
            disabled={!doc}
          >
            Print / PDF
          </button>
        </div>
      </ViewPaneHeader>

      <div className="report-scroll">
        {runs.length === 0 && !error && (
          <div className="analytics-empty">
            <p>No stored runs yet. Solve a model, then come back — reports read stored runs.</p>
          </div>
        )}
        {error && (
          <div className="analytics-empty">
            <p style={{ color: 'var(--danger, #dc2626)' }}>{error}</p>
          </div>
        )}
        {busy && !doc && <p className="report-loading">Assembling report…</p>}
        {doc && !error && (
          <>
            {active && (
              <p className="report-audience-note">{active.description}</p>
            )}
            <ReportDocument doc={doc} layout={layout} />
          </>
        )}
      </div>
    </ViewPanel>
  );
}
