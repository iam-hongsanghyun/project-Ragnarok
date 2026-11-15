/**
 * Sessions section: every Ragnarok backend on this machine, the sessions each holds, and which one this
 * screen shows.
 *
 * A machine often runs more than one backend: the app's own and one a host started for an agent (another
 * port, its own data folder). Each keeps one project per session. This screen is bound to one backend and
 * one session (`?api=<base>&session=<id>` in its address, else the app's own backend and `default`); opening
 * another loads that project whole - its model, data, settings, runs and queue - and the list updates by
 * itself as sessions change. Opening reloads the page once.
 *
 * Buttons: Find sessions (look again for backends and sessions), Disconnect (leave the session this screen
 * shows and go back to the app's own backend, `default`), Stop (cancel a backend's running and queued
 * solves; the backend keeps running, so an agent using it stays connected).
 *
 * Working folder: the folder this screen's session works in (`RAGNAROK_DATA_DIR` of its backend). Change… opens
 * the system folder picker; the backend working in the chosen folder is opened, or started on it (as
 * `RAGNAROK_DATA_DIR=<folder> run.command` would), and this screen connects to it. Shut down stops a backend
 * opened this way.
 */
import React, { useCallback, useEffect, useState } from 'react';

import { API_BASE_FROM_ADDRESS } from 'lib/constants';
import {
  DEFAULT_SESSION_ID,
  listServerBackends,
  getDataFolder,
  listServerSessions,
  newestSessionOf,
  openDataFolder,
  pickDataFolder,
  sessionUrl,
  stopBackendSolves,
  stopServerBackend,
  type DataFolderInfo,
  type ServerBackend,
  type ServerSession,
} from 'lib/api/session';
import { useServerChange } from 'shared/hooks/useServerChange';

function formatSaved(iso: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function summary(session: ServerSession): string {
  const counts = session.componentCounts ?? {};
  const parts = ['buses', 'generators', 'lines', 'links', 'storage_units', 'stores', 'loads']
    .filter((k) => counts[k])
    .map((k) => `${counts[k]} ${k.replace('_', ' ')}`);
  if (session.snapshotCount) parts.push(`${session.snapshotCount} snapshots`);
  return parts.join(' · ');
}

/** The `api` parameter a link to this backend needs: none for the app's own backend. */
function apiParamFor(backend: ServerBackend): string {
  return backend.self && !API_BASE_FROM_ADDRESS ? '' : backend.apiBase;
}

function queueText(backend: ServerBackend): string {
  const { running, queued } = backend.queue ?? { running: 0, queued: 0 };
  if (!running && !queued) return '';
  return [running ? `${running} solving` : '', queued ? `${queued} queued` : ''].filter(Boolean).join(', ');
}

export function SessionsSection(): React.ReactElement {
  const [backends, setBackends] = useState<ServerBackend[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [stopping, setStopping] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const connectedElsewhere = Boolean(API_BASE_FROM_ADDRESS) || DEFAULT_SESSION_ID !== 'default';
  const [folder, setFolder] = useState<DataFolderInfo | null>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    void getDataFolder().then(setFolder).catch(() => setFolder(null));
  }, []);

  // Finder (the system picker) chooses the folder; the backend working there is opened, or started, and this
  // screen connects to it.
  const chooseFolder = useCallback(async () => {
    setNotice(null);
    setOpening(true);
    try {
      const path = await pickDataFolder(folder?.current ?? '');
      if (!path) { setOpening(false); return; }
      const opened = await openDataFolder(path);
      const session = await newestSessionOf(opened.apiBase);
      window.location.assign(sessionUrl(session, opened.apiBase));
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not open the folder.');
      setOpening(false);
    }
  }, [folder]);

  const shutDown = useCallback(async (backend: ServerBackend) => {
    if (!window.confirm(`Shut down the backend on ${backend.apiBase}? Its folder keeps every session and run.`)) return;
    try {
      await stopServerBackend(backend.port);
      setNotice(`Shut down ${backend.apiBase}.`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not shut the backend down.');
    }
  }, []);

  const stop = useCallback(async (backend: ServerBackend) => {
    const { running, queued } = backend.queue ?? { running: 0, queued: 0 };
    const where = backend.apiBase || 'this backend';
    if (!window.confirm(`Stop ${running} running and ${queued} queued solve(s) on ${where}? They are cancelled (they can be re-run from the queue); the backend keeps running.`)) return;
    setStopping(backend.apiBase);
    try {
      const n = await stopBackendSolves(backend.apiBase);
      setNotice(`Stopped ${n} solve(s) on ${where}.`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not stop the solves.');
    } finally {
      setStopping(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    setSearching(true);
    try {
      setBackends(await listServerBackends());
      setError(null);
    } catch {
      // A backend older than the discovery route: list its own sessions at least.
      try {
        const sessions = await listServerSessions();
        setBackends([{ apiBase: API_BASE_FROM_ADDRESS, port: 0, dataDir: '', self: true, sessions, queue: { running: 0, queued: 0 } }]);
        setError('This backend cannot list the other backends on this machine (it runs older code).');
      } catch (err) {
        setBackends([]);
        setError(err instanceof Error ? err.message : 'Could not list sessions.');
      }
    } finally {
      setSearching(false);
      setCheckedAt(new Date());
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useServerChange(['sessions', 'queue', 'backends', 'data-folder'], () => { void refresh(); });

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Sessions</h3>
        <p>
          Every Ragnarok backend running on this machine and the projects it holds. This screen shows session{' '}
          <strong>{DEFAULT_SESSION_ID}</strong> of {API_BASE_FROM_ADDRESS ? <strong>{API_BASE_FROM_ADDRESS}</strong> : 'the app’s own backend'}.
          Open another to see its model, data, settings, runs and queue as they are; changes made there by an
          agent appear here live. The list updates by itself.
        </p>
      </header>
      <div className="sessions-toolbar">
        <button type="button" className="tb-btn" onClick={() => { void refresh(); }} disabled={searching}>
          {searching ? 'Finding…' : 'Find sessions'}
        </button>
        {connectedElsewhere && (
          <button type="button" className="tb-btn tb-btn--muted" onClick={() => { window.location.assign(sessionUrl('default', '')); }}>
            Disconnect
          </button>
        )}
        {checkedAt && <span className="sessions-muted">Checked {checkedAt.toLocaleTimeString()}</span>}
      </div>
      {notice && <p className="sessions-muted" role="status">{notice}</p>}
      <div className="sessions-folder sessions-toolbar">
        <span className="sessions-folder__label">Working folder</span>
        <code className="sessions-folder__path">{folder?.current ?? '…'}</code>
        <button type="button" className="tb-btn" onClick={() => { void chooseFolder(); }} disabled={opening}>
          {opening ? 'Opening…' : 'Change…'}
        </button>
      </div>
      {error && <p className="sessions-error" role="alert">{error}</p>}
      {backends === null && !error && <p className="sessions-empty">Looking for backends…</p>}
      {(backends ?? []).map((backend) => {
        const apiParam = apiParamFor(backend);
        const busy = queueText(backend);
        return (
          <div key={backend.apiBase || 'self'} className="sessions-backend">
            <h4 className="sessions-backend__head">
              {backend.self ? 'This screen’s backend' : 'Backend'}{' '}
              <code>{backend.apiBase || 'same origin'}</code>
              {busy && <span className="sessions-badge">{busy}</span>}
              {backend.startedFromRagnarok && !backend.self && (
                <button type="button" className="tb-btn tb-btn--muted" onClick={() => { void shutDown(backend); }}>
                  Shut down
                </button>
              )}
              {busy && (
                <button type="button" className="tb-btn tb-btn--muted" onClick={() => { void stop(backend); }}
                  disabled={stopping === backend.apiBase}>
                  {stopping === backend.apiBase ? 'Stopping…' : 'Stop'}
                </button>
              )}
            </h4>
            {backend.dataDir && <p className="sessions-muted sessions-backend__dir">{backend.dataDir}</p>}
            {backend.sessions.length === 0 ? (
              <p className="sessions-empty">No session holds a project.</p>
            ) : (
              <table className="sessions-table">
                <colgroup>
                  <col className="sessions-col--id" />
                  <col className="sessions-col--project" />
                  <col />
                  <col className="sessions-col--saved" />
                  <col className="sessions-col--actions" />
                </colgroup>
                <thead>
                  <tr><th>Session</th><th>Project</th><th>Contents</th><th>Saved</th><th aria-label="Actions" /></tr>
                </thead>
                <tbody>
                  {backend.sessions.map((s) => {
                    const isCurrent = backend.self && s.id === DEFAULT_SESSION_ID;
                    const href = sessionUrl(s.id, apiParam);
                    return (
                      <tr key={s.id} className={isCurrent ? 'is-current' : undefined}>
                        <td>
                          <strong>{s.id}</strong>
                          {isCurrent && <span className="sessions-badge">this screen</span>}
                        </td>
                        <td>{s.scenarioName || s.filename || '—'}</td>
                        <td className="sessions-muted">{summary(s)}</td>
                        <td className="sessions-muted">{formatSaved(s.savedAt)}</td>
                        <td className="sessions-actions"><div className="sessions-actions__row">
                          {isCurrent ? (connectedElsewhere && (
                            <button type="button" className="tb-btn tb-btn--muted" onClick={() => { window.location.assign(sessionUrl('default', '')); }}>
                              Disconnect
                            </button>
                          )) : (
                            <button type="button" className="tb-btn" onClick={() => { window.location.assign(href); }}>
                              Connect
                            </button>
                          )}
                          <a className="tb-btn tb-btn--muted" href={href} target="_blank" rel="noreferrer">New tab</a>
                        </div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </section>
  );
}
