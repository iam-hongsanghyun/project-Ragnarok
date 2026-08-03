/**
 * Module 3 — Networks and congestion (10 steps).
 *
 * Modules 1 and 2 had one bus, so every generator competed with every other on
 * equal terms and there was one price. Module 3 splits that bus in two and joins
 * the halves with a line, and the moment the line fills the model stops being a
 * sort and starts being a network: two prices, congestion rent, and a generator
 * that is cheap but cannot reach the demand.
 *
 * The model, and every number the course asks a learner to reconcile, verified
 * against a real HiGHS solve before the prose was written:
 *
 *   bus_1  coal_1 50 @ 20, wind_1 60 @ 0      line_1, s_nom 60
 *   bus_2  gas_1 100 @ 50, oil_1 40 @ 120, load_1 40 / 80 / 170
 *
 *   h1  demand  40   wind 40, 14 curtailed   price   0 /   0    cost      0
 *   h2  demand  80   line FULL at 60         price  20 /  50    cost  1,720
 *   h3  demand 170   line 56, not binding    price 120 / 120    cost  7,680
 *                                            objective 9,400
 *
 * The closing move is the one that makes the module: uprate the line to 100 MW
 * and the answer collapses to 8,980 — module 2's objective, exactly. A line big
 * enough to never bind IS a single bus, so the 420 difference is precisely what
 * the constraint costs. A learner who sees that has understood what a network
 * adds better than any amount of prose about Kirchhoff could manage.
 */
import { TutorialStep } from '../types';

const SECTION = '3 · Networks and congestion';

export const MODULE_3_NETWORKS: TutorialStep[] = [
  {
    id: 'm3-why-geography',
    section: SECTION,
    title: 'Why geography changes the answer',
    tab: 'Build',
    where: 'Build → Buses step',
    startOptions: {
      prebuiltExampleId: 'training_m2',
      completeExampleId: 'training_m3',
      note:
        'Module 3 takes module 2\'s four-unit fleet — coal, gas, an oil peaker and wind on one bus — and '
        + 'splits it across two buses joined by a single line. Nothing is added except the second bus and '
        + 'the line; two generators and the load simply move.',
    },
    concept: [
      'Everything so far has assumed power can get from wherever it is made to wherever it is needed. '
      + 'One bus means one place, and a single place has no transport problem. Real systems are not like '
      + 'that: the cheap generation is usually a long way from the demand, and the wires in between have '
      + 'limits.',

      'Once there is more than one bus, "cheapest first" stops being enough. A generator can be the '
      + 'cheapest in the system and still not run, because the line to the demand is already full. '
      + 'Least cost now means cheapest-that-can-actually-get-there.',

      'And power does not choose its route. It is not a parcel with an address — it flows across every '
      + 'path in proportion to the physics, and a contract to sell from one place to another does not '
      + 'make the electrons obey it. That is why a network model has to solve the flows rather than just '
      + 'the quantities.',

      'The consequence to watch for: price stops being one number. Each bus gets its own, and when the '
      + 'wires between two buses are full those two numbers come apart. Everything in this module follows '
      + 'from that.',
    ],
    explain: [
      'The model you are starting from is module 2\'s: one bus, four generators, one load with a '
      + '40 / 80 / 170 MW profile, and wind with an availability profile. It answered 8,980, with prices '
      + 'of 0, 50 and 120.',

      'Over the next three steps you will add a second bus, move the demand and two generators onto it, '
      + 'and join the two with a line. No new generators and no new demand: the same fleet serving the '
      + 'same load, rearranged in space.',

      'That is deliberate. Because nothing about the fleet or the demand changes, any difference in the '
      + 'answer is caused by the network alone — which makes the cost of the network measurable rather '
      + 'than assumed.',

      'One thing to notice before you start: the Buses step shows a map, and the Carriers step did not. '
      + 'A bus is the only component with a position, and from here on that position matters.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="buses"]',
        buildStep: 'buses',
        title: 'The Buses step',
        tab: 'Build',
        note: 'One row today — bus_1, carrying the entire model. By the end of this module there will be '
          + 'two, and which components sit on which will decide the answer.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'buses',
        title: 'The map',
        tab: 'Build',
        note: 'Back for the first time since module 1, and now it earns its place. A bus is the one '
          + 'component with coordinates, and clicking the map drops one and fills its x and y for you.',
      },
      {
        selector: '.build-step-strip',
        title: 'The step you have never used',
        tab: 'Build',
        note: 'Lines has been sitting in the strip since module 1, blank, and that was correct — one bus '
          + 'has nowhere to send power to. It is the step this module is about.',
      },
    ],
    verify: [
      'The session holds the module-2 model: 1 bus, 4 generators, 1 load, 3 snapshots',
      'You can say why a cheap generator might not run in a networked model',
      'You can say why the Buses step shows a map and the Carriers step does not',
    ],
    pitfalls: [
      'Expecting a network to make the answer cheaper. It cannot: adding a constraint to a model never '
      + 'lowers the cost, it only ever raises it or leaves it alone. What the network adds is realism, '
      + 'and the cost of that realism is what this module measures.',
    ],
  },

  {
    id: 'm3-second-bus',
    section: SECTION,
    title: 'The second bus',
    tab: 'Build',
    where: 'Build → Buses step',
    concept: [
      'A bus is a place where power balances. Two buses means two separate balance constraints, each '
      + 'enforced in every snapshot, and each with its own shadow price — which is where the second '
      + 'price comes from.',

      'Coordinates are not decoration. Once a model has geography, x and y drive the map, and in a real '
      + 'study they drive line lengths, losses and the cost of building new circuits. Here they only '
      + 'have to be far enough apart to look like two places.',
    ],
    explain: [
      'Build → Buses, "+ Add bus", and fill the row. You can also click the map to drop the bus, which '
      + 'fills x and y for you — then type the name, voltage and carrier into the table as usual.',

      'Give it the same 380 kV and the same AC carrier as bus_1. Two buses at different voltages would '
      + 'need a transformer between them rather than a line, which is a complication this module does '
      + 'not need.',

      'Nothing else changes yet. Adding a bus with nothing attached to it is harmless — an isolated bus '
      + 'with no generator and no load balances trivially at zero — but validation will warn about it, '
      + 'and the warning is correct until the next step.',
    ],
    spotlights: [
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'buses',
        title: 'Add the bus',
        tab: 'Build',
        note: 'The same two-step pattern as every sheet: create the row, then fill its cells. The new row '
          + 'lands at the bottom of the table and is selected in the attribute form on the right.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'buses',
        title: 'Or click the map',
        tab: 'Build',
        note: 'Clicking an empty spot drops a bus there and fills x and y from where you clicked. It is '
          + 'the one place in Build where the map writes to the sheet rather than just displaying it.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'buses',
        title: 'Two rows now',
        tab: 'Build',
        note: 'bus_1 and bus_2, both 380 kV and both AC. Check the name is exactly bus_2 — the line and '
          + 'the components you move next all point at this text, and a typo detaches every one of them.',
      },
    ],
    entries: [
      {
        field: 'buses.name (new row)',
        label: 'bus name',
        value: 'bus_2',
        why: 'The text the line, the load and two generators will all point at. This one string is about '
          + 'to be referenced four times, which makes it the single most load-bearing cell in the module — '
          + 'a typo here detaches everything that names it.',
      },
      {
        field: 'buses.v_nom (new row)',
        label: 'nominal voltage',
        value: '380',
        unit: 'kV',
        why: 'The voltage level this node operates at. It must match bus_1 for a plain line to join them: '
          + 'two different voltages are a transformer, not a line. It does not affect this linear solve, '
          + 'but a blank raises a validation warning and power-flow calculations need it.',
      },
      {
        field: 'buses.carrier (new row)',
        label: 'carrier',
        value: 'AC',
        why: 'The kind of energy that balances here — electricity, the same as bus_1. Two buses with '
          + 'different carriers cannot be joined by a line at all; that needs a Link, which is module 5.',
      },
      {
        field: 'buses.x (new row)',
        label: 'longitude',
        value: '129.0',
        unit: 'degrees east',
        why: 'Where the bus sits on the map. Filled for you if you click the map instead of typing. It '
          + 'has no effect on this solve — the line\'s limit is what matters, not its length — but in a '
          + 'real study distance drives line cost and losses.',
      },
      {
        field: 'buses.y (new row)',
        label: 'latitude',
        value: '35.2',
        unit: 'degrees north',
        why: 'The other half of the position. Roughly 250 km from bus_1, which is a plausible distance '
          + 'for a transmission corridor between a generation region and a demand centre.',
      },
    ],
    verify: [
      'The `buses` sheet has 2 rows: bus_1 and bus_2',
      'Both read 380 in `v_nom` and AC in `carrier`',
      'Two markers appear on the map, some distance apart',
      'Validation warns that bus_2 has nothing attached — which is true, for one more step',
    ],
    pitfalls: [
      'Giving bus_2 a different `v_nom`. The model will still solve, but joining two voltages with a '
      + 'plain line is not what a real network does, and it will confuse the power-flow work later.',
      'Clicking the map repeatedly and creating three or four buses by accident. Check the row count is '
      + 'exactly 2 before moving on; extra isolated buses are harmless but they clutter every result.',
    ],
  },

  {
    id: 'm3-move-the-fleet',
    section: SECTION,
    title: 'Move the demand and half the fleet',
    tab: 'Build',
    where: 'Build → Generators, then Build → Loads',
    concept: [
      'This is the step that creates the problem worth solving. Put the cheap generation at one end and '
      + 'the demand at the other, and suddenly the cheap energy has to travel.',

      'The split is the classic one, and it is the shape of most real systems: coal and wind are where '
      + 'the coal and the wind are, which is rarely where the people are. Gas and oil peakers are built '
      + 'close to demand precisely because they are the units you need when the wires are full.',

      'Nothing is added and nothing is removed. Four generators before, four after. Only the `bus` cell '
      + 'changes on two of them, plus the load — three cells in total, and they change the answer more '
      + 'than anything you have typed so far.',
    ],
    explain: [
      'Build → Generators. Change `bus` from bus_1 to bus_2 on gas_1 and on oil_1. Leave coal_1 and '
      + 'wind_1 where they are.',

      'Then Build → Loads, and change load_1\'s `bus` to bus_2 as well. The demand now sits with the '
      + 'expensive plant, and the cheap plant is stranded at the other end until you build the line.',

      'Between this step and the next the model is briefly infeasible, and that is expected: bus_2 now '
      + 'has 170 MW of peak demand and only 140 MW of local generation, with no line to bring the rest. '
      + 'Do not run it yet — or do, and read the INFEASIBLE for what it is worth. A model that cannot '
      + 'serve its load tells you so, which is the most useful thing it can do.',

      'Watch the map as you go. Generators and loads have no coordinates of their own — they inherit '
      + 'their position from the bus they name — so moving one from bus_1 to bus_2 moves it on the map, '
      + 'without you touching an x or a y.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Two cells to change',
        tab: 'Build',
        note: 'gas_1 and oil_1 move to bus_2; coal_1 and wind_1 stay on bus_1. Only the `bus` column '
          + 'changes — capacities, costs and the wind profile are all untouched.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'generators',
        title: 'Watch them move',
        tab: 'Build',
        note: 'A generator has no coordinates of its own; it inherits the position of the bus it names. '
          + 'Change the `bus` cell and the unit jumps across the map, which is the quickest confirmation '
          + 'that the reference actually resolved.',
      },
      {
        selector: '[data-build-step="loads"]',
        buildStep: 'loads',
        title: 'And the demand',
        tab: 'Build',
        note: 'One cell: load_1\'s `bus` becomes bus_2. Its p_set profile of 40 / 80 / 170 is unchanged — '
          + 'the same demand, in a different place.',
      },
    ],
    entries: [
      {
        field: 'generators.bus (gas_1)',
        label: 'which bus it connects to',
        value: 'bus_2',
        why: 'Moves the 100 MW gas unit to the demand end. It is the workhorse of the system and it now '
          + 'sits behind no wires at all, which is why it can always serve bus_2 — and why bus_2\'s price '
          + 'is 50 whenever gas is the marginal unit there.',
      },
      {
        field: 'generators.bus (oil_1)',
        label: 'which bus it connects to',
        value: 'bus_2',
        why: 'Moves the 40 MW peaker to the demand end too. This is what peakers are for: local capacity '
          + 'for the hours when demand is high and the wires are already full. Left at bus_1 it would be '
          + 'useless — expensive AND stranded.',
      },
      {
        field: 'generators.bus (coal_1)',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'Unchanged — the cheap coal stays at the far end. It is the cheapest dispatchable unit in '
          + 'the model at 20 per MWh, and the whole tension of this module is that being cheapest no '
          + 'longer guarantees it runs.',
      },
      {
        field: 'generators.bus (wind_1)',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'Unchanged — the wind stays at the far end too, which is where wind usually is. Free energy '
          + 'stranded behind a constraint is the commonest reason real systems curtail renewables.',
      },
      {
        field: 'loads.bus (load_1)',
        label: 'which bus it draws from',
        value: 'bus_2',
        why: 'Moves all the demand to the second bus. Its 40 / 80 / 170 MW profile is unchanged, so the '
          + 'system serves exactly the same energy as module 2 — any difference in cost from here is the '
          + 'network, and nothing else.',
      },
    ],
    verify: [
      '`generators.bus` reads bus_2 for gas_1 and oil_1, and bus_1 for coal_1 and wind_1',
      '`loads.bus` reads bus_2',
      'The map shows two generators at each bus, with the load at bus_2',
      'You can say why the model is infeasible right now, and in which hour',
    ],
    pitfalls: [
      'Moving all four generators. Leave coal_1 and wind_1 at bus_1 — with nothing at the far end there '
      + 'is no reason for a line and no congestion to study.',
      'Typing bus2 or Bus_2. References are exact plain text; a mismatch detaches the component silently '
      + 'and the model reports INFEASIBLE without saying why.',
      'Running now and concluding something is broken. INFEASIBLE is the correct answer to a system with '
      + '170 MW of demand and 140 MW of reachable generation. The line fixes it.',
    ],
  },

  {
    id: 'm3-the-line',
    section: SECTION,
    title: 'The line that joins them',
    tab: 'Build',
    where: 'Build → Lines step',
    concept: [
      'A line carries power between two buses. The attribute that matters here is `s_nom` — its rating, '
      + 'in MW, the most it may carry in either direction. That single number is the constraint this '
      + 'whole module is about.',

      'The electrical attributes `r` and `x` — resistance and reactance — decide how power SPLITS between '
      + 'parallel paths. With one line between two buses there is nothing to split: everything that flows '
      + 'takes the only route there is. They still have to be filled in, because the solver builds a real '
      + 'network from them, but they cannot change this answer. In a meshed network they decide '
      + 'everything, which is why they exist.',

      '60 MW is deliberately too small. Peak demand is 170 MW and local generation at bus_2 is 140 MW, so '
      + 'the line must carry at least 30 MW in the peak hour for the model to be feasible at all — and at '
      + '60 MW it will fill up in the middle hour, which is the hour worth studying.',
    ],
    explain: [
      'Build → Lines, "+ Add line", and fill the row. `bus0` and `bus1` are the two ends; the order does '
      + 'not matter, but it does set the sign convention for the reported flow — positive means power '
      + 'flowing from bus0 to bus1.',

      'You can also draw the line on the map: the Lines step lets you pick two buses and creates the row '
      + 'with `bus0` and `bus1` filled. You still type the rating.',

      'Once the row is in, the Lines step should pick up a tick and validation should go quiet — bus_2 is '
      + 'no longer isolated, and the model is feasible again.',

      'Do not run it yet. The next step is the run, and it is worth predicting the answer before you see '
      + 'it — the arithmetic is in that step\'s concept block and it is the last module where doing it by '
      + 'hand is realistic.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="lines"]',
        buildStep: 'lines',
        title: 'The Lines step, at last',
        tab: 'Build',
        note: 'Blank since module 1, because one bus has nowhere to send power to. Note the map is here '
          + 'too — a line has geography, inherited from the two buses it joins.',
      },
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'lines',
        title: 'Add the line',
        tab: 'Build',
        note: 'Creates the row; you then fill the two ends and the rating. Drawing it on the map instead '
          + 'fills bus0 and bus1 for you, which is the safer route — no chance of a mistyped bus name.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'lines',
        title: 'The corridor appears',
        tab: 'Build',
        note: 'Once bus0 and bus1 resolve, the line draws between the two markers. If no line appears, one '
          + 'of the two names does not match a bus — which is the fastest check there is.',
      },
      {
        selector: '.build-step-strip',
        title: 'Feasible again',
        tab: 'Build',
        note: 'Lines should now carry a tick, and the error badge that appeared when you moved the load '
          + 'should be gone. Bus_2 is connected, so its demand can be served.',
      },
    ],
    entries: [
      {
        field: 'lines.name',
        label: 'line name',
        value: 'line_1',
        why: 'Identifies the corridor in results — its flow, its loading and its congestion all report '
          + 'under this name. With one line it hardly matters; in a national model the line names are how '
          + 'you find the constraint that is costing you money.',
      },
      {
        field: 'lines.bus0',
        label: 'one end',
        value: 'bus_1',
        why: 'The generation end. Must match `buses.name` exactly. Which end is bus0 does not change the '
          + 'physics, but it sets the sign of the reported flow: positive means power moving from bus0 to '
          + 'bus1, so a positive flow here means the cheap end is exporting.',
      },
      {
        field: 'lines.bus1',
        label: 'the other end',
        value: 'bus_2',
        why: 'The demand end. Together with bus0 this is the whole topology of the model — two nodes and '
          + 'the one path between them.',
      },
      {
        field: 'lines.s_nom',
        label: 'thermal rating',
        value: '60',
        unit: 'MW',
        why: 'The most this line may carry, in either direction, in any snapshot. THE number of this '
          + 'module. At 60 MW it is comfortably big enough in the quiet hour, exactly full in the middle '
          + 'hour, and not the binding limit in the peak hour — three different regimes from one rating, '
          + 'which is why 60 was chosen rather than a rounder number.',
      },
      {
        field: 'lines.x',
        label: 'series reactance',
        value: '0.1',
        unit: 'ohms',
        why: 'How strongly the line opposes alternating current, and in a meshed network the thing that '
          + 'decides how power divides between parallel routes. With a single path there is nothing to '
          + 'divide, so it cannot change this answer — but the solver needs it to build the network, and a '
          + 'zero or blank reactance makes the power-flow equations singular.',
      },
      {
        field: 'lines.r',
        label: 'series resistance',
        value: '0.01',
        unit: 'ohms',
        why: 'What the line dissipates as heat — the source of transmission losses. A linear dispatch '
          + 'solve like this one ignores losses, so it changes nothing here; it matters the moment you run '
          + 'an AC power flow, and the ratio of r to x is what tells you how lossy a corridor is.',
      },
      {
        field: 'lines.length',
        label: 'circuit length',
        value: '200',
        unit: 'km',
        why: 'How long the corridor is. Purely descriptive in this solve, but it is what per-km capital '
          + 'costs multiply in module 7, and it is a useful sanity check: a 200 km line between two points '
          + '250 km apart on the map would be suspicious.',
      },
    ],
    verify: [
      'The `lines` sheet has exactly 1 row',
      '`bus0` and `bus1` read bus_1 and bus_2, and a line is drawn between the two map markers',
      '`s_nom` reads 60',
      'The Lines step shows a tick and Analytics → Validation reports no errors',
    ],
    pitfalls: [
      'Leaving `x` blank or zero. The model may refuse to build, or build a network whose power flow is '
      + 'undefined. Any small positive number works for a single-line model.',
      'Setting `s_nom` below 30. Peak demand is 170 MW against 140 MW of local plant, so anything under '
      + '30 MW leaves the peak hour infeasible no matter what else is right.',
      'Confusing `s_nom` with `length`. The rating is the limit that binds; the length is decoration '
      + 'until module 7 puts a cost on it.',
    ],
  },

  {
    id: 'm3-run-two-prices',
    section: SECTION,
    title: 'Run: one price becomes two',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Work the three hours out before you run them. The fleet and the demand are module 2\'s; only the '
      + 'geography is new.',

      'Hour 1, demand 40 at bus_2. Wind at bus_1 can make 54 (0.9 × 60) and it is free, so it serves all '
      + '40 and 14 MWh is curtailed. The line carries 40, well under its 60. Cost 0, and because the '
      + 'marginal unit is free wind reachable from both ends, the price is 0 at BOTH buses.',

      'Hour 2, demand 80. Bus_1 can offer wind 24 plus coal 50 — 74 MW of cheap energy — but the line '
      + 'only carries 60. So 60 arrives (wind 24 free, coal 36 at 20) and gas at bus_2 makes up the last '
      + '20 at 50. Cost 720 + 1,000 = 1,720. And now the prices split: one more MWh at bus_1 would come '
      + 'from coal at 20, but one more MWh at bus_2 must come from gas at 50, because the line is full '
      + 'and nothing more can cross. Bus_1 is 20, bus_2 is 50.',

      'Hour 3, demand 170. Wind is down to 6 (0.1 × 60), so bus_1 can only offer 56 in total — less than '
      + 'the line\'s 60. The line is NOT the constraint here; bus_1 simply has nothing more to send. All '
      + '56 crosses, and bus_2 covers the remaining 114 with gas 100 and oil 14. Cost 1,000 + 5,000 + '
      + '1,680 = 7,680. With the line not binding, the two buses are effectively one and both prices are '
      + '120.',

      'Total 9,400. Module 2 answered 8,980 for the identical fleet and the identical demand. The whole '
      + '420 difference is the network.',
    ],
    explain: [
      'Validate first — moving components between buses is exactly the kind of edit that leaves a '
      + 'dangling reference. Then run for real and read the objective in Analytics → Result.',

      'Reconcile against 9,400 before anything else. If you get 8,980 the line is not binding, so check '
      + '`s_nom` really reads 60. If it is INFEASIBLE, the load or a generator is pointing at a bus name '
      + 'that does not exist.',

      'Then look at the headline price on the Result dashboard — and be careful with it. It reports ONE '
      + 'price per snapshot, and on a network that number is an average across the buses. In hour 2 it '
      + 'shows 35, which is the mean of 20 and 50 and is the price at neither bus. The average price in '
      + 'the KPI strip is 51.7 for the same reason.',

      'That is not a bug, it is a summary doing what summaries do, and it is worth meeting deliberately: '
      + 'the moment a model has more than one bus, any single system price is a weighted average hiding a '
      + 'distribution. The next step opens the view that shows the real ones.',
    ],
    spotlights: [
      {
        selector: '.run-button',
        title: 'Validate, then run',
        runDialog: 'closed',
        note: 'Same two passes as always: Dry run on to validate the new references, then off to solve. '
          + 'Both presses are yours.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'Same window as module 2',
        runDialog: 'open',
        note: 'Still 3 snapshots at 1h. It matters here more than usual: the whole point is comparing '
          + 'against module 2\'s 8,980, and two runs over different windows are not comparable at all.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile 9,400',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Three hours worked out by hand: 0 + 1,720 + 7,680. If it reads 8,980 the line is not '
          + 'binding — check s_nom is 60 and not 600.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The average that hides the answer',
        tab: 'Analytics',
        note: 'Total cost 9,400 against module 2\'s 8,980, and the same 290 MWh served. But read AVG PRICE '
          + 'carefully: 51.7 is an average over buses as well as hours, and no participant in this market '
          + 'ever faced it.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'A price that belongs to nobody',
        tab: 'Analytics',
        note: 'It reports gas setting the price at an average of 35 — the mean of bus_1\'s 20 and bus_2\'s '
          + '50. On a single-bus model this card was exact; on a network it is averaging two different '
          + 'answers, and the next step is where you see them separately.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the new bus, the moved references and the line — a second or two.',
        'The solve optimises 4 generators and 1 line over 3 snapshots. Instant.',
      ],
      expect: 'An objective of 9,400 — 420 more than module 2 answered for the same fleet and the same demand.',
    },
    verify: [
      'Analytics → Result shows an objective of 9,400',
      'You can say where the 420 difference from module 2 comes from',
      'You have noticed the headline price reads 35 in hour 2, and can say why that is nobody\'s price',
      'Total energy served is still 290 MWh — the network changed the cost, not the demand',
    ],
    pitfalls: [
      'An objective of 8,980 means the line never binds. Either `s_nom` is too large, or the generators '
      + 'did not actually move — check `generators.bus` reads bus_2 for gas_1 and oil_1.',
      'INFEASIBLE means something cannot reach the load. Check every `bus` cell against `buses.name`, and '
      + 'check the line names both buses.',
      'Taking the single system price seriously on a networked model. From here on it is an average, and '
      + 'the more congested the system the less it means.',
    ],
  },

  {
    id: 'm3-nodal-prices',
    section: SECTION,
    title: 'Two prices, seen properly',
    tab: 'Analytics',
    where: 'Analytics → Analytics → Presets → Nodal view',
    concept: [
      'Each bus has its own balance constraint, so each has its own shadow price — a locational marginal '
      + 'price, or LMP. It is the cost of serving one more MWh AT THAT BUS, and when the wires between '
      + 'two buses are full those two costs have no reason to agree.',

      'In hour 2 they do not: 20 at bus_1, 50 at bus_2. Both are correct answers to different questions. '
      + 'One more MWh of demand at bus_1 is served by coal, which has spare capacity right there. One more '
      + 'MWh at bus_2 cannot be served by that coal at any price, because the line is full — so it costs '
      + 'whatever the cheapest local option costs, which is gas at 50.',

      'The difference between them, 30 per MWh, is the price of the constraint itself. It is not a '
      + 'market failure and it is not somebody overcharging: it is what it costs the system that the wire '
      + 'is too small. Widen the wire and the difference goes away.',

      'This is the mechanism behind every nodal market in the world, and behind the endless argument '
      + 'about zonal ones. A zonal market averages prices across a region and hides exactly this signal — '
      + 'which is convenient for traders and terrible for anyone deciding where to build.',
    ],
    explain: [
      'The Result dashboard is built for you from what the run produced, and it reports one system price. '
      + 'The per-bus prices live on the Analytics subtab next to it, which is the CONFIGURABLE dashboard: '
      + 'same run, layouts you choose.',

      'Go to Analytics → Analytics, open the Presets menu in the toolbar, and load "Nodal view". It '
      + 'rebuilds the page as a network map coloured by average price, a Nodal SMP chart with one line per '
      + 'bus, and load by bus.',

      'Read the Nodal SMP chart. Two series, bus_1 and bus_2. They sit on top of each other in hours 1 '
      + 'and 3 — 0 and 120, the same at both ends — and separate in hour 2 to 20 and 50. That separation '
      + 'is congestion, drawn.',

      'Then look at the map. Its legend runs from about 47 to 57: those are the average prices at the two '
      + 'buses over the three hours — (0 + 20 + 120) / 3 = 46.7 at bus_1, and (0 + 50 + 120) / 3 = 56.7 at '
      + 'bus_2. On a real network this colouring is how you find the constrained corner of a system at a '
      + 'glance.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Analytics"]',
        title: 'The other dashboard',
        tab: 'Analytics',
        note: 'Result is built for you from the run; Analytics is the one you configure, and it is the only '
          + 'one with a Presets menu. Same run, same numbers — a different set of questions asked of them.',
      },
      {
        selector: '[data-tour="dashboard-presets"]',
        title: 'Presets',
        tab: 'Analytics',
        note: 'Fifteen ready-made layouts. Two of them exist for exactly this module: "Nodal view" for '
          + 'per-bus prices, and "Branch loading" for what the lines are doing. Open it and pick Nodal view.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="smp"]',
        title: 'Nodal SMP',
        tab: 'Analytics',
        note: 'One series per bus. Together in hours 1 and 3, apart in hour 2 — 20 at bus_1 and 50 at '
          + 'bus_2. The gap between the two lines IS the congestion, and its height is what the constraint '
          + 'costs per MWh.',
      },
      {
        selector: '[data-card="map"]',
        title: 'The map, priced',
        tab: 'Analytics',
        note: 'Buses coloured by average price, legend running 47 to 57. Those are the two averages over '
          + 'the three hours. On a system with hundreds of buses this is how you find the expensive corner '
          + 'without reading a single number.',
      },
    ],
    verify: [
      'The Nodal SMP chart shows two series that coincide in hours 1 and 3 and separate in hour 2',
      'You can read 20 and 50 off it for hour 2',
      'The map legend spans roughly 47 to 57, and you can say where those two numbers come from',
      'You can explain the 30 per MWh gap without using the word "congestion"',
    ],
    pitfalls: [
      'Looking for the Presets menu on the Result subtab. It is not there — Result is the automatic '
      + 'dashboard, Analytics is the configurable one.',
      'Reading the map legend as an hourly price. It is the average across the run, which is why it says '
      + '47 and 57 rather than any of 0, 20, 50 or 120.',
    ],
  },

  {
    id: 'm3-congestion',
    section: SECTION,
    title: 'Reading the congestion',
    tab: 'Analytics',
    where: 'Analytics → Analytics → Presets → Branch loading',
    concept: [
      'A line is congested in a snapshot when it is carrying its rating and the model would send more if '
      + 'it could. That is a binary state, and it is what makes prices diverge — a line at 99% is not '
      + 'congested at all, and prices either side of it are equal.',

      'Loading is the flow as a percentage of the rating. Reading it hour by hour tells you which hours '
      + 'the constraint actually bit, which on a real system is a far shorter list than people expect: '
      + 'most corridors are congested for a small fraction of the year and cost a great deal in exactly '
      + 'those hours.',

      'Hour 3 is the instructive one. The line carries 56 of its 60 MW — 93%, nearly full, and not '
      + 'congested at all. Bus_1 simply had nothing more to send: wind was down to 6 MW and coal was flat '
      + 'out at 50. The prices are equal at 120 because the line was not the thing standing in the way.',

      'That distinction — full because the wire is small, versus full because there is nothing more to '
      + 'send — is the one people get wrong most often when they look at flow data without prices.',
    ],
    explain: [
      'Open the Presets menu again and load "Branch loading". You get the map, a Branch loading chart as '
      + 'a percentage, and daily losses.',

      'Read the loading chart across the three hours: about 67% in hour 1 (40 of 60), 100% in hour 2, and '
      + '93% in hour 3 (56 of 60). Only the middle hour is a flat 100%.',

      'Now put it beside what you saw in the Nodal view. Hour 2 is the only hour at 100%, and it is the '
      + 'only hour where the two prices differ. That correspondence is exact and it is the whole '
      + 'diagnostic: congestion is where loading pins at 100 AND prices split.',

      'Hour 3 is the trap. 93% looks nearly congested, and it is not — the prices are identical. If you '
      + 'were sizing a transmission upgrade from flow data alone you would build the wrong thing.',
    ],
    spotlights: [
      {
        selector: '[data-tour="dashboard-presets"]',
        title: 'Branch loading',
        tab: 'Analytics',
        note: 'The second of the two presets this module needs. Same run again — you are still reading '
          + 'the answer you already have, from another angle.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="loading"]',
        title: 'Loading, hour by hour',
        tab: 'Analytics',
        note: 'Flow as a percentage of s_nom: about 67, then 100, then 93. Only the flat 100 is '
          + 'congestion. Compare it against the Nodal SMP chart and the hours line up exactly.',
      },
      {
        selector: '[data-card="map"]',
        title: 'Where it is happening',
        tab: 'Analytics',
        note: 'One corridor here, so the map has little to add. On a national model this is the view that '
          + 'turns "the system is expensive" into "this corridor is the reason", which is the question '
          + 'planners are actually asked.',
      },
    ],
    verify: [
      'Branch loading reads about 67%, 100% and 93% across the three hours',
      'You can name the only congested hour and say how you know',
      'You can say why hour 3 at 93% is not congested even though it is nearly full',
      'You can state the test for congestion in one sentence, using both loading and price',
    ],
    pitfalls: [
      'Calling a nearly-full line congested. Congestion is about whether the limit is BINDING — whether '
      + 'the model wanted to send more and could not. Loading alone cannot tell you; you need the prices.',
      'Assuming the most-loaded corridor is the most valuable to upgrade. The valuable one is the one '
      + 'with the largest price difference across it, for the most hours — which is often not the one '
      + 'with the highest peak loading.',
    ],
  },

  {
    id: 'm3-congestion-rent',
    section: SECTION,
    title: 'Congestion rent — who collects the difference',
    tab: 'Analytics',
    where: 'Analytics → Result → asset economics',
    concept: [
      'Follow the money in hour 2. Demand at bus_2 pays the bus_2 price on every MWh it takes: 80 MWh at '
      + '50 is 4,000. Generators are paid the price at their OWN bus — coal earns 36 × 20 = 720, wind '
      + 'earns 24 × 0 = 0, gas earns 20 × 50 = 1,000. That is 1,720 paid out against 4,000 collected.',

      'The gap is 2,280, and part of it is familiar: coal running at a cost of 20 and being paid 20 earns '
      + 'nothing extra, but demand paid 50 for energy that cost 20 to make. The specifically NETWORK part '
      + 'is the 60 MWh that crossed the line, bought at 20 on one side and sold at 50 on the other — '
      + '60 × 30 = 1,800.',

      'That 1,800 is congestion rent. Nobody sets it and no generator earns it: it falls out of the same '
      + 'MWh having two different prices in two places, and in a real market it accrues to whoever owns '
      + 'the transmission rights — the system operator, or the holders of financial transmission rights, '
      + 'depending on the market.',

      'It is also the honest measure of how badly you need a bigger wire. A corridor collecting large '
      + 'congestion rent year after year is a corridor whose upgrade would pay for itself, and that '
      + 'comparison — rent against capital cost — is the actual basis on which transmission gets built.',
    ],
    explain: [
      'There is no congestion-rent card, so work it out: it is the flow across the line multiplied by the '
      + 'price difference across it, summed over the hours. Hours 1 and 3 have no price difference, so '
      + 'they contribute nothing. Hour 2 gives 60 × (50 − 20) = 1,800.',

      'Then open Analytics → Result and find the asset economics card. It reports revenue and cost per '
      + 'generator, and every unit is paid the price at its own bus — so coal at bus_1 is paid bus_1 '
      + 'prices and gas at bus_2 is paid bus_2 prices.',

      'Compare coal against module 2. It produced the same kind of energy, but its revenue is now set by '
      + 'a price it is stuck behind. Being cheap and stranded is worth less than being cheap and '
      + 'connected, and that is a real result about where to build a power station — not an artefact.',

      'The mirror of that: gas and oil at bus_2 are worth MORE than their marginal costs suggest, because '
      + 'they sit where the constraint puts a premium on local supply. This is precisely why "locational" '
      + 'in locational marginal pricing is not a technicality.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: 'Back to the built dashboard',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Asset economics is on Result, not on the configurable Analytics page. Still the same run — '
          + 'you have not re-solved anything since the objective was 9,400.',
      },
      {
        selector: '[data-card="generator-economics"]',
        title: 'Revenue at each unit\'s own bus',
        tab: 'Analytics',
        note: 'Every generator is paid the price where it sits. Coal at bus_1 is behind the constraint and '
          + 'earns bus_1 prices; gas at bus_2 earns bus_2 prices. Compare coal here against what it earned '
          + 'in module 2 on a single bus.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'What demand actually paid',
        tab: 'Analytics',
        note: 'Total cost is 9,400 — what it cost to RUN the system. What demand PAYS is a different '
          + 'number again, because it pays the price rather than the cost, and the difference includes the '
          + '1,800 of congestion rent.',
      },
    ],
    verify: [
      'You can compute the congestion rent from the flow and the two prices, and get 1,800',
      'You can say which hours contribute to it and why the other two do not',
      'You can say who collects it, and why it is not a generator\'s revenue',
      'You can say why a stranded cheap generator is worth less than a connected one',
    ],
    pitfalls: [
      'Treating congestion rent as profit for someone. It is the arithmetic consequence of two prices, '
      + 'and in most markets it is used to fund transmission or refunded to consumers.',
      'Confusing system cost with what consumers pay. 9,400 is the cost of running the fleet; payments at '
      + 'locational prices are larger, and the gap is rent — inframarginal to generators, congestion rent '
      + 'to the network.',
    ],
  },

  {
    id: 'm3-uprate',
    section: SECTION,
    title: 'Uprate the line — and get module 2 back',
    tab: 'Analytics',
    where: 'Build → Lines, then run again',
    concept: [
      'The cleanest way to measure what a constraint costs is to remove it and re-run. Everything else is '
      + 'held fixed, so the difference is attributable to the one thing you changed.',

      'Raise `s_nom` from 60 to 100 and the middle hour stops binding: bus_1 can offer 74 MW of cheap '
      + 'energy and all of it now fits. Coal runs flat out at 50 instead of being held to 36, gas at '
      + 'bus_2 drops from 20 MW to 6, and that hour costs 1,300 instead of 1,720.',

      'Hours 1 and 3 do not change at all — the line was never the binding constraint in either. So the '
      + 'new total is 8,980, and that number should be familiar: it is exactly module 2\'s answer.',

      'That is the whole lesson of the module in one number. A line big enough never to bind IS a single '
      + 'bus — modellers call it a copper plate — and modules 1 and 2 were quietly assuming one all along. '
      + 'The 420 difference is precisely what the 60 MW constraint costs the system over these three '
      + 'hours, and it is the honest upper bound on what you should pay to relieve it.',
    ],
    explain: [
      'Build → Lines, change `s_nom` from 60 to 100, and run again. One cell, one run.',

      'Read the objective: 8,980. Then go back to the Nodal view preset and look at the Nodal SMP chart — '
      + 'the two series now sit on top of each other in every hour. No congestion anywhere, one price '
      + 'system-wide, congestion rent zero.',

      'Compare the two runs properly rather than from memory. Analytics → Comparison holds runs side by '
      + 'side, and History keeps both — this is the first point in the course where comparing two runs is '
      + 'the actual analysis rather than a convenience.',

      'Then decide what you have learnt. 420 over three hours is the value of the upgrade in this tiny '
      + 'model. Scale that to a year and compare it against what the line costs to build, and you have '
      + 'the beginnings of a transmission business case — which is module 7\'s machinery, applied to wires '
      + 'instead of generators.',

      'Set `s_nom` back to 60 before you finish, so the model you carry into module 4 is the congested '
      + 'one. The checkpoint this module ships is the 60 MW version.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="lines"]',
        buildStep: 'lines',
        title: 'One cell',
        tab: 'Build',
        note: 'Change s_nom from 60 to 100. Nothing else — not the fleet, not the demand, not the window. '
          + 'A controlled experiment is only controlled if you change exactly one thing.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '8,980 again',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Module 2\'s objective, to the currency unit, from a two-bus model. A line that never binds '
          + 'is a single bus — which is what modules 1 and 2 were assuming without saying so.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Compare the two runs',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both runs are in History, so put them side by side rather than trusting your memory of the '
          + 'first. From here on, most real analysis is a comparison rather than a single answer.',
      },
    ],
    entries: [
      {
        field: 'lines.s_nom (the uprate)',
        label: 'thermal rating, widened',
        value: '100',
        unit: 'MW',
        why: 'Large enough that the line never binds: bus_1 can offer at most 74 MW of cheap energy in any '
          + 'hour, so 100 MW of capacity is never the thing standing in the way. Anything above 74 gives '
          + 'the same answer, which is itself worth noticing — past the point where a constraint stops '
          + 'binding, more of it is worth nothing at all.',
      },
      {
        field: 'lines.s_nom (restore before module 4)',
        label: 'thermal rating, back to congested',
        value: '60',
        unit: 'MW',
        why: 'Put it back so the model you carry forward is the interesting one. Module 4 adds storage, '
          + 'and storage behind a constraint behaves quite differently from storage on a copper plate — '
          + 'the congestion is what makes that module worth doing.',
      },
    ],
    run: {
      label: 'Run dialog → Run model, twice',
      detail: [
        'Once with s_nom at 100 to measure the uprate, then once more at 60 to restore the model.',
        'Both solve instantly; both land in History so you can compare them.',
      ],
      expect: 'An objective of 8,980 at 100 MW — module 2\'s answer exactly — and 9,400 again at 60 MW.',
    },
    verify: [
      'At s_nom 100 the objective is 8,980, matching module 2 exactly',
      'The Nodal SMP series coincide in every hour, with no gap anywhere',
      'You can say why hours 1 and 3 did not change',
      'You can state what the 60 MW constraint costs over these three hours, and what that number is an upper bound on',
      '`s_nom` is back to 60 before you move on',
    ],
    pitfalls: [
      'Changing more than one thing between the two runs. The comparison is only meaningful if the fleet, '
      + 'the demand and the snapshot window are identical.',
      'Concluding the upgrade is worth 420. It is worth 420 over THESE three hours, in this model, with '
      + 'no capital cost counted. Annualising a three-hour result is the commonest way model outputs get '
      + 'misused.',
      'Forgetting to set s_nom back. Module 4 assumes the congested model, and starting it from a copper '
      + 'plate quietly removes the reason storage is interesting there.',
    ],
  },

  {
    id: 'm3-what-changed',
    section: SECTION,
    title: 'What module 3 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours, and they are what separates a network model from a spreadsheet of '
      + 'generators.',

      'Cheapest no longer means dispatched. A generator has to be able to reach the demand, and coal sat '
      + 'idle at 20 per MWh in hour 2 while gas ran at 50, because the wire between them was full.',

      'Price is locational. Each bus has its own balance constraint and therefore its own shadow price, '
      + 'and a binding line between them lets those prices come apart. Any single system price on a '
      + 'networked model is an average that belongs to nobody.',

      'Congestion has a value. The price difference across a binding corridor, times the flow, is '
      + 'congestion rent — and it is the number a transmission business case is built on.',

      'And a constraint costs what removing it saves. Uprating the line gave back exactly module 2\'s '
      + '8,980, so the 60 MW limit cost 420. That subtraction — run it, relax it, re-run, difference — is '
      + 'the single most useful technique in this course, and it works on any constraint, not just wires.',
    ],
    explain: [
      'Three limits to name, each of which is a later module.',

      'Two buses and one line is not a network, it is a corridor. With no loops there is nothing for `r` '
      + 'and `x` to do — power has one route and takes it. Add a third bus and a second path and the flows '
      + 'divide by physics rather than by choice, loop flow appears, and a line can be congested by power '
      + 'that nobody wanted to send down it. That is where reactance starts to matter.',

      'The hours are still independent. Hour 2 was congested and hour 1 threw away 14 MWh of free wind, '
      + 'and there is nothing in this model that can carry that energy from the hour it was wasted to the '
      + 'hour it was needed. Storage is what couples hours, and it is module 4 — and now that there is a '
      + 'constraint in the model, WHERE you put the storage matters as much as how big it is.',

      'And capacity is still fixed. You measured what the line constraint costs, but you cannot ask the '
      + 'model whether to build a bigger one, because there is no capital cost anywhere in it. Module 6 '
      + 'adds that, and the transmission business case sketched two steps ago is where it gets used.',

      'Export the project before you go — Model → Export project. Module 4 ships this model as a '
      + 'checkpoint, but a file you saved yourself is the one you will trust when the two disagree.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: '9,400 to serve the same 290 MWh that module 2 served for 8,980, with the same four '
          + 'generators. Nothing about the fleet changed — only where it sits, and what joins it up.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project writes the whole workbook to a file. Worth doing at the end of every '
          + 'module: it takes a second, and it is the only copy that is unambiguously yours.',
      },
      {
        selector: '.activity-bar',
        title: 'Still untouched',
        note: 'Forge, Market & Policy and Post-analysis have gone unused for three modules. They act on '
          + 'the model you have built rather than adding sheets to it, and the later modules are largely '
          + 'about those views.',
      },
    ],
    verify: [
      'You can explain locational marginal pricing to someone who has not done this course',
      'You can say why a cheap generator might earn less than an expensive one',
      'You can describe the run-relax-rerun technique and name one other constraint you could apply it to',
      'You can say what a second path between the buses would add, and why one line does not need reactance',
      'You have exported the project and know where the file is',
    ],
    pitfalls: [
      'Generalising from a two-bus model. Real networks are meshed, and almost everything counter-'
      + 'intuitive about them — loop flow, a line congested by power nobody scheduled across it — needs at '
      + 'least three buses and two paths to appear at all.',
      'Taking the 420 as "the value of transmission". It is the value of this uprate, on this fleet, over '
      + 'three hours, with no capital cost. Every one of those qualifiers matters.',
    ],
  },
];
