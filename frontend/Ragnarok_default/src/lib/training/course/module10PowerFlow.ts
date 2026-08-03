/**
 * Module 10 — Meshed networks and power flow (10 steps).
 *
 * The one module that deliberately steps AWAY from the course's growing model,
 * and says so in its first step. Everything before it teaches decisions —
 * dispatch, storage, investment, policy. This teaches a mechanism: how power
 * divides between parallel paths, and therefore why a network is not a set of
 * pipes you can route power through. A mechanism is only visible in a model
 * small enough to compute by hand, and module 7's 8,760-hour year is not that
 * model.
 *
 * So module 10 opens a purpose-built three-bus ring (`training_m10`): equal
 * reactance on every line, cheap coal at bus_1, dear gas at bus_2, all 90 MW of
 * demand at bus_3. Every figure it teaches is hand-derivable and every one is
 * pinned by a real solve in ``backend/tests/test_training_checkpoints.py``:
 *
 *   uncongested   5,400 · flows 60 / 30 / 30 MW · one price of 20 everywhere
 *   line_13 → 50  8,100 · flows 50 / 40 / 10 MW · prices 20 / 50 / 80
 *   AC pf         converges in 3 iterations · 1.000 / 0.9993 / 0.9987 pu · 0.3 MWh lost
 *   linear pf     the same flows, zero losses
 *   N-1           2 of 3 outages insecure; either long-path leg out → 180% on line_13
 *
 * The 80 at bus_3 is the module's finding, and the reason it exists: a nodal
 * price ABOVE every generator's marginal cost, in a model containing nothing
 * more exotic than three lines.
 */
import { TutorialStep } from '../types';

const SECTION = '10 · Meshed networks and power flow';

export const MODULE_10_POWER_FLOW: TutorialStep[] = [
  {
    id: 'm10-why-a-loop',
    section: SECTION,
    title: 'Why a loop changes everything',
    tab: 'Build',
    where: 'Build — with the ring network loaded',
    startOptions: {
      prebuiltExampleId: 'training_m10',
      completeExampleId: 'training_m10',
      note:
        'Both options load the same three-bus ring, because this module changes settings rather than '
        + 'the model. It is NOT module 9\'s system: see the first paragraph for why the course puts its '
        + 'year aside here.',
    },
    concept: [
      'Every network in this course so far has been radial — a line between two buses, with exactly one '
      + 'route from anywhere to anywhere. On a radial network the transport intuition is correct: 40 MW '
      + 'leaves bus_1, 40 MW arrives at bus_2, and the only question is whether the line is big enough.',

      'Real transmission systems are meshed. There is more than one path between most pairs of points, '
      + 'and that single fact breaks the intuition completely. You cannot choose which path power takes. '
      + 'It divides itself across every available path at once, in proportions set by the electrical '
      + 'properties of those paths, and no operator, market or optimiser can override that division.',

      'The law behind it is Kirchhoff\'s voltage law: around any closed loop, the voltage drops sum to '
      + 'zero. On a lossless AC network the drop along a path is proportional to its reactance times the '
      + 'flow, so two parallel paths carry flows inversely proportional to their reactance. A path with '
      + 'twice the reactance carries half the power. That is not a modelling assumption — it is what the '
      + 'physical system does.',

      'The consequence is the thing worth learning: in a meshed network you cannot relieve an overloaded '
      + 'line by re-routing. You can only change WHERE power is injected and withdrawn. Every congestion '
      + 'remedy in a real power system — redispatch, curtailment, a new line, storage siting — is a '
      + 'variation on that single move.',
    ],
    explain: [
      'This module works on a purpose-built network rather than the year you carried through modules 6 '
      + 'to 9, and that is a deliberate choice worth naming. To learn a mechanism you need a model small '
      + 'enough that you can compute the answer yourself and catch the tool being wrong. Module 7\'s '
      + '8,760 hours cannot do that. Three buses and three lines can.',

      'Load the ring from the start selector above. Three 380 kV buses — bus_1, bus_2, bus_3 — joined by '
      + 'three lines into a triangle. Cheap coal (20 per MWh, 200 MW) sits at bus_1, dear gas (50 per '
      + 'MWh, 100 MW) at bus_2, and all 90 MW of demand at bus_3. Three snapshots, flat demand.',

      'Look at the three lines before you go on. `line_12`, `line_23` and `line_13` all carry the same '
      + 'reactance — `x` = 30 — and the same 200 MW rating. Equal reactance per line is what makes the '
      + 'arithmetic in the next step doable in your head: the path that goes the long way round has two '
      + 'lines in series and therefore twice the reactance of the direct one.',

      'Those impedances are also the first realistic ones in the course. Earlier modules carried a token '
      + '`x` of 0.1 because nothing read it; 30 ohms is what about 100 km of 380 kV overhead line really '
      + 'is, and step 8 runs an AC power flow that needs it to produce a voltage drop worth reading.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="buses"]',
        buildStep: 'buses',
        title: 'Three buses',
        tab: 'Build',
        note: 'bus_1 with the coal, bus_2 with the gas, bus_3 with all the demand. Nothing here is new — '
          + 'it is the same sheet you have filled since module 1.',
      },
      {
        selector: '[data-build-step="lines"]',
        buildStep: 'lines',
        title: 'Three lines — and one loop',
        tab: 'Build',
        note: 'This is the whole difference. Two lines between three buses would be radial; the third '
          + 'closes the triangle and creates a loop. Check that `x` reads 30 on all three rows.',
      },
    ],
    entries: [
      {
        field: 'lines.x (all three rows)',
        label: 'series reactance',
        value: '30',
        unit: 'ohms',
        why: 'The number that decides how power divides, and the only electrical property that matters '
          + 'to the flows. Equal on all three lines, so the split is decided purely by how many lines a '
          + 'path contains. Halve it on one line and that line would carry twice as much.',
      },
      {
        field: 'lines.r (all three rows)',
        label: 'series resistance',
        value: '3',
        unit: 'ohms',
        why: 'Where the losses come from. The optimisation ignores it entirely; the AC power flow in '
          + 'step 8 is the only thing in Ragnarok that reads it. A tenth of the reactance is typical for '
          + 'overhead line at this voltage.',
      },
      {
        field: 'lines.s_nom (all three rows)',
        label: 'thermal rating',
        value: '200',
        unit: 'MW',
        why: 'Deliberately generous to begin with, so the first run shows what the physics does when '
          + 'nothing constrains it. Step 5 tightens one of them, which is where the module turns.',
      },
    ],
    verify: [
      'The `buses` sheet has 3 rows and the `lines` sheet has 3 rows',
      'All three lines read `x` = 30, `r` = 3, `s_nom` = 200',
      'You can trace two distinct paths from bus_1 to bus_3 on the map',
      'You can say why this module is not using the model from module 9',
    ],
    pitfalls: [
      'Reading the triangle as "three connections" rather than "one loop". The count that matters is '
      + 'lines minus buses plus one: 3 − 3 + 1 = 1 independent loop, and that is the number of extra '
      + 'physical constraints the network imposes on the flows.',
    ],
  },

  {
    id: 'm10-predict-the-split',
    section: SECTION,
    title: 'Predict the split before you run it',
    tab: 'Build',
    where: 'Away from the screen, with a pen',
    concept: [
      'Two paths run from bus_1 to bus_3. The direct one is a single line, `line_13`, with reactance 30. '
      + 'The indirect one goes bus_1 → bus_2 → bus_3 through two lines in series, so its reactance is 30 '
      + '+ 30 = 60.',

      'Flows divide inversely with reactance. The direct path has half the reactance of the indirect '
      + 'one, so it carries twice the power: two thirds down the direct line, one third the long way '
      + 'round. With 90 MW leaving bus_1, that is 60 MW on `line_13` and 30 MW on each of `line_12` and '
      + '`line_23`.',

      'Note what is NOT in that calculation: cost, capacity, distance in kilometres, or anything anyone '
      + 'chose. The 30 MW taking the scenic route is called a loop flow, and it is the single most '
      + 'common source of surprise in network modelling — power appearing on a line that nobody is '
      + 'trading across.',

      'One more thing to hold on to: the optimiser is about to reproduce this exactly. PyPSA\'s linear '
      + 'optimal power flow is not a transport model. It imposes the loop equation as a constraint on '
      + 'every cycle in the network, which means the LP you have been running since module 3 has always '
      + 'been doing physics — you just could not see it, because a radial network has no cycles.',
    ],
    explain: [
      'Do the arithmetic now, before the answer is on screen. Write down what you expect on each of the '
      + 'three lines with 90 MW injected at bus_1 and withdrawn at bus_3, and how much you expect the '
      + 'system to cost.',

      'The cost is the easy half: coal at bus_1 can serve all 90 MW at 20 per MWh, nothing constrains '
      + 'it, so the gas never runs. 90 × 20 × 3 hours = 5,400.',

      'The flows are the half worth writing down: 60 MW on `line_13`, 30 MW on `line_12`, 30 MW on '
      + '`line_23`. As a fraction of the 200 MW rating that is 30%, 15% and 15% — which is exactly how '
      + 'Ragnarok reports line loading, so you can compare directly.',

      'If you would rather derive it than take it on trust: let f be the flow on `line_13`. The '
      + 'remaining 90 − f goes the long way. Kirchhoff says the drop is equal around the loop, so 30f = '
      + '60(90 − f), giving f = 60.',
    ],
    entries: [
      {
        field: 'Your prediction — line_13',
        label: 'direct path',
        value: '60 MW (30% loaded)',
        why: 'Two thirds of 90, because the direct path has half the reactance of the alternative. This '
          + 'is the number to check first — if the model disagrees, either a reactance is wrong or a '
          + 'line is attached to the wrong bus.',
      },
      {
        field: 'Your prediction — line_12 and line_23',
        label: 'the long way round',
        value: '30 MW (15% loaded)',
        why: 'The loop flow. Nobody arranged for power to pass through bus_2, and no generator or load '
          + 'there is involved in it — the electricity simply divides.',
      },
      {
        field: 'Your prediction — objective',
        label: 'total system cost',
        value: '5,400',
        why: '90 MW × 20 per MWh × 3 hours. The gas at bus_2 never runs, because nothing stops the coal '
          + 'from serving everything.',
      },
    ],
    verify: [
      'You have three flow numbers written down before you press Run',
      'You can state the rule in one sentence: flows divide inversely with reactance',
      'You can say why the answer does not depend on the cost of anything',
    ],
    pitfalls: [
      'Expecting all 90 MW on the direct line because it is "the obvious route". Nothing in the physics '
      + 'prefers a route; the only reason the direct line carries more is that it has less reactance.',
      'Expecting the split to follow line RATINGS. Capacity has no influence on how power divides — it '
      + 'only decides whether the resulting flow is allowed.',
    ],
  },

  {
    id: 'm10-run-the-ring',
    section: SECTION,
    title: 'Run it: the network divides the power itself',
    tab: 'Analytics',
    where: 'Run dialog, then History → View result → Analytics → Result, and Analytics → Analytics',
    concept: [
      'A dispatch result you have already predicted is the most useful kind, because the only thing left '
      + 'to learn from it is whether you were right — and if you were not, exactly which part of your '
      + 'reasoning to repair.',

      'The objective will read 5,400 and every bus will price at 20. That is the familiar part: one '
      + 'marginal unit, one price, no constraint binding anywhere. The unfamiliar part is on the line '
      + 'loading card.',
    ],
    explain: [
      'Run the model — Run → Dry run off → Run model — then open it from History with View result, as '
      + 'you have since module 1.',

      'Read the objective first: 5,400, and a single price of 20 at all three buses. With no line '
      + 'binding, a meshed network prices exactly like a single bus. Everything you learnt about the '
      + 'merit order still holds.',

      'Then go to the other dashboard for the flows: Analytics → Analytics, open the Presets menu and '
      + 'pick Branch loading — the same preset module 3 used. Compare it against your predictions: '
      + '`line_13` at 30%, `line_12` and `line_23` at 15% each. Sixty megawatts direct, thirty the long '
      + 'way round.',

      'Sit with the 30 MW for a moment. Bus_2 is generating nothing and consuming nothing. No trade '
      + 'involves it. Yet 30 MW of somebody else\'s power is flowing through it in every hour, and if '
      + 'those lines were owned by a different system operator, that operator would be carrying a third '
      + 'of a transaction they were not party to. That is the real-world problem this arithmetic '
      + 'describes.',
    ],
    spotlights: [
      {
        selector: '.run-button',
        title: 'Run',
        runDialog: 'closed',
        note: 'Nothing about running changes in this module: Run, then History, then View result.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The familiar half',
        tab: 'Analytics',
        note: 'Total cost 5,400, average price 20. A meshed network with nothing binding behaves exactly '
          + 'like the single bus of module 2.',
      },
      {
        selector: '[data-tour="dashboard-presets"]',
        title: 'Branch loading',
        tab: 'Analytics',
        note: 'On Analytics → Analytics, not Result. Open Presets and pick Branch loading — the flows '
          + 'are not on the Result dashboard.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="loading"]',
        title: 'The unfamiliar half',
        tab: 'Analytics',
        note: '30% on line_13, 15% on the other two, flat across all three hours. This is the prediction '
          + 'you wrote down — and the first result in this course that came from physics rather than '
          + 'from economics.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: [
        'Three snapshots, three buses, two generators. Effectively instant.',
      ],
      expect: 'An objective of 5,400, one price of 20 at every bus, and line loadings of 30% / 15% / 15%.',
    },
    verify: [
      'Analytics → Result shows a total cost of 5,400',
      'All three buses price at 20 in every hour',
      '`line_13` is 30% loaded and `line_12` and `line_23` are 15% each',
      'Your predictions from the previous step match, or you can say which one was wrong and why',
    ],
    pitfalls: [
      'Finding all 90 MW on one line. That means the loop is not closed — check that all three lines '
      + 'exist and that `bus0` / `bus1` on each spell the bus names exactly.',
      'Finding a solver failure about a singular network. A line with `x` blank or zero cannot carry a '
      + 'loop equation, and PyPSA will say so rather than guess.',
    ],
  },

  {
    id: 'm10-cap-the-line',
    section: SECTION,
    title: 'Constrain the direct line and watch the dispatch move',
    tab: 'Build',
    where: 'Build → Lines, then run again',
    concept: [
      'The physics wants 60 MW on `line_13`. Rate that line at 50 MW and the model has a problem it '
      + 'cannot solve by re-routing, because re-routing is not available. The proportions are fixed by '
      + 'reactance.',

      'The only lever left is where power is injected. Every megawatt generated at bus_2 instead of '
      + 'bus_1 does two things at once: it removes some flow from the direct path, and it adds a '
      + 'counter-flow through the loop. Generation moves; flows follow.',

      'Work out how much has to move. With g1 at bus_1 and g2 at bus_2 serving 90 MW, superposing the '
      + 'two injections gives a flow on `line_13` of ⅔g1 + ⅓g2. Substituting g2 = 90 − g1 makes that 30 '
      + '+ g1/3, so the 50 MW limit binds at g1 = 60. Sixty megawatts of coal, thirty of gas.',

      'That costs 60 × 20 + 30 × 50 = 2,700 an hour against 1,800 before — 8,100 over three hours '
      + 'against 5,400. The 2,700 difference is the cost of the constraint, and it bought nothing: same '
      + 'demand, same fleet, same energy served.',
    ],
    explain: [
      'Go to Build → Lines and change `s_nom` on `line_13` from 200 to 50. That is the only edit in this '
      + 'step. Leave the other two lines at 200 so the long path is never the binding one.',

      'Predict again before running: coal 60 MW, gas 30 MW, objective 8,100. And on the lines — this is '
      + 'the interesting part — `line_13` exactly full at 50 MW, `line_23` at 40 MW, and `line_12` at '
      + 'only 10 MW.',

      'Those last two are worth deriving, because they show superposition doing its work. Coal\'s 60 MW '
      + 'splits 40 direct and 20 round; gas\'s 30 MW splits 20 down `line_23` and 10 the other way, back '
      + 'through `line_12` and on down `line_13`. Add them: 40 + 10 = 50 on the direct line, 20 + 20 = '
      + '40 on `line_23`, 20 − 10 = 10 on `line_12`.',

      'Run it and check all five numbers.',
    ],
    entries: [
      {
        field: 'lines.s_nom (line_13)',
        label: 'thermal rating of the direct line',
        value: '50',
        unit: 'MW',
        why: 'Chosen to sit below the 60 MW the physics wants, so the constraint binds and the model '
          + 'must redispatch. At 60 it would be exactly full and cost nothing; above 60 it would be '
          + 'invisible. The gap between what physics wants and what the wire allows is the entire '
          + 'subject of this step.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['Still three snapshots. Instant.'],
      expect: 'An objective of 8,100 — coal down to 180 MWh and gas up to 90 MWh over the three hours.',
    },
    verify: [
      'Analytics → Result shows a total cost of 8,100, against 5,400 before',
      'coal_1 produces 180 MWh and gas_2 produces 90 MWh across the three hours',
      '`line_13` reads 100% loaded, `line_23` 20%, `line_12` 5%',
      'You can say why gas runs at all, given that it is more than twice the price of coal',
    ],
    pitfalls: [
      'Reading the redispatch as the model "choosing" to send power a different way. It cannot. It chose '
      + 'a different generator, and the flows followed.',
      'Rating the line below 30 MW. Below about 30 the coal cannot help at all and the gas alone cannot '
      + 'cover 90 MW, so the run returns INFEASIBLE rather than an expensive answer.',
    ],
  },

  {
    id: 'm10-price-above-everything',
    section: SECTION,
    title: 'A price higher than any generator in the model',
    tab: 'Analytics',
    where: 'Analytics → Analytics → Presets → Nodal view',
    concept: [
      'Open the nodal prices on the congested run: 20 at bus_1, 50 at bus_2, and 80 at bus_3. The first '
      + 'two are unremarkable — each is a generator\'s cost. The third is not. There is no 80 in this '
      + 'model. The most expensive thing in it costs 50.',

      'A nodal price is the cost of serving one more MW at that bus, and at bus_3 that megawatt is '
      + 'expensive in a way no single generator explains. More coal is not available: it would push the '
      + 'direct line past its limit. So the extra megawatt has to come from gas — and because gas '
      + 'injection also relieves the loop, adding gas lets a little more coal run, which pushes the flow '
      + 'back up again. Working the algebra through, total cost is 80D − 4,500, so the marginal cost of '
      + 'demand is exactly 80.',

      'Two megawatts of adjustment for one megawatt of demand. That is what a binding constraint in a '
      + 'meshed network does to a price, and it is why nodal prices in real markets sometimes exceed '
      + 'every offer on the system — and occasionally go negative, when relieving a constraint requires '
      + 'paying someone to consume.',

      'Module 3 introduced two prices either side of one line. This is the same idea with the mesh '
      + 'turned on: the price separation is no longer bounded by the generators you own.',
    ],
    explain: [
      'With the congested run loaded, go to Analytics → Analytics, open Presets and pick Nodal view — '
      + 'the same preset module 3 used for two prices, now showing three. Read them off the Nodal SMP '
      + 'chart: 20 at bus_1, 50 at bus_2, 80 at bus_3, flat across all three hours.',

      'Check the arithmetic of the middle one too. Bus_2 prices at 50 because gas is the marginal unit '
      + 'there — an extra megawatt of demand at bus_2 is served by the machine standing next to it, with '
      + 'no loop consequences at all.',

      'Then ask the question this module exists to make you ask: if you owned a generator, where would '
      + 'you want it? Not at bus_1, where your output earns 20. The same machine at bus_3 earns 80 for '
      + 'the identical megawatt-hour. Location is not a detail of a power market — for a great deal of '
      + 'the time it is the whole of it.',

      'And the counterpart: congestion rent. The system pays 80 at bus_3 and 20 at bus_1 for power that '
      + 'crosses a 50 MW line, so 50 × 60 = 3,000 an hour accrues to nobody who generated or consumed '
      + 'anything. Module 3 met this on one line; it is the same calculation here.',
    ],
    spotlights: [
      {
        selector: '[data-tour="dashboard-presets"]',
        title: 'Nodal view',
        tab: 'Analytics',
        note: 'Analytics → Analytics again. Result reports one system price; the per-bus prices are '
          + 'here, and on a mesh the per-bus prices are the whole story.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="smp"]',
        title: 'Three prices',
        tab: 'Analytics',
        note: 'Three flat series at 20, 50 and 80. Find the 80 and remember that the dearest generator '
          + 'in the model costs 50.',
      },
    ],
    verify: [
      'The Nodal SMP chart shows three flat series at 20, 50 and 80',
      'You can explain in one sentence why bus_3 exceeds the cost of every generator',
      'You can say where you would site a new generator in this system, and why',
    ],
    pitfalls: [
      'Assuming a price above the highest marginal cost means a bug. In a meshed network with a binding '
      + 'line it is the correct answer, and the algebra above gives it exactly.',
      'Reading the 80 as the cost of energy. It is the cost of energy AT BUS 3 — the same megawatt-hour '
      + 'is worth 20 two buses away, and the difference is entirely the network.',
    ],
  },

  {
    id: 'm10-what-the-lp-was-doing',
    section: SECTION,
    title: 'What the LP was doing all along',
    tab: 'Analytics',
    where: 'Analytics → Result, and a look back at module 3',
    concept: [
      'A linear program that only enforced supply = demand at each bus and a limit on each line would be '
      + 'a transport model — power as freight, routable at will. On the ring, a transport model would '
      + 'have sent all 90 MW down the cheapest unconstrained path and never produced a loop flow.',

      'It did not, because PyPSA\'s optimisation imposes the loop equation on every independent cycle of '
      + 'the AC network. That is the linearised (DC) power flow embedded in the LP: flows are '
      + 'proportional to voltage-angle differences, and around a loop those differences must cancel.',

      'So every result in this course from module 3 onwards has been physically consistent. On a radial '
      + 'network you could not tell, because a network with no cycles has no loop equations to impose — '
      + 'transport and physics give the same answer. The mesh is what makes the difference observable.',

      'What the LP does NOT model is the rest of AC physics: voltage magnitudes, reactive power, and '
      + 'losses. It assumes every bus sits at nominal voltage and that a megawatt leaving one end of a '
      + 'line arrives at the other. The next two steps run the studies that drop those assumptions.',
    ],
    explain: [
      'No run in this step. It is the one place in the module to stop and reconcile what you have just '
      + 'seen with what you have been doing for seven modules.',

      'The reconciliation: the flows on your congested run were not produced by a routing decision, and '
      + 'they were not produced by cost. They came out of a constraint the LP has always been writing '
      + 'for you, and which module 3\'s single line was too simple to reveal.',

      'The practical consequence for your own models: reactance is not decoration. On a radial network '
      + 'you can put any positive number in `x` and the answer will not change. On a meshed one, `x` '
      + 'decides which lines congest, which generators run, and what everything is priced at. A '
      + 'plausible-looking mesh with made-up reactances gives confidently wrong answers.',

      'And the limitation to carry forward: the LP\'s flows are a linearisation. It is a good one for '
      + 'high-voltage transmission at reasonable loading — which is why the industry has used it for '
      + 'decades — and the next step measures how good.',
    ],
    verify: [
      'You can say what a transport model would have answered on the ring, and why it would be wrong',
      'You can say why module 3\'s radial network could not have shown you this',
      'You can name two things the LP still does not model',
    ],
    pitfalls: [
      'Concluding that the optimisation is "really" a power flow. It solves a linearised active-power '
      + 'subset of one — enough for flows, not enough for voltages, losses or reactive power.',
    ],
  },

  {
    id: 'm10-dc-power-flow',
    section: SECTION,
    title: 'The linear power-flow study',
    tab: 'Settings',
    where: 'Settings → Solve → Power flow',
    concept: [
      'A power-flow study asks a completely different question from an optimisation. An optimisation '
      + 'asks "what should run?" and answers with a dispatch and a set of prices. A power flow asks '
      + '"given what IS running, what does the network do?" and answers with flows and voltages. There '
      + 'is no objective, no cost and no price anywhere in the result.',

      'It is the study an operator runs before a switching action, and the study a planner runs to check '
      + 'whether a proposed network can carry a known injection pattern. In this course it does one '
      + 'thing: it lets you see the flow calculation on its own, with the economics taken away.',

      'The linear (DC) method is the same approximation the LP embeds — flows from angle differences, '
      + 'unit voltage magnitudes, no losses. It is direct rather than iterative, so it cannot fail to '
      + 'converge, which is exactly why it is the workhorse.',
    ],
    explain: [
      'Go to Settings → Solve → Power flow. Set Mode to On, then Method to Linear (DC). Read the panel '
      + 'text while you are there: it tells you the study needs branch reactance and a generator in each '
      + 'connected sub-network to act as slack.',

      'Set the `line_13` rating back to 200 first, in Build → Lines. A power-flow study takes no notice '
      + 'of ratings when it computes flows — it will happily report 180% loading — so leaving the cap on '
      + 'would only confuse the comparison you are about to make.',

      'Run. The result dashboard looks different because most of it is missing: no cost, no prices, no '
      + 'emissions. What you get is the method, whether it converged, the bus and branch counts, and the '
      + 'line loading.',

      'Compare that line loading against the run from step 3: 30% on `line_13`, 15% on the other two. '
      + 'Identical. That is the proof of what the last step claimed — the LP\'s flows and the DC power '
      + 'flow\'s flows are the same calculation.',

      'One thing to notice about the injections. A power-flow study does not optimise, so it does not '
      + 'choose a dispatch; the slack generator absorbs whatever imbalance remains. Here that means all '
      + '90 MW is injected at bus_1, which happens to match the uncongested optimum. On your own models '
      + 'it usually will not — check what the study actually assumed before you read anything into its '
      + 'flows.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="powerflow"]',
        title: 'Power flow',
        tab: 'Settings',
        note: 'Under Solve. Turning it on replaces the optimisation entirely — the panel says so, and '
          + 'the result proves it.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → Power flow → Mode',
        value: 'On',
        why: 'Swaps the solve for a physics study. Mutually exclusive with rolling horizon, pathway, '
          + 'stochastic, sampling and SCLOPF — the panel greys itself out and names the conflict rather '
          + 'than failing at run time.',
      },
      {
        field: 'Settings → Solve → Power flow → Method',
        value: 'Linear (DC)',
        why: 'The approximation the LP already uses: lossless, unit voltages, flows from angle '
          + 'differences. Direct rather than iterative, so it always returns an answer.',
      },
      {
        field: 'lines.s_nom (line_13)',
        label: 'restore the rating',
        value: '200',
        unit: 'MW',
        why: 'So the flows you compare against step 3 are the unconstrained ones. A power-flow study '
          + 'ignores ratings when computing flows and only uses them to express loading as a percentage.',
      },
    ],
    run: {
      label: 'Run → Run model (with power flow on)',
      detail: ['A direct linear solve. Faster than the optimisation it replaces.'],
      expect: 'Method "Linear (DC)", no cost or price cards at all, and line loadings of 30% / 15% / 15%.',
    },
    verify: [
      'The result reports Method: Linear (DC) and reports no objective, prices or emissions',
      'Line loadings match step 3 exactly: 30%, 15%, 15%',
      'Losses report as zero — the linear method cannot produce any',
      'You can say what injection pattern the study assumed, and where it came from',
    ],
    pitfalls: [
      'Expecting a cost. There is not one, and its absence is the point: physics does not price.',
      'Leaving power flow on for the next optimisation. Every later run in this module and elsewhere '
      + 'will silently be a physics study until you set Mode back to Off (optimise).',
    ],
  },

  {
    id: 'm10-ac-power-flow',
    section: SECTION,
    title: 'The AC power flow: voltages and losses',
    tab: 'Settings',
    where: 'Settings → Solve → Power flow → Method: AC',
    concept: [
      'The AC power flow drops both linearising assumptions. Bus voltage magnitudes become unknowns '
      + 'rather than fixed at 1.0 per unit, and the resistance of each line finally does something: '
      + 'current flowing through it dissipates I²R as heat.',

      'The equations are non-linear, so they are solved iteratively by Newton-Raphson, and iterative '
      + 'methods can fail. A heavily loaded or badly conditioned network may not converge at all — which '
      + 'is itself information, and one of the reasons planners run AC checks on cases the LP declared '
      + 'fine.',

      'Per-unit voltage is the convention to know: 1.0 pu means the bus is at its nominal voltage, so '
      + '0.9987 pu on a 380 kV bus is 379.5 kV. Grid codes typically require every bus to stay within a '
      + 'few percent of nominal, and a voltage violation is a real operating limit that no amount of '
      + 'economic dispatch will fix.',

      'Losses are the other output the optimisation never gives you. Every model in this course has '
      + 'assumed a megawatt leaving one end of a line arrives at the other. It does not, and on a long '
      + 'transmission system the shortfall is a few percent of everything generated.',
    ],
    explain: [
      'Same panel, change Method to AC (Newton-Raphson), and run again.',

      'Read the convergence line first — it is the one that can fail. On this network it converges in 3 '
      + 'iterations with a maximum mismatch around 1e-13, which is machine precision. If it had not '
      + 'converged, nothing else in the result would be worth reading.',

      'Then the voltage profile: bus_1 at 1.000 pu, bus_2 at 0.9993, bus_3 at 0.9987. The slack bus '
      + 'holds its voltage by definition and everything downstream sags a little, most at the bus '
      + 'furthest from generation. A tenth of a percent is nothing — this is a small network at light '
      + 'loading — but the SHAPE is the lesson: voltage falls away from generation and towards load.',

      'And the losses: about 0.3 MWh across the three hours. Small in absolute terms, and exactly zero '
      + 'in every optimisation you have run. Note which direction the error goes — the LP under-states '
      + 'what has to be generated, because it never pays for what the wires consume.',

      'Compare the flows once more. They are the same 30% / 15% / 15% the linear study gave, to the '
      + 'resolution the card shows. That is the answer to "how good is the DC approximation?" on a '
      + 'network like this one: good enough that the difference is in the losses, not the flows.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="powerflow"]',
        title: 'Method: AC',
        tab: 'Settings',
        note: 'The other button. Everything else about the run is identical, which makes this the '
          + 'cleanest comparison in the module.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → Power flow → Method',
        value: 'AC (Newton-Raphson)',
        why: 'Solves the full non-linear equations: voltage magnitudes and angles at every bus, and '
          + 'real losses on every branch. Costs iterations, and can fail to converge where the linear '
          + 'method cannot.',
      },
    ],
    run: {
      label: 'Run → Run model (AC method)',
      detail: [
        'Newton-Raphson on three buses. Converges in about three iterations, effectively instantly.',
      ],
      expect: 'Converged, a voltage range of roughly 0.999–1.000 pu, and a small non-zero loss figure.',
    },
    verify: [
      'The result reports Converged, with a voltage range around 0.999–1.000 pu',
      'bus_1 sits at 1.000 pu and bus_3 is the lowest of the three',
      'Losses are greater than zero — the first non-zero loss figure in this course',
      'The line loadings still match the linear study',
    ],
    pitfalls: [
      'Reading a converged AC solve as a validated model. Convergence means the equations were '
      + 'satisfied, not that the injections were sensible — and the injections came from the slack, not '
      + 'from an optimisation.',
      'Expecting the losses to change the objective. They cannot: the objective came from a different '
      + 'study, run against a network model that does not contain them.',
    ],
  },

  {
    id: 'm10-n-minus-1',
    section: SECTION,
    title: 'N-1: the network has to survive losing a line',
    tab: 'Settings',
    where: 'Settings → Solve → N-1 contingency',
    concept: [
      'Every transmission system in the world is planned and operated to an N-1 standard: the loss of '
      + 'any single element must not cause an overload, a voltage violation or a loss of supply. Not '
      + 'because failures are common, but because they are certain over a long enough horizon and '
      + 'unpredictable in timing.',

      'On a meshed network, N-1 is a genuinely non-obvious calculation. Removing a line does not just '
      + 'delete its flow — it redistributes that flow across everything that remains, in proportions '
      + 'that the reactances decide. A line that looked comfortable at 30% can be the one that fails.',

      'This is also the answer to "why build a mesh at all". A radial network fails N-1 by construction: '
      + 'lose the single line and the load beyond it is disconnected. The loop flows that made this '
      + 'module complicated are the price of redundancy.',
    ],
    explain: [
      'Set the `line_13` rating back to 50 MW in Build → Lines — the congested case is where the '
      + 'question has teeth. Then set Settings → Solve → Power flow → Mode back to Off, and turn on '
      + 'Settings → Solve → N-1 contingency instead. Like power flow, it is a study mode: it takes over '
      + 'the run rather than adding to it.',

      'Run. The study picks the peak-demand snapshot, computes the base flows, then removes each branch '
      + 'in turn and recomputes.',

      'The results, and they are worth predicting first. Lose `line_13` and the remaining path carries '
      + 'all 90 MW — 45% of a 200 MW line, comfortable. Lose either `line_12` or `line_23` and the whole '
      + '90 MW is forced onto `line_13`, which is rated at 50: 180%, an overload of nearly two to one. '
      + 'Two of the three outages leave the system insecure.',

      'Note what that means about the 50 MW cap. It is not just expensive in normal operation, costing '
      + '2,700 over three hours — it makes two of the three single-line failures unsurvivable. The '
      + 'business case for uprating that line is the sum of both, and only the first of them shows up in '
      + 'an objective function.',

      'One caveat to read honestly, because it changes what the numbers mean. Like the power-flow study, '
      + 'the contingency study runs on the injections in the network as entered, with the slack '
      + 'generator taking up the balance — not on the dispatch your last optimisation chose. That is why '
      + 'its base case shows `line_13` at 120% rather than the 100% your congested run produced: it is '
      + 'testing the all-coal injection pattern. Security-constrained dispatch, which optimises subject '
      + 'to surviving every outage, is a separate mode (Settings → Solve → SCLOPF).',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="contingency"]',
        title: 'N-1 contingency',
        tab: 'Settings',
        note: 'Under Solve, two below Power flow. Another study mode — no costs come back from it.',
      },
      {
        selector: '[data-settings-section="sclopf"]',
        title: 'And its optimising cousin',
        tab: 'Settings',
        note: 'SCLOPF dispatches subject to surviving every outage, rather than testing a dispatch '
          + 'after the fact. Not part of this module — worth knowing it is the tool for the job.',
      },
    ],
    entries: [
      {
        field: 'lines.s_nom (line_13)',
        label: 'back to the congested rating',
        value: '50',
        unit: 'MW',
        why: 'At 200 every outage is survivable and the study reports a secure system, which is true '
          + 'but teaches nothing. The interesting question is what the constrained network does when '
          + 'something else fails as well.',
      },
      {
        field: 'Settings → Solve → Power flow → Mode',
        value: 'Off (optimise)',
        why: 'Two study modes cannot both take over the run. Turn power flow off before turning '
          + 'contingency on, or the app will tell you they conflict.',
      },
      {
        field: 'Settings → Solve → N-1 contingency',
        value: 'On',
        why: 'Removes each branch in turn at the peak snapshot and recomputes every remaining flow. '
          + 'Three lines here, so three outages tested.',
      },
    ],
    run: {
      label: 'Run → Run model (contingency on)',
      detail: ['Three linear solves, one per outage. Instant on this network.'],
      expect: 'Insecure: 2 of 3 outages overload something, with a worst case of 180% on line_13.',
    },
    verify: [
      'The study reports 3 outages tested and 2 insecure',
      'Losing `line_12` or `line_23` drives `line_13` to 180%',
      'Losing `line_13` is survivable — 45% on the remaining path',
      'You can say why the base case reads 120% rather than the 100% your dispatch produced',
    ],
    pitfalls: [
      'Reading the contingency result as a verdict on your optimised dispatch. It is a verdict on the '
      + 'injection pattern in the network as entered — check which that is before quoting the numbers.',
      'Leaving a study mode on. Both power flow and contingency replace the optimisation, and a run '
      + 'that comes back with no costs is almost always one of them still switched on.',
    ],
  },

  {
    id: 'm10-what-changes',
    section: SECTION,
    title: 'What this module changes about the nine before it',
    tab: 'Analytics',
    where: 'Analytics → Result, and everything you have built',
    concept: [
      'Nothing in modules 1 to 9 was wrong. Every one of those models was radial or single-bus, and on '
      + 'a network with no loops the transport intuition and the physics agree exactly. But the reason '
      + 'they agreed was a property of those networks, not a property of modelling — and you now know '
      + 'which property it was.',

      'What changes is what you must check the moment a model has a loop in it. Reactances stop being '
      + 'decoration and become the numbers that decide which line congests. A generator\'s value becomes '
      + 'a function of where it sits. And a nodal price stops being bounded by the fleet\'s marginal '
      + 'costs.',

      'It also reframes congestion. Module 3 taught congestion as a wire that is too small for the '
      + 'transaction. On a mesh it is subtler: the wire may be too small for a flow that nobody '
      + 'transacted, arriving because of what two other parties did somewhere else.',
    ],
    explain: [
      'Take stock of the four things this module put in your hands, because they are separate tools and '
      + 'they answer separate questions.',

      'The optimisation answers "what should run, and what is it worth?" — and, since module 3, it has '
      + 'been enforcing the loop equations while it does. That is the tool for nearly everything.',

      'The linear power flow answers "what does the network do with a given injection pattern?" with no '
      + 'economics attached. Use it to check flows in isolation, or to understand a result you do not '
      + 'believe.',

      'The AC power flow answers "and what does that cost in voltage and losses?" — the two things the '
      + 'LP assumes away. Run it when voltage is a real constraint, or when losses are large enough to '
      + 'matter to the conclusion.',

      'The N-1 study answers "does this survive a failure?" — a question no objective function asks, and '
      + 'the one that most often decides whether a network gets built.',

      'Then go back to your own year from module 7 with a specific question: has it got a loop in it? If '
      + 'it has, the reactances you never looked at are deciding part of your answer. If it has not, you '
      + 'now know exactly which of this module\'s complications you are entitled to ignore — which is a '
      + 'better position than never having met them.',
    ],
    verify: [
      'You can state in one sentence why a meshed network cannot be treated as a set of pipes',
      'You can name the four study types this module used and what question each answers',
      'You can say which of your earlier models this changes, and which it does not',
      'You can explain to somebody else why a nodal price can exceed every generator\'s cost',
    ],
    pitfalls: [
      'Concluding that every model now needs an AC power flow. Most do not. The point is knowing what '
      + 'the approximation costs you, so that skipping it is a decision rather than an oversight.',
      'Leaving this module\'s ring network in the session and taking it into other work. It is a '
      + 'teaching device — three buses, flat demand, one loop — not a system.',
    ],
  },
];
