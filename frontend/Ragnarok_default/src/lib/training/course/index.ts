/**
 * The power-market modelling course — 48 steps in 8 modules.
 *
 * One tutorial, not eight, because the course is cumulative: the model built in
 * module 1 is the model policy instruments are applied to in module 6. Modules
 * are `section` headings on the steps, so the rail groups them while progress
 * stays a single track.
 *
 * ── Design decisions this course is built on ─────────────────────────────────
 *
 *   Audience — a student new to BOTH power systems and modelling. Nothing is
 *   assumed: what a bus physically is, why supply must equal demand instantly,
 *   and what an objective function is all get explained before they are used.
 *
 *   One model, checkpointed — every module grows the SAME model, so the learner
 *   ends with something they built and understand end to end. Each module after
 *   the first opens by naming the bundled example to load as its starting
 *   point, so a mistake in module 2 does not poison module 7 and a learner can
 *   join at any module.
 *
 *   Theory and tool together — each step carries a `concept` block (the
 *   modelling idea, tool-independent) ahead of `explain` (what to do in
 *   Ragnarok). Neither reads as an aside to the other.
 *
 * Steps live one module per file so each stays reviewable. Add a module by
 * appending its array to `STEPS` below.
 */
import { Tutorial } from '../types';
import { MODULE_1_FOUNDATIONS } from './module1Foundations';

const STEPS = [
  ...MODULE_1_FOUNDATIONS,
];

export const POWER_MARKET_COURSE: Tutorial = {
  id: 'power-market-modelling',
  title: 'Power market modelling with Ragnarok',
  level: 'Beginner',
  minutes: 12 * 60,
  summary:
    'A 48-step course in eight modules. Build one power-system model from an empty sheet to a '
    + 'policy-tested investment case, learning the modelling theory and the Ragnarok mechanics '
    + 'together at every step. Assumes no prior knowledge of power systems or optimisation.',
  outcomes: [
    'Explain what a power-system optimisation model is: objective, decision variables, constraints',
    'Build a network from scratch — buses, generators, loads, lines, snapshots, profiles',
    'Read dispatch, prices and congestion, and say why the model produced them',
    'Turn a dispatch model into a capacity-expansion model on a defensible cost basis',
    'Test carbon prices, emissions caps and renewable targets, and compare them honestly',
    'Take a result to a decision, with provenance that survives review',
  ],
  prerequisites: [
    'Ragnarok is running and the top bar shows a status other than a connection error',
    'No prior power-systems or optimisation knowledge — the course starts from the beginning',
    'About 12 hours in total; each module stands alone from its checkpoint, so it need not be one sitting',
  ],
  steps: STEPS,
};
