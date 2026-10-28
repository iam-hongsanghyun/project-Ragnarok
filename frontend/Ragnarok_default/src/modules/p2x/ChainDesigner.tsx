/**
 * ChainDesigner — pick the products, H2 bus, electrolyser, storage, offtake, designated RES generators and
 * parameter edits, preview what the backend would add to the model, then apply it through the ordinary
 * fragment merge. The backend builds everything (`/api/p2x/chain`); this component only collects inputs.
 */
import React from 'react';
import type { ChainPreview, ChainSummaryRow, P2XDerivative, P2XProduct, TechCatalogue } from 'lib/api/p2x';
import { P2X_DERIVATIVES, previewChain } from 'lib/api/p2x';
import type { WorkbookFragment } from 'lib/api/databases';
import type { GridRow, WorkbookModel } from 'lib/types';
import { numberValue, stringValue } from 'lib/utils/helpers';
import { activeTechnologies, DesignerForm, formToSpec, nextChainId, OfftakeForm } from './spec';

interface Props {
  model: WorkbookModel;
  form: DesignerForm;
  onChange: (next: DesignerForm) => void;
  catalogue: TechCatalogue | null;
  catalogueError: string | null;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void | Promise<void>;
  existingChainIds: string[];
}

const PRODUCT_LABEL: Record<P2XProduct, string> = { H2: 'Hydrogen', NH3: 'Ammonia', MeOH: 'Methanol', eFuel: 'E-fuel (FT)' };
const RES_CARRIER = /wind|solar|pv|hydro|ror/i;

const fmt = (v: number | undefined, digits = 3): string =>
  v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: digits });

function sizeOf(r: ChainSummaryRow): string {
  if (r.sheet === 'loads') return `${fmt(r.p_set)} MW`;
  if (r.sheet === 'stores') return r.e_nom_extendable ? 'optimised' : `${fmt(r.e_nom)} MWh`;
  return r.p_nom_extendable ? 'optimised' : `${fmt(r.p_nom)} MW`;
}

function ports(r: ChainSummaryRow): string {
  if (r.sheet === 'links' || r.sheet === 'processes') return [r.bus0, r.bus1, r.bus2, r.bus3].filter(Boolean).join(' → ');
  return r.bus ?? '';
}

export function ChainDesigner({ model, form, onChange, catalogue, catalogueError, onApplyFragment, existingChainIds }: Props) {
  const [preview, setPreview] = React.useState<ChainPreview | null>(null);
  const [previewKey, setPreviewKey] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [applied, setApplied] = React.useState<string | null>(null);

  const spec = React.useMemo(() => formToSpec(form), [form]);
  const specKey = React.useMemo(() => JSON.stringify(spec), [spec]);
  const buses = React.useMemo(() => (model.buses ?? []).map((b: GridRow) => ({ name: stringValue(b.name), carrier: stringValue(b.carrier) })).filter((b) => b.name), [model.buses]);
  const generators = React.useMemo(
    () => (model.generators ?? []).map((g: GridRow) => ({
      name: stringValue(g.name), carrier: stringValue(g.carrier), bus: stringValue(g.bus), buildYear: numberValue(g.build_year), extendable: stringValue(g.p_nom_extendable).toLowerCase() === 'true' || g.p_nom_extendable === true,
    })).filter((g) => g.name),
    [model.generators],
  );
  const set = (patch: Partial<DesignerForm>) => onChange({ ...form, ...patch });
  const derivs = P2X_DERIVATIVES.filter((p) => form.products[p]);
  const needsCo2 = form.products.MeOH || form.products.eFuel;
  const fresh = preview !== null && previewKey === specKey;

  const runPreview = async () => {
    setBusy(true); setError(null); setApplied(null);
    try {
      setPreview(await previewChain(spec, model));
      setPreviewKey(specKey);
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview || !fresh) return;
    setBusy(true); setError(null);
    try {
      await onApplyFragment(preview.fragment, 'P2X chain', 'working model');
      setApplied(`Chain “${preview.registry.chainId}” added to the working model (${Object.entries(preview.rowCounts).map(([s, n]) => `${n} ${s}`).join(', ')}). Open the RFNBO tab to set the matching rules, then solve.`);
      setPreview(null);
      set({ chainId: nextChainId(form.chainId, [...existingChainIds, form.chainId]) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const setOfftake = (p: P2XProduct, patch: Partial<OfftakeForm>) => set({ offtake: { ...form.offtake, [p]: { ...form.offtake[p], ...patch } } });
  const loadProfile = (p: P2XProduct, file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setOfftake(p, { profileText: String(reader.result ?? ''), mode: 'profile' });
    reader.readAsText(file);
  };
  const toggleGen = (name: string) =>
    set({ designated: form.designated.includes(name) ? form.designated.filter((g) => g !== name) : [...form.designated, name] });

  return (
    <div className="p2x-grid">
      <div>
        <div className="p2x-card">
          <h3>Chain</h3>
          <div className="p2x-row"><label htmlFor="p2x-id">Chain id</label>
            <input id="p2x-id" type="text" value={form.chainId} onChange={(e) => set({ chainId: e.target.value })} /></div>
          <div className="p2x-row"><label htmlFor="p2x-anchor">Electricity bus</label>
            <select id="p2x-anchor" value={form.anchorBus} onChange={(e) => set({ anchorBus: e.target.value })}>
              <option value="">(first electricity bus)</option>
              {buses.map((b) => <option key={b.name} value={b.name}>{b.name}{b.carrier ? ` · ${b.carrier}` : ''}</option>)}
            </select></div>
          <div className="p2x-row"><label htmlFor="p2x-h2bus">H2 bus</label>
            <select id="p2x-h2bus" value={form.h2Bus} onChange={(e) => set({ h2Bus: e.target.value })}>
              <option value="">(new H2 bus)</option>
              {buses.map((b) => <option key={b.name} value={b.name}>{b.name}{b.carrier ? ` · ${b.carrier}` : ''}</option>)}
            </select></div>
          <div className="p2x-row"><label htmlFor="p2x-dr">Discount rate</label>
            <input id="p2x-dr" type="number" step="0.005" min="0" max="0.99" value={form.discountRate} onChange={(e) => set({ discountRate: e.target.value })} />
            <span className="p2x-src">fraction/year; the solve annualises capex at the run’s rate</span></div>
          <h4>Products</h4>
          <div className="p2x-row">
            {(['H2', 'NH3', 'MeOH', 'eFuel'] as P2XProduct[]).map((p) => (
              <label key={p} style={{ minWidth: 0 }}>
                <input type="checkbox" checked={p === 'H2' ? true : form.products[p]} disabled={p === 'H2'}
                  onChange={(e) => set({ products: { ...form.products, [p]: e.target.checked } })} /> {PRODUCT_LABEL[p]}
              </label>
            ))}
          </div>
          {existingChainIds.length > 0 && <p className="p2x-note">Chains already in this model: {existingChainIds.join(', ')}.</p>}
        </div>

        <div className="p2x-card">
          <h3>Electrolyser</h3>
          <div className="p2x-row"><label htmlFor="p2x-tech">Technology</label>
            <select id="p2x-tech" value={form.electrolyser.tech} onChange={(e) => set({ electrolyser: { ...form.electrolyser, tech: e.target.value as 'aec' | 'pem' } })}>
              <option value="aec">Alkaline (AEC)</option><option value="pem">PEM</option>
            </select></div>
          <div className="p2x-row"><label>Size</label>
            <label style={{ minWidth: 0 }}><input type="radio" name="p2x-size" checked={form.electrolyser.extendable} onChange={() => set({ electrolyser: { ...form.electrolyser, extendable: true } })} /> Extendable</label>
            <label style={{ minWidth: 0 }}><input type="radio" name="p2x-size" checked={!form.electrolyser.extendable} onChange={() => set({ electrolyser: { ...form.electrolyser, extendable: false } })} /> Fixed</label></div>
          {form.electrolyser.extendable ? (
            <div className="p2x-row"><label htmlFor="p2x-pmax">Maximum size</label>
              <input id="p2x-pmax" type="number" min="0" value={form.electrolyser.pNomMax} placeholder="no limit" onChange={(e) => set({ electrolyser: { ...form.electrolyser, pNomMax: e.target.value } })} /> MW_el</div>
          ) : (
            <div className="p2x-row"><label htmlFor="p2x-pnom">Size</label>
              <input id="p2x-pnom" type="number" min="0" value={form.electrolyser.pNom} onChange={(e) => set({ electrolyser: { ...form.electrolyser, pNom: e.target.value } })} /> MW_el</div>
          )}
          <div className="p2x-row"><label htmlFor="p2x-by">Commissioning year</label>
            <input id="p2x-by" type="number" step="1" value={form.electrolyser.buildYear} placeholder="first snapshot year" onChange={(e) => set({ electrolyser: { ...form.electrolyser, buildYear: e.target.value } })} />
            <span className="p2x-src">sets the additionality reference</span></div>
          <div className="p2x-row">
            <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.electrolyser.applyAvailability} onChange={(e) => set({ electrolyser: { ...form.electrolyser, applyAvailability: e.target.checked } })} /> Apply DEA availability (forced + planned outage)</label></div>
          <div className="p2x-row">
            <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.electrolyser.enforceMinLoad} disabled={form.electrolyser.extendable} onChange={(e) => set({ electrolyser: { ...form.electrolyser, enforceMinLoad: e.target.checked } })} /> Enforce minimum load (fixed size only; makes the solve a MIP)</label></div>
        </div>

        <div className="p2x-card">
          <h3>Hydrogen storage</h3>
          <div className="p2x-row"><label htmlFor="p2x-stype">Type</label>
            <select id="p2x-stype" value={form.storage.type} onChange={(e) => set({ storage: { ...form.storage, type: e.target.value as DesignerForm['storage']['type'] } })}>
              <option value="none">None</option><option value="tank">Compressed tank</option><option value="cavern">Salt cavern</option>
            </select></div>
          {form.storage.type !== 'none' && (<>
            <div className="p2x-row">
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.storage.compressor} onChange={(e) => set({ storage: { ...form.storage, compressor: e.target.checked } })} /> Explicit compressor with an electricity penalty</label></div>
            <div className="p2x-row"><label>Size</label>
              <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.storage.extendable} onChange={(e) => set({ storage: { ...form.storage, extendable: e.target.checked } })} /> Extendable</label>
              {!form.storage.extendable && <input aria-label="Store size" type="number" min="0" value={form.storage.eNom} onChange={(e) => set({ storage: { ...form.storage, eNom: e.target.value } })} />}
              {!form.storage.extendable && <span>MWh_H2</span>}</div>
          </>)}
        </div>

        {derivs.length > 0 && (
          <div className="p2x-card">
            <h3>Synthesis</h3>
            {derivs.map((p: P2XDerivative) => (
              <div key={p} className="p2x-row"><label>{PRODUCT_LABEL[p]}</label>
                <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.synthesis[p].extendable} onChange={(e) => set({ synthesis: { ...form.synthesis, [p]: { ...form.synthesis[p], extendable: e.target.checked } } })} /> Extendable</label>
                {!form.synthesis[p].extendable && <><input aria-label={`${p} plant size`} type="number" min="0" value={form.synthesis[p].pNom} onChange={(e) => set({ synthesis: { ...form.synthesis, [p]: { ...form.synthesis[p], pNom: e.target.value } } })} /> MW_H2 in</>}
                <label style={{ minWidth: 0 }}><input type="checkbox" checked={form.productStorage[p].enabled} onChange={(e) => set({ productStorage: { ...form.productStorage, [p]: { enabled: e.target.checked } } })} /> Product tank</label>
              </div>
            ))}
            {needsCo2 && (
              <div className="p2x-row"><label htmlFor="p2x-co2">CO2 supply</label>
                <select id="p2x-co2" value={form.co2Source} onChange={(e) => set({ co2Source: e.target.value as 'dac' | 'point' })}>
                  <option value="dac">Direct air capture</option><option value="point">Point source (cement kiln)</option>
                </select></div>
            )}
            {form.products.NH3 && <p className="p2x-note">Ammonia adds an air separation unit for the nitrogen.</p>}
          </div>
        )}

        <div className="p2x-card">
          <h3>Offtake</h3>
          <p className="p2x-note">The chain only runs for what is asked of it. Tonnes per year become a flat load in MW (LHV); a profile is normalised to a mean of 1 and scaled by that level.</p>
          {(['H2', ...derivs] as P2XProduct[]).map((p) => {
            const o = form.offtake[p];
            return (
              <div key={p}>
                <div className="p2x-row"><label htmlFor={`p2x-off-${p}`}>{PRODUCT_LABEL[p]}</label>
                  <select id={`p2x-off-${p}`} value={o.mode} onChange={(e) => setOfftake(p, { mode: e.target.value as OfftakeForm['mode'] })}>
                    <option value="none">None</option><option value="flat">Flat</option><option value="profile">Profile</option>
                  </select>
                  {o.mode !== 'none' && <><input aria-label={`${p} tonnes per year`} type="number" min="0" value={o.tonnesPerYear} onChange={(e) => setOfftake(p, { tonnesPerYear: e.target.value })} /> t/yr</>}
                </div>
                {o.mode === 'profile' && (
                  <div className="p2x-row" style={{ paddingLeft: 128 }}>
                    <input type="file" accept=".csv,.txt" aria-label={`${p} profile file`} onChange={(e) => loadProfile(p, e.target.files?.[0])} />
                    <textarea aria-label={`${p} profile values`} placeholder="One value per snapshot (newline, comma or space separated)" value={o.profileText} onChange={(e) => setOfftake(p, { profileText: e.target.value })} />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="p2x-card">
          <h3>Designated renewable generators (RFNBO matching)</h3>
          <p className="p2x-note">The RES the electrolyser is matched to (the PPA, Delegated Regulation (EU) 2023/1184). Used by the RFNBO tab and by the PPA electricity-cost option.</p>
          <div className="p2x-row">
            <button type="button" className="p2x-btn" onClick={() => set({ designated: generators.filter((g) => RES_CARRIER.test(g.carrier)).map((g) => g.name) })}>Select wind, solar and hydro</button>
            <button type="button" className="p2x-btn" onClick={() => set({ designated: [] })}>Clear</button></div>
          <div className="p2x-gens" role="group" aria-label="Designated generators">
            {generators.length === 0 && <span className="p2x-src">The model has no generators.</span>}
            {generators.map((g) => (
              <label key={g.name}><input type="checkbox" checked={form.designated.includes(g.name)} onChange={() => toggleGen(g.name)} />
                {g.name} <span className="p2x-src">{g.carrier}{g.buildYear > 0 ? ` · ${g.buildYear}` : g.extendable ? ' · extendable' : ''} · {g.bus}</span></label>
            ))}
          </div>
        </div>
      </div>

      <div>
        <div className="p2x-card">
          <h3>Preview and apply</h3>
          <div className="p2x-row">
            <button type="button" className="p2x-btn" onClick={runPreview} disabled={busy}>Preview</button>
            <button type="button" className="p2x-btn p2x-btn--primary" onClick={apply} disabled={busy || !fresh}>Apply to model</button>
            {preview && !fresh && <span className="p2x-src">Inputs changed since the preview — preview again.</span>}
          </div>
          {error && <div className="p2x-error" role="alert">{error}</div>}
          {applied && <div className="p2x-note" role="status">{applied}</div>}
          {preview && (<>
            {preview.warnings.map((w) => <div key={w} className="p2x-warn">{w}</div>)}
            <table className="p2x-table" aria-label="Chain preview">
              <thead><tr><th>Component</th><th>Name</th><th>Ports</th><th className="num">Size</th><th className="num">Efficiency</th><th className="num">Overnight cost</th></tr></thead>
              <tbody>
                {preview.summary.map((r) => (
                  <tr key={r.name}>
                    <td>{r.label}</td><td>{r.name}</td><td>{ports(r)}</td><td className="num">{sizeOf(r)}</td>
                    <td className="num">{r.efficiency !== undefined ? fmt(r.efficiency, 4) : '—'}{r.efficiency2 !== undefined ? ` / ${fmt(r.efficiency2, 4)}` : ''}{r.efficiency3 !== undefined ? ` / ${fmt(r.efficiency3, 4)}` : ''}</td>
                    <td className="num">{r.overnightCapex !== undefined ? `${fmt(r.overnightCapex, 1)} ${r.overnightUnit ?? ''}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="p2x-note">Rows to merge: {Object.entries(preview.rowCounts).map(([s, n]) => `${n} ${s}`).join(', ')}. Efficiencies: product / electricity / feed (negative = consumed per unit of H2 in).</p>
          </>)}
          {!preview && !error && !applied && <p className="p2x-note">Preview shows exactly what would be added to the working model; nothing changes until you apply.</p>}
        </div>

        <div className="p2x-card">
          <h3>Technology parameters</h3>
          {catalogueError && <div className="p2x-error">{catalogueError}</div>}
          {!catalogue && !catalogueError && <p className="p2x-note">Loading the technology data…</p>}
          {catalogue && (<>
            <p className="p2x-note">
              Defaults from {String((catalogue.sources['technology-data'] as { repository?: string; version?: string } | undefined)?.repository ?? 'technology-data')}
              {' '}{String((catalogue.sources['technology-data'] as { version?: string } | undefined)?.version ?? '')} and the Danish Energy Agency catalogue, {catalogue.basis.currency}{catalogue.basis.costYear} prices, technology year {catalogue.basis.technologyYear}.
              Edit a value to override it for this chain (hover a row for its source).
            </p>
            {activeTechnologies(form).filter((k) => catalogue.technologies[k]).map((key) => {
              const tech = catalogue.technologies[key];
              return (
                <div key={key}>
                  <h4>{tech.label}</h4>
                  <table className="p2x-table p2x-params" aria-label={`${tech.label} parameters`}>
                    <tbody>
                      {Object.entries(tech.parameters).map(([name, p]) => {
                        const pk = `${key}.${name}`;
                        const shown = form.params[pk] ?? String(p.default);
                        const edited = form.params[pk] !== undefined && Number(form.params[pk]) !== p.default;
                        return (
                          <tr key={name} title={`${p.source.document} — ${p.source.locator} (${p.source.year})${p.note ? `\n${p.note}` : ''}`}>
                            <td>{name.replace(/_/g, ' ')}</td>
                            <td className="num"><input aria-label={`${key} ${name}`} type="number" step="any" value={shown} onChange={(e) => set({ params: { ...form.params, [pk]: e.target.value } })} /></td>
                            <td>{p.unit}</td>
                            <td><span className={`p2x-chip p2x-chip--${p.verified}`}>{p.verified}</span>{edited && <button type="button" className="p2x-btn" onClick={() => { const next = { ...form.params }; delete next[pk]; set({ params: next }); }}>reset</button>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {tech.notes && <p className="p2x-src">{tech.notes}</p>}
                </div>
              );
            })}
          </>)}
        </div>
      </div>
    </div>
  );
}
