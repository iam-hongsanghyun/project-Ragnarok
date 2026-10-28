/**
 * Chain-designer form state <-> the backend `ChainSpec`. Pure (no React) so the mapping is unit-tested.
 *
 * Numbers are held as strings while the user types (so deleting a digit never snaps to 0) and parsed
 * here, once, when the spec is built.
 */
import type { ReportRunOption } from 'lib/reporting/types';
import type { ChainSpec, OfftakeSpec, P2XDerivative, P2XProduct } from 'lib/api/p2x';
import { P2X_DERIVATIVES, P2X_PRODUCTS } from 'lib/api/p2x';

export interface OfftakeForm { mode: 'none' | 'flat' | 'profile'; tonnesPerYear: string; mw: string; profileText: string }
export interface DesignerForm {
  chainId: string;
  anchorBus: string;
  h2Bus: string;
  discountRate: string;
  products: Record<P2XProduct, boolean>;
  electrolyser: { tech: 'aec' | 'pem'; extendable: boolean; pNom: string; pNomMax: string; applyAvailability: boolean; enforceMinLoad: boolean; buildYear: string };
  storage: { type: 'none' | 'tank' | 'cavern'; compressor: boolean; extendable: boolean; eNom: string; eNomMax: string };
  co2Source: 'dac' | 'point';
  synthesis: Record<P2XDerivative, { extendable: boolean; pNom: string }>;
  productStorage: Record<P2XDerivative, { enabled: boolean }>;
  offtake: Record<P2XProduct, OfftakeForm>;
  designated: string[];
  params: Record<string, string>;
}

const emptyOfftake = (): OfftakeForm => ({ mode: 'none', tonnesPerYear: '', mw: '', profileText: '' });

export function defaultForm(discountRate: number, anchorBus = ''): DesignerForm {
  return {
    chainId: 'p2x', anchorBus, h2Bus: '', discountRate: String(discountRate),
    products: { H2: true, NH3: false, MeOH: false, eFuel: false },
    electrolyser: { tech: 'aec', extendable: true, pNom: '100', pNomMax: '', applyAvailability: true, enforceMinLoad: false, buildYear: '' },
    storage: { type: 'tank', compressor: false, extendable: true, eNom: '0', eNomMax: '' },
    co2Source: 'dac',
    synthesis: { NH3: { extendable: true, pNom: '0' }, MeOH: { extendable: true, pNom: '0' }, eFuel: { extendable: true, pNom: '0' } },
    productStorage: { NH3: { enabled: true }, MeOH: { enabled: true }, eFuel: { enabled: true } },
    offtake: { H2: { ...emptyOfftake(), mode: 'flat', tonnesPerYear: '1000' }, NH3: emptyOfftake(), MeOH: emptyOfftake(), eFuel: emptyOfftake() },
    designated: [],
    params: {},
  };
}

/** Numbers in a pasted / uploaded profile: any mix of newlines, commas, semicolons and spaces; non-numeric tokens are dropped. */
export function parseProfile(text: string): number[] {
  return text.split(/[\s,;]+/).map((t) => t.trim()).filter((t) => t !== '').map(Number).filter((n) => Number.isFinite(n));
}

const num = (s: string, fallback = 0): number => {
  const n = Number(s);
  return s.trim() !== '' && Number.isFinite(n) ? n : fallback;
};
const optNum = (s: string): number | null => {
  const n = num(s, 0);
  return n > 0 ? n : null;
};

function offtakeSpec(f: OfftakeForm): OfftakeSpec {
  if (f.mode === 'none') return { mode: 'none' };
  const base: OfftakeSpec = { mode: f.mode };
  if (f.tonnesPerYear.trim() !== '') base.tonnesPerYear = num(f.tonnesPerYear);
  else base.mw = num(f.mw);
  if (f.mode === 'profile') base.profile = parseProfile(f.profileText);
  return base;
}

/** The backend spec for a form (inactive products are left out of ``products`` and ``offtake``). */
export function formToSpec(form: DesignerForm): ChainSpec {
  const products = P2X_PRODUCTS.filter((p) => p === 'H2' || form.products[p]);
  const offtake: Record<string, OfftakeSpec> = {};
  for (const p of products) offtake[p] = offtakeSpec(form.offtake[p]);
  const synthesis: ChainSpec['synthesis'] = {};
  const productStorage: ChainSpec['productStorage'] = {};
  for (const p of P2X_DERIVATIVES) {
    synthesis[p] = { extendable: form.synthesis[p].extendable, pNom: num(form.synthesis[p].pNom) };
    productStorage[p] = { enabled: form.productStorage[p].enabled, extendable: true, eNom: 0 };
  }
  const params: Record<string, number> = {};
  for (const [k, v] of Object.entries(form.params)) if (v.trim() !== '' && Number.isFinite(Number(v))) params[k] = Number(v);
  return {
    chainId: form.chainId.trim(),
    anchorBus: form.anchorBus || null,
    h2Bus: form.h2Bus || null,
    discountRate: num(form.discountRate, 0.05),
    products,
    electrolyser: {
      tech: form.electrolyser.tech, extendable: form.electrolyser.extendable, pNom: num(form.electrolyser.pNom),
      pNomMax: optNum(form.electrolyser.pNomMax), applyAvailability: form.electrolyser.applyAvailability,
      enforceMinLoad: form.electrolyser.enforceMinLoad, buildYear: Math.trunc(num(form.electrolyser.buildYear)),
    },
    storage: { type: form.storage.type, compressor: form.storage.compressor, extendable: form.storage.extendable, eNom: num(form.storage.eNom), eNomMax: optNum(form.storage.eNomMax) },
    co2: { source: form.co2Source },
    synthesis, productStorage, offtake,
    designatedGenerators: form.designated,
    params,
  };
}

/** Technology keys whose parameters the chain uses for ``form`` (drives the parameter table). */
export function activeTechnologies(form: DesignerForm): string[] {
  const keys = [form.electrolyser.tech === 'aec' ? 'electrolyser_aec' : 'electrolyser_pem', 'water'];
  if (form.storage.type !== 'none') {
    if (form.storage.compressor) keys.push('h2_compressor');
    keys.push(form.storage.type === 'cavern' ? 'h2_storage_cavern' : form.storage.compressor ? 'h2_storage_tank_bare' : 'h2_storage_tank');
  }
  if (form.products.NH3) keys.push('haber_bosch', 'asu', ...(form.productStorage.NH3.enabled ? ['nh3_storage'] : []));
  if (form.products.MeOH) keys.push('methanolisation', ...(form.productStorage.MeOH.enabled ? ['meoh_storage'] : []));
  if (form.products.eFuel) keys.push('fischer_tropsch', ...(form.productStorage.eFuel.enabled ? ['efuel_storage'] : []));
  if (form.products.MeOH || form.products.eFuel) keys.push(form.co2Source === 'dac' ? 'co2_dac' : 'co2_point');
  return Array.from(new Set(keys));
}

/** First unused chain id of the form ``base``, ``base_2``, ... given the ids already in the model. */
export function nextChainId(base: string, taken: readonly string[]): string {
  if (!taken.includes(base)) return base;
  let i = 2;
  while (taken.includes(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}

/**
 * Whether a stored run is a pathway (multi-period) run and which periods it has, from the run list meta
 * (`isPathway` / `pathwayPeriods`; older sidecars carry only `pathway`). The P2X results picker offers exactly these.
 */
export function pathwayPeriodsOf(run: ReportRunOption | undefined): { isPathway: boolean; periods: number[] } {
  if (!run) return { isPathway: false, periods: [] };
  const enabled = run.isPathway ?? Boolean(run.pathway?.enabled);
  if (!enabled) return { isPathway: false, periods: [] };
  const raw = run.pathwayPeriods ?? (run.pathway?.periods ?? []).map((p) => (typeof p === 'number' ? p : p?.period));
  const periods = raw.map(Number).filter((p) => Number.isFinite(p));
  return { isPathway: true, periods: Array.from(new Set(periods)).sort((a, b) => a - b) };
}
