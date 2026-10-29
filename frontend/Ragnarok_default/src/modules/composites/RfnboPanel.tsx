/**
 * RfnboPanel — the Composites -> Rules RFNBO matching rules (Commission Delegated Regulation (EU) 2023/1184) as run settings, with the
 * additionality and geographic checks shown BEFORE the solve. The settings are stored for the session and ride with
 * the next solve that does not set its own `options.rfnboConfig`; the checks come from `/api/p2x/rfnbo/checks`.
 */
import React from 'react';
import type { CheckRow, RfnboChecks, RfnboConfig } from 'lib/api/p2x';
import { fetchRfnboChecks, fetchRfnboConfig, saveRfnboConfig } from 'lib/api/p2x';
import type { WorkbookModel } from 'lib/types';
import { stringValue } from 'lib/utils/helpers';

interface Props { model: WorkbookModel }

const firstSnapshotYear = (model: WorkbookModel): number | null => {
  const raw = stringValue(model.snapshots?.[0]?.snapshot);
  const y = Number(raw.slice(0, 4));
  return Number.isFinite(y) && y > 0 ? y : null;
};

function StatusChip({ status }: { status: string }) {
  return <span className={`p2x-chip p2x-chip--${status}`}>{status}</span>;
}

function CheckTable({ title, rows, label }: { title: string; rows: CheckRow[]; label: string }) {
  return (
    <>
      <h4>{title}</h4>
      {rows.length === 0 ? <p className="p2x-src">No designated generators.</p> : (
        <table className="p2x-table" aria-label={label}>
          <thead><tr><th>Generator</th><th>Status</th><th>Why</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.generator}><td>{r.generator}</td><td><StatusChip status={r.status} /></td><td>{r.reason}</td></tr>)}</tbody>
        </table>
      )}
    </>
  );
}

export function RfnboPanel({ model }: Props) {
  const [cfg, setCfg] = React.useState<RfnboConfig | null>(null);
  const [saved, setSaved] = React.useState<string>('');
  const [checks, setChecks] = React.useState<RfnboChecks | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    fetchRfnboConfig()
      .then((r) => { if (live) setCfg(r.config ?? r.defaults); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  React.useEffect(() => {
    if (!cfg) return undefined;
    let live = true;
    const timer = window.setTimeout(() => {
      fetchRfnboChecks(cfg, model)
        .then((c) => { if (live) { setChecks(c); setError(null); } })
        .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [cfg, model]);

  if (!cfg) return <div className="p2x-results">{error ? <div className="p2x-error">{error}</div> : <p className="p2x-note">Loading RFNBO settings…</p>}</div>;

  const set = (patch: Partial<RfnboConfig>) => { setCfg({ ...cfg, ...patch }); setSaved(''); };
  const year = firstSnapshotYear(model);
  const monthlyTooLate = cfg.temporal === 'monthly' && year !== null && year >= 2030;
  const save = async () => {
    try {
      await saveRfnboConfig(cfg);
      setSaved('Saved. The next solve uses these settings unless it sets its own rfnboConfig.');
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="p2x-results">
      <div className="p2x-grid">
        <div>
          <div className="p2x-card">
            <h3>Matching rules</h3>
            <p className="p2x-note">When on, the solve adds: electrolyser electricity in each period ≤ the designated renewable generators’ output in the same period (PPA matching, Art. 6). Additionality and geography are checks and candidate filters, not LP constraints.</p>
            <div className="p2x-row">
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> <b>RFNBO matching on</b></label></div>
            <div className="p2x-row"><label htmlFor="rf-temporal">Temporal correlation</label>
              <select id="rf-temporal" value={cfg.temporal} onChange={(e) => set({ temporal: e.target.value as RfnboConfig['temporal'] })}>
                <option value="hourly">Hourly (every snapshot)</option>
                <option value="monthly">Monthly (calendar month)</option>
                <option value="auto">Auto (monthly before 2030, hourly from)</option>
              </select></div>
            <p className="p2x-src">Art. 6: monthly is accepted until 31 Dec 2029; hourly from 1 Jan 2030 (a Member State may apply it from 1 Jul 2027). Monthly sums over the snapshots of each month with the snapshot weightings.</p>
            {monthlyTooLate && <div className="p2x-warn">The model starts in {year}: monthly matching is no longer accepted from 1 Jan 2030, so a monthly result would not demonstrate compliance.</div>}
            {cfg.temporal === 'auto' && <div className="p2x-row"><label htmlFor="rf-from">Hourly from</label><input id="rf-from" type="text" value={cfg.hourlyFrom} onChange={(e) => set({ hourlyFrom: e.target.value })} /></div>}
            <h4>Additionality (Art. 5(a), 3(b))</h4>
            <div className="p2x-row">
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={cfg.enforceAdditionality} onChange={(e) => set({ enforceAdditionality: e.target.checked })} /> Drop designated generators that fail (candidate filter)</label></div>
            <div className="p2x-row"><label htmlFor="rf-months">Window</label>
              <input id="rf-months" type="number" min="0" value={cfg.additionalityMonths} onChange={(e) => set({ additionalityMonths: Number(e.target.value) })} /> months before the electrolyser
              <select aria-label="Unknown build year" value={cfg.unknownBuildYearAs} onChange={(e) => set({ unknownBuildYearAs: e.target.value as 'fail' | 'pass' })}>
                <option value="fail">no build_year counts as fail</option><option value="pass">no build_year counts as pass</option></select></div>
            <h4>Geographic correlation (Art. 7(1)(a))</h4>
            <div className="p2x-row">
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={cfg.enforceGeographic} onChange={(e) => set({ enforceGeographic: e.target.checked })} /> Drop designated generators in another bidding zone</label></div>
            <div className="p2x-row"><label htmlFor="rf-zone">Zone column</label>
              <input id="rf-zone" type="text" value={cfg.zoneColumn ?? ''} placeholder="bidding_zone | zone | country" onChange={(e) => set({ zoneColumn: e.target.value || null })} /></div>
            <h4>Art. 6(3) price rule</h4>
            <div className="p2x-row">
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={cfg.priceRule.enabled} onChange={(e) => set({ priceRule: { ...cfg.priceRule, enabled: e.target.checked } })} /> Report hours at or below</label>
              <input aria-label="Price threshold" type="number" value={cfg.priceRule.thresholdEurPerMwh} onChange={(e) => set({ priceRule: { ...cfg.priceRule, thresholdEurPerMwh: Number(e.target.value) } })} /> EUR/MWh (informational)</div>
            <div className="p2x-row">
              <button type="button" className="p2x-btn p2x-btn--primary" onClick={save}>Save settings</button>
              {saved && <span className="p2x-src" role="status">{saved}</span>}</div>
            {error && <div className="p2x-error" role="alert">{error}</div>}
          </div>
        </div>
        <div>
          <div className="p2x-card">
            <h3>Checks before the solve</h3>
            {!checks && <p className="p2x-note">Checking…</p>}
            {checks && (<>
              <p className="p2x-note">Electrolyser: {checks.electrolysers.join(', ') || 'none found'} · designated: {checks.designated.join(', ') || 'none'}</p>
              {checks.electrolysers.length === 0 && <div className="p2x-warn">No electrolyser in the model: add a P2X composite first. A solve with matching on would be refused.</div>}
              {checks.designated.length === 0 && checks.electrolysers.length > 0 && <div className="p2x-warn">No designated generators: pick them under Connections of the P2X composite (or the solve is refused).</div>}
              {checks.willBeRefused && checks.designated.length > 0 && <div className="p2x-error">With these settings no designated generator is eligible, so a solve with matching on would be refused.</div>}
              <CheckTable title="Additionality" rows={checks.additionality} label="Additionality checks" />
              <CheckTable title="Geographic correlation" rows={checks.geographic} label="Geographic checks" />
              {checks.dropped.length > 0 && <>
                <h4>Dropped by the filters</h4>
                <ul>{checks.dropped.map((d) => <li key={d.generator}>{d.generator}: {d.rule}</li>)}</ul></>}
              <h4>Needs attestation or a solved run</h4>
              <table className="p2x-table" aria-label="Attestation items">
                <tbody>{checks.attest.map((a) => <tr key={a.article}><td>{a.article}</td><td>{a.rule}</td><td><StatusChip status={a.status} /></td></tr>)}</tbody>
              </table>
              <p className="p2x-src">{checks.regulation}</p>
            </>)}
          </div>
        </div>
      </div>
    </div>
  );
}
