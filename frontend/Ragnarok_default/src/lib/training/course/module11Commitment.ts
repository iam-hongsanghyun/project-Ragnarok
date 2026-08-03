/**
 * Module 11 — Commitment and operating constraints (10 steps).
 *
 * The promissory note the course has been writing since module 1, where the Run
 * dialog's Force LP entry says "unit commitment is not in play". Module 2 said
 * start-up costs can make it worth generating at a loss; module 6 said a coarse
 * axis cannot see what ramp limits are for; module 9 listed unit commitment
 * among the things it had not done. This redeems all three.
 *
 * The model (`training_m11`) is six hours with a windy midday dip: demand
 * 90/90/50/50/90/90 against wind that is zero except in the two dip hours, where
 * it is full. That puts a committable coal unit in front of one clean decision —
 * hold minimum stable output and push out free wind, or shut down for two hours
 * and pay to restart — so a single number flips the answer. Every figure below
 * is pinned by a real solve in ``backend/tests/test_training_checkpoints.py``:
 *
 *   as shipped (start-up 3,000)   8,800 · coal holds 40 MW · 70 MW/h of wind spilt · 0 starts
 *   start-up 1,000                7,200 fuel + 1,000 start-up = 8,200 · 1 start · online 67%
 *   min_down_time 3               8,800 again — the dip is too short to shut for
 *   ramp_limit 0.3                9,800 · and the cost lands BESIDE the dip, not in it
 *   Force LP                      7,200 · the relaxation, and the only run that prices
 *
 * Two app defects were found and fixed while writing it, both of which would
 * have made the module unteachable: start-up costs were missing from the cost
 * breakdown (so the 1,000 was invisible), and Force LP cleared `committable`
 * while leaving `p_min_pu` behind, which turns a minimum-when-running into an
 * always-on floor and made the "relaxation" cost MORE than the MILP.
 */
import { TutorialStep } from '../types';

const SECTION = '11 · Commitment and operating constraints';

export const MODULE_11_COMMITMENT: TutorialStep[] = [
  {
    id: 'm11-not-a-tap',
    section: SECTION,
    title: 'A power station is not a tap',
    tab: 'Build',
    where: 'Build → Generators, with the committable fleet loaded',
    startOptions: {
      prebuiltExampleId: 'training_m11',
      completeExampleId: 'training_m11',
      note:
        'Both options load the same six-hour fleet, because this module changes one generator attribute '
        + 'at a time and re-runs. Like module 10 it is a purpose-built teaching model rather than a '
        + 'continuation of the year.',
    },
    concept: [
      'Every model in this course so far has treated a generator as a tap: it can produce anything from '
      + 'zero to its rating, in any hour, at no cost beyond fuel. That is a good enough description of a '
      + 'battery inverter or a wind farm. It is a bad description of a thermal power station.',

      'A real thermal plant has a minimum stable output — below roughly 40% of rating, combustion and '
      + 'steam conditions cannot be held and the unit trips. It cannot start instantly: a warm gas unit '
      + 'takes tens of minutes, a cold coal unit most of a day. Starting costs real money in fuel burnt '
      + 'without export and in thermal-cycling damage to the plant. And once stopped it must usually '
      + 'stay stopped for hours before it can start again.',

      'Together those are unit commitment: on top of "how much should each plant produce" sits a prior, '
      + 'yes/no question — "should this plant be running at all?" And a yes/no variable is an integer, '
      + 'which turns the linear program you have been solving into a mixed-integer one. That change has '
      + 'consequences all the way through this module, including for prices.',

      'The word to keep separate from "dispatch" is "commitment". Dispatch is how much a running unit '
      + 'produces. Commitment is whether it is running. The second decision has to be made before the '
      + 'first, over a horizon, and it is where most of the operational complexity of a power system '
      + 'lives.',
    ],
    explain: [
      'Load the fleet from the start selector. One bus, six hours, three units: a committable coal unit, '
      + 'a flexible gas unit and a wind farm.',

      'The demand profile is the point of the model: 90, 90, 50, 50, 90, 90 MW. A deep two-hour dip in '
      + 'the middle. And the wind profile is its mirror — zero availability in the four busy hours, full '
      + '80 MW availability in exactly the two dip hours. Windy nights with low demand are the real '
      + 'situation this abstracts, and they are when commitment decisions actually bite.',

      'Open Build → Generators and read the coal row across. Four attributes there are new, and they are '
      + 'the module: `committable`, `p_min_pu`, `start_up_cost` and `min_down_time`. The gas unit and the '
      + 'wind farm have none of them — they stay taps, which is what makes the contrast legible.',

      'Note that `p_min_pu` means something different on a committable unit than anywhere else in this '
      + 'course. On an ordinary generator it is a floor in every snapshot. On a committable one it is a '
      + 'floor only while the unit is running, and zero while it is off. Step 9 shows what happens when '
      + 'that distinction is lost.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'The committable row',
        tab: 'Build',
        note: 'coal_1 carries all four commitment attributes. Scroll right if the columns are off the '
          + 'edge — `committable`, `p_min_pu`, `start_up_cost` and `min_down_time` are the ones to find.',
      },
    ],
    entries: [
      {
        field: 'generators.committable (coal_1)',
        label: 'is this unit switched on and off?',
        value: 'true',
        why: 'The flag that adds the yes/no variable. Without it every other attribute in this list '
          + 'either does nothing or means something else. It is also what turns the solve from an LP '
          + 'into a MILP, which is why it is a flag rather than the default.',
      },
      {
        field: 'generators.p_min_pu (coal_1)',
        label: 'minimum stable output, as a fraction of p_nom',
        value: '0.4',
        why: '40% of 100 MW, so 40 MW is the least this unit can produce WHILE RUNNING. It is the '
          + 'number that makes the dip a decision: demand in the dip is 50 MW and free wind could cover '
          + 'all of it, but a running coal unit insists on 40 of those megawatts.',
      },
      {
        field: 'generators.start_up_cost (coal_1)',
        label: 'cost of one start',
        value: '3000',
        unit: 'currency per start',
        why: 'Charged once per transition from off to on — fuel burnt before export plus the thermal '
          + 'damage of cycling. It is a cost per EVENT, not per MWh, which is why no amount of studying '
          + 'the marginal cost tells you whether stopping is worth it. Step 4 changes this one number '
          + 'and gets the opposite answer.',
      },
      {
        field: 'generators.min_down_time (coal_1)',
        label: 'hours it must stay off once stopped',
        value: '2',
        unit: 'hours',
        why: 'A stopped unit cannot restart immediately — the boiler has to be brought back up. Two '
          + 'hours exactly fits the dip, so it does not bind as shipped. Step 6 raises it to 3 and the '
          + 'shutdown becomes impossible.',
      },
    ],
    verify: [
      'The `generators` sheet has 3 rows, and only coal_1 has `committable` set',
      'The demand profile reads 90 / 90 / 50 / 50 / 90 / 90',
      'The wind profile reads 0 / 0 / 1 / 1 / 0 / 0',
      'You can say the difference between commitment and dispatch in one sentence',
    ],
    pitfalls: [
      'Setting `committable` on the wind farm or the gas unit "for realism". Every committable unit '
      + 'adds binary variables per snapshot, and this module wants exactly one decision to watch.',
    ],
  },

  {
    id: 'm11-predict-the-dip',
    section: SECTION,
    title: 'Work out what it should do in the dip',
    tab: 'Build',
    where: 'Away from the screen, with a pen',
    concept: [
      'Hours 1, 2, 5 and 6 are not a decision. Demand is 90 MW, there is no wind, and coal at 20 is '
      + 'cheaper than gas at 50 — so coal runs at 90 in each of them, costing 1,800 an hour, 7,200 in '
      + 'total. That part is module 2 and needs no thought.',

      'The dip is the decision, and it has exactly two options.',

      'Stay on. The unit cannot go below 40 MW while running, so it produces 40 and wind covers the '
      + 'other 10 of the 50 MW demand. That costs 40 × 20 = 800 an hour, 1,600 over the two hours — and '
      + 'it spills 70 MW of free wind in each of them, because the wind was there and the coal was in '
      + 'the way.',

      'Shut down. Wind covers all 50 MW for nothing, so the dip itself is free — but the unit must be '
      + 'restarted for hour 5, and that costs whatever `start_up_cost` says.',

      'So the comparison is 1,600 of unnecessary coal against one start-up charge. At a start-up cost '
      + 'of 3,000 the unit stays on and the answer is 7,200 + 1,600 = 8,800. Everything in this module '
      + 'follows from that single inequality.',
    ],
    explain: [
      'Write down both totals before you run anything: 8,800 for staying on, 10,200 for shutting down '
      + 'and restarting at 3,000. Then write the number that would flip it — anything below 1,600.',

      'Also predict what you expect the wind to do, because it is the part people miss. Staying on '
      + 'spills 70 MW an hour of a free resource. That is not a rounding error: it is 140 MWh of clean '
      + 'energy thrown away to avoid a 3,000 start-up charge, and the model is right to do it.',

      'This is the mechanism behind a real and much-discussed phenomenon. When a system is full of '
      + 'must-run thermal plant that cannot afford to stop, wind and solar get curtailed and prices go '
      + 'to zero or below in exactly the hours renewables are most abundant. You are about to reproduce '
      + 'it in six hours and three generators.',
    ],
    entries: [
      {
        field: 'Your prediction — objective',
        label: 'total system cost',
        value: '8,800',
        why: '7,200 for the four busy hours plus 1,600 of minimum-stable coal through the dip. Staying '
          + 'on beats a 3,000 restart.',
      },
      {
        field: 'Your prediction — coal in the dip hours',
        label: 'held at minimum',
        value: '40 MW',
        why: 'p_min_pu × p_nom. Not a choice the optimiser makes — the floor it is stuck with once it '
          + 'has decided to stay on.',
      },
      {
        field: 'Your prediction — wind spilt in each dip hour',
        label: 'curtailment',
        value: '70 MW',
        why: '80 MW available, 10 MW taken. The coal unit is occupying 40 MW of a 50 MW demand, so the '
          + 'wind gets what is left.',
      },
    ],
    verify: [
      'You have written down 8,800 and the alternative 10,200',
      'You can say what start-up cost would change the decision',
      'You can explain why free wind gets thrown away without anything being wrong',
    ],
    pitfalls: [
      'Comparing the dip options on fuel cost alone. The start-up charge is not per MWh and does not '
      + 'appear anywhere in a merit order — which is exactly why commitment cannot be reasoned about '
      + 'with the tools of module 2.',
    ],
  },

  {
    id: 'm11-run-committed',
    section: SECTION,
    title: 'Run it: the unit stays on and the wind pays for it',
    tab: 'Analytics',
    where: 'Run dialog, then History → View result → Analytics → Result',
    concept: [
      'The answer should be 8,800, with coal pinned at 40 MW through the dip and 70 MW of wind spilt in '
      + 'each of those hours. If it is, you have just reproduced the single most-discussed operational '
      + 'phenomenon in a decarbonising power system from four generator attributes.',

      'The Result dashboard grows a card it has never shown you before: the commitment view, listing '
      + 'each committable unit with the number of starts, the fraction of the horizon it was online, '
      + 'and the run segments. On this run it should read zero starts and 100% online.',
    ],
    explain: [
      'Run — Run → Dry run off → Run model — and open it from History with View result.',

      'Read the objective first: 8,800, as predicted. Then the dispatch chart: coal at 90 in the four '
      + 'busy hours and a flat shelf at 40 through the dip. That shelf is `p_min_pu` made visible.',

      'Then the curtailment card. 70 MW an hour of wind spilt in the two dip hours — against 30 MW an '
      + 'hour if the coal had been able to get out of the way, which is the run you will do in step 9.',

      'And find the new commitment card. Zero starts, 100% online, one continuous run segment covering '
      + 'all six hours. The unit never stopped, so it never paid to start.',

      'One thing to leave alone for now: the prices. They will read zero in every hour, including the '
      + 'busy ones, which is obviously wrong — coal is running at 20. Step 8 is about why, and it is a '
      + 'property of mixed-integer problems rather than a bug in this model.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The objective',
        tab: 'Analytics',
        note: '8,800. Reconcile it against your 7,200 + 1,600 before reading anything else.',
      },
      {
        selector: '[data-card="commitment"]',
        title: 'The commitment card',
        tab: 'Analytics',
        note: 'New in this module, and it only appears when a run has committable units. Starts, online '
          + 'fraction, and the on/off segments. Zero starts here — the unit never stopped.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="curtailment"]',
        title: 'What it cost the wind',
        tab: 'Analytics',
        note: '70 MW an hour spilt in the dip. Free energy discarded so a coal unit could avoid a '
          + 'start-up charge — correctly, on these numbers.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: [
        'Six snapshots and one binary variable per snapshot. HiGHS solves it at the root node — '
        + 'instant, though the log now mentions a branch-and-bound tree where it used to say simplex.',
      ],
      expect: 'An objective of 8,800, coal flat at 40 MW through the dip, and a commitment card '
        + 'reporting zero starts.',
    },
    verify: [
      'Analytics → Result shows a total cost of 8,800',
      'Coal sits at exactly 40 MW in both dip hours and 90 MW in the other four',
      'The commitment card reports 0 starts and 100% online',
      '70 MW of wind is curtailed in each dip hour',
    ],
    pitfalls: [
      'An INFEASIBLE result. If you lowered demand in the dip below 40 MW, a running coal unit produces '
      + 'more than the system needs and nothing can absorb it — with no storage, no export and no load '
      + 'shedding, there is no answer at all.',
      'Reading zero prices as free electricity. They are meaningless on this run; step 8 explains.',
    ],
  },

  {
    id: 'm11-one-number',
    section: SECTION,
    title: 'One number, and the plant makes the opposite decision',
    tab: 'Build',
    where: 'Build → Generators, then run again',
    concept: [
      'The inequality from step 2 was 1,600 of unnecessary coal against one start-up charge. Nothing '
      + 'about the physics changes if the start-up charge is smaller — but the answer does, completely.',

      'At a start-up cost of 1,000 the arithmetic reverses: pay 1,000 once, save 1,600 of coal, and let '
      + 'the wind have the dip. The unit stops for two hours and restarts for hour 5. Total: 7,200 of '
      + 'fuel plus 1,000 of start-up, 8,200.',

      'It is worth registering how large that swing is for how small an edit. One cell, no change to '
      + 'demand, capacity, fuel price or anything a merit order can see, and the system runs '
      + 'differently, emits differently and spills less than half as much wind. Commitment parameters '
      + 'are among the least-scrutinised numbers in most models and among the most consequential.',
    ],
    explain: [
      'Change `start_up_cost` on coal_1 from 3000 to 1000. That is the only edit. Then run again.',

      'Predict first: 8,200, with the dip served entirely by wind, one start, and the unit online for '
      + 'four of the six hours — 67%.',

      'Read the objective, then go back to the commitment card. One start now, online fraction 67%, and '
      + 'the segments show a run, a gap and a run rather than one continuous block. That card is the '
      + 'clearest picture of what changed.',

      'And check the curtailment: 30 MW an hour instead of 70. The wind is still spilt — 80 MW '
      + 'available against 50 MW of demand and nowhere to put the surplus — but far less of it.',
    ],
    entries: [
      {
        field: 'generators.start_up_cost (coal_1)',
        label: 'cost of one start',
        value: '1000',
        unit: 'currency per start',
        why: 'Below the 1,600 that staying on costs, so stopping becomes worth it. Anything above 1,600 '
          + 'and the unit holds on; the break-even is a number you can compute rather than discover.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['Same six snapshots. Instant.'],
      expect: 'An objective of 8,200 — 7,200 of fuel and 1,000 of start-up — with one start and the '
        + 'unit offline through the dip.',
    },
    verify: [
      'Analytics → Result shows a total cost of 8,200',
      'Coal produces nothing in the two dip hours and wind covers all 50 MW',
      'The commitment card reports 1 start and an online fraction of about 67%',
      'Curtailment drops from 70 MW an hour to 30 MW',
    ],
    pitfalls: [
      'Expecting the objective to fall by the full 1,600. It falls by 600 — the saving less the start-up '
      + 'you now pay. 8,800 → 8,200.',
    ],
  },

  {
    id: 'm11-where-the-cost-is',
    section: SECTION,
    title: 'Where the 1,000 appears — and why "fuel cost" is not the answer',
    tab: 'Analytics',
    where: 'Analytics → Result → cost breakdown',
    concept: [
      'Look at the cost breakdown on the run you just did. Fuel cost reads 7,200 — the same as a run '
      + 'with no commitment at all. The other 1,000 is on its own line: start-up / shut-down cost.',

      'That line only appears when a unit actually changed state, and it exists because a start-up '
      + 'charge is not proportional to anything. Every other cost in this course scales with energy: '
      + 'fuel with MWh, carbon with MWh times an emission factor, capital with MW. A start is a fixed '
      + 'charge for an event that either happened or did not.',

      'This is why the objective and the fuel bill diverge under commitment, and why quoting "fuel '
      + 'cost" as system cost silently understates a committed system. On the previous run the two '
      + 'agreed at 8,800 only because the unit never stopped.',
    ],
    explain: [
      'Find the cost breakdown on the Result dashboard and read all four rows on the 8,200 run: fuel '
      + '7,200, carbon 0, load shedding 0, start-up / shut-down 1,000.',

      'Then go back and load the 8,800 run from History and look again. Three rows — no start-up line '
      + 'at all, because there were no starts to charge. The absence is informative.',

      'The habit to take away is a small one and it applies well beyond this module: when a model gains '
      + 'a new kind of cost, check that the total you are quoting includes it. A number that was '
      + 'complete in module 2 is not automatically complete in module 11.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Total cost vs fuel cost',
        tab: 'Analytics',
        note: 'The KPI total is the one to trust. Fuel alone reads 7,200 on this run and the system '
          + 'cost 8,200.',
      },
    ],
    verify: [
      'The 8,200 run shows a start-up / shut-down cost of 1,000 in the breakdown',
      'The 8,800 run shows no start-up line at all',
      'You can say why a start-up cost cannot appear in a merit order',
    ],
    pitfalls: [
      'Comparing two commitment runs on fuel cost. Both of these report 7,200 or 8,800 of fuel; the '
      + 'decision between them turns entirely on the line that is not fuel.',
    ],
  },

  {
    id: 'm11-min-down-time',
    section: SECTION,
    title: 'Minimum down time: the shutdown that is not allowed',
    tab: 'Build',
    where: 'Build → Generators, then run again',
    concept: [
      'A start-up cost says stopping is expensive. Minimum down time says stopping is sometimes simply '
      + 'not available. Once a thermal unit is off, boiler and turbine conditions have to be re-established '
      + 'before it can be brought back — hours for a warm unit, most of a day for a cold one.',

      'As shipped, `min_down_time` is 2 and the dip is exactly two hours long, so the constraint is '
      + 'satisfied with nothing to spare. Raise it to 3 and the only available shutdown no longer fits: '
      + 'stopping at hour 3 would mean staying off through hour 5, when demand is back at 90 MW.',

      'So the unit stays on and the answer returns to 8,800 — with the start-up cost still at 1,000. '
      + 'The economics say stop; the operating constraint says you cannot. That distinction, between '
      + 'what is worth doing and what is possible, is most of what unit commitment adds.',
    ],
    explain: [
      'Leave `start_up_cost` at 1000 and change `min_down_time` from 2 to 3. Run again.',

      'The objective goes back to 8,800 and the commitment card back to zero starts — the same answer '
      + 'as the original run, reached for a completely different reason. In step 3 the unit stayed on '
      + 'because stopping was too expensive. Here it stays on because stopping is infeasible.',

      'Two runs, identical outputs, different explanations. If you only ever read objectives you cannot '
      + 'tell them apart, which is the argument for the commitment card and for reading the inputs that '
      + 'produced a result rather than only the result.',

      'Set `min_down_time` back to 2 before the next step, so you are working from the shipped model '
      + 'again. There is also a `min_up_time` with the mirror meaning — how long a unit must run once '
      + 'started — which this model does not need but a real fleet always has.',
    ],
    entries: [
      {
        field: 'generators.min_down_time (coal_1)',
        label: 'hours off before it may restart',
        value: '3',
        unit: 'hours',
        why: 'One hour longer than the dip, which is all it takes. The optimiser can no longer buy the '
          + 'cheap two-hour shutdown at any price, so the start-up cost stops mattering.',
      },
      {
        field: 'generators.min_down_time (coal_1)',
        label: 'restore before step 7',
        value: '2',
        unit: 'hours',
        why: 'Back to the shipped model so the ramp experiment that follows is not confounded by a '
          + 'binding down-time constraint.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['Instant, as before.'],
      expect: 'An objective of 8,800 with zero starts — the shutdown from step 4 has become impossible.',
    },
    verify: [
      'With min_down_time 3 the objective returns to 8,800 and the commitment card shows 0 starts',
      'You can say why the start-up cost of 1,000 no longer influences the answer',
      'min_down_time is back at 2 before you continue',
    ],
    pitfalls: [
      'Concluding that min_down_time always costs money. It costs money only when a shutdown was worth '
      + 'having. At a start-up cost of 3,000 it changes nothing at all, because the unit was staying on '
      + 'regardless.',
    ],
  },

  {
    id: 'm11-ramp-limits',
    section: SECTION,
    title: 'Ramp limits: the cost lands beside the dip, not in it',
    tab: 'Build',
    where: 'Build → Generators, then run again',
    concept: [
      'The last operating constraint in this module does not care whether a unit is on or off. A ramp '
      + 'limit bounds how much its output may change from one hour to the next — thermal stress in the '
      + 'boiler and turbine is a function of the rate of change, not the level.',

      '`ramp_limit_up` and `ramp_limit_down` are fractions of p_nom per hour. At 0.3 this unit may move '
      + '30 MW an hour, which sounds generous until you look at what the profile asks of it: 90 down to '
      + '40 between hours 2 and 3 is a 50 MW step, and 40 back to 90 between hours 4 and 5 is another.',

      'What the model does about it is the interesting part, and it is not what most people guess. It '
      + 'does not shed load and it does not spill more wind in the dip. It starts moving EARLY — coal '
      + 'walks 90, 80, 50, 50, 80, 90 — and buys the 10 MW it is now short in the hours either side '
      + 'from the gas unit at 50. The constraint binds in the dip and the cost is paid next door.',
    ],
    explain: [
      'With the shipped model restored — start-up 3000, min_down_time 2 — set `ramp_limit_up` and '
      + '`ramp_limit_down` on coal_1 to 0.3. Run again.',

      'The objective is 9,800, a thousand more than the 8,800 you started with. Then read the dispatch '
      + 'chart hour by hour, because the shape is the lesson: coal 90 / 80 / 50 / 50 / 80 / 90, and gas '
      + 'running 10 MW in hours 2 and 5 — hours where demand is 90 and nothing appeared to be wrong.',

      'Sit with that. Gas ran in an hour that had no scarcity, no congestion and no outage, purely '
      + 'because of what the coal unit had to do two hours later. Ramp constraints propagate: they '
      + 'couple hours the way storage does, and a cost that shows up in one hour can be caused by '
      + 'another.',

      'Note also that coal now sits at 50 in the dip rather than 40. It never reaches its own minimum, '
      + 'because it could not get down that far in one step from 80. The floor was not the binding '
      + 'constraint any more — the rate was.',

      'Clear both ramp limits before the next step.',
    ],
    entries: [
      {
        field: 'generators.ramp_limit_up (coal_1)',
        label: 'maximum hourly increase, as a fraction of p_nom',
        value: '0.3',
        why: '30 MW an hour. Typical for a large coal unit; a modern CCGT does better and an open-cycle '
          + 'turbine far better, which is a large part of why flexible plant is worth having.',
      },
      {
        field: 'generators.ramp_limit_down (coal_1)',
        label: 'maximum hourly decrease',
        value: '0.3',
        why: 'The same limit downwards. It is what forces the early descent — the unit has to start '
          + 'coming down an hour before the dip to be anywhere near its floor when the dip arrives.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['Six snapshots with ramp constraints linking them. Still instant.'],
      expect: 'An objective of 9,800, coal walking 90 / 80 / 50 / 50 / 80 / 90, and gas running 10 MW '
        + 'in two hours where nothing else looks unusual.',
    },
    verify: [
      'The objective reads 9,800',
      'Coal never changes by more than 30 MW between consecutive hours',
      'Gas produces 10 MW in hours 2 and 5, and nothing anywhere else',
      'Coal sits at 50 in the dip rather than its 40 MW floor — and you can say why',
      'Both ramp limits are cleared before you continue',
    ],
    pitfalls: [
      'Looking for the cost of a ramp limit in the hour where the ramp happens. It is usually next '
      + 'door: the plant that had to be held back, or brought up, in an adjacent hour.',
      'Setting a ramp limit tighter than a profile can accommodate and getting INFEASIBLE. With no '
      + 'flexible unit to fill the gap, a 0.1 limit here would have no feasible schedule at all.',
    ],
  },

  {
    id: 'm11-prices-are-not-prices',
    section: SECTION,
    title: 'The prices on these runs are not prices',
    tab: 'Analytics',
    where: 'Analytics → Result, and the run notes',
    concept: [
      'Every price in this course so far has been a shadow price: the dual of the supply-equals-demand '
      + 'constraint, the cost of serving one more MW. Duals are a property of linear programs. A '
      + 'mixed-integer program does not have them.',

      'The reason is easy to see once stated. A dual answers "what would one more MW cost?" — and with '
      + 'integers in the problem the honest answer can be a discrete jump: nothing at all until a unit '
      + 'has to be started, then thousands. There is no single derivative, because the cost function is '
      + 'not smooth.',

      'PyPSA still fills the marginal-price field after a MILP solve, with whatever the solver left '
      + 'behind — on these runs a flat zero in every hour. Read literally that says the system gave '
      + 'power away for six hours while burning coal, which nobody would believe. But a plausible wrong '
      + 'number is more dangerous than an obviously wrong one, and capture prices, revenues and the '
      + 'whole asset-economics card are built on top of it.',

      'The standard practice, in this tool and in the industry, is two solves: run the MILP to decide '
      + 'the commitment, then fix that schedule and re-solve as an LP to get prices. Real markets do '
      + 'exactly this — the prices published after a day-ahead auction come from a pricing run, not '
      + 'from the commitment optimisation.',
    ],
    explain: [
      'Load any of this module\'s runs and look at the price cards: zero, everywhere, in every hour, '
      + 'regardless of what the unit was doing.',

      'Then read the run notes on the Result dashboard. Ragnarok says so explicitly — that prices from '
      + 'a unit-commitment run are not shadow prices, that the marginal prices, capture prices and '
      + 'revenues below are unreliable, and what to do about it. Notes are the least-read part of a '
      + 'result dashboard and they are where this kind of thing lives.',

      'Compare that against every module before this one, where the price WAS the answer to a question '
      + 'you cared about — the marginal unit in module 2, congestion in module 3, the carbon shadow '
      + 'price in module 8. Turning on commitment costs you all of it, and that is a real trade-off '
      + 'rather than a defect.',

      'The next step does the LP pricing run.',
    ],
    spotlights: [
      {
        selector: '[data-card="notes"]',
        title: 'The run notes',
        tab: 'Analytics',
        note: 'At the bottom of the Result dashboard. The commitment warning is here, and so is the '
          + 'list of what the build phase did to your model. Worth reading on every unfamiliar result.',
      },
      {
        selector: '[data-card="generator-economics"]',
        title: 'Built on sand',
        tab: 'Analytics',
        note: 'Revenue, capture price and cost recovery all derive from the marginal price. On a MILP '
          + 'run every one of them is unusable — which is not obvious from looking at them.',
      },
    ],
    verify: [
      'The marginal price reads zero in every hour of a commitment run',
      'You can find the run note that says commitment prices are not shadow prices',
      'You can explain in one sentence why a MILP has no duals',
      'You can name three cards on the dashboard that a MILP run makes unreliable',
    ],
    pitfalls: [
      'Quoting a capture price or a revenue from a commitment run. They are computed from a price that '
      + 'does not mean anything, and nothing in the number itself gives that away.',
    ],
  },

  {
    id: 'm11-force-lp',
    section: SECTION,
    title: 'Force LP: the relaxation, the bound, and the prices',
    tab: 'Analytics',
    where: 'Run dialog → Force LP',
    concept: [
      'Force LP drops the integer variables and solves the same fleet as an ordinary linear program. '
      + 'The unit may then be "60% committed" — which is physically meaningless and analytically very '
      + 'useful, for three separate reasons.',

      'It is a bound. A relaxation can never cost more than the problem it relaxes, so its objective is '
      + 'a floor under the true answer. Here it is 7,200 against a committed 8,800: the gap, 1,600, is '
      + 'the price of the operating constraints, isolated in a single number.',

      'It prices. With no integers there are duals again, and they are sensible: 20 in the four hours '
      + 'coal is marginal and 0 in the two dip hours where free wind is. That is a usable price series, '
      + 'and pairing it with the MILP\'s commitment decision is the two-solve pattern from the previous '
      + 'step.',

      'And it is fast. Every committable unit multiplies the search space; a year of a real fleet can '
      + 'take hours as a MILP and seconds as an LP. Solving the relaxation first is how you find out '
      + 'whether the commitment detail is worth waiting for.',
    ],
    explain: [
      'With the shipped model restored, open the Run dialog and turn Force LP on, then run.',

      'The objective is 7,200, with no start-up line, coal free to fall to zero through the dip, and 30 '
      + 'MW an hour of wind curtailed rather than 70. It is the same fleet answering the question '
      + '"what if physics did not get in the way?".',

      'Read the prices: 20, 20, 0, 0, 20, 20. After a whole module of zeros, prices that mean something.',

      'And read the run notes again. Force LP reports what it overrode — the committable flags, and '
      + 'also `p_min_pu` on the units it de-committed. That second override matters more than it '
      + 'sounds, and the next step is about why.',

      'Finally, hold the three numbers together: 7,200 relaxed, 8,800 committed as shipped, 8,200 '
      + 'committed with a cheaper start. The first is a bound, the other two are answers, and the '
      + 'distance between the bound and an answer is what the operating constraints cost.',
    ],
    spotlights: [
      {
        selector: '[data-tour="force-lp"]',
        title: 'Force LP',
        runDialog: 'open',
        note: 'In the optimisation settings, beside Dry run. It changes WHAT is solved rather than '
          + 'whether it is solved, and it stays on until you turn it off.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="system_price"]',
        title: 'Prices that mean something',
        tab: 'Analytics',
        note: '20 / 20 / 0 / 0 / 20 / 20 — the marginal unit in each hour, exactly as module 2 taught. '
          + 'The relaxation is the only run in this module that can tell you this.',
      },
    ],
    entries: [
      {
        field: 'Run dialog → Force LP',
        value: 'on',
        why: 'Relaxes every committable flag for this run only — the workbook is untouched. Gives a '
          + 'lower bound on the committed answer and a usable price series, and solves far faster on a '
          + 'large fleet.',
      },
    ],
    run: {
      label: 'Run → Force LP on → Run model',
      detail: ['A plain LP again — no branch-and-bound tree in the solver log.'],
      expect: 'An objective of 7,200 with prices of 20 / 20 / 0 / 0 / 20 / 20 and no start-up cost.',
    },
    verify: [
      'The objective reads 7,200 — below both committed answers',
      'The price series reads 20 / 20 / 0 / 0 / 20 / 20',
      'The run notes say what Force LP overrode, including p_min_pu',
      'You can say what the 1,600 gap between 7,200 and 8,800 represents',
    ],
    pitfalls: [
      'Reporting a Force LP objective as the system cost. It is a bound, and a fleet it describes could '
      + 'not be operated — units run at fractional commitment and below their stable minimum.',
      'Forgetting to turn it off. Every later run is a relaxation until you do, and nothing on the '
      + 'dashboard shouts about it except the notes.',
    ],
  },

  {
    id: 'm11-the-trap-and-the-cost',
    section: SECTION,
    title: 'The p_min_pu trap, and what commitment costs to use',
    tab: 'Analytics',
    where: 'Analytics → Validation, then a look back',
    concept: [
      'The trap is worth knowing because it is silent and the model still solves. `p_min_pu` means '
      + '"minimum while running" on a committable unit and "minimum in every snapshot" on any other. '
      + 'Clear the `committable` flag and leave the 0.4 behind, and the unit is not de-committed — it '
      + 'is welded on at 40 MW for the whole horizon.',

      'That model can cost more than the committed one it was meant to simplify, and on a profile with '
      + 'a deep enough trough it is infeasible outright. Ragnarok\'s validation now names it, and Force '
      + 'LP clears the floor along with the flag, but a hand-edited workbook will not.',

      'The other cost of commitment is arithmetic. Each committable unit adds a binary variable per '
      + 'snapshot: one unit over six hours is six binaries and solves at the root node, while thirty '
      + 'units over 8,760 hours is a quarter of a million, and a problem that took seconds as an LP can '
      + 'take hours. That is why commitment is a flag, and why "should this be committable?" is a '
      + 'modelling decision rather than a realism setting.',
    ],
    explain: [
      'See the trap once, deliberately. Clear `committable` on coal_1 but leave `p_min_pu` at 0.4, then '
      + 'open the Run dialog with Dry run on and press Validate. Analytics → Validation reports it: '
      + 'p_min_pu without committable=True is an unconditional floor, and it tells you the two ways out.',

      'Then decide when commitment is worth turning on at all. It earns its cost when the question is '
      + 'operational — cycling, minimum-generation curtailment, start-up costs, whether a plant can '
      + 'follow a renewable profile. It rarely earns it in a capacity-expansion study, where the '
      + 'question is what to build and a year of hourly binaries buys precision nobody uses.',

      'And go back over this course with the operating constraints in mind. Module 2\'s peaker switched '
      + 'on and off freely and cost nothing to start. Module 4\'s battery had no minimum output, which '
      + 'is realistic. Module 6\'s day showed a morning ramp that no generator in it was constrained to '
      + 'follow. Module 7 built capacity assuming everything it built could be dispatched as a tap.',

      'None of those was wrong — each answered its own question, and a model that carries every real '
      + 'constraint answers no question in reasonable time. But you now know which simplification each '
      + 'one was making, which is the difference between using a model and believing it.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Validation"]',
        title: 'Where the trap surfaces',
        tab: 'Analytics',
        note: 'Validation catches the p_min_pu floor in seconds, without a solve. It is also the '
          + 'cheapest habit in this application and the one people skip.',
      },
    ],
    verify: [
      'Validation reports the p_min_pu-without-commitment finding when you clear the flag',
      'You can say why that model can cost MORE than the committed one',
      'You can say roughly how many binary variables 30 committable units over a year implies',
      'You can name one question that needs commitment and one that does not',
    ],
    pitfalls: [
      'Making every thermal unit committable in a long study because it is more realistic. It is more '
      + 'realistic and it may not finish; representative days or a relaxed year are the usual answers.',
      'Leaving Force LP on after this module. Modules 1 to 10 all solve the same either way, so nothing '
      + 'will look wrong — which is exactly the problem.',
    ],
  },
];
