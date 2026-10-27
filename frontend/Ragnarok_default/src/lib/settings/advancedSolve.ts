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

export interface AdvancedSolveOptions {
  solverName?: string;
  transmissionLosses?: boolean;
  linearizedUnitCommitment?: boolean;
  committableBigM?: number;
  cycleBasisMethod?: 'bfs-refined' | 'paton';
  computeInfeasibilities?: boolean;
  piecewiseOptions?: PiecewiseOption[];
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
  return out;
}
