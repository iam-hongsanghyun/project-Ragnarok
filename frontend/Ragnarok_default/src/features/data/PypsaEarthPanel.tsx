/**
 * PyPSA-Earth whole-country network builder (I9) — Data-view right rail.
 *
 * Focused from the left rail like a source, but it's an async server job: submit
 * a build, poll it, then apply the ingested network through the same
 * `applyFragment` path importers use. Availability-gated — on a server without
 * PyPSA-Earth configured it shows setup guidance instead of a build form.
 */
import React, { useEffect, useRef, useState } from 'react';
import type { WorkbookFragment } from 'lib/api/databases';
import {
  checkAvailable,
  getBuildResult,
  getBuildStatus,
  startBuild,
  type BuildJobStatus,
  type PypsaEarthAvailability,
} from 'lib/api/pypsaEarth';

interface Props {
  selectedCountry: { iso: string; name: string } | null;
  applyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function PypsaEarthPanel({ selectedCountry, applyFragment }: Props) {
  const [avail, setAvail] = useState<PypsaEarthAvailability | null>(null);
  const [horizon, setHorizon] = useState(2030);
  const [clusters, setClusters] = useState(10);
  const [job, setJob] = useState<BuildJobStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    checkAvailable().then((a) => mounted.current && setAvail(a)).catch(() => {});
    return () => { mounted.current = false; };
  }, []);

  const build = async () => {
    if (!selectedCountry) return;
    setBusy(true); setError(null); setJob(null);
    try {
      let s = await startBuild({
        countryIso: selectedCountry.iso, countryName: selectedCountry.name,
        horizonYear: horizon, clusters,
      });
      setJob(s);
      // The real build is minutes–hours; poll generously until terminal.
      for (let i = 0; i < 4000 && (s.status === 'queued' || s.status === 'running'); i++) {
        await sleep(2500);
        if (!mounted.current) return;
        s = await getBuildStatus(s.jobId);
        setJob(s);
      }
      if (s.status === 'error') {
        setError(s.error || 'Build failed.');
      } else if (s.status === 'done') {
        const res = await getBuildResult(s.jobId);
        applyFragment(res.fragment, 'PyPSA-Earth', selectedCountry.name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed.');
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <aside className="view-rail view-rail--right data-import-filters">
      <div className="view-rail-header"><span>PyPSA-Earth</span></div>
      <div className="view-rail-body data-import-filters__body">
        <p className="sg-setting-hint">
          Build an entire country's network — buses, lines, power plants with capacities, renewable
          profiles and demand — from PyPSA-Earth, then merge it into the workbook. This is a
          long-running server job, not an instant fetch.
        </p>

        {!avail ? (
          <p className="sg-setting-hint">Checking availability…</p>
        ) : !avail.available ? (
          <div className="pe-panel__notice">
            <strong>Not configured on this server.</strong>
            <p className="sg-setting-hint">{avail.detail}</p>
            <p className="sg-setting-hint">See <code>{avail.docs}</code>.</p>
          </div>
        ) : (
          <>
            <div className="pe-panel__row">
              <label>Horizon year
                <input type="number" className="ss-input" min={2020} max={2100} value={horizon}
                  onChange={(e) => setHorizon(Math.trunc(Number(e.target.value) || 2030))} />
              </label>
              <label>Clusters (buses)
                <input type="number" className="ss-input" min={1} max={512} value={clusters}
                  onChange={(e) => setClusters(Math.max(1, Math.trunc(Number(e.target.value) || 10)))} />
              </label>
            </div>
            <button className="run-button" disabled={!selectedCountry || busy} onClick={build}>
              {busy ? 'Building…' : selectedCountry ? `Build ${selectedCountry.name}` : 'Pick a country first'}
            </button>
            {job && (
              <p className="sg-setting-hint">
                <b>{job.status}</b> — {job.phase}{job.detail ? `: ${job.detail}` : ''}
              </p>
            )}
          </>
        )}
        {error && <p className="pe-panel__error">{error}</p>}
      </div>
    </aside>
  );
}
