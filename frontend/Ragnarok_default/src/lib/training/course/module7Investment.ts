/**
 * Module 7 — Investment and capacity expansion (10 steps).
 *
 * Every module so far has ended by saying the model cannot tell you whether
 * something was worth building. This is where that stops being true: capacity
 * becomes a decision variable, capital cost enters the objective, and the
 * optimiser chooses what to build as well as how hard to run it.
 *
 * Built on module 5's model (7,099.59). Verified against real HiGHS solves:
 *
 *   step 6   wind extendable, line fixed     7,099.59  builds NOTHING
 *   step 8   line extendable too              5,995.48  line 97.25 MW, wind 90 MW
 *   step 9   discount rate 0.05 -> 0.07       6,187.27  the wind farm disappears

 * All at Ragnarok's default discount rate of 0.05 unless stated, so a learner who
 * never opens Settings still matches every number.
 *
 * Two things make this module worth its length.
 *
 * The first is a trap. Ragnarok treats a workbook `capital_cost` as an OVERNIGHT
 * cost and annualises it for you, using `lifetime` and the discount rate — but it
 * does NOT scale that annual figure to the window actually modelled. On a
 * three-hour model an annual cost is 2,920 times too large, the optimiser builds
 * nothing, and a learner concludes that nothing is worth building. The fix is to
 * pre-scale the overnight cost by 3/8760, and the real fix is module 7.
 *
 * The second is the answer itself. Wind offered on its own is worth nothing,
 * because it sits behind a line that is already full. Offer the LINE as well and
 * the model builds 37.25 MW of wire AND 30 MW of wind — the wire is what makes
 * the wind farm worth building, which is the third time this course has found
 * that assets behind a constraint are worth a fraction of the same assets in
 * front of it.
 *
 * Then step 9 moves the discount rate from 0.05 to 0.07 and the wind farm
 * disappears while the wire survives. One financing assumption, no change to any
 * technology, and a generation investment flips — which is why the application
 * puts that number in front of you and why a study that does not state it has
 * not stated its most important input.
 */
import { TutorialStep } from '../types';

const SECTION = '7 · Investment and capacity expansion';

export const MODULE_7_INVESTMENT: TutorialStep[] = [
  {
    id: 'm7-what-to-build',
    section: SECTION,
    title: 'From how hard to run, to what to build',
    tab: 'Build',
    where: 'Build → Generators step',
    startOptions: {
      prebuiltExampleId: 'training_m6',
      completeExampleId: 'training_m7',
      note:
        'Module 6 continues module 5\'s model — two electrical buses and a gas bus, a CCGT, a gas store, '
        + 'wind, run-of-river, a battery and a pumped-hydro scheme — which answered 7,099.59. Nothing is '
        + 'added here. Two existing components simply become decisions instead of givens.',
    },
    concept: [
      'Five modules have asked one question: given this equipment, how should it run? The answer has '
      + 'always been a dispatch. Capacity was fixed, so unused capacity was free, so the model could '
      + 'never say whether a plant was worth having — only what it was worth running.',

      'Capacity expansion turns capacity into a decision variable. Instead of `p_nom` being a number you '
      + 'typed, it becomes something the optimiser chooses, bounded by a minimum and a maximum, with a '
      + 'cost attached to whatever it chooses. The objective stops being "cheapest way to run this fleet" '
      + 'and becomes "cheapest way to serve this demand, counting what the fleet costs to own".',

      'That is a genuinely different question, and it needs a genuinely different number: capital cost. '
      + 'Everything you have priced so far has been marginal — the cost of one more MWh. Capital cost is '
      + 'the cost of one more MW of existing, whether or not it ever runs, and the two are not comparable '
      + 'until the capital cost has been spread over time.',

      'That spreading is where nearly every capacity-expansion model goes wrong, and this module spends '
      + 'three steps on it before building anything. The arithmetic is not hard; the units are, and a '
      + 'capital cost in the wrong units produces an answer that looks plausible and is out by three '
      + 'orders of magnitude.',
    ],
    explain: [
      'Nothing to change in this step. It is worth knowing what is coming, because the order matters.',

      'Steps 2 to 4 are about the cost: what `capital_cost` means in Ragnarok, what the discount rate '
      + 'does to it, and why a three-hour model needs the number scaled before it means anything.',

      'Steps 5 and 6 make wind extendable and run it — and the model builds nothing, which is a result '
      + 'rather than a failure, and the reason takes a moment to see.',

      'Steps 7 and 8 make the LINE extendable too and finish the business case module 3 sketched. Now '
      + 'the model builds — and it builds the wire AND the wind farm, because the wire is what makes the '
      + 'wind farm reachable.',

      'Then step 9 changes one financing assumption, the discount rate, and watches the wind farm '
      + 'disappear while the wire survives.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'p_nom, about to become a decision',
        tab: 'Build',
        note: 'Every generator has carried a p_nom you typed. Scroll the columns and you will find '
          + 'p_nom_extendable, p_nom_min, p_nom_max, capital_cost and lifetime sitting unused beside it — '
          + 'the whole of capacity expansion, already in the sheet.',
      },
      {
        selector: '.build-step-strip',
        title: 'No new components',
        tab: 'Build',
        note: 'Nothing is added in this module. Investment is not a new kind of thing in the model — it is '
          + 'a handful of extra attributes on components you already have.',
      },
    ],
    verify: [
      'The session holds module 5\'s model and answers 7,099.59',
      'You can say why a dispatch model cannot value a plant, only its output',
      'You can say what changes about `p_nom` when an asset becomes extendable',
      'You can say why capital cost and marginal cost are not directly comparable',
    ],
    pitfalls: [
      'Expecting expansion to be a different kind of model. It is the same LP with a few more decision '
      + 'variables and a few more terms in the objective — which is also why it can be so much slower.',
    ],
  },

  {
    id: 'm7-capital-cost',
    section: SECTION,
    title: 'Overnight, annual, and who does the arithmetic',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'A wind farm costs something like 1,200,000 per MW to build. That is the OVERNIGHT cost — what it '
      + 'would cost if you could build it instantly, with no financing. It is the number cost databases '
      + 'publish and the number engineers quote.',

      'It cannot go into the objective as it stands, because the objective is a cost over a period of '
      + 'operation and the overnight cost is a lump sum. Spreading it is annuitisation: the capital '
      + 'recovery factor turns a lump sum into the equal annual payment that repays it over the asset\'s '
      + 'life at a given discount rate.',

      'CRF = r(1+r)^n / ((1+r)^n − 1). At 5% over 25 years that is 0.0710, so 1,200,000 per MW becomes '
      + 'about 85,150 per MW per year. That annual figure is what belongs beside fuel costs.',

      'Ragnarok does this for you, and knowing that is the point of this step. The `capital_cost` column '
      + 'holds the OVERNIGHT cost; the app multiplies it by CRF using the row\'s `lifetime` and the '
      + 'discount rate from Settings. Many tools — including PyPSA used directly — expect you to have '
      + 'annuitised already, so a cost that is right in one tool is 12 times too large in the other. '
      + 'Always check which convention you are in.',
    ],
    explain: [
      'Nothing to enter yet. Find the columns first: on the Generators step, scroll right past '
      + '`efficiency` and you will reach `p_nom_extendable`, `p_nom_min`, `p_nom_max`, `capital_cost`, '
      + '`lifetime` and `overnight_cost`. They have been there since module 1.',

      'The `lifetime` column matters more than it looks. If it is blank, PyPSA defaults it to infinity, '
      + 'which has no finite annuity — so Ragnarok substitutes 20 years rather than letting the cost '
      + 'silently annuitise to nothing. A blank lifetime is not a neutral choice; it is a 20-year '
      + 'assumption you did not make deliberately.',

      'Two numbers to hold on to for the next steps: a wind farm at 1,200,000 per MW over 25 years, and '
      + 'a transmission line at 600,000 per MW of capacity over 40 years. Both are plausible round '
      + 'figures rather than quotations, and both are about to be scaled.',
    ],
    spotlights: [
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'The columns that have been waiting',
        tab: 'Build',
        note: 'Scroll right, or use the Columns button, and find p_nom_extendable, p_nom_min, p_nom_max, '
          + 'capital_cost and lifetime. Every model you have built has carried them empty — expansion is '
          + 'attributes, not new components.',
      },
    ],
    verify: [
      'You can state the capital recovery factor formula and say what each symbol is',
      'You can compute the annual cost of a 1,200,000/MW asset over 25 years at 5%',
      'You can say which convention Ragnarok uses for `capital_cost`, and why that matters',
      'You can say what happens if `lifetime` is left blank',
    ],
    pitfalls: [
      'Entering an already-annuitised cost. Ragnarok annuitises what you give it, so an annual figure '
      + 'gets annuitised twice and comes out roughly twelve times too small — which makes new capacity '
      + 'look nearly free.',
      'Leaving `lifetime` blank and assuming it does not matter. It becomes 20 years, which is wrong for '
      + 'almost everything: wind is 25, transmission is 40 or more, and the difference moves the annual '
      + 'cost by a third.',
    ],
  },

  {
    id: 'm7-discount-rate',
    section: SECTION,
    title: 'The discount rate — the assumption you inherit',
    tab: 'Settings',
    where: 'Settings → Project defaults → Discount rate',
    concept: [
      'The discount rate decides how heavily a future cost counts today, and in a capacity-expansion '
      + 'model it decides how much capital gets built. A low rate makes capital-heavy, fuel-free '
      + 'technologies — wind, solar, nuclear, transmission — look cheap. A high rate favours '
      + 'cheap-to-build, expensive-to-run plant, which is gas.',

      'The effect is large. Moving from 5% to 10% raises the annual cost of a 25-year asset by about '
      + '45%, with no change to the technology at all. Two studies that disagree about renewable build-out '
      + 'often disagree about nothing except this number.',

      'Ragnarok puts the number in front of you rather than burying it: Settings → Project defaults → '
      + 'Discount rate, with the app\'s own note underneath saying what it is for. It ships at 0.05, and '
      + 'that default is worth taking seriously as a hazard — an assumption you inherit silently is more '
      + 'dangerous than one you are forced to supply, because nothing prompts you to defend it.',

      'The API is stricter than the GUI here. A run submitted without a discount rate, while extendable '
      + 'assets carry capital costs, is refused outright with a message explaining why — so an agent or a '
      + 'script cannot accidentally author this assumption. The GUI gives you 0.05 instead, and expects '
      + 'you to look at it.',

      'This course uses the 0.05 default so every number matches what you see out of the box. Step 9 '
      + 'changes it to 0.07 and watches an investment decision reverse, which is the most direct '
      + 'demonstration of why it matters that this course can offer.',
    ],
    explain: [
      'Open Settings → Project defaults and find Discount rate. Confirm it reads 0.05 and leave it there '
      + 'for now — the rest of the module assumes it.',

      'It sits with the project defaults rather than on any component, because it applies to every capital '
      + 'cost in the model at once: one financing assumption for the whole study.',

      'Read the app\'s own note under the field — "used to annualise capital costs for extendable assets, '
      + '0.05 = 5% WACC". That is the whole mechanism in one line, and it is worth knowing the setting '
      + 'does nothing at all until something is extendable, which is why five modules never needed it.',

      'Nothing to run yet. But make a note that you have looked at this number and accepted it, because '
      + 'in a real study that is the difference between an assumption and an accident.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Settings',
        note: 'Project defaults holds it, because it is a scenario-level assumption rather than a '
          + 'component attribute — one number applied to every capital cost in the model. It ships at 0.05 '
          + 'and the note under the field tells you exactly what it does.',
      },
    ],
    entries: [
      {
        field: 'Settings → Project defaults → Discount rate',
        value: '0.05',
        why: 'The app\'s default, kept deliberately so every figure in this module matches what you see '
          + 'without changing anything. Five per cent is a plausible weighted average cost of capital for '
          + 'a regulated utility. It sets the capital recovery factor for every extendable asset, so it '
          + 'decides how much capital the model is willing to build — step 9 moves it to 0.07 and an '
          + 'investment decision reverses.',
      },
    ],
    verify: [
      'Settings → Project defaults → Discount rate reads 0.05',
      'You can say which technologies a low discount rate favours, and why',
      'You can say what the GUI does about a missing rate and what the API does instead',
      'You can say roughly how much a 25-year asset\'s annual cost changes between 5% and 10%',
    ],
    pitfalls: [
      'Accepting the 0.05 default without deciding it is right. An inherited assumption is still your '
      + 'assumption once you publish the answer, and this is the one most likely to be challenged.',
      'Confusing it with inflation or with a project IRR. Here it is the rate at which the model '
      + 'annuitises capital, and it should reflect the cost of capital for the entity doing the building.',
    ],
  },

  {
    id: 'm7-window-scaling',
    section: SECTION,
    title: 'Three hours against a year — the 2,920× trap',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'Here is the trap, and it catches nearly everyone building their first expansion model.',

      'The annuitised capital cost is a cost per YEAR. The objective in this model covers three hours. '
      + 'Put an annual cost into a three-hour objective and you are asking the model to recover a whole '
      + 'year of capital from three hours of fuel savings — so it builds nothing, and the answer looks '
      + 'like a considered "no" rather than a unit error.',

      'The mismatch is 8760/3 = 2,920 times. Ragnarok does not correct it: the app annuitises for you but '
      + 'does not know that your three snapshots are meant to stand for a year, because on a model with '
      + 'weighted representative periods they might not be.',

      'There are two honest fixes. Model a full year, which is module 7. Or scale the overnight cost by '
      + 'the fraction of the year you actually model — 3/8760 — so the capital charge covers the same '
      + 'period as the fuel bill. This module does the second, because it is the one that fits in three '
      + 'snapshots, and it flags loudly that it is a workaround rather than a technique.',

      'So the numbers you will type are 1,200,000 × 3/8760 = 410.96 for wind and 600,000 × 3/8760 = '
      + '205.48 for the line. Ragnarok then applies CRF and the objective sees about 29.16 and 11.98 per '
      + 'MW at the default 5% — the cost of owning that MW for three hours.',
    ],
    explain: [
      'Nothing to enter yet — this step is the arithmetic you need before the next one makes sense.',

      'Work it through once. A wind farm at 1,200,000 per MW, 25 years, 5%: annuitised that is 85,150 '
      + 'per MW per year. Three hours is 3/8760 of a year, so the share of the annual charge attributable '
      + 'to this window is 29.16 per MW. That is what the objective should see.',

      'Since Ragnarok multiplies by CRF itself, you type the SCALED OVERNIGHT cost — 410.96 — and let it '
      + 'do the annuitisation. Scale first, then let the app annuitise; doing both yourself makes it '
      + 'annuitise a second time.',

      'And write down what you did. A capital cost of 410.96 in a sheet is meaningless to anyone who does '
      + 'not know it has been scaled by 3/8760, and this is exactly the sort of undocumented adjustment '
      + 'that makes a model impossible to review. Module 9 has more to say about that.',
    ],
    spotlights: [
      {
        selector: '.sg-scenario-summary',
        title: 'Three snapshots at 1h',
        runDialog: 'open',
        note: 'The line you have checked before every run since module 1, now load-bearing for a different '
          + 'reason: it is the window your capital cost has to match. Three snapshots at 1h is 3 hours of '
          + 'a 8,760-hour year.',
      },
    ],
    verify: [
      'You can say why an annual capital cost in a three-hour objective builds nothing',
      'You can compute the scaling factor for this model and get 3/8760',
      'You can compute the scaled overnight cost for wind and get about 411',
      'You can say why you scale the overnight cost rather than the annuitised one in Ragnarok',
    ],
    pitfalls: [
      'Concluding "nothing is worth building" from an unscaled run. That is a unit error wearing the '
      + 'costume of a result, and it is the single commonest mistake in first expansion models.',
      'Scaling AND annuitising by hand, then letting Ragnarok annuitise again. Scale only; the app does '
      + 'the CRF.',
      'Leaving the scaling undocumented. A reviewer seeing 410.96 per MW for a wind farm will assume the '
      + 'model is broken, and they will be right to.',
    ],
  },

  {
    id: 'm7-extendable-wind',
    section: SECTION,
    title: 'Make wind a decision',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'Four attributes turn a fixed generator into a decision.',

      '`p_nom_extendable` says the optimiser may choose the capacity. `p_nom_min` and `p_nom_max` bound '
      + 'what it may choose. `capital_cost` is what each MW costs — here the scaled overnight figure. And '
      + '`lifetime` feeds the annuitisation.',

      '`p_nom_min` is where brownfield modelling lives. Set it to the capacity that already exists and '
      + 'the model may build more but may not un-build what is there — which is right, because a wind '
      + 'farm that is already standing is a sunk cost and demolishing it saves nothing. Set it to zero '
      + 'and you are asking a greenfield question: what would you build if nothing existed?',

      'Those two questions have very different answers and are constantly confused. This module asks the '
      + 'brownfield one, because it is the one an operator or a regulator actually faces.',
    ],
    explain: [
      'Build → Generators, on the wind_1 row. Tick `p_nom_extendable`, set `p_nom_min` to 60 — the '
      + 'capacity that already exists — `p_nom_max` to 300, `capital_cost` to 410.96 and `lifetime` to 25.',

      'The columns are to the right of the ones you have used so far, so scroll or use the Columns '
      + 'button. The attribute form on the right is easier for a row with this many fields.',

      '`p_nom_max` of 300 is a siting limit: how much wind this location could physically host. Real '
      + 'studies get it from land area, grid connection capacity or planning constraints, and leaving it '
      + 'unbounded is usually a mistake — an unbounded model will build implausible amounts of the '
      + 'cheapest thing.',

      'Do not run yet. Predict first: wind is free to run, so more of it displaces fuel. Does that make '
      + 'it worth 29.16 per MW for these three hours? The next step is the answer, and it is worth having '
      + 'a guess on record.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'One row, five cells',
        tab: 'Build',
        note: 'Only wind_1 changes. Everything else in the fleet stays fixed, so whatever the model does '
          + 'is attributable to this one decision — the same controlled-experiment discipline as every '
          + 'other module.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'Scroll right',
        tab: 'Build',
        note: 'p_nom_extendable is a checkbox, and p_nom_min / p_nom_max / capital_cost / lifetime are '
          + 'numbers beside it. They are past the columns you have used so far — the Columns button lists '
          + 'them all if scrolling is awkward.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom_extendable (wind_1)',
        label: 'capacity is a decision',
        value: 'true',
        why: 'Turns p_nom from a number you typed into a variable the optimiser chooses. This one '
          + 'checkbox is the difference between a dispatch model and an expansion model.',
      },
      {
        field: 'generators.p_nom_min (wind_1)',
        label: 'capacity that already exists',
        value: '60',
        unit: 'MW',
        why: 'The existing farm. Setting the floor here makes this a brownfield question — build more if '
          + 'it pays, but never pretend you could unbuild what is standing. Set it to 0 instead and you '
          + 'are asking what you would build from nothing, which is a different study.',
      },
      {
        field: 'generators.p_nom_max (wind_1)',
        label: 'siting limit',
        value: '300',
        unit: 'MW',
        why: 'The most this site could physically host — land, connection capacity, planning. An '
          + 'unbounded maximum lets the model build implausible quantities of whatever is cheapest, so '
          + 'a real limit is part of describing the world honestly rather than a modelling convenience.',
      },
      {
        field: 'generators.capital_cost (wind_1)',
        label: 'overnight cost, scaled to the window',
        value: '410.96',
        unit: 'currency per MW',
        why: '1,200,000 per MW scaled by 3/8760 for the three hours this model covers. Ragnarok multiplies '
          + 'it by CRF(5%, 25 y) itself, giving about 29.16 per MW in the objective — the cost of owning '
          + 'a MW of wind for three hours.',
      },
      {
        field: 'generators.lifetime (wind_1)',
        label: 'economic life',
        value: '25',
        unit: 'years',
        why: 'How long the asset repays its capital over, which sets the annuity factor. Leave it blank '
          + 'and Ragnarok assumes 20 years — a 15% higher annual cost than 25, applied silently.',
      },
    ],
    verify: [
      'wind_1 has `p_nom_extendable` ticked, `p_nom_min` 60, `p_nom_max` 300',
      '`capital_cost` is 410.96 and `lifetime` is 25',
      'Every other generator is unchanged',
      'You have written down a prediction for how much wind gets built',
    ],
    pitfalls: [
      'Leaving `p_nom_min` at 0. The model may then choose LESS wind than exists, which is not a decision '
      + 'anybody can act on — you cannot un-build a wind farm to save its capital cost.',
      'Typing the unscaled 1,200,000. The model will build nothing, and the "no" will look considered.',
    ],
  },

  {
    id: 'm7-run-wind',
    section: SECTION,
    title: 'Run: it builds nothing, and that is a result',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'The objective comes back at 7,099.59 — module 5\'s answer, unchanged — and `p_nom_opt` for wind_1 '
      + 'is 60. The model declined to build a single MW.',

      'That is not the scaling error. The cost is right this time, and the reason is more interesting: '
      + 'extra wind at bus_1 has nowhere to go. The line to the demand is full in the first two hours '
      + 'already, and in the third hour — when the system is stretched — wind availability is 0.1, so a '
      + 'new MW contributes 0.1 MW exactly when it would be worth something.',

      'Work it through. One more MW of wind yields 0.9 + 0.4 + 0.1 = 1.4 MWh over the window. Most of it '
      + 'arrives in hours when the line is already full, so it would be curtailed. Against a capital '
      + 'charge of 29.16, the answer is comfortably no.',

      'This is what a constrained network does to a generation business case, and it is why "the resource '
      + 'is good here" is not sufficient reason to build. It is also the mirror image of module 5\'s '
      + 'pumped-hydro result: the same constraint that made storage worthless at bus_1 makes generation '
      + 'worthless there too.',
    ],
    explain: [
      'Run it — validate first, since you have changed a row\'s structure rather than just a number.',

      'The GUI supplies 0.05 so the run will not stop to ask you for it. If you are driving Ragnarok '
      + 'through the API or an agent instead, an omitted rate is refused outright — the message names the '
      + 'extendable assets carrying a cost and says where the setting lives.',

      'Read the objective — 7,099.59, unchanged — and then find `p_nom_opt` for wind_1. It reads 60, '
      + 'which is `p_nom_min`: the model built exactly nothing and could not go lower.',

      'Resist the urge to lower the capital cost until something gets built. The model is telling you '
      + 'something true about this network, and the fix is not a cheaper wind farm — it is the next step.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: '7,099.59, unchanged',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The same answer as module 5. An expansion run that builds nothing is a real result, and the '
          + 'question to ask is WHY — which is nearly always about what the new capacity could reach.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'Optimal capacity',
        tab: 'Analytics',
        note: 'The per-carrier statistics table carries the solved capacities. wind_1 sits at 60 MW — its '
          + 'floor — so the optimiser chose the smallest wind fleet it was allowed.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="curtailment"]',
        title: 'Why not',
        tab: 'Analytics',
        note: 'Curtailment is the clue. Wind that cannot reach the demand is wind nobody should pay to '
          + 'build, and on this network more wind at bus_1 means more curtailment rather than more energy.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'The problem now has a capacity variable in it as well as dispatch, so it is a slightly larger LP. Still instant.',
        'If the discount rate is unset, the run fails with a message rather than guessing.',
      ],
      expect: 'An objective of 7,099.59 and p_nom_opt of 60 for wind_1 — nothing built.',
    },
    verify: [
      'The objective is 7,099.59, unchanged from module 5',
      '`p_nom_opt` for wind_1 is 60, which is its minimum',
      'You can explain why, in terms of what a new MW of wind could actually deliver',
      'You can connect this result to module 5\'s pumped-hydro finding',
    ],
    pitfalls: [
      'Lowering the capital cost until the model builds something. That is fitting the assumption to the '
      + 'desired answer, and it is how expansion studies lose their credibility.',
      'Concluding wind is uneconomic in general. It is uneconomic BEHIND THIS LINE, which is a statement '
      + 'about the network rather than the technology.',
    ],
  },

  {
    id: 'm7-extendable-line',
    section: SECTION,
    title: 'Make the line a decision — module 3\'s business case, finished',
    tab: 'Build',
    where: 'Build → Lines step',
    concept: [
      'Module 3 measured what the 60 MW line constraint cost — 420 over three hours — and said that was '
      + 'the upper bound on what you should pay to relieve it. This is where that becomes a decision '
      + 'rather than an observation.',

      'A Line expands exactly like a generator, with `s_nom` in place of `p_nom`: `s_nom_extendable`, '
      + '`s_nom_min`, `s_nom_max`, `capital_cost` and `lifetime`. The naming difference is only that a '
      + 'line is rated in apparent power.',

      'Transmission capital costs are usually quoted per MW-km, which is one reason `length` has been '
      + 'sitting in the sheet since module 3 doing nothing. Here the cost is expressed per MW for a line '
      + 'of this length, which keeps the arithmetic visible — 600,000 per MW, over 40 years, because '
      + 'transmission assets outlive generation by a wide margin.',

      'That long life matters. At 5%, CRF over 40 years is 0.058 against 0.071 over 25 — so transmission '
      + 'carries a lower annual charge per unit of capital than a wind farm, which is part of why '
      + 'networks are so often the cheapest way to fix a problem.',
    ],
    explain: [
      'Build → Lines, on the line_1 row. Tick `s_nom_extendable`, set `s_nom_min` to 60 — the existing '
      + 'circuit — `s_nom_max` to 300, `capital_cost` to 205.48 and `lifetime` to 40.',

      '205.48 is 600,000 scaled by the same 3/8760 as the wind. Use exactly the same scaling for every '
      + 'capital cost in a model; mixing scaled and unscaled figures is the fastest way to produce an '
      + 'answer nobody can reconstruct.',

      'Leave wind extendable as it is. Step 9 depends on both being available at once, and it is worth '
      + 'seeing the line result on its own first.',

      'Predict again before running. Module 3 said the constraint was worth 420 over three hours at a '
      + '40 MW uprate. The wire now costs about 11.98 per MW for the window. Does that pay?',
    ],
    spotlights: [
      {
        selector: '[data-build-step="lines"]',
        buildStep: 'lines',
        title: 'The same five attributes',
        tab: 'Build',
        note: 's_nom_extendable, s_nom_min, s_nom_max, capital_cost, lifetime — identical in meaning to '
          + 'the generator ones, named for apparent power. Expansion is one mechanism applied to every '
          + 'component type.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'lines',
        title: 'Scaled the same way',
        tab: 'Build',
        note: '205.48 is 600,000 per MW scaled by 3/8760, exactly as the wind cost was. Every capital cost '
          + 'in a model must share one scaling convention or the comparison between them is meaningless.',
      },
    ],
    entries: [
      {
        field: 'lines.s_nom_extendable (line_1)',
        label: 'capacity is a decision',
        value: 'true',
        why: 'Lets the optimiser choose the line rating. This is the cell that turns module 3\'s '
          + 'observation — the constraint costs 420 — into a question the model can answer for itself.',
      },
      {
        field: 'lines.s_nom_min (line_1)',
        label: 'existing circuit',
        value: '60',
        unit: 'MW',
        why: 'The wire that is already strung. Brownfield again: the model may add capacity but may not '
          + 'remove what exists, because taking a line down does not refund the money spent building it.',
      },
      {
        field: 'lines.s_nom_max (line_1)',
        label: 'corridor limit',
        value: '300',
        unit: 'MW',
        why: 'The most this route could carry — right of way, tower design, planning consent. As with the '
          + 'wind siting limit, an unbounded corridor invites the model to solve every problem with wire.',
      },
      {
        field: 'lines.capital_cost (line_1)',
        label: 'overnight cost, scaled to the window',
        value: '205.48',
        unit: 'currency per MW',
        why: '600,000 per MW for a line of this length, scaled by 3/8760. Ragnarok applies CRF(5%, 40 y), '
          + 'giving about 11.98 per MW in the objective — less than half the wind figure, because the '
          + 'same capital is spread over 40 years instead of 25.',
      },
      {
        field: 'lines.lifetime (line_1)',
        label: 'economic life',
        value: '40',
        unit: 'years',
        why: 'Transmission outlives generation, and the difference is not cosmetic: 40 years gives a CRF '
          + 'of 0.058 against 25 years\' 0.071, so every unit of capital costs 18% less per year. Long '
          + 'life is a real part of why networks are often the cheapest fix.',
      },
    ],
    verify: [
      'line_1 has `s_nom_extendable` ticked, `s_nom_min` 60, `s_nom_max` 300',
      '`capital_cost` is 205.48 and `lifetime` is 40',
      'wind_1 is still extendable from the previous step',
      'You have a prediction on record for how much wire gets built',
    ],
    pitfalls: [
      'Scaling the line cost differently from the wind cost. Every capital figure must share one '
      + 'convention, or the model is comparing quantities in different units.',
      'Forgetting `lifetime` on the line. The 20-year default would overstate its annual cost by about a '
      + 'quarter and could flip the decision.',
    ],
  },

  {
    id: 'm7-run-line',
    section: SECTION,
    title: 'Run: the wire, and the wind farm it unlocks',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'The objective falls from 7,099.59 to 5,995.48. `s_nom_opt` for line_1 comes back at 97.25 MW, so '
      + 'the model built 37.25 MW of new transmission — and `p_nom_opt` for wind_1 comes back at 90 MW, '
      + 'so it built 30 MW of new wind as well.',

      'That is the result worth stopping on. In the previous step, offered on its own, the wind farm was '
      + 'not worth a single MW. Nothing about the wind farm has changed — same cost, same site, same '
      + 'profile. What changed is that there is now somewhere for its output to go.',

      'So the wire did not compete with the wind farm; it created it. Generation and transmission are '
      + 'complements here, and evaluating either alone gets the wrong answer — which is the case for '
      + 'co-optimising them in one model rather than running two studies.',

      'The 1,104.11 saving is NET of both capital costs, since the capital charges are in the objective '
      + 'alongside the fuel. And note where the model stopped: not at the 300 MW corridor limit and not '
      + 'where congestion vanishes, but where the marginal MW of each asset costs exactly what it saves. '
      + 'That is what an optimum looks like, and it is why "eliminate congestion" is not a sensible '
      + 'planning objective.',
    ],
    explain: [
      'Run it. Reconcile the objective against 5,995.48, then find `s_nom_opt` on the line and '
      + '`p_nom_opt` on wind_1.',

      'Compare against the previous step deliberately: same wind farm, same capital cost, same discount '
      + 'rate, and it went from zero MW built to thirty. The only difference is that the line was allowed '
      + 'to grow at the same time.',

      'Then compare against module 3, which measured the 60 MW constraint at 420 over three hours for a '
      + '40 MW uprate. The model has now chosen its own uprate and the benefit is far larger, because the '
      + 'system around it has changed — a battery, a gas store, run-of-river hydro, and now a bigger wind '
      + 'farm that only exists because the wire does.',

      'This is the transmission business case module 3 promised, done properly: costs on both sides, one '
      + 'objective, and capacities the model chose rather than ones you guessed.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: '5,995.48',
        tab: 'Analytics',
        runDialog: 'closed',
        note: '1,104.11 better than module 5, NET of both capital costs. The first genuinely '
          + 'investment-aware answer in the course, and the first that builds two things at once.',
      },
      {
        selector: '[data-card="statistics"]',
        title: '97.25 MW of wire, 90 MW of wind',
        tab: 'Analytics',
        note: '37.25 MW of new transmission and 30 MW of new wind. The wind farm was worth nothing one '
          + 'step ago and is worth building now — the wire is what changed, not the turbine.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Prices, once the constraint eases',
        tab: 'Analytics',
        note: 'The congested hour no longer clears at a generator\'s marginal cost. Numbers with no '
          + 'round-figure explanation are what prices look like when a partially-relieved constraint is '
          + 'setting them, which is most of the time in a real system.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: [
        'Two capacity variables now — the wind farm and the line — plus the dispatch. Still instant on three snapshots.',
      ],
      expect: 'An objective of 5,995.48, with s_nom_opt 97.25 MW on line_1 and p_nom_opt 90 MW on wind_1.',
    },
    verify: [
      'The objective is 5,995.48',
      '`s_nom_opt` for line_1 is 97.25 MW and `p_nom_opt` for wind_1 is 90 MW',
      'You can say why the wind farm is worth building now and was not one step ago',
      'You can say why the saving is net rather than gross',
      'You can say why the model did not eliminate congestion entirely',
    ],
    pitfalls: [
      'Reading 1,104.11 as the value of transmission. It is the value of this uprate AND the wind farm it '
      + 'enabled, on this system, over three hours, at this discount rate — and it depends on the battery '
      + 'and the gas store being there too.',
      'Expecting an optimum to remove the constraint. An optimum leaves congestion in exactly the hours '
      + 'where relieving it would cost more than it saves.',
    ],
  },

  {
    id: 'm7-complements',
    section: SECTION,
    title: 'Change one assumption, lose the wind farm',
    tab: 'Analytics',
    where: 'Settings → Project defaults, then run again',
    concept: [
      'Everything about the model is now settled: the technologies, their costs, their lifetimes, the '
      + 'demand, the network. One number is not a fact about any of them — the discount rate — and this '
      + 'step changes it from 0.05 to 0.07 and runs again.',

      'The wind farm disappears. `p_nom_opt` goes back to 60 MW, its floor, and the line settles at 87.55 '
      + 'instead of 97.25. The objective is 6,187.27.',

      'Nothing physical changed. No technology got worse, no resource got scarcer, no demand moved. A '
      + 'financing assumption moved two percentage points and a 30 MW generation investment stopped being '
      + 'worth making.',

      'The reason is that capital-heavy, fuel-free technologies are the ones a discount rate bites '
      + 'hardest. Wind is entirely capital; its whole case rests on spreading that capital over 25 years, '
      + 'and a higher rate makes those distant years count for less. Gas, which is mostly fuel, barely '
      + 'notices. That asymmetry is why the discount rate is not a neutral technical parameter but an '
      + 'input that systematically favours one kind of system over another.',

      'Note too what did NOT flip. The line stayed, and stayed large. Transmission survives a higher rate '
      + 'better than generation does here, partly because its 40-year life spreads the capital further — '
      + 'so a study run at the wrong rate does not just get the quantities wrong, it gets the RANKING '
      + 'wrong, which is worse.',
    ],
    explain: [
      'Settings → Project defaults → Discount rate. Change 0.05 to 0.07 and run again. One number.',

      'Read the objective — 6,187.27 — and then the two capacities: line 87.55, wind back to 60. Compare '
      + 'against the previous run side by side in Analytics → Comparison rather than from memory; both '
      + 'runs are in History and this is exactly the comparison the feature exists for.',

      'Then think about what you would report. "The model builds 30 MW of wind" and "the model builds no '
      + 'wind" are both true statements about this system, and which one you publish depends entirely on '
      + 'a number you could reasonably have picked either way. A result that flips inside a plausible '
      + 'range of an assumption is not a finding — it is a sensitivity, and it has to be reported as one.',

      'This is the honest answer to "what should we build?" on this model: it depends, here is what it '
      + 'depends on, and here is how much. Module 9 is about turning that into something a decision-maker '
      + 'can act on.',

      'Set the rate back to 0.05 before you finish, so the model matches the checkpoint module 7 starts '
      + 'from.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: '6,187.27, and no wind farm',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Two percentage points on the discount rate removed a 30 MW generation investment. Nothing '
          + 'physical changed — which is why this number belongs in the summary of any expansion study, '
          + 'not in an appendix.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'Wind back to its floor',
        tab: 'Analytics',
        note: 'p_nom_opt 60 — the minimum it was allowed. The line meanwhile only fell from 97.25 to '
          + '87.55, so the network investment survived what the generation investment did not.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'The two runs, side by side',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both are in History. Comparing them here is the point of the step — a result that moves '
          + 'this much across a plausible range of one input is a sensitivity, and reporting it as a '
          + 'single answer would be misleading.',
      },
    ],
    entries: [
      {
        field: 'Settings → Project defaults → Discount rate (the experiment)',
        value: '0.07',
        why: 'Two percentage points higher — well inside the range reasonable people choose. It raises '
          + 'the annual cost of every capital asset, and it does so hardest for the ones whose case rests '
          + 'entirely on capital: the 30 MW wind investment stops paying while the transmission, with its '
          + '40-year life, survives.',
      },
      {
        field: 'Settings → Project defaults → Discount rate (restore)',
        value: '0.05',
        why: 'Back to the app default, which is the state the checkpoint and module 7 assume. Leaving it '
          + 'at 0.07 would quietly change every figure in the next module.',
      },
    ],
    run: {
      label: 'Run dialog → Run model, twice',
      detail: [
        'Once at 0.07 to see the decision reverse, then once more at 0.05 to restore the model.',
        'Both solve instantly and both land in History, so they can be compared properly.',
      ],
      expect: 'An objective of 6,187.27 with wind back at 60 MW, then 5,995.48 again once the rate is restored.',
    },
    verify: [
      'At 0.07 the objective is 6,187.27, wind_1 is 60 MW and line_1 is 87.55 MW',
      'You can say why a higher discount rate hurts wind more than gas',
      'You can say why it hurt the wind farm more than the transmission line',
      'You can explain why this result should be reported as a sensitivity rather than an answer',
      'The discount rate is back to 0.05 before you move on',
    ],
    pitfalls: [
      'Picking the rate that gives the answer you wanted. It is the easiest number in the model to '
      + 'justify either way, which is exactly why it needs to be chosen and stated before the runs, not '
      + 'after.',
      'Reporting the 0.05 result alone. A conclusion that reverses within a plausible range of one '
      + 'assumption has to be presented with that range attached.',
      'Forgetting to restore 0.05. Module 7 assumes it, and the discount rate is not stored in the '
      + 'checkpoint — it lives in your settings.',
    ],
  },

  {
    id: 'm7-what-changed',
    section: SECTION,
    title: 'What module 6 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'Capacity can be a decision. Four attributes — extendable, min, max, capital cost — turn any '
      + 'component into an investment question, and the same mechanism works for generators, lines, '
      + 'links and storage alike.',

      'Capital costs must be annuitised and matched to the modelled window. Ragnarok annuitises for you '
      + 'from the overnight cost, the lifetime and the discount rate; matching the window is still yours '
      + 'to do, and getting it wrong produces a confident "build nothing" that is really a unit error.',

      'The discount rate is the most consequential assumption in an expansion study. Two percentage '
      + 'points removed a 30 MW wind investment while leaving the transmission untouched — so it changes '
      + 'not just how much gets built but WHAT, and a study that does not state its rate has not stated '
      + 'its most important input.',

      'And investments interact. Offered alone the wind farm was worth nothing; offered alongside the '
      + 'line it was worth 30 MW. The wire did not compete with it, the wire created it — which is the '
      + 'case for co-optimising generation and network rather than studying them separately, and the '
      + 'third time this course has found that assets behind a constraint are worth a fraction of the '
      + 'same assets in front of it.',
    ],
    explain: [
      'Three limits, and the first is severe enough to change how you should read everything above.',

      'Three hours is not a basis for an investment decision. You have been scaling an annual capital '
      + 'cost onto a three-hour window, which is arithmetically defensible and physically absurd: these '
      + 'three hours are not a representative sample of a year, they were chosen to teach dispatch. A '
      + 'real expansion study needs a full year or a carefully chosen set of representative periods, and '
      + 'that is module 7 — which is now the most important remaining module rather than a technicality.',

      'There is one investment period. Everything is built at once, at the same prices, and there is no '
      + 'sense in which the model can build wind now and a battery in ten years. PyPSA supports '
      + 'multi-period pathways and Ragnarok exposes them, but the ideas belong after module 7 has fixed '
      + 'the time axis.',

      'And there is still no policy. A carbon price would change every one of these decisions — it raises '
      + 'the cost of the gas the wire lets you avoid, which makes both the wire and the wind farm worth '
      + 'more. Module 8 turns the carbon numbers on, and it will be the second time an expansion answer '
      + 'moves for a reason that is not physical. The first was the discount rate.',

      'Export the project before you go.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Six modules on',
        tab: 'Analytics',
        note: '5,995.48 against module 1\'s 12,000, for exactly the same 290 MWh of demand. Nothing was '
          + 'asked of the consumer at any point; every saving came from describing the system better and '
          + 'letting the optimiser use the description.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. Module 7 ships this model as a checkpoint, and it is about to do '
          + 'something drastic to the time axis — so a copy of the three-hour version is worth keeping.',
      },
    ],
    verify: [
      'You can name the four attributes that make a component extendable',
      'You can say what Ragnarok does with `capital_cost` and what it leaves to you',
      'You can explain the window-scaling trap to someone about to fall into it',
      'You can say why the wind farm was worth nothing alone and 30 MW alongside the line',
      'You can say why this model is not a basis for a real investment decision',
      'The discount rate is 0.05, the model reads 5,995.48, and you have exported it',
    ],
    pitfalls: [
      'Quoting any number from this module as an investment result. The time horizon makes them '
      + 'illustrative, and the honest version of this study starts in module 7.',
      'Assuming the window scaling generalises. It works because these three hours are treated as a '
      + 'literal 3/8760 of the year; the moment snapshots are weighted to represent more time than they '
      + 'occupy, the arithmetic changes and the weights do the work instead.',
    ],
  },
];
