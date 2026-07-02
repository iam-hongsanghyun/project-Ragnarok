/**
 * PyPSA-Earth whole-country network builder (I9) — Data-view right rail.
 *
 * The build is a long server-side job, so this panel is deliberately stateless
 * about it: the active jobId is persisted and the panel RE-ATTACHES on mount
 * (tab switches, reloads and unmounts never stop the build — the only way to
 * stop it is the Stop button). Polling drives the status/progress/log display;
 * when a build finishes, its network is applied to the workbook exactly once.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { WorkbookFragment } from 'lib/api/databases';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import {
  checkAvailable,
  configureEnv,
  getBuildResult,
  getBuildStatus,
  listBuilds,
  startBuild,
  stopBuild,
  type BuildJobStatus,
  type PypsaEarthAvailability,
} from 'lib/api/pypsaEarth';

interface Props {
  selectedCountry: { iso: string; name: string } | null;
  applyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

const KEY_JOB = 'ragnarok:pypsa-earth:job-id';
const KEY_APPLIED = 'ragnarok:pypsa-earth:applied-job-ids';
const POLL_MS = 2500;

const isActive = (s: BuildJobStatus['status'] | undefined) => s === 'queued' || s === 'running';

export function PypsaEarthPanel({ selectedCountry, applyFragment }: Props) {
  const [avail, setAvail] = useState<PypsaEarthAvailability | null>(null);
  const [horizon, setHorizon] = useState(2030);
  const [clusters, setClusters] = useState(10);
  const [jobId, setJobId] = usePersistedState<string | null>(KEY_JOB, null);
  const [appliedIds, setAppliedIds] = usePersistedState<string[]>(KEY_APPLIED, []);
  const [job, setJob] = useState<BuildJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dir, setDir] = useState('');
  const [configuring, setConfiguring] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const logRef = useRef<HTMLPreElement>(null);
  const applyingRef = useRef(false);

  // Availability + re-attach: if we aren't tracking a job (or ours is gone),
  // adopt any build the backend says is still running — a build started before
  // a tab switch or reload keeps going and shows up here again.
  useEffect(() => {
    let alive = true;
    checkAvailable().then((a) => alive && setAvail(a)).catch(() => {});
    listBuilds()
      .then(({ jobs }) => {
        if (!alive) return;
        const running = [...jobs].reverse().find((entry) => isActive(entry.status));
        if (running && (!jobId || !jobs.some((entry) => entry.jobId === jobId && isActive(entry.status)))) {
          setJobId(running.jobId);
        }
      })
      .catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyOnce = useCallback(async (s: BuildJobStatus) => {
    if (applyingRef.current || appliedIds.includes(s.jobId)) return;
    applyingRef.current = true;
    try {
      const res = await getBuildResult(s.jobId);
      applyFragment(res.fragment, 'PyPSA-Earth', s.countryName || s.countryIso || 'the selected country');
      setAppliedIds([...appliedIds, s.jobId]);
    } finally {
      applyingRef.current = false;
    }
  }, [appliedIds, applyFragment, setAppliedIds]);

  // Poll the tracked job. Unmount only stops the POLLING — never the build;
  // the mount effect above re-attaches next time the panel renders.
  useEffect(() => {
    if (!jobId) { setJob(null); return; }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const s = await getBuildStatus(jobId);
        if (!alive) return;
        setJob(s);
        if (s.status === 'done') void applyOnce(s);
        if (isActive(s.status)) timer = setTimeout(tick, POLL_MS);
      } catch {
        // Unknown job (backend restarted; registry is in-memory) — let go. Any
        // orphaned workflow is reclaimed automatically by the next build.
        if (alive) { setJob(null); setJobId(null); }
      }
    };
    void tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [jobId, applyOnce, setJobId]);

  // Keep the streamed log pinned to the newest line.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job?.log]);

  const build = async () => {
    if (!selectedCountry) return;
    setError(null);
    try {
      const s = await startBuild({
        countryIso: selectedCountry.iso, countryName: selectedCountry.name,
        horizonYear: horizon, clusters,
      });
      setJob(s);
      setJobId(s.jobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed to start.');
    }
  };

  const stop = async () => {
    if (!jobId) return;
    try {
      const s = await stopBuild(jobId);
      setJob(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Stop failed.');
    }
  };

  const applyDirectory = async (path?: string) => {
    const target = (path ?? dir).trim();
    if (!target) return;
    setConfiguring(true); setConfigError(null);
    try {
      const a = await configureEnv(target);
      setAvail(a);  // flips to the build form when valid
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : 'Could not use that directory.');
    } finally {
      setConfiguring(false);
    }
  };

  const active = isActive(job?.status);

  return (
    <aside className="view-rail view-rail--right data-import-filters">
      <div className="view-rail-header"><span>PyPSA-Earth</span></div>
      <div className="view-rail-body data-import-filters__body">
        <p className="sg-setting-hint">
          Build an entire country's network — buses, lines, power plants with capacities, renewable
          profiles and demand — from PyPSA-Earth, then merge it into the workbook. The build runs on
          the server: switching tabs or closing this panel never stops it — only the Stop button does.
        </p>

        {!avail ? (
          <p className="sg-setting-hint">Checking availability…</p>
        ) : !avail.available ? (
          <div className="pe-panel__notice">
            <strong>Not configured on this server.</strong>
            <p className="sg-setting-hint">
              Point Ragnarok at a pypsa-earth checkout on the <b>server</b> (the machine running the
              backend). It must have its conda env installed and a CDS API key configured.
            </p>
            {(avail.candidates?.length ?? 0) > 0 && (
              <div className="pe-panel__found">
                <span className="sg-setting-hint">Found on this server — click to use:</span>
                {avail.candidates!.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className="pe-panel__candidate"
                    disabled={configuring}
                    onClick={() => { setDir(c); void applyDirectory(c); }}
                    title={c}
                  >
                    {c}
                  </button>
                ))}
              </div>
            )}
            <label className="pe-panel__dir">
              PyPSA-Earth directory (server path)
              <input
                type="text"
                className="ss-input"
                placeholder="/path/to/pypsa-earth"
                value={dir}
                onChange={(e) => setDir(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void applyDirectory(); }}
              />
            </label>
            <button className="run-button" disabled={!dir.trim() || configuring} onClick={() => applyDirectory()}>
              {configuring ? 'Checking…' : 'Use this directory'}
            </button>
            {configError && <p className="pe-panel__error">{configError}</p>}
            <details className="pe-panel__setup">
              <summary>First time? One-time setup</summary>
              <p className="sg-setting-hint">Run these on the server, then paste the path above:</p>
              <pre className="pe-panel__cmd">{`git clone https://github.com/pypsa-meets-earth/pypsa-earth
cd pypsa-earth
conda env create -f envs/environment.yaml   # ~20-30 min
# then add a CDS API key: https://cds.climate.copernicus.eu (see ~/.cdsapirc)`}</pre>
              <p className="sg-setting-hint">Full guide: <code>{avail.docs}</code>.</p>
            </details>
          </div>
        ) : (
          <>
            <div className="pe-panel__row">
              <label>Horizon year
                <input type="number" className="ss-input" min={2020} max={2100} value={horizon}
                  disabled={active}
                  onChange={(e) => setHorizon(Math.trunc(Number(e.target.value) || 2030))} />
              </label>
              <label>Clusters (buses)
                <input type="number" className="ss-input" min={1} max={512} value={clusters}
                  disabled={active}
                  onChange={(e) => setClusters(Math.max(1, Math.trunc(Number(e.target.value) || 10)))} />
              </label>
            </div>
            <div className="pe-panel__actions">
              <button className="run-button" disabled={!selectedCountry || active} onClick={build}>
                {active
                  ? `Building ${job?.countryName || job?.countryIso || ''}…`
                  : selectedCountry ? `Build ${selectedCountry.name}` : 'Pick a country first'}
              </button>
              {active && (
                <button className="pe-panel__stop" onClick={stop} title="Stop the build (completed steps are kept)">
                  Stop
                </button>
              )}
            </div>
            {job && (
              <div className="pe-panel__job">
                <p className="sg-setting-hint">
                  <b>{job.status}</b> — {job.phase}
                  {typeof job.progress === 'number' ? ` · ${job.progress}%` : ''}
                  {job.detail ? `: ${job.detail}` : ''}
                </p>
                {typeof job.progress === 'number' && (
                  <div className="pe-panel__bar"><span style={{ width: `${Math.max(2, Math.min(100, job.progress))}%` }} /></div>
                )}
                {job.log && job.log.length > 0 && (
                  <pre ref={logRef} className="pe-panel__log">{job.log.join('\n')}</pre>
                )}
                {job.status === 'error' && job.error && <p className="pe-panel__error">{job.error}</p>}
                {job.status === 'done' && appliedIds.includes(job.jobId) && (
                  <p className="sg-setting-hint">Network added to the workbook — see Model or Build.</p>
                )}
              </div>
            )}
          </>
        )}
        {error && <p className="pe-panel__error">{error}</p>}
      </div>
    </aside>
  );
}
