/**
 * Advanced `n.optimize` options (PyPSA 1.4) edited in Settings → Solver and sent
 * verbatim as top-level run options. Every key is optional: an empty object leaves
 * the solve call unchanged. Backend parser: backend/pypsa/optimise_options.py.
 */
export type PiecewiseMethod = 'auto' | 'lp' | 'incremental' | 'sos2';

export interface PiecewiseOption {
  component: string;
  attribute: string;
  method: PiecewiseMethod;
  /** Limit the override to these component names. */
  name?: string[];
  /** Constraint sense; omitted = PyPSA default (>= for costs, = for efficiency/rate). */
  sign?: '>=' | '<=' | '=';
}

/** CVaR weights in stochastic mode (`options.riskPreference`): alpha and omega are both fractions in (0,1) / [0,1]. */
export interface RiskPreferenceOptions {
  alpha: number;
  omega: number;
}

/** Discrete link module size for iterative expansion; one row of `linkUnitSize` / `linkThreshold`. */
export interface LinkUnitOption {
  link: string;
  /** MW per unit. */
  unitSize: number;
  /** Fraction of one unit (0-1) above which a fractional unit rounds up; blank = PyPSA default. */
  threshold?: number;
}

/** Iterative transmission expansion (`options.iterativeExpansion`). Units: see the run-options reference. */
export interface IterativeExpansionOptions {
  enabled: boolean;
  msqThreshold: number;
  minIterations: number;
  maxIterations: number;
  /** MVA per discrete line unit; undefined = continuous expansion. */
  lineUnitSize?: number;
  /** Fraction of a unit (0-1). */
  lineThreshold?: number;
  fractionalLastUnitSize: boolean;
  links: LinkUnitOption[];
}

export type CofiringUnit = 'energy' | 'vol';
export type CofiringScope = 'hourly' | 'period';

/** One blend-share limit block; shares are fractions (0.3 = 30 %), null = no limit on that side. */
export interface CofiringLimits {
  minShare: number | null;
  maxShare: number | null;
  unit: CofiringUnit;
  scope: CofiringScope;
}

/** Gas + H2 co-firing blend-share limits (`options.cofiringConfig`). Undefined in settings = the plants' stored limits apply. */
export interface CofiringOptions extends CofiringLimits {
  enabled: boolean;
  /** Plant ids to constrain; empty = every fuel-network co-firing plant. */
  plants: string[];
  perPlant: Record<string, CofiringLimits>;
}

export const DEFAULT_RISK_PREFERENCE: RiskPreferenceOptions = { alpha: 0.95, omega: 0.5 };

export const DEFAULT_ITERATIVE_EXPANSION: IterativeExpansionOptions = {
  enabled: true, msqThreshold: 0.05, minIterations: 1, maxIterations: 10, fractionalLastUnitSize: false, links: [],
};

export const DEFAULT_COFIRING: CofiringOptions = {
  enabled: true, plants: [], minShare: null, maxShare: null, unit: 'energy', scope: 'hourly', perPlant: {},
};

export interface AdvancedSolveOptions {
  solverName?: string;
  transmissionLosses?: boolean;
  linearizedUnitCommitment?: boolean;
  committableBigM?: number;
  cycleBasisMethod?: 'bfs-refined' | 'paton';
  computeInfeasibilities?: boolean;
  piecewiseOptions?: PiecewiseOption[];
  /** CVaR in stochastic mode; undefined = risk-neutral. */
  riskPreference?: RiskPreferenceOptions;
  /** Size capacities on the LP relaxation, fix them, re-solve the dispatch. */
  twoStage?: boolean;
  iterativeExpansion?: IterativeExpansionOptions;
  cofiringConfig?: CofiringOptions;
}

function iterativeToOptions(it: IterativeExpansionOptions): Record<string, unknown> {
  const out: Record<string, unknown> = {
    enabled: true,
    msqThreshold: it.msqThreshold,
    minIterations: it.minIterations,
    maxIterations: it.maxIterations,
    fractionalLastUnitSize: it.fractionalLastUnitSize,
  };
  if (it.lineUnitSize && it.lineUnitSize > 0) out.lineUnitSize = it.lineUnitSize;
  if (it.lineThreshold !== undefined) out.lineThreshold = it.lineThreshold;
  const links = it.links.filter((l) => l.link && l.unitSize > 0);
  if (links.length) out.linkUnitSize = Object.fromEntries(links.map((l) => [l.link, l.unitSize]));
  const thresholds = links.filter((l) => l.threshold !== undefined);
  if (thresholds.length) out.linkThreshold = Object.fromEntries(thresholds.map((l) => [l.link, l.threshold]));
  return out;
}

const limitsToOptions = (l: CofiringLimits): Record<string, unknown> => ({
  minShare: l.minShare, maxShare: l.maxShare, unit: l.unit, scope: l.scope,
});

function cofiringToOptions(c: CofiringOptions): Record<string, unknown> {
  const perPlant = Object.fromEntries(Object.entries(c.perPlant).map(([id, l]) => [id, limitsToOptions(l)]));
  return { enabled: c.enabled, plants: c.plants, ...limitsToOptions(c), perPlant };
}

/** Drop unset keys so a default Settings page adds nothing to the run payload. */
export function advancedSolveToOptions(adv?: AdvancedSolveOptions): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!adv) return out;
  if (adv.solverName && adv.solverName !== 'highs') out.solverName = adv.solverName;
  if (adv.transmissionLosses) out.transmissionLosses = true;
  if (adv.linearizedUnitCommitment) out.linearizedUnitCommitment = true;
  if (adv.committableBigM && adv.committableBigM > 0) out.committableBigM = adv.committableBigM;
  if (adv.cycleBasisMethod && adv.cycleBasisMethod !== 'bfs-refined') out.cycleBasisMethod = adv.cycleBasisMethod;
  if (adv.computeInfeasibilities) out.computeInfeasibilities = true;
  const pw = (adv.piecewiseOptions ?? [])
    .filter((p) => p.component && p.attribute)
    .map((p) => ({
      component: p.component,
      attribute: p.attribute,
      method: p.method,
      ...(p.name && p.name.length ? { name: p.name } : {}),
      ...(p.sign ? { sign: p.sign } : {}),
    }));
  if (pw.length) out.piecewiseOptions = pw;
  if (adv.riskPreference) out.riskPreference = { alpha: adv.riskPreference.alpha, omega: adv.riskPreference.omega };
  if (adv.twoStage) out.twoStage = { enabled: true };
  if (adv.iterativeExpansion?.enabled) out.iterativeExpansion = iterativeToOptions(adv.iterativeExpansion);
  // An explicit cofiringConfig (even disabled) overrides the limits stored with each plant, so it is sent as set.
  if (adv.cofiringConfig) out.cofiringConfig = cofiringToOptions(adv.cofiringConfig);
  return out;
}
