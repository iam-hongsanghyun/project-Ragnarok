/**
 * The power-market modelling course — 12 modules, complete.
 *
 * All twelve are written. The tutorial's summary, `minutes` and `outcomes`
 * describe what is actually there: a learner reading the catalog card should be
 * told the truth about what they are starting, and progress is a percentage of
 * real steps.
 *
 * One tutorial, not ten, because the course is cumulative: the model built in
 * module 1 is the model policy instruments are applied to in module 8. Modules
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
 *   point, so a mistake in module 2 does not poison module 8 and a learner can
 *   join at any module.
 *
 *   Theory and tool together — each step carries a `concept` block (the
 *   modelling idea, tool-independent) ahead of `explain` (what to do in
 *   Ragnarok). Neither reads as an aside to the other.
 *
 * Steps live one module per file so each stays reviewable. Add a module by
 * appending its array to `STEPS` below.
 */
import { CourseModule, Tutorial } from '../types';
import { MODULE_1_FOUNDATIONS } from './module1Foundations';
import { MODULE_2_DISPATCH } from './module2Dispatch';
import { MODULE_3_NETWORKS } from './module3Networks';
import { MODULE_4_STORAGE } from './module4Storage';
import { MODULE_5_SECTOR_COUPLING } from './module5SectorCoupling';
import { MODULE_6_TIME } from './module6Time';
import { MODULE_7_INVESTMENT } from './module7Investment';
import { MODULE_8_POLICY } from './module8Policy';
import { MODULE_9_DECISION } from './module9Decision';
import { MODULE_10_POWER_FLOW } from './module10PowerFlow';
import { MODULE_11_COMMITMENT } from './module11Commitment';
import { MODULE_12_ADEQUACY } from './module12Adequacy';

const STEPS = [
  ...MODULE_1_FOUNDATIONS,
  ...MODULE_2_DISPATCH,
  ...MODULE_3_NETWORKS,
  ...MODULE_4_STORAGE,
  ...MODULE_5_SECTOR_COUPLING,
  ...MODULE_6_TIME,
  ...MODULE_7_INVESTMENT,
  ...MODULE_8_POLICY,
  ...MODULE_9_DECISION,
  ...MODULE_10_POWER_FLOW,
  ...MODULE_11_COMMITMENT,
  ...MODULE_12_ADEQUACY,
];

/**
 * The modules a learner picks from, in teaching order.
 *
 * `section` matches the string on the module's steps — the join between the two
 * — so a module with no steps written yet simply has none to show, and a step
 * whose section is not listed here would be unreachable rather than silently
 * mis-grouped. `catalog.test.ts` checks both directions.
 */
const MODULES: CourseModule[] = [
  {
    section: '1 · Foundations',
    title: 'Foundations',
    level: 'Beginner',
    minutes: 60,
    summary: 'What a power-system model is, what a network is made of, and one full '
      + 'change → validate → run → read loop on a model small enough to check by hand.',
  },
  {
    section: '2 · Economic dispatch',
    title: 'Economic dispatch',
    level: 'Beginner',
    minutes: 120,
    summary: 'The merit order, the marginal unit that sets the price, demand that varies '
      + 'by the hour, and variable generation with its curtailment and zero prices.',
  },
  {
    section: '3 · Networks and congestion',
    title: 'Networks and congestion',
    level: 'Intermediate',
    minutes: 110,
    summary: 'Split the fleet across two buses joined by one line: a cheap generator that cannot reach '
      + 'the demand, two prices instead of one, congestion rent, and what the constraint costs.',
  },
  {
    section: '4 · Storage and time coupling',
    title: 'Storage and time coupling',
    level: 'Intermediate',
    minutes: 100,
    summary: 'The first component that links one hour to the next: a battery that charges on the cheap '
      + 'hour, removes the peaker from the answer entirely, and is worth three times as much on one side '
      + 'of the constraint as the other.',
  },
  {
    section: '5 · Sector coupling and fuel supply',
    title: 'Sector coupling and fuel supply',
    level: 'Intermediate',
    minutes: 120,
    summary: 'Gas gets its own bus, its own price and its own store, and the gas plant becomes what it '
      + 'is — a CCGT converting fuel into power. Adds run-of-river hydro and a pumped-hydro scheme worth '
      + 'a fraction of a battery a tenth its size.',
  },
  {
    section: '6 · Time — resolution and horizon',
    title: 'Time — resolution and horizon',
    level: 'Advanced',
    minutes: 110,
    summary: 'Replace three snapshots with a real day and find out how much of what you concluded was '
      + 'about the axis: the pumped hydro written off in module 5 turns out to be worth twenty-three '
      + 'times more. Then resolution, representative periods and rolling horizon, and what each breaks.',
  },
  {
    section: '7 · Investment and capacity expansion',
    title: 'Investment and capacity expansion',
    level: 'Advanced',
    minutes: 150,
    summary: 'Capacity becomes a decision on a full year. Four assets compete, three get built, and '
      + 'solar wins a place despite losing on levelised cost. Ends by showing what a brownfield run '
      + 'hides and how two points on the discount rate reweight the whole portfolio.',
  },
  {
    section: '8 · Policy instruments',
    title: 'Policy instruments',
    level: 'Expert',
    minutes: 140,
    summary: 'The carbon factors typed in module 1 finally matter. A price and a cap turn out to be the '
      + 'same instrument — verified by setting the price to the cap\'s shadow price and getting the same '
      + 'system back — and a carbon price is what finally makes storage worth building.',
  },
  {
    section: '9 · From result to decision',
    title: 'From result to decision',
    level: 'Expert',
    minutes: 90,
    summary: 'The capstone, and the only module that adds no modelling capability. Turns the runs you '
      + 'already have into a range with its conditions, a sensitivity ranking, a provenance trail and an '
      + 'honest statement of what the model cannot see.',
  },
  {
    section: '10 · Meshed networks and power flow',
    title: 'Meshed networks and power flow',
    level: 'Expert',
    minutes: 100,
    summary: 'Steps back to a three-bus ring small enough to compute by hand, and shows that power '
      + 'divides itself between parallel paths whatever anyone wants. Ends with a nodal price above '
      + 'every generator in the model, an AC power flow, and an N-1 check two outages fail.',
  },
  {
    section: '11 · Commitment and operating constraints',
    title: 'Commitment and operating constraints',
    level: 'Expert',
    minutes: 100,
    summary: 'A power station is not a tap. Minimum stable output, start-up costs, minimum down time '
      + 'and ramp limits — and a coal unit that holds on through a windy dip, spilling free wind to '
      + 'avoid a start-up charge, until one number is changed and it does the opposite.',
  },
  {
    section: '12 · Adequacy and uncertainty',
    title: 'Adequacy and uncertainty',
    level: 'Expert',
    minutes: 110,
    summary: 'The closing module: plant breaks. Samples forced outages across the year module 7 started '
      + 'from and finds a system seven times outside the reliability standard nothing had measured — '
      + 'then asks what module 7\'s least-cost expansion did to that, by accident.',
  },
];

export const POWER_MARKET_COURSE: Tutorial = {
  id: 'power-market-modelling',
  title: 'Power market modelling with Ragnarok',
  modules: MODULES,
  level: 'Beginner',
  // The twelve modules as written, at the pace of someone typing every value and
  // reading the concept blocks rather than skimming them. Modules 7 to 9 solve a
  // full year, so their runs take about a minute each, which is included; module
  // 10 goes back to three snapshots and is instant again.
  minutes: 23 * 60,
  summary:
    'Build one power-system model from an empty sheet to a policy-tested investment case, learning the '
    + 'modelling theory and the Ragnarok mechanics together at every step. Twelve modules: foundations, '
    + 'economic dispatch, networks and congestion, storage, sector coupling, time and horizon, '
    + 'investment, policy instruments and turning a result into a decision — then three closing modules '
    + 'on meshed networks and power flow, on unit commitment, and on what any of it is worth once plant '
    + 'starts breaking. Assumes no prior knowledge of power systems or optimisation, and every answer '
    + 'up to module 5 — and all of modules 10 and 11 — is small enough to check by hand.',
  outcomes: [
    'Explain what a power-system optimisation model is: objective, decision variables, constraints',
    'Build a working network from scratch — carriers, buses, generators, loads, snapshots, profiles',
    'Explain the merit order, and say which unit sets the price in any hour and why',
    'Read congestion, locational prices and congestion rent, and say what a constraint costs',
    'Model storage and say why the same asset is worth three times more in one place than another',
    'Give a fuel its own bus, price it, store it, and convert it with a Link',
    'Choose a time resolution and horizon you can defend, and say what each shortcut breaks',
    'Turn a dispatch model into an investment model on an annuitised, window-matched cost basis',
    'Apply a carbon price or an emissions cap, and explain why they are the same instrument',
    'Produce a range with its conditions, a sensitivity ranking and an honest statement of limits',
    'Read a meshed network: why flows divide by reactance, and why a nodal price can exceed every offer',
    'Choose between an optimisation, a DC power flow, an AC power flow and an N-1 study, and say why',
    'Model a plant that cannot switch on and off freely, and say what commitment costs to solve',
    'Measure adequacy as a distribution — LOLE, EUE and capacity credit — against a stated standard',
  ],
  prerequisites: [
    'Ragnarok is running and the top bar shows a status other than a connection error',
    'No prior power-systems or optimisation knowledge — the course starts from the beginning',
    'About 23 hours across twelve modules; each opens from a checkpoint, so it need not be one sitting',
    'Modules 7 to 9 solve a full year, so expect roughly a minute per run from there on',
  ],
  steps: STEPS,
};
