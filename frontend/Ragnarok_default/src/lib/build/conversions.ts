/**
 * Conversion-technology template library (sector coupling).
 *
 * A "conversion technology" is a PyPSA Link that moves energy between two
 * carriers (gas → electricity, electricity → hydrogen, electricity → heat, …).
 * Hand-wiring one means creating the counterpart carrier bus, the carrier
 * entries, and — for fuel-fed conversions — a fuel-supply generator, then the
 * Link itself with the right bus0/bus1/efficiency. This module turns a picked
 * template + an anchor bus into a ready-to-merge {@link WorkbookFragment} so the
 * whole wiring lands in one action.
 *
 * Emissions are handled the app's usual way (see backend `utils/emissions.py`):
 * CO₂ is counted at the fuel-carrier *generator* at primary energy (efficiency
 * aware), never on the Link — so a fuel-fed template seeds the fuel carrier's
 * `co2_emissions` and a supply generator, and the Link stays a pure converter.
 *
 * Pure: no I/O, no React. Unit-tested in `conversions.test.ts`.
 */
import type { GridRow, Primitive, WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';

/** One end of a conversion Link. */
export interface ConversionEndpoint {
  /** `power` binds to the user-selected anchor bus (whatever its carrier —
   *  usually electricity); `carrier` binds to a bus of the named vector,
   *  reusing an existing one or creating it. */
  role: 'power' | 'carrier';
  /** Required for `role: 'carrier'`. */
  carrier?: string;
  /** A primary fuel (gas): seeds `co2_emissions` on the carrier and a
   *  fuel-supply generator so the conversion has something to burn. */
  fuel?: boolean;
}

export interface ConversionTemplate {
  id: string;
  label: string;
  description: string;
  /** `Link.carrier` — the technology label used to group the Link in the
   *  per-carrier energy balance (e.g. "CCGT", "electrolysis"). */
  linkCarrier: string;
  input: ConversionEndpoint; // bus0
  output: ConversionEndpoint; // bus1
  output2?: ConversionEndpoint; // bus2 (e.g. CHP heat co-product)
  /** bus1 / bus0 conversion ratio (a heat-pump COP is > 1). */
  efficiency: number;
  /** bus2 / bus0 ratio, if `output2` is set. */
  efficiency2?: number;
  /** Indicative annualised capital cost (€/MW of bus0) — used when extendable. */
  capitalCost: number;
  /** €/MWh on the Link (usually 0; fuel cost lives on the supply generator). */
  marginalCost?: number;
  lifetime?: number;
  /** €/MWh for the fuel-supply generator (only when an endpoint is `fuel`). */
  fuelCost?: number;
  /** tCO₂/MWh (thermal) for the fuel carrier (only when an endpoint is `fuel`). */
  co2?: number;
}

/** Carrier names the app treats as electricity when choosing a default anchor. */
const POWER_CARRIERS = new Set(['', 'ac', 'dc', 'electricity', 'elec', 'power']);

/** Short, readable bus-name prefixes per vector. */
const BUS_PREFIX: Record<string, string> = { hydrogen: 'H2', heat: 'heat', gas: 'gas' };

export const CONVERSION_TEMPLATES: ConversionTemplate[] = [
  {
    id: 'ccgt', label: 'CCGT (gas → electricity)',
    description: 'Combined-cycle gas turbine burning gas to make power.',
    linkCarrier: 'CCGT', input: { role: 'carrier', carrier: 'gas', fuel: true }, output: { role: 'power' },
    efficiency: 0.55, capitalCost: 40000, lifetime: 30, fuelCost: 25, co2: 0.20,
  },
  {
    id: 'ocgt', label: 'OCGT (gas → electricity)',
    description: 'Open-cycle gas turbine — a cheaper, lower-efficiency peaker.',
    linkCarrier: 'OCGT', input: { role: 'carrier', carrier: 'gas', fuel: true }, output: { role: 'power' },
    efficiency: 0.39, capitalCost: 25000, lifetime: 30, fuelCost: 25, co2: 0.20,
  },
  {
    id: 'chp', label: 'CHP (gas → electricity + heat)',
    description: 'Gas combined heat & power; co-produces electricity and heat.',
    linkCarrier: 'CHP', input: { role: 'carrier', carrier: 'gas', fuel: true },
    output: { role: 'power' }, output2: { role: 'carrier', carrier: 'heat' },
    efficiency: 0.40, efficiency2: 0.45, capitalCost: 60000, lifetime: 25, fuelCost: 25, co2: 0.20,
  },
  {
    id: 'electrolyser', label: 'Electrolyser (electricity → hydrogen)',
    description: 'Uses power to split water into hydrogen.',
    linkCarrier: 'electrolysis', input: { role: 'power' }, output: { role: 'carrier', carrier: 'hydrogen' },
    efficiency: 0.70, capitalCost: 90000, lifetime: 20,
  },
  {
    id: 'fuel_cell', label: 'Hydrogen fuel cell (hydrogen → electricity)',
    description: 'Converts stored hydrogen back into power.',
    linkCarrier: 'fuel cell', input: { role: 'carrier', carrier: 'hydrogen' }, output: { role: 'power' },
    efficiency: 0.50, capitalCost: 90000, lifetime: 20,
  },
  {
    id: 'heat_pump', label: 'Heat pump (electricity → heat)',
    description: 'Electric heat pump with a coefficient of performance above 1.',
    linkCarrier: 'heat pump', input: { role: 'power' }, output: { role: 'carrier', carrier: 'heat' },
    efficiency: 3.0, capitalCost: 60000, lifetime: 20,
  },
  {
    id: 'resistive_heater', label: 'Resistive heater (electricity → heat)',
    description: 'Direct electric heating (power-to-heat).',
    linkCarrier: 'resistive heater', input: { role: 'power' }, output: { role: 'carrier', carrier: 'heat' },
    efficiency: 0.99, capitalCost: 5000, lifetime: 20,
  },
  {
    id: 'gas_boiler', label: 'Gas boiler (gas → heat)',
    description: 'Burns gas to make heat.',
    linkCarrier: 'gas boiler', input: { role: 'carrier', carrier: 'gas', fuel: true }, output: { role: 'carrier', carrier: 'heat' },
    efficiency: 0.90, capitalCost: 5000, lifetime: 20, fuelCost: 25, co2: 0.20,
  },
  {
    id: 'methanation', label: 'Methanation (hydrogen → gas)',
    description: 'Sabatier process converting hydrogen to synthetic gas.',
    linkCarrier: 'methanation', input: { role: 'carrier', carrier: 'hydrogen' }, output: { role: 'carrier', carrier: 'gas' },
    efficiency: 0.60, capitalCost: 100000, lifetime: 25,
  },
];

export interface ConversionOptions {
  /** Existing bus the `power` endpoint connects to (and the location for any
   *  newly-created carrier buses). */
  anchorBus: string;
  /** Link name; auto-generated from the template id when blank. */
  name?: string;
  /** Fixed input capacity (MW) when not extendable. */
  pNom: number;
  /** Let the solver size the Link (uses the template's capital cost). */
  extendable: boolean;
}

const norm = (s: unknown): string => String(s ?? '').trim().toLowerCase();

function rows(model: WorkbookModel, sheet: string): GridRow[] {
  return ((model as Record<string, GridRow[]>)[sheet] ?? []) as GridRow[];
}

function uniqueName(base: string, taken: Set<string>): string {
  if (!taken.has(base)) { taken.add(base); return base; }
  let i = 2;
  while (taken.has(`${base}_${i}`)) i += 1;
  const out = `${base}_${i}`;
  taken.add(out);
  return out;
}

/** A sensible default anchor: the first electricity-carrier bus, else the first bus. */
export function defaultAnchorBus(model: WorkbookModel): string | null {
  const buses = rows(model, 'buses');
  const elec = buses.find((b) => POWER_CARRIERS.has(norm(b.carrier)));
  return String((elec ?? buses[0])?.name ?? '') || null;
}

/**
 * Build the fragment that adds one conversion technology to the model.
 *
 * Reuses existing carrier buses / fuel supplies / carriers where present (so a
 * second electrolyser shares the hydrogen bus) and only emits genuinely-new
 * rows. Throws if the anchor bus is unknown.
 */
export function buildConversionFragment(
  template: ConversionTemplate,
  options: ConversionOptions,
  model: WorkbookModel,
): WorkbookFragment {
  const buses = rows(model, 'buses');
  const anchor = buses.find((b) => String(b.name) === options.anchorBus);
  if (!anchor) throw new Error(`Anchor bus "${options.anchorBus}" not found.`);

  const takenBusNames = new Set(buses.map((b) => String(b.name)));
  const newBuses: GridRow[] = [];
  const resolveBus = (ep: ConversionEndpoint): string => {
    if (ep.role === 'power') return options.anchorBus;
    const carrier = ep.carrier as string;
    const existing = buses.find((b) => norm(b.carrier) === norm(carrier));
    if (existing) return String(existing.name);
    const created = newBuses.find((b) => norm(b.carrier) === norm(carrier));
    if (created) return String(created.name);
    const name = uniqueName(BUS_PREFIX[carrier] ?? carrier, takenBusNames);
    const row: GridRow = { name, carrier };
    if (anchor.x !== undefined && anchor.x !== null && anchor.x !== '') row.x = anchor.x as Primitive;
    if (anchor.y !== undefined && anchor.y !== null && anchor.y !== '') row.y = anchor.y as Primitive;
    newBuses.push(row);
    return name;
  };

  const bus0 = resolveBus(template.input);
  const bus1 = resolveBus(template.output);
  const bus2 = template.output2 ? resolveBus(template.output2) : null;

  // Carriers: link carrier + each named vector (fuel vectors seed co2).
  const existingCarriers = new Set(rows(model, 'carriers').map((c) => String(c.name)));
  const newCarriers: GridRow[] = [];
  const ensureCarrier = (name: string, co2 = 0): void => {
    if (!name || existingCarriers.has(name) || newCarriers.some((c) => c.name === name)) return;
    const row: GridRow = { name };
    if (co2) row.co2_emissions = co2;
    newCarriers.push(row);
  };
  ensureCarrier(template.linkCarrier);
  for (const ep of [template.input, template.output, template.output2]) {
    if (ep?.role === 'carrier') ensureCarrier(ep.carrier as string, ep.fuel ? (template.co2 ?? 0) : 0);
  }

  // Fuel-supply generator on any fuel input, so the conversion has fuel to burn.
  const gens = rows(model, 'generators');
  const takenGenNames = new Set(gens.map((g) => String(g.name)));
  const newGens: GridRow[] = [];
  if (template.input.fuel) {
    const fuelCarrier = template.input.carrier as string;
    const hasSupply = gens.some((g) => String(g.bus) === bus0 && norm(g.carrier) === norm(fuelCarrier));
    if (!hasSupply) {
      newGens.push({
        name: uniqueName(`${BUS_PREFIX[fuelCarrier] ?? fuelCarrier}_supply`, takenGenNames),
        bus: bus0, carrier: fuelCarrier,
        p_nom_extendable: true, capital_cost: 0, marginal_cost: template.fuelCost ?? 0,
      });
    }
  }

  // The conversion Link itself.
  const takenLinkNames = new Set(rows(model, 'links').map((l) => String(l.name)));
  const link: GridRow = {
    name: uniqueName(options.name?.trim() || template.id, takenLinkNames),
    bus0, bus1, carrier: template.linkCarrier, efficiency: template.efficiency,
  };
  if (bus2) { link.bus2 = bus2; link.efficiency2 = template.efficiency2 ?? 0; }
  if (options.extendable) { link.p_nom_extendable = true; link.capital_cost = template.capitalCost; }
  else { link.p_nom = options.pNom; }
  if (template.marginalCost) link.marginal_cost = template.marginalCost;
  if (template.lifetime) link.lifetime = template.lifetime;

  const sheets: Record<string, GridRow[]> = { links: [link] };
  if (newCarriers.length) sheets.carriers = newCarriers;
  if (newBuses.length) sheets.buses = newBuses;
  if (newGens.length) sheets.generators = newGens;
  return { sheets };
}
