/**
 * Siting view — power-system location optimisation as a use-case surface.
 *
 * Location optimisation in PyPSA is capacity expansion with a spatial
 * candidate set, so this surface is a thin pipeline over machinery that
 * already exists: draw a candidate region on the map (two clicks), scan it
 * (`POST /api/siting/scan` samples a grid, fetches keyless weather per point,
 * and returns extendable candidate assets), add the candidates to the model
 * via the same fragment merge the Data view uses, and run an ordinary solve.
 * The expansion LP builds capacity only where resource quality beats
 * generator capex + distance-priced grid connection; this view then reads the
 * winners back out of `expansionResults` (candidates are name-prefixed
 * `siting_`) and shows built MW per site on the map and in a table.
 *
 * Goal → candidate set → costs → answer: a use-case surface (like
 * Procurement), not a config panel.
 *
 * The statistical pre-screen of sites and regions on historical series is a module of
 * its own (the Screening tab, `modules/screening/`); this tab is only the
 * expansion-based flow.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { LatLngBoundsExpression } from 'leaflet';
import { ViewPaneHeader } from '../shared/components/primitives';
import { useToast } from '../shared/components/Toast';
import { ExpansionAsset, WorkbookModel } from 'lib/types';
import { WorkbookFragment } from 'lib/api/databases';
import { SitingCandidate, runSitingScan } from 'lib/api/siting';
import { fetchRunAnalysis } from 'lib/api/resultsDerived';
import { useAsync } from '../shared/hooks/useAsync';
import { numberValue, stringValue } from 'lib/utils/helpers';
import { Bbox, SitingMap } from '../features/siting/SitingMap';
import type { SitingHandoff } from 'lib/screening/screening';

interface Props {
  model: WorkbookModel;
  bounds: LatLngBoundsExpression | null;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
  expansionResults: ExpansionAsset[] | null;
  currencySymbol: string;
  /** Settings -> Discount rate: written to every candidate row as `discount_rate` (PyPSA annuitises `overnight_cost` with it). */
  discountRate?: number;
  /** Stored run the siting totals are read from (`analysis/totals`); null = none yet. */
  runName?: string | null;
  /** Pathway investment period; null = the whole horizon. */
  period?: number | null;
  /** Sites carried from the Screening tab ("Open in Siting"); null = none. */
  handoff?: SitingHandoff | null;
  /** Drop the carried sites (the Siting tab keeps its own region and settings). */
  onClearHandoff?: () => void;
}

const WEATHER_SOURCES = [
  { value: 'open-meteo', label: 'Open-Meteo (global ERA5)' },
  { value: 'pvgis', label: 'PVGIS (EU JRC)' },
  { value: 'nasa-power', label: 'NASA POWER (MERRA-2)' },
];

/** Model buses that carry coordinates (PyPSA x = lon, y = lat). */
export function connectableBusesOf(buses: WorkbookModel['buses']): Array<{ name: string; x: number; y: number }> {
  return buses
    .map((b) => {
      const name = stringValue(b.name);
      const x = b.x;
      const y = b.y;
      if (!name || x === undefined || x === null || x === '' || y === undefined || y === null || y === '') return null;
      return { name, x: numberValue(x), y: numberValue(y) };
    })
    .filter(Boolean) as Array<{ name: string; x: number; y: number }>;
}

/** The model's snapshot labels, in order. */
export function snapshotLabelsOf(snapshots: WorkbookModel['snapshots']): string[] {
  return (snapshots ?? []).map((r) => stringValue(r.snapshot)).filter(Boolean);
}

/** Siting tab: candidate scan + expansion solve. */
export function SitingView(props: Props) {
  return (
    <div className="analytics-view">
      <div className="analytics-view-main">
        <ViewPaneHeader variant="analytics">
          <div>
            <p className="eyebrow">Siting</p>
            <h2>Location optimisation</h2>
          </div>
        </ViewPaneHeader>
        <div style={{ display: 'flex', flex: 1, minHeight: 0, flexDirection: 'column' }}>
          <OptimiseStep {...props} />
        </div>
      </div>
    </div>
  );
}

function OptimiseStep({ model, bounds, onApplyFragment, expansionResults, currencySymbol, discountRate, runName = null, period = null, handoff = null, onClearHandoff }: Props) {
  const { showToast } = useToast();

  // ── Scan configuration ────────────────────────────────────────────────
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [solarOn, setSolarOn] = useState(true);
  const [windOn, setWindOn] = useState(true);
  const [gridPoints, setGridPoints] = useState(25);
  const [dateFrom, setDateFrom] = useState('2019-01-01');
  const [dateTo, setDateTo] = useState('2019-01-31');
  const [utcOffset, setUtcOffset] = useState(0);
  const [weatherSource, setWeatherSource] = useState('open-meteo');
  const [siteCapacityMw, setSiteCapacityMw] = useState(400);
  const [solarCapex, setSolarCapex] = useState(35000);
  const [windCapex, setWindCapex] = useState(60000);
  const [connCostPerMwKm, setConnCostPerMwKm] = useState(150);

  // ── Scan result ───────────────────────────────────────────────────────
  const [scanning, setScanning] = useState(false);
  const [candidates, setCandidates] = useState<SitingCandidate[] | null>(null);
  const [fragment, setFragment] = useState<WorkbookFragment | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [applied, setApplied] = useState(false);

  const connectableBuses = useMemo(() => connectableBusesOf(model.buses), [model.buses]);

  // A hand-off from Screening sets the candidate region to the sites' envelope and the technologies to those they use.
  // Applied once per hand-off object; the user's later edits to the region or technologies stand.
  useEffect(() => {
    if (!handoff) return;
    setBbox(handoff.bbox);
    if (handoff.technologies.length > 0) {
      setSolarOn(handoff.technologies.includes('solar'));
      setWindOn(handoff.technologies.includes('wind'));
    }
    setCandidates(null);
    setFragment(null);
    setApplied(false);
  }, [handoff]);

  // Candidates already merged into the workbook (an earlier apply, possibly a
  // previous session) — lets the results table work without a fresh scan.
  const sitingAssets = useMemo(
    () => (expansionResults ?? []).filter((a) => a.name.startsWith('siting_')),
    [expansionResults],
  );
  // MW built per site bus, the total and the annual capex are server sums over those rows.
  const totals = useAsync(
    runName && sitingAssets.length > 0 ? `${runName}|siting-totals|${period ?? ''}` : null,
    () => fetchRunAnalysis(runName as string, 'totals', { period }),
  );
  const builtMwBySiteBus = useMemo(() => totals.data?.siting?.builtMwBySiteBus ?? {}, [totals.data]);
  const builtTotalMw = totals.data?.siting?.builtTotalMw ?? 0;
  const sitingCapexAnnual = totals.data?.siting?.capexAnnual ?? 0;

  // Land candidate profiles on the model's EXISTING snapshots (tiled) so the
  // solve window keeps its demand data; importing the weather window as new
  // snapshots would leave the load series empty there and nothing would build.
  const targetSnapshots = useMemo(() => snapshotLabelsOf(model.snapshots), [model.snapshots]);

  const technologies = [...(solarOn ? ['solar'] : []), ...(windOn ? ['wind'] : [])];
  const canScan = !!bbox && technologies.length > 0 && connectableBuses.length > 0 && !scanning;

  const handleScan = async () => {
    if (!bbox) return;
    setScanning(true);
    setApplied(false);
    try {
      const resp = await runSitingScan({
        bbox,
        technologies,
        gridPoints,
        dateFrom,
        dateTo,
        utcOffset,
        weatherSource,
        performanceRatio: 0.9,
        buses: connectableBuses,
        siteCapacityMw,
        capitalCostPerMw: { solar: solarCapex, wind: windCapex },
        connectionCostPerMwKm: connCostPerMwKm,
        discountRate,
        marginalCost: 0,
        targetSnapshots: targetSnapshots.length > 0 ? targetSnapshots : undefined,
      });
      setCandidates(resp.candidates);
      setFragment(resp.fragment);
      setNotes(resp.preview.notes ?? []);
      showToast(`Scanned ${resp.candidates.length} candidate site(s).`, 'success');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Siting scan failed.';
      showToast(msg, 'error');
    } finally {
      setScanning(false);
    }
  };

  const handleApply = () => {
    if (!fragment || !candidates) return;
    onApplyFragment(fragment, 'Siting candidates', `${candidates.length} site(s)`);
    setApplied(true);
  };

  return (
    <>
      <div className="inline-stats" style={{ padding: '8px 16px 0' }}>
        <span>{connectableBuses.length} grid buses</span>
        {candidates && <span>{candidates.length} candidates</span>}
        {builtTotalMw > 0 && <span>{Math.round(builtTotalMw)} MW sited</span>}
      </div>

      <div style={{ display: 'flex', gap: 16, padding: 16, flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {/* ── Left rail: goal → candidate set → costs ── */}
        <aside style={{ width: 300, flexShrink: 0, overflowY: 'auto', paddingRight: 4 }}>
          {handoff && (
            <div className="sg-setting-row" data-tour="siting-handoff">
              <label className="sg-setting-label">From Screening · {handoff.sites.length} site(s)</label>
              <p className="sg-setting-hint">
                {handoff.sites.map((s) => `${s.name} (${s.technology})`).join(', ')}. The candidate region below is their
                envelope plus a margin, and the technologies are the ones these sites use; the scan samples candidates over
                that region, and the screened sites are the dots on the map.
                {handoff.withoutLocation.length > 0 && ` Left behind, no location: ${handoff.withoutLocation.join(', ')}.`}
              </p>
              {onClearHandoff && <button className="tb-btn tb-btn--muted" onClick={onClearHandoff}>Clear screened sites</button>}
            </div>
          )}
          <div className="sg-setting-row">
            <label className="sg-setting-label">1 · Candidate region</label>
            <p className="sg-setting-hint">
              Click two opposite corners on the map to draw the region to scan.
            </p>
            {bbox ? (
              <div className="sg-btn-row" style={{ gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 12 }}>
                  {bbox[1].toFixed(2)}–{bbox[3].toFixed(2)}N · {bbox[0].toFixed(2)}–{bbox[2].toFixed(2)}E
                </span>
                <button className="tb-btn tb-btn--muted" onClick={() => setBbox(null)}>Clear</button>
              </div>
            ) : (
              <p className="sg-setting-hint">No region yet.</p>
            )}
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">2 · Technologies</label>
            <div className="sg-btn-row">
              <button
                className={`tb-btn sg-solver-btn${solarOn ? '' : ' tb-btn--muted'}`}
                onClick={() => setSolarOn(!solarOn)}
              >
                Solar
              </button>
              <button
                className={`tb-btn sg-solver-btn${windOn ? '' : ' tb-btn--muted'}`}
                onClick={() => setWindOn(!windOn)}
              >
                Wind
              </button>
            </div>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Candidate sites · weather window</label>
            <div className="sg-btn-row" style={{ gap: 8 }}>
              <input
                type="number" className="sg-number-input" min={1} max={200} step={1}
                value={gridPoints} onChange={(e) => setGridPoints(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
                title="Number of candidate sites sampled across the region"
              />
              <input
                type="date" className="sg-number-input" value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)} title="Weather window start (UTC)"
              />
              <input
                type="date" className="sg-number-input" value={dateTo}
                onChange={(e) => setDateTo(e.target.value)} title="Weather window end (UTC)"
              />
            </div>
            <p className="sg-setting-hint">
              Weather from this window is tiled onto the model&apos;s existing snapshots, so
              pick a window that represents the season you are planning for. Site count
              times hours grows the expansion LP fast — a short window screens well;
              confirm shortlisted sites with a full-year run.
            </p>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Weather source · local UTC offset</label>
            <div className="sg-btn-row" style={{ gap: 8 }}>
              <select
                className="sg-number-input" value={weatherSource}
                onChange={(e) => setWeatherSource(e.target.value)}
              >
                {WEATHER_SOURCES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
              <input
                type="number" className="sg-number-input" min={-12} max={14} step={1}
                value={utcOffset} onChange={(e) => setUtcOffset(Number(e.target.value) || 0)}
                title="Shift snapshots from UTC to local time (e.g. 9 for Korea)"
                style={{ width: 64 }}
              />
            </div>
          </div>

          <div className="sg-setting-divider" />

          <div className="sg-setting-row">
            <label className="sg-setting-label">3 · Costs ({currencySymbol}/MW)</label>
            <p className="sg-setting-hint">
              Per-site build cap (MW), then solar and wind overnight capex per MW — the
              solver annuitises it with the model discount rate and lifetime.
            </p>
            <div className="sg-btn-row" style={{ gap: 8 }}>
              <input
                type="number" className="sg-number-input" min={1} step={50}
                value={siteCapacityMw} onChange={(e) => setSiteCapacityMw(Math.max(1, Number(e.target.value) || 1))}
                title="Per-site build ceiling (p_nom_max, MW)"
              />
              <input
                type="number" className="sg-number-input" min={0} step={1000}
                value={solarCapex} onChange={(e) => setSolarCapex(Math.max(0, Number(e.target.value) || 0))}
                title={`Solar capital cost (${currencySymbol}/MW)`}
              />
              <input
                type="number" className="sg-number-input" min={0} step={1000}
                value={windCapex} onChange={(e) => setWindCapex(Math.max(0, Number(e.target.value) || 0))}
                title={`Wind capital cost (${currencySymbol}/MW)`}
              />
            </div>
          </div>

          <div className="sg-setting-row">
            <label className="sg-setting-label">Grid connection ({currencySymbol}/MW·km)</label>
            <input
              type="number" className="sg-number-input" min={0} step={10}
              value={connCostPerMwKm} onChange={(e) => setConnCostPerMwKm(Math.max(0, Number(e.target.value) || 0))}
              title="Connection capex rate; each candidate pays rate times distance to its nearest bus"
            />
            <p className="sg-setting-hint">
              Each candidate connects to its nearest bus via an extendable link priced at
              rate times distance — great resource far from the grid competes against
              mediocre resource next to it.
            </p>
            <p className="sg-setting-hint">
              The prices above are OVERNIGHT: each candidate carries PyPSA&apos;s overnight_cost with a
              25-year life (40 for the connection) and the discount rate from Settings, and PyPSA annuitises it
              and scales it by the modelled horizon, so a short sample is priced against its own share of the year.
            </p>
          </div>

          <div className="sg-setting-divider" />

          <div className="sg-setting-row">
            <div className="sg-btn-row" style={{ gap: 8 }}>
              <button className="tb-btn" disabled={!canScan} onClick={handleScan}>
                {scanning ? 'Scanning…' : '4 · Scan candidates'}
              </button>
              <button className="tb-btn" disabled={!fragment || applied} onClick={handleApply}>
                {applied ? 'Added' : '5 · Add to model'}
              </button>
            </div>
            {connectableBuses.length === 0 && (
              <p className="sg-setting-hint">
                The model has no buses with coordinates — build or import a network first.
              </p>
            )}
            {notes.map((n) => (
              <p key={n} className="sg-setting-hint">{n}</p>
            ))}
            {applied && (
              <p className="sg-setting-hint">
                Candidates are in the model. Run a solve (Analytics view) — the expansion
                picks the winning sites, and built MW appears here and on the map.
              </p>
            )}
          </div>
        </aside>

        {/* ── Map + tables ── */}
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, overflowY: 'auto' }}>
          <SitingMap
            buses={model.buses}
            bounds={bounds}
            bbox={bbox}
            onBboxChange={setBbox}
            candidates={candidates}
            builtMwBySiteBus={builtMwBySiteBus}
            currencySymbol={currencySymbol}
            screenedSites={handoff?.sites ?? null}
          />

          {candidates && candidates.length > 0 && (
            <div>
              <p className="eyebrow">Candidates</p>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Site</th>
                    <th>Lat / Lon</th>
                    {solarOn && <th>Solar CF</th>}
                    {windOn && <th>Wind CF</th>}
                    <th>Grid bus</th>
                    <th>Distance</th>
                    <th>Connection {currencySymbol}/MW</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.id}>
                      <td>{c.id}</td>
                      <td>{c.lat.toFixed(2)} / {c.lon.toFixed(2)}</td>
                      {solarOn && <td>{((c.meanCf.solar ?? 0) * 100).toFixed(0)}%</td>}
                      {windOn && <td>{((c.meanCf.wind ?? 0) * 100).toFixed(0)}%</td>}
                      <td>{c.gridBus}</td>
                      <td>{c.distanceKm} km</td>
                      <td>{Math.round(c.connectionCostPerMw).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sitingAssets.length > 0 && (
            <div>
              <p className="eyebrow">
                Siting result — {Math.round(builtTotalMw)} MW built · {currencySymbol}
                {Math.round(sitingCapexAnnual).toLocaleString()}/yr capex
              </p>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Carrier</th>
                    <th>Bus</th>
                    <th>Built MW</th>
                    <th>Annual capex</th>
                  </tr>
                </thead>
                <tbody>
                  {sitingAssets
                    .filter((a) => a.component === 'Generator')
                    .sort((a, b) => b.delta_mw - a.delta_mw)
                    .map((a) => (
                      <tr key={a.name} style={a.delta_mw > 0 ? undefined : { opacity: 0.55 }}>
                        <td>{a.name}</td>
                        <td>{a.carrier}</td>
                        <td>{a.bus}</td>
                        <td>{a.delta_mw.toFixed(1)}</td>
                        <td>{currencySymbol}{a.capex_annual.toLocaleString()}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              <p className="sg-setting-hint">
                Zero-built rows are rejected locations — the LP found their resource not
                worth the capex plus connection cost.
              </p>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
