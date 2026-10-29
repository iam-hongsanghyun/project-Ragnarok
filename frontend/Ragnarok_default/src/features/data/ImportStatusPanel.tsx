/**
 * Importer status (Data view): the database registry, upstream reachability and the import provenance log.
 *
 *  - `GET /api/import/databases`: every dataset with its licence, version hint and availability.
 *  - `GET /api/import/health`: one probe per upstream source (takes a few seconds, so it runs on request).
 *  - `GET /api/import/provenance`: the append-only log of imports, newest first.
 * Collapsed by default; the registry and log load the first time it is opened.
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  getImportHealth,
  getImportProvenance,
  listImportDatabases,
  type ProvenanceEntry,
  type RegistryEntry,
  type SourceHealth,
} from 'lib/api/importerStatus';

/** `{"buses": 12, "lines": 30}` (a JSON string from the log) -> "buses 12, lines 30"; unparsable text is shown as is. */
export function formatRowCounts(raw: string): string {
  if (!raw) return '';
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return Object.entries(parsed).map(([k, v]) => `${k} ${String(v)}`).join(', ');
  } catch {
    return raw;
  }
}

function healthText(h: SourceHealth | undefined): string {
  if (!h) return 'not checked';
  return h.ok ? `reachable, ${Math.round(h.latencyMs)} ms` : `unreachable${h.error ? ` (${h.error})` : h.status ? ` (HTTP ${h.status})` : ''}`;
}

export function ImportStatusPanel() {
  const [loaded, setLoaded] = useState(false);
  const started = useRef(false);
  const [databases, setDatabases] = useState<RegistryEntry[]>([]);
  const [imports, setImports] = useState<ProvenanceEntry[]>([]);
  const [health, setHealth] = useState<Record<string, SourceHealth>>({});
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [dbs, log] = await Promise.all([listImportDatabases(), getImportProvenance(50)]);
      setDatabases(dbs);
      setImports(log);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the importer status.');
    } finally {
      setLoaded(true);
    }
  }, []);

  const checkHealth = async () => {
    setChecking(true);
    try {
      setHealth(await getImportHealth());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Source health check failed.');
    } finally {
      setChecking(false);
    }
  };

  return (
    <details
      className="import-status"
      onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open && !started.current) { started.current = true; void load(); } }}
    >
      <summary>Source status and import history</summary>
      <div className="import-status__body">
        {error && <p className="sg-setting-hint" role="alert">{error}</p>}

        <div className="import-status__head">
          <b>Databases</b>
          <button type="button" className="tb-btn" disabled={checking} onClick={() => void checkHealth()}>
            {checking ? 'Checking sources' : 'Check source health'}
          </button>
        </div>
        <div className="import-status__scroll">
          <table className="data-table">
            <thead>
              <tr><th>Database</th><th>Source</th><th>Licence</th><th>Version</th><th>Availability</th><th>Upstream</th></tr>
            </thead>
            <tbody>
              {databases.map((d) => (
                <tr key={d.id}>
                  <td>{d.short_name || d.name}</td>
                  <td>{d.source_label || d.source_id || d.id}</td>
                  <td>{d.license}</td>
                  <td>{d.version_hint}</td>
                  <td>{d.available ? (d.requires_secrets?.length ? `needs key: ${d.requires_secrets.join(', ')}` : 'available') : (d.unavailable_reason || 'unavailable')}</td>
                  <td>{healthText(health[d.source_id ?? d.id])}</td>
                </tr>
              ))}
              {loaded && databases.length === 0 && <tr><td colSpan={6}>No databases registered.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="import-status__head"><b>Recent imports</b></div>
        {loaded && imports.length === 0 ? (
          <p className="sg-setting-hint">No imports recorded yet.</p>
        ) : (
          <div className="import-status__scroll">
            <table className="data-table">
              <thead>
                <tr><th>Version</th><th>Recorded</th><th>Source</th><th>Datasets</th><th>Country</th><th>Rows</th></tr>
              </thead>
              <tbody>
                {imports.map((i) => (
                  <tr key={i.version} title={i.filters}>
                    <td>{i.version}</td>
                    <td>{i.recordedAt}</td>
                    <td>{i.sourceId}</td>
                    <td>{(i.datasetIds.length ? i.datasetIds : [i.databaseId]).filter(Boolean).join(', ')}</td>
                    <td>{i.countryName || i.countryIso}</td>
                    <td>{formatRowCounts(i.rowCounts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
}
