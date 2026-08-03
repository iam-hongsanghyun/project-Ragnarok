/**
 * Module 2 — Economic dispatch (steps 7–16).
 *
 * Module 1 built a model with exactly one feasible answer. Module 2 gives the
 * optimiser something to choose between, and the whole of power-market
 * economics falls out of that one change: a merit order, a marginal unit, an
 * hourly price that is nothing like average cost, and — once wind is added —
 * curtailment and a zero price.
 *
 * The model stays small enough to check by hand at every stage. Three
 * checkpoints, each verified against a real HiGHS solve before the prose was
 * written:
 *
 *   after step 8  — coal + gas, flat 80 MW        → 7,500,  price 50 / 50 / 50
 *   after step 12 — peaker + load 40 / 80 / 170   → 11,700, price 20 / 50 / 120
 *   after step 15 — wind at p_max_pu .9 / .4 / .1 → 8,980,  price  0 / 50 / 120
 *
 * Capacity is fixed throughout: the model chooses how hard to run what exists,
 * never what to build. That is module 6, and step 16 says so explicitly rather
 * than letting a learner conclude that a dispatch model has an opinion about
 * investment.
 */
import { TutorialStep } from '../types';

const SECTION = '2 · Economic dispatch';

export const MODULE_2_DISPATCH: TutorialStep[] = [
  {
    id: 'm2-merit-order',
    section: SECTION,
    title: 'Cheapest first — the merit order',
    tab: 'Build',
    where: 'Build → Carriers, then Build → Generators',
    startOptions: {
      prebuiltExampleId: 'training_m1',
      completeExampleId: 'training_m2',
      note:
        'Module 2 grows the module-1 model — one bus, one 100 MW gas unit at 50 per MWh, one 80 MW load, '
        + 'three hourly snapshots — into a four-unit fleet with a demand profile and a wind availability '
        + 'profile. If you finished module 1 yourself, leave this on Empty and carry on with your own model.',
    },
    concept: [
      'With one generator there was no decision to make. Add a second and the model has to choose, and '
      + 'the rule it follows is the whole of short-run power economics: serve demand from the cheapest '
      + 'available source first, then the next cheapest, until demand is met. Sort the fleet by marginal '
      + 'cost and you have the merit order — the supply curve of the system.',

      'Nobody writes that rule into the model. It is what minimising total cost MEANS when the only '
      + 'decision is how hard to run each unit: any answer that runs an expensive unit while a cheaper '
      + 'one sits idle can be improved by swapping a MWh between them, so the optimiser never returns it.',

      'The unit that happens to be last in the money — the most expensive one running in a given hour — '
      + 'is the marginal unit. Remember it. Everything about price in the next three steps is about that '
      + 'one unit, and which unit it is changes hour by hour.',

      'Marginal cost is what it costs to produce one MORE MWh: fuel, plus variable operations and '
      + 'maintenance. It deliberately excludes what it cost to BUILD the plant, because that money is '
      + 'already spent and cannot be changed by a dispatch decision. Sunk cost does not belong in a '
      + 'sorting rule about the next MWh.',
    ],
    explain: [
      'You are adding one carrier and one generator to the model you already have. Nothing else changes '
      + 'yet — same bus, same load, same three snapshots.',

      'Go to Build → Carriers first, and add a row for `coal`. Carriers before generators, for the same '
      + 'reason as module 1: the generator points at the carrier by name, and a name that does not exist '
      + 'yet is a dangling reference.',

      'Then Build → Generators, "+ Add Generator", and fill the row below. Coal at 20 per MWh against '
      + 'gas at 50 sits BELOW gas in the merit order, so it should displace gas the moment you re-run.',

      'Do not delete gas_1. The point of this module is a fleet with a choice in it — one unit that is '
      + 'cheap but too small to cover demand alone, and one that is expensive but big enough to make up '
      + 'the difference.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'Carriers first',
        tab: 'Build',
        note: 'Two rows here already — AC and gas from module 1. Add a third for coal. The generator you '
          + 'add next points at this name as plain text, so a carrier that does not exist yet is a broken '
          + 'reference waiting to happen.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Then the second generator',
        tab: 'Build',
        note: 'One row here already — gas_1. You are adding a second unit that undercuts it, which is what '
          + 'turns a model with one feasible answer into a model that has to choose. Watch the row count go '
          + 'from 1 to 2.',
      },
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'generators',
        title: 'Add the row',
        tab: 'Build',
        note: 'Same two-step pattern as every sheet in module 1: create the row first, then fill its cells. '
          + 'The new row lands at the bottom of the table and is selected in the attribute form on the right.',
      },
      {
        selector: '.build-step-strip',
        title: 'Nothing else needs to change',
        tab: 'Build',
        note: 'The ticks stay exactly as they were — Network, Snapshots, Carriers, Buses, Generators, Loads. '
          + 'A second generator does not need a second bus, a second load, or a line. It attaches to the bus '
          + 'that is already there.',
      },
    ],
    entries: [
      {
        field: 'carriers.name (new row)',
        label: 'carrier name',
        value: 'coal',
        why: 'The fuel the new unit burns. The generator row points at this exact text, so a mismatch here '
          + 'is the same silent-detachment failure module 1 warned about — only now it detaches the CHEAP '
          + 'unit, and the model quietly returns module 1\'s answer instead of erroring.',
      },
      {
        field: 'carriers.co2_emissions (new row)',
        label: 'emission factor',
        value: '0.34',
        unit: 'tCO2 per MWh of fuel burnt',
        why: 'Coal is roughly 1.7 times as carbon-intensive as gas per MWh of fuel, and worse still per MWh '
          + 'of electricity because it converts less efficiently. It changes nothing in this module — no '
          + 'carbon price and no emissions cap yet — but module 8 turns exactly this number into a reason '
          + 'the merit order flips.',
      },
      {
        field: 'generators.name',
        label: 'generator name',
        value: 'coal_1',
        why: 'Identifies the unit in every result: its hourly dispatch, its revenue, its emissions. Once '
          + 'there is more than one generator, these names are how you read the answer at all.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'The same single bus. Both generators inject at the same place, which is what makes this a '
          + 'pure merit-order problem with no geography in it — module 3 adds a second bus and a line, and '
          + 'the answer stops being a simple sort.',
      },
      {
        field: 'generators.carrier',
        label: 'fuel / technology',
        value: 'coal',
        why: 'Links the unit to the emission factor you just typed and groups it in per-carrier results. '
          + 'Must match `carriers.name` exactly.',
      },
      {
        field: 'generators.p_nom',
        label: 'installed capacity',
        value: '50',
        unit: 'MW',
        why: 'Deliberately smaller than the 80 MW load. If coal could cover demand on its own, gas would '
          + 'never run and there would be no marginal unit to talk about. At 50 MW it takes the bottom of '
          + 'the stack and leaves gas to fill the last 30 MW — which is exactly the situation that sets a price.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'cost per extra MWh',
        value: '20',
        unit: 'currency per MWh',
        why: 'Below gas at 50, so coal sits first in the merit order and runs flat out whenever it can. '
          + 'This one number is the entire reason the answer changes: it is what the optimiser sorts on.',
      },
      {
        field: 'generators.efficiency',
        label: 'fuel-to-electricity conversion',
        value: '0.4',
        why: 'MWh of electricity out per MWh of fuel in. Lower than the gas unit\'s 0.5, which is typical — '
          + 'coal plants convert less of their fuel. Combined with the 0.34 carrier factor it means 0.85 '
          + 'tCO2 per MWh generated, against gas\'s 0.4.',
      },
    ],
    verify: [
      'The `carriers` sheet has 3 rows: AC, gas, coal',
      'The `generators` sheet has 2 rows: gas_1 and coal_1, both with `bus` reading exactly bus_1',
      'You can say, without running anything, which of the two will produce more in the answer — and why',
    ],
    pitfalls: [
      'Editing gas_1 instead of adding a row. You want two generators, not one renamed one — check the '
      + 'row count reads 2 before moving on.',
      'A `carrier` of "Coal" instead of "coal". References are case-sensitive plain text, and the '
      + 'mismatch detaches the unit silently rather than erroring.',
    ],
  },

  {
    id: 'm2-run-the-stack',
    section: SECTION,
    title: 'Run it: the stack forms',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Do the arithmetic before you look at the answer. It is the last module where you can, and getting '
      + 'into the habit now is the point.',

      'Demand is 80 MW in each of 3 hours — 240 MWh, unchanged from module 1. Coal is cheapest, so it '
      + 'runs flat out: 50 MW every hour. Gas covers the remaining 30 MW. Per hour that is 50 × 20 plus '
      + '30 × 50 = 1,000 + 1,500 = 2,500. Over three hours, 7,500.',

      'Module 1 answered 12,000 for the same demand. The 4,500 difference is what a merit order is worth: '
      + 'no new capacity, no change in what is consumed, only a cheaper way to serve it. This is the '
      + 'single clearest illustration of what "least cost" buys you.',

      'Note what did NOT change: total energy served. A dispatch model cannot reduce demand, only re-shuffle '
      + 'which units meet it. Every saving in this module comes from substitution.',
    ],
    explain: [
      'Validate first, as always — Run → Dry run on → Validate. A second generator is exactly the kind of '
      + 'change that introduces a dangling `bus` or `carrier` reference, and validation catches both in seconds.',

      'Then run for real: Dry run off, Run model. Three snapshots and two generators solve instantly.',

      'Read Analytics → Result for the objective and reconcile it against 7,500 before you look at '
      + 'anything else. If it reads 12,000, coal is not in the answer at all — its `bus` or `carrier` '
      + 'reference is wrong and the unit is detached.',

      'The objective and the whole result dashboard both live under Analytics → Result — the Analytics '
      + 'subtab beside it is a smaller set of time-series charts, not the run\'s dashboard. Scroll Result '
      + 'down past the KPIs and the dispatch charts and you reach the card you want: the merit order. It is '
      + 'the supply stack, with cumulative capacity along the bottom and marginal cost up the side. Coal is '
      + 'the short cheap block on the left, gas the tall one beside it, and the vertical demand line shows '
      + 'where the stack is cut.',
    ],
    spotlights: [
      {
        selector: '.run-button',
        title: 'Validate, then run',
        runDialog: 'closed',
        note: 'The same two passes as module 1: Dry run on to validate, then Dry run off to solve. Both '
          + 'presses are yours. Validation is the cheap way to catch a mistyped reference before you spend '
          + 'a solve on it.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'Check the window first',
        runDialog: 'open',
        note: 'Snapshot range and resolution should still read 3 snapshots at 1h. If the resolution is not '
          + '1h your objective will not be 7,500 no matter how correct the model is, and you will spend the '
          + 'next ten minutes debugging the wrong thing.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'The objective',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Find it and reconcile against 7,500 before reading anything else. A number you predicted is '
          + 'worth more than a number you were given — and any mismatch is far cheaper to chase now than '
          + 'four steps later.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'The dashboard is on Result',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Everything the run produced lands here as a card — KPIs, dispatch, prices, the merit order — '
          + 'in a layout built from what the run actually contains, which you can rearrange. The Analytics '
          + 'subtab next door is a smaller chart set; the dashboard is here.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'The merit order card',
        tab: 'Analytics',
        note: 'The supply stack: cumulative capacity along the bottom, marginal cost up the side, one block '
          + 'per unit coloured by carrier. Coal is the short cheap block, gas the tall expensive one. The '
          + 'vertical line is demand — read across from where it cuts the stack and you have the price.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The headline numbers',
        tab: 'Analytics',
        note: 'Total cost, energy served and emissions for the run. Worth a glance after every solve — the '
          + 'quickest way to notice that a change you thought was small moved something by an order of '
          + 'magnitude.',
      },
    ],
    entries: [
      { field: 'Run dialog → Dry run', value: 'on (first pass)', why: 'Validates the two new references — the coal carrier and coal_1\'s bus — without spending a solve on them.' },
      { field: 'Run dialog → Dry run', value: 'off (second pass)', why: 'The real solve. This is the run whose objective you reconcile against 7,500.' },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation builds the network and stops. A second or two, and no history entry.',
        'The solve optimises 2 generators over 3 snapshots. Effectively instant.',
      ],
      expect: 'An objective of 7,500, with coal at 50 MW and gas at 30 MW in every hour.',
    },
    verify: [
      'Analytics → Result shows an objective of 7,500 — down from module 1\'s 12,000 for the same demand',
      'Dispatch shows coal_1 at 50 MW and gas_1 at 30 MW in all three snapshots',
      'The merit order card shows two blocks, coal to the left of gas',
      'You can say where the 4,500 saving came from without looking it up',
    ],
    pitfalls: [
      'An objective of 12,000 means coal contributed nothing — check coal_1\'s `bus` and `carrier` cells '
      + 'before anything else. A detached generator does not error; it simply is not there.',
      'An objective of 2,500 rather than 7,500 is one hour rather than three: the simulation window in '
      + 'Settings → Setup is narrowed, or the snapshot weight is not 1h.',
    ],
  },

  {
    id: 'm2-marginal-price',
    section: SECTION,
    title: 'The marginal unit sets the price',
    tab: 'Analytics',
    where: 'Analytics → Result → price cards',
    concept: [
      'Coal produced 50 of the 80 MW at a marginal cost of 20. Gas produced 30 at 50. So the price is 50 '
      + '— not 31.25, which is what the MWh actually cost on average.',

      'That is not an accounting convention, it is the answer to a question. Price here is the shadow '
      + 'price of the supply-equals-demand constraint at this bus in this hour: what it would cost the '
      + 'system to serve one more MWh. Coal is already flat out, so that extra MWh has to come from gas, '
      + 'and it costs 50. Ask a different question and you get a different number; this model is answering '
      + 'the marginal one.',

      'Which is how real wholesale markets clear, and why. Every generator is paid the marginal price, so '
      + 'coal earns 50 for electricity that cost it 20 — 30 per MWh of inframarginal rent. That rent is '
      + 'not a windfall to be designed away: it is what pays back the capital cost of the plant, which '
      + 'marginal cost deliberately excludes. A unit paid its own marginal cost would never recover its '
      + 'construction cost and would never be built.',

      'The marginal unit itself earns exactly its marginal cost and no rent at all. Keep that in mind '
      + 'through step 13, where the peaker only ever runs at the margin.',
    ],
    explain: [
      'Nothing to enter and nothing to run here — this step is reading the answer you already have. '
      + 'Stay on Analytics → Result.',

      'Find the price in the demand-and-price chart or the price-formation card. It should read 50 in all '
      + 'three snapshots. Check that it does before accepting the explanation above; the number is the evidence.',

      'The price-formation card is the one to get familiar with. It reports which unit was marginal and '
      + 'how often, which is the single most useful diagnostic in this whole application: it turns "the '
      + 'price was high" into "the price was high because THIS unit was setting it, in THESE hours".',

      'Right now that card is dull, because one unit sets the price in every hour. Come back to it after '
      + 'step 12, when three different units set three different prices.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: 'Back to the dashboard',
        tab: 'Analytics',
        note: 'The same Result dashboard as the last step, from the same run. Nothing has been re-solved — '
          + 'you are reading a different part of an answer you already have, which is most of what analysis '
          + 'actually is.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Price formation',
        tab: 'Analytics',
        note: 'Which unit set the price, in how many hours, at what average level. With one marginal unit '
          + 'this is a single line — the card earns its place after step 12, when the marginal unit changes '
          + 'from hour to hour and this becomes the fastest explanation of any price you did not expect.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Cost is not price',
        tab: 'Analytics',
        note: 'Total cost here is 7,500 over 240 MWh — 31.25 per MWh on average. The price is 50. Two '
          + 'different questions with two different answers, and confusing them is the commonest mistake '
          + 'made with a model like this.',
      },
    ],
    verify: [
      'The marginal price reads 50 in every snapshot',
      'You can say why it is 50 and not 31.25, in terms of one more MWh',
      'You can say what coal_1 earns per MWh, what it costs per MWh, and what the difference is for',
    ],
    pitfalls: [
      'No prices at all in the results means the run was not a linear program — a unit-commitment or '
      + 'mixed-integer run has no duals to report. Force LP off and a plain dispatch run gives prices.',
      'Reading average cost as "the price". They answer different questions and, from step 12 on, they '
      + 'are nowhere near each other.',
    ],
  },

  {
    id: 'm2-peaker',
    section: SECTION,
    title: 'A peaker that never runs',
    tab: 'Build',
    where: 'Build → Carriers, then Build → Generators',
    concept: [
      'Real systems carry plant that runs a handful of hours a year: old oil units, open-cycle turbines, '
      + 'anything cheap to keep and expensive to burn. They exist for the few hours when everything else '
      + 'is already flat out. Add one, and then confirm it does nothing — because confirming a change had '
      + 'no effect is a skill in itself.',

      'At 120 per MWh this unit sits at the top of the merit order. Demand is 80 MW; coal and gas cover '
      + 'it with 70 MW to spare. So the peaker produces nothing, earns nothing, and changes neither the '
      + 'objective nor the price.',

      'Note what that implies, because it is a real limitation and not a quirk: in a dispatch model, '
      + 'capacity you do not use is free. There is no fixed cost, no capital charge, nothing to pay for '
      + 'having built it. Which means this model can never tell you whether the peaker is worth keeping. '
      + 'That question needs capital costs and the freedom to choose capacity — module 6.',

      'It becomes the most valuable unit in the fleet in step 12, when demand goes above what coal and '
      + 'gas can serve between them. Adding it now means that step changes one thing only.',
    ],
    explain: [
      'Same two-sheet pattern as step 7. Build → Carriers first for `oil`, then Build → Generators for '
      + 'the unit itself.',

      'Then re-run — validate, then solve. Expect the objective to be 7,500 again, unchanged, with the '
      + 'peaker at 0 MW in every hour.',

      'An unchanged answer is a result. It tells you the merit order is doing what you think: expensive '
      + 'capacity is held back rather than used, and the optimiser is not paying for anything it does not '
      + 'need. If the objective moved, something else changed too and you should find out what.',

      'The merit order card is the place to see it. The stack is now three blocks wide, and the demand '
      + 'line cuts it well to the left of the oil block — the visual form of "held in reserve".',
    ],
    spotlights: [
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'A fourth carrier',
        tab: 'Build',
        note: 'AC, gas, coal, and now oil. The list of carriers is the list of fuels the model knows about, '
          + 'and it is also where every emission factor lives — which is why module 8 begins by reading '
          + 'this sheet rather than the generators one.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'A third generator',
        tab: 'Build',
        note: 'Three rows after this: coal_1, gas_1, oil_1. Read them as a fleet sorted by marginal cost — '
          + '20, 50, 120 — because that sort is exactly what the optimiser is about to do with them.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'Three blocks now',
        tab: 'Analytics',
        note: 'Re-run first, then look. The stack has a third, much taller block on the right, and the '
          + 'demand line still cuts it in the same place as before. Everything to the right of that line is '
          + 'capacity the system is holding but not using.',
      },
    ],
    entries: [
      {
        field: 'carriers.name (new row)',
        label: 'carrier name',
        value: 'oil',
        why: 'The peaker\'s fuel. Kept separate from gas so its cost and emissions can move independently — '
          + 'in a real study the whole point of a distinct carrier is that you can reprice it on its own.',
      },
      {
        field: 'carriers.co2_emissions (new row)',
        label: 'emission factor',
        value: '0.27',
        unit: 'tCO2 per MWh of fuel burnt',
        why: 'Oil sits between gas (0.2) and coal (0.34) per MWh of fuel. Its poor conversion efficiency '
          + 'makes it worse than that per MWh of electricity, which is one reason peakers are the first '
          + 'units a carbon price pushes out.',
      },
      {
        field: 'generators.name',
        label: 'generator name',
        value: 'oil_1',
        why: 'Identifies the peaker in results. Once it starts running in step 12 you will want to see its '
          + 'hours and its revenue separately from the baseload units, and this name is how.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'The same bus again. Still one node, so still a pure merit-order problem — every unit competes '
          + 'against every other with nothing between them.',
      },
      {
        field: 'generators.carrier',
        label: 'fuel / technology',
        value: 'oil',
        why: 'Must match the `carriers.name` you just typed. This is the third time this reference has come '
          + 'up, and it is still the commonest way to break a model.',
      },
      {
        field: 'generators.p_nom',
        label: 'installed capacity',
        value: '40',
        unit: 'MW',
        why: '40 MW on top of coal\'s 50 and gas\'s 100 gives the system 190 MW. Step 12 pushes demand to '
          + '170 MW in one hour, which only this unit\'s capacity makes feasible — so choose it now with '
          + 'that in mind.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'cost per extra MWh',
        value: '120',
        unit: 'currency per MWh',
        why: 'More than double gas. That is what puts it at the top of the merit order and keeps it out of '
          + 'the answer until nothing else is left — and it is also why, in the one hour it does run, the '
          + 'price more than doubles.',
      },
      {
        field: 'generators.efficiency',
        label: 'fuel-to-electricity conversion',
        value: '0.35',
        why: 'Low, as peakers are — they are built to start quickly and cheaply, not to run efficiently. It '
          + 'is part of why their marginal cost is so high in the first place.',
      },
    ],
    verify: [
      'The `generators` sheet has 3 rows and the `carriers` sheet has 4',
      'After re-running, the objective is still 7,500 — unchanged',
      'Dispatch shows oil_1 at 0 MW in every snapshot',
      'The price is still 50 in every snapshot',
      'You can say why this model cannot tell you whether the peaker is worth keeping',
    ],
    pitfalls: [
      'An objective that moved means something other than the peaker changed. Compare the generator rows '
      + 'against the values above before assuming the model is wrong.',
      'Expecting an unused unit to cost something. It does not, and that is a property of dispatch models '
      + 'worth remembering rather than a bug — it is precisely the gap module 6 fills.',
    ],
  },

  {
    id: 'm2-demand-profile',
    section: SECTION,
    title: 'Demand that moves',
    tab: 'Build',
    where: 'Build → Loads → time-series panel',
    concept: [
      'Demand has been flat at 80 MW, which no real demand ever is. It follows daily and seasonal cycles, '
      + 'and the whole reason a system needs more than one kind of plant is that its peak is far above its '
      + 'average.',

      'Every component attribute in PyPSA comes in two forms: a static value on the component sheet, and '
      + 'a time-varying profile indexed by the snapshots. `loads.p_set` is the static one you typed in '
      + 'module 1; `loads-p_set` is its profile, one column per load and one row per snapshot. When a '
      + 'profile exists for a component, it wins and the static value is ignored — so you can leave the '
      + '80 where it is.',

      'That is the same pattern for every temporal attribute in the model: generator availability, '
      + 'storage inflow, link efficiency. Learn it once here and it is the last time it needs explaining.',

      'The three values are chosen to make the model do three different things: 40 MW, which coal alone '
      + 'can serve; 80 MW, which needs gas as well; and 170 MW, which needs every unit including the '
      + 'peaker. One profile, three regimes, three prices.',
    ],
    explain: [
      'Go to Build → Loads. On the right, under the attribute form, is a "Loads · time-series" panel. It '
      + 'starts collapsed — click its header to open it, and it lists the attributes of a load that can '
      + 'vary over time: `p_set` and `q_set`. You want `p_set`, the real power demanded; `q_set` is '
      + 'reactive power, which a linear dispatch model does not use. Click `p_set` and the table on the '
      + 'left switches from the loads sheet to that profile.',

      'The profile is empty, so the grid offers "Write from scratch" — press it. It seeds one row per '
      + 'snapshot, with a blank column for each load. Three snapshots, one load, so three rows and one '
      + 'column to fill.',

      'Type the three values into the `load_1` column. The snapshot column itself is locked on purpose: '
      + 'the time index belongs to the snapshots sheet, and letting it be edited here is how a profile '
      + 'silently stops lining up with the run.',

      'The panel also offers Import, which takes a CSV with a snapshot column and one column per load. '
      + 'That is what you would actually use for 8760 rows of metered demand — typing three by hand is a '
      + 'teaching exercise, not a workflow.',

      'Click `p_set` again in the panel to switch the table back to the static loads sheet. The old 80 is '
      + 'still sitting there, and it no longer does anything.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="loads"]',
        buildStep: 'loads',
        title: 'The Loads step',
        tab: 'Build',
        note: 'One row — load_1 on bus_1, p_set 80. That static row stays exactly as it is; you are adding '
          + 'a profile alongside it, not replacing it.',
      },
      {
        selector: '.build-ts-panel',
        buildStep: 'loads',
        title: 'The time-series panel',
        tab: 'Build',
        note: 'Collapsed to start with — click the header to open it. Inside are the attributes of a load '
          + 'that can vary over time, p_set and q_set, with the row count beside each so you can see which '
          + 'are populated. Click p_set now: the next stop points at a control that only exists once you have.',
      },
      {
        selector: '[data-tour="ts-seed"]',
        buildStep: 'loads',
        title: 'Write from scratch',
        tab: 'Build',
        note: 'Only here once the p_set profile is selected and still empty — if this stop reports its target '
          + 'missing, go back and click p_set in the panel. It creates one row per snapshot with a blank '
          + 'column per load, which is the alternative to importing a CSV for a real 8760-row profile.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'loads',
        title: 'Where the values go',
        tab: 'Build',
        note: 'Three rows, one per snapshot, with the snapshot column locked and a load_1 column to fill. '
          + 'The lock is deliberate: the time index belongs to the snapshots sheet, and a profile whose '
          + 'index drifts from the run\'s is the hardest class of error to spot.',
      },
    ],
    entries: [
      {
        field: 'loads-p_set.load_1 (row 1, 2030-01-01 00:00)',
        label: 'demand in hour 1',
        value: '40',
        unit: 'MW',
        why: 'Below coal\'s 50 MW, so coal alone serves this hour and sets the price at 20. This is the '
          + 'overnight-minimum end of a demand curve, and it exists in the profile to show that the price '
          + 'can fall as well as spike.',
      },
      {
        field: 'loads-p_set.load_1 (row 2, 2030-01-01 01:00)',
        label: 'demand in hour 2',
        value: '80',
        unit: 'MW',
        why: 'The same 80 MW as before, kept deliberately so one hour of the new answer is directly '
          + 'comparable with the old one: coal 50, gas 30, price 50. A control case inside your own model.',
      },
      {
        field: 'loads-p_set.load_1 (row 3, 2030-01-01 02:00)',
        label: 'demand in hour 3',
        value: '170',
        unit: 'MW',
        why: 'Above coal plus gas (150 MW), so the peaker must run and sets the price at 120. Also close to '
          + 'the fleet\'s 190 MW limit — push it past that and the model returns INFEASIBLE, which is the '
          + 'only way a dispatch model can tell you the system is short of capacity.',
      },
    ],
    verify: [
      'The `loads-p_set` profile has 3 rows and a load_1 column reading 40, 80, 170',
      'The static `loads` sheet still has its one row with p_set 80, untouched',
      'The time-series panel shows "3 rows" beside p_set rather than "empty"',
      'You can say which value the model will use, and why the other is ignored',
    ],
    pitfalls: [
      'Typing the values into the static `loads` sheet instead of the profile. There is only one p_set '
      + 'cell there, so the third value overwrites the first two and demand stays flat.',
      'A profile with fewer rows than there are snapshots. Every snapshot needs a value; a gap is not '
      + 'interpolated for you, and Analytics → Validation is what reports it.',
    ],
  },

  {
    id: 'm2-three-prices',
    section: SECTION,
    title: 'Three hours, three prices',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Work each hour out before you run it. The merit order is the same in all three — coal 20, gas 50, '
      + 'oil 120 — only the demand line moves.',

      'Hour 1, 40 MW: coal alone, part-loaded. Cost 40 × 20 = 800. Coal is the marginal unit, so the price '
      + 'is 20.',

      'Hour 2, 80 MW: coal flat out at 50, gas fills 30. Cost 1,000 + 1,500 = 2,500. Gas is marginal, so '
      + 'the price is 50.',

      'Hour 3, 170 MW: coal 50, gas 100, and the peaker covers the last 20. Cost 1,000 + 5,000 + 2,400 = '
      + '8,400. Oil is marginal, so the price is 120.',

      'Total 11,700 over 290 MWh, with prices of 20, 50 and 120. One fleet, one merit order, three '
      + 'completely different hours — and every part of that difference comes from where the demand line '
      + 'cuts the stack.',
    ],
    explain: [
      'Validate, then run. Read the objective in Analytics → Result and reconcile against 11,700 before '
      + 'anything else.',

      'Then look at the dispatch chart over time. Coal is flat-topped — it hits 50 and stays there, '
      + 'because there is never a reason for the cheapest unit to hold back. Gas follows the shape of '
      + 'demand. Oil is a single spike in the last hour.',

      'That shape has a name worth knowing: coal is running baseload, gas is load-following, oil is '
      + 'peaking. Nobody assigned those roles — they fall out of three numbers in a marginal_cost column.',

      'Now open the price-formation card again. It was a single line two steps ago; it now has three '
      + 'entries, one per marginal unit, and reading it tells you the whole story of the run without '
      + 'looking at a single dispatch number.',
    ],
    spotlights: [
      {
        selector: '.sg-scenario-summary',
        title: 'Same window, new profile',
        runDialog: 'open',
        note: 'Still 3 snapshots at 1h — the profile changed the demand values, not the time axis. Worth '
          + 'confirming, because a profile and an axis that disagree is a mistake this summary catches and '
          + 'nothing else will.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile 11,700',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Three hours worked out by hand: 800 + 2,500 + 8,400. If the answer is 7,500 the profile is '
          + 'not being read at all and demand is still flat at 80 — check the profile has three rows and a '
          + 'column named exactly load_1.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Three marginal units',
        tab: 'Analytics',
        note: 'Now the card earns its place: one row per unit that set the price, with the hours it was '
          + 'marginal and the average price while it was. This is the fastest route from "why was the price '
          + 'that?" to an answer, on a model of any size.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'The line that moves',
        tab: 'Analytics',
        note: 'The stack is fixed — the same three blocks in the same order all module. It is the demand '
          + 'line that moves across it, hour by hour, and where it lands is both the dispatch and the '
          + 'price. That single picture is most of what this module is teaching.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the profile lines up with the snapshots — a mismatched index is reported here.',
        'The solve optimises 3 generators over 3 snapshots. Instant.',
      ],
      expect: 'An objective of 11,700, with prices of 20, 50 and 120 across the three snapshots.',
    },
    verify: [
      'Analytics → Result shows an objective of 11,700',
      'Prices read 20, 50 and 120 across the three snapshots',
      'Dispatch shows coal_1 at 40, 50, 50; gas_1 at 0, 30, 100; oil_1 at 0, 0, 20',
      'You can name the marginal unit in each hour without opening the price-formation card',
    ],
    pitfalls: [
      'An objective of 7,500 means the profile is not being used — most often a column named `load1` or '
      + '`Load_1` rather than `load_1`, which matches no load and is silently ignored.',
      'INFEASIBLE in hour 3 means demand exceeds the 190 MW the fleet can produce. Check the third value '
      + 'reads 170 and not 1700.',
    ],
  },

  {
    id: 'm2-price-vs-cost',
    section: SECTION,
    title: 'Price is not average cost',
    tab: 'Analytics',
    where: 'Analytics → Result → price and economics cards',
    concept: [
      'The run cost 11,700 to serve 290 MWh — 40.3 per MWh on average. The prices were 20, 50 and 120. '
      + 'Neither of those sets of numbers is wrong, and they are not attempts at the same quantity.',

      'Average cost answers "what did this cost in total, spread over what it delivered?". Price answers '
      + '"what would one more MWh have cost, right then?". In a system where the marginal unit changes '
      + 'hour to hour, the second question has a different answer every hour and no reason to resemble '
      + 'the first.',

      'Follow the money for one unit. Coal produced 140 MWh across the three hours at a marginal cost of '
      + '20, so it cost 2,800 to run. It was paid the hourly price on every MWh: 40 at 20, then 50 at 50, '
      + 'then 50 at 120 — 800 + 2,500 + 6,000 = 9,300. Its margin above running cost is 6,500, and that '
      + 'is what has to cover building the plant.',

      'Now the peaker. It ran for one hour, produced 20 MWh at a cost of 2,400, and was paid 120 × 20 = '
      + '2,400. Exactly its cost, and not a currency unit more, because it was the marginal unit whenever '
      + 'it ran at all. A plant that only ever runs at the margin earns no margin — which is the whole of '
      + 'the "missing money" problem in one line, and the reason capacity markets exist.',

      'This is why an average cost per MWh is a poor summary of a power system, and why the shape of the '
      + 'price distribution matters more than its mean. A few extreme hours can carry the economics of an '
      + 'entire fleet.',
    ],
    explain: [
      'Nothing to enter and nothing to run. Stay on the dashboard from the last step and read it properly.',

      'Start with the KPI strip for total cost and energy served, and do the division yourself — 11,700 '
      + 'over 290 MWh. Then compare it against the price series. The gap is the point of this step.',

      'The price duration curve sorts every hour\'s price from highest to lowest, discarding time. With '
      + 'three hours it is barely a curve, but the shape is the one you will meet everywhere: a short '
      + 'steep head where scarcity lives, a long flat body, and the head carrying far more of the revenue '
      + 'than its width suggests.',

      'If the run produced an asset-economics card, open it: revenue, cost and margin per generator, '
      + 'which is the arithmetic above already done for every unit. Reproduce coal\'s numbers by hand '
      + 'first, then check the card agrees — that way you know what it is telling you.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Total cost, total energy',
        tab: 'Analytics',
        note: '11,700 and 290 MWh. Divide them and you get 40.3 per MWh — a number that describes no single '
          + 'hour of this run, and that no participant in it ever faced. Averages hide exactly the hours '
          + 'that matter.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Where the money is made',
        tab: 'Analytics',
        note: 'Read it as a revenue story rather than a price story: the hours a unit is marginal are the '
          + 'hours it earns nothing above cost, and the hours it is inframarginal are the hours it pays for '
          + 'itself. Coal is inframarginal twice; oil never is.',
      },
      {
        selector: '[data-card="duration-curve"][data-card-source="price"]',
        title: 'The price duration curve',
        tab: 'Analytics',
        note: 'Every hour sorted by price, highest to lowest, with time thrown away — there is a load '
          + 'duration curve just above it doing the same for demand. Three hours makes a crude staircase, '
          + 'but it is the standard way to read a year: the steep left-hand head is where scarcity and the '
          + 'peaking economics live.',
      },
    ],
    verify: [
      'You can state the average cost per MWh and say why no hour actually had that price',
      'You can work out coal_1\'s revenue and margin from the price series alone',
      'You can say why the peaker earned exactly its costs, and what that implies for building one',
      'You can explain inframarginal rent to someone who has not done this course',
    ],
    pitfalls: [
      'Concluding the peaker is uneconomic. In this three-hour model it breaks exactly even; whether it '
      + 'is worth building depends on capital cost and on how often the tight hours recur — neither of '
      + 'which this model contains.',
      'Averaging prices across hours to get "the" price. Weight by volume if you must, and expect the '
      + 'answer to depend heavily on a handful of hours.',
    ],
  },

  {
    id: 'm2-variable-generation',
    section: SECTION,
    title: 'Variable generation — availability, not capacity',
    tab: 'Build',
    where: 'Build → Carriers, Build → Generators, then its time-series panel',
    concept: [
      'A thermal unit\'s `p_nom` is what it can produce whenever asked. A wind farm\'s is not: it is what '
      + 'the machine could produce in a perfect wind, and the actual ceiling changes every hour with the '
      + 'weather. That difference is the single most important thing to get right about renewables in a '
      + 'model.',

      'PyPSA expresses it as `p_max_pu` — the per-unit maximum, a fraction between 0 and 1 that multiplies '
      + '`p_nom` to give this hour\'s ceiling. A 60 MW farm at p_max_pu 0.4 can produce at most 24 MW in '
      + 'that hour. It is a ceiling and not a target: the model may produce less, and the difference has '
      + 'a name.',

      'Marginal cost is 0. Wind burns nothing, so producing one more MWh costs essentially nothing, which '
      + 'puts it at the very bottom of the merit order — it displaces everything else whenever it is '
      + 'available. That is why adding wind to a system reduces prices as well as emissions, and why the '
      + 'units it displaces are the expensive ones first.',

      'Because it is free and it is capped, wind creates a case that could not arise before: more '
      + 'available than the system needs. What happens then is step 15.',
    ],
    explain: [
      'Three pieces, in order. Build → Carriers for the `wind` carrier. Build → Generators for the farm '
      + 'itself. Then its time-series panel for the availability profile.',

      'Leave the generator\'s static `p_max_pu` cell empty. Its default is 1, meaning "always fully '
      + 'available", which is right for a thermal unit and wrong for this one — and the profile you add '
      + 'next overrides it anyway, exactly as the load profile overrode the static demand.',

      'For the profile: with the Generators step open, expand the "Generators · time-series" panel on the '
      + 'right. It is a longer list than the loads one — ten attributes, because almost everything about a '
      + 'generator can be made to vary over time, including its marginal cost and its ramp limits. The one '
      + 'you want is `p_max_pu`. Click it and the table switches to that profile sheet.',

      'Then press "Write from scratch" and it seeds three rows — but note the columns. It creates one per '
      + 'GENERATOR, so you get columns for gas_1, coal_1, oil_1 and wind_1.',

      'Fill in the wind_1 column only, and leave the other three blank. A blank means "no profile for this '
      + 'unit", so the thermal units keep their static default of 1 and stay fully available. Typing 1 into '
      + 'them would work too, but blank is the honest expression of "this does not vary".',

      'The three values represent a windy hour, an average one and a still one. In a real study they come '
      + 'from reanalysis weather data — Ragnarok\'s Data view imports them for any location — and there '
      + 'would be 8,760 of them.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'A fourth generator',
        tab: 'Build',
        note: 'coal_1, gas_1, oil_1 and now wind_1. Note what makes it different in the table: marginal_cost '
          + '0, and a p_max_pu cell you deliberately leave blank. Everything else looks like any other unit.',
      },
      {
        selector: '.build-ts-panel',
        buildStep: 'generators',
        title: 'The generator profiles',
        tab: 'Build',
        note: 'Open it and compare with the loads panel: ten entries rather than two, because nearly '
          + 'everything about a generator can vary over time — even its marginal cost and its ramp limits. '
          + 'Click p_max_pu, which is the one that matters for renewables and the one the next stop needs.',
      },
      {
        selector: '[data-tour="ts-seed"]',
        buildStep: 'generators',
        title: 'Seed the profile',
        tab: 'Build',
        note: 'Only here once p_max_pu is selected and still empty. Same control as the load profile, but '
          + 'watch the result: it creates a column for EVERY generator, not just the one you care about. '
          + 'Fill in wind_1 and leave the thermal columns blank so they keep full availability.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'One column of three',
        tab: 'Build',
        note: 'Three rows, four generator columns, and only wind_1 gets values. A blank cell here is not '
          + 'missing data — it means this unit has no time-varying ceiling, which is exactly true of a '
          + 'thermal plant.',
      },
    ],
    entries: [
      {
        field: 'carriers.name (new row)',
        label: 'carrier name',
        value: 'wind',
        why: 'The energy source. It groups wind in per-carrier results and carries the emission factor — '
          + 'zero here, because the fuel is free and carbon-free at the point of generation.',
      },
      {
        field: 'carriers.co2_emissions (new row)',
        label: 'emission factor',
        value: '0',
        unit: 'tCO2 per MWh of fuel',
        why: 'No fuel is burnt, so nothing is emitted in operation. Lifecycle emissions from manufacture '
          + 'and construction are real but are not what this attribute means — it is the operational factor '
          + 'the solver multiplies by fuel consumption.',
      },
      {
        field: 'generators.name',
        label: 'generator name',
        value: 'wind_1',
        why: 'Identifies the farm in results, and — importantly — is the column header you type the '
          + 'availability profile under. Get it wrong in one of the two places and the profile matches '
          + 'nothing, leaving the farm fully available in every hour.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'Still the one bus. In reality wind sits where the wind is, which is rarely where the demand '
          + 'is — and that mismatch is what causes congestion, which needs the second bus and the line of '
          + 'module 3.',
      },
      {
        field: 'generators.carrier',
        label: 'fuel / technology',
        value: 'wind',
        why: 'Must match the carrier name exactly. It is also what makes the unit show up as renewable in '
          + 'per-carrier results and in the renewable-share metrics.',
      },
      {
        field: 'generators.p_nom',
        label: 'installed capacity',
        value: '60',
        unit: 'MW',
        why: 'The nameplate rating — what it makes in a perfect wind, not what it makes on average. Sized '
          + 'deliberately above the 40 MW demand of hour 1, so that in the windy hour there is more wind '
          + 'available than the system can use.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'cost per extra MWh',
        value: '0',
        unit: 'currency per MWh',
        why: 'Producing one more MWh from an already-built wind farm costs essentially nothing — no fuel '
          + 'to buy. That is what puts it at the bottom of the merit order and lets it displace everything '
          + 'else, and it is also why it drags the price down whenever it is the marginal unit.',
      },
      {
        field: 'generators.efficiency',
        label: 'fuel-to-electricity conversion',
        value: '1',
        why: 'There is no fuel to convert, so the conversion is one-to-one by convention. Together with a '
          + 'zero emission factor it means the farm contributes nothing to the emissions total no matter '
          + 'how hard it runs.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (row 1, 2030-01-01 00:00)',
        label: 'availability in hour 1',
        value: '0.9',
        why: 'A windy hour: 90% of 60 MW is 54 MW available. Demand in that hour is only 40 MW, so for the '
          + 'first time the model has more free energy on offer than it can use — which is the situation '
          + 'step 15 is built around.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (row 2, 2030-01-01 01:00)',
        label: 'availability in hour 2',
        value: '0.4',
        why: 'An ordinary hour: 24 MW available against 80 MW of demand. Wind takes the bottom of the stack '
          + 'and the thermal units cover the rest — the normal case, and the one that shows wind displacing '
          + 'the most expensive running unit rather than the cheapest.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (row 3, 2030-01-01 02:00)',
        label: 'availability in hour 3',
        value: '0.1',
        why: 'A still hour, and deliberately the hour of highest demand — 6 MW available against 170 MW '
          + 'needed. Wind and peak demand not coinciding is the central planning problem of a renewable '
          + 'system, and this row is that problem in miniature.',
      },
    ],
    verify: [
      'The `carriers` sheet has 5 rows and the `generators` sheet has 4',
      'wind_1 has marginal_cost 0 and an empty static p_max_pu cell',
      'The `generators-p_max_pu` profile has 3 rows, with values only in the wind_1 column',
      'You can say what 0.4 means in MW for this farm, without a calculator',
    ],
    pitfalls: [
      'Typing the availability into `p_nom` rather than `p_max_pu` — a 0.9 MW wind farm rather than a '
      + '60 MW one at 90% availability. The dispatch chart makes this obvious: wind contributes almost nothing.',
      'Filling in the thermal columns with 0. That pins coal, gas and oil to zero output and the model '
      + 'goes infeasible the moment demand exceeds what wind can supply. Blank, or 1, never 0.',
      'A wind_1 column header that does not match the generator name exactly. The profile is then ignored '
      + 'and the farm runs at full 60 MW in every hour — which looks like a wonderful result and is wrong.',
    ],
  },

  {
    id: 'm2-zero-prices',
    section: SECTION,
    title: 'Run: curtailment and a zero price',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Hour by hour again, before you run it.',

      'Hour 1, demand 40, wind available 54. Wind is free, so it serves all 40 and every other unit stays '
      + 'off. But 14 MW of available wind has nowhere to go — the model simply does not produce it. That '
      + 'is curtailment: energy that was available and was not taken. Cost for the hour: 0. And the '
      + 'marginal unit is wind, whose marginal cost is 0, so the price is 0.',

      'Hour 2, demand 80, wind available 24. Wind produces all 24, coal runs flat out at 50, gas covers '
      + 'the last 6. Cost 1,000 + 300 = 1,300, and gas is marginal, so the price is 50 — unchanged from '
      + 'before. Note what wind displaced: 24 MWh that gas would have produced at 50, not coal at 20. Free '
      + 'generation always pushes out the most expensive unit running.',

      'Hour 3, demand 170, wind available 6. Wind 6, coal 50, gas 100, oil 14. Cost 1,000 + 5,000 + 1,680 '
      + '= 7,680, and the price is still 120 — the peaker is still marginal. Wind barely helped in the '
      + 'hour the system needed it most.',

      'Total 8,980, down from 11,700. Wind saved 2,720 — but look at where the saving came from: almost '
      + 'all of it in hours that were already cheap. The tight hour, which drives both the price and the '
      + 'capacity the system must own, is barely touched. That asymmetry is the central fact of renewable '
      + 'integration, and this three-hour model shows it as clearly as an 8,760-hour one.',
    ],
    explain: [
      'Validate, then run. Reconcile the objective against 8,980 first, as always.',

      'Then find the curtailment. The dashboard carries a curtailment-by-carrier chart beside the merit '
      + 'order; it should report 14 MWh of wind in hour 1 and nothing after. You can also read it as the '
      + 'gap between what the profile allowed — 0.9 × 60 = 54 MW — and what wind_1 actually produced.',

      'Curtailment is an economic outcome, not a fault. It means the system had more free energy on offer '
      + 'than it could use at that moment. The cures are all things this model does not have: storage to '
      + 'move it to another hour (module 4), a line to move it somewhere else (module 3), or flexible '
      + 'demand to consume it now.',

      'Then look at the price in hour 1: zero. When the marginal unit costs nothing to run, one more MWh '
      + 'costs nothing, so the price is nothing. Real markets go further and price negatively, because '
      + 'subsidies and start-up costs can make it worth paying to keep generating — the mechanism is the '
      + 'same one you are looking at.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile 8,980',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Three hours: 0 + 1,300 + 7,680. If it reads lower, wind is running above its availability — '
          + 'the profile is not matched to the generator name. If it reads 11,700, wind is not in the answer '
          + 'at all.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'A new bottom to the stack',
        tab: 'Analytics',
        note: 'Wind now sits at the far left at zero cost, pushing every thermal block to the right. The '
          + 'demand line has not moved, so everything it now cuts through is cheaper than it was — that '
          + 'shift is the whole economic effect of renewables in one picture.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Wind sets a price too',
        tab: 'Analytics',
        note: 'Four units in the fleet and three of them set the price at some point, wind among them at '
          + 'zero. A renewable being marginal is exactly what a zero or negative price means, and this card '
          + 'is where you confirm it rather than guessing.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'What changed and what did not',
        tab: 'Analytics',
        note: 'Cost falls from 11,700 to 8,980 and emissions fall with it, but energy served is unchanged at '
          + '290 MWh — the same demand met more cheaply. Check all three numbers, not just the one that '
          + 'moved in the direction you hoped.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the availability profile lines up with the snapshots and matches a real generator name.',
        'The solve optimises 4 generators over 3 snapshots. Instant.',
      ],
      expect: 'An objective of 8,980, prices of 0, 50 and 120, and 14 MWh of wind curtailed in the first hour.',
    },
    verify: [
      'Analytics → Result shows an objective of 8,980',
      'Prices read 0, 50 and 120 across the three snapshots',
      'wind_1 produces 40, 24 and 6 MW — never above 0.9, 0.4 and 0.1 times its 60 MW',
      '14 MWh of wind is curtailed in the first snapshot and none afterwards',
      'You can say why wind displaced gas rather than coal in the second hour',
    ],
    pitfalls: [
      'An objective below 8,980 usually means wind ran above its ceiling — the profile column name does '
      + 'not match wind_1, so the static default of 1 applied and the farm was fully available all three hours.',
      'Reading curtailment as an error. It is the model correctly declining free energy it cannot use, and '
      + 'the fix is storage, transmission or flexible demand — none of which this model has yet.',
      'Expecting wind to reduce the peak price. It does not here, and usually does not in reality: the '
      + 'tight hour was the still hour, which is precisely why it was tight.',
    ],
  },

  {
    id: 'm2-what-changed',
    section: SECTION,
    title: 'What module 2 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours, and they are the load-bearing ideas of short-run power economics.',

      'The merit order: least cost means cheapest-first, and nobody had to write that rule down — it is '
      + 'what minimising cost means when the only decision is how hard to run what exists.',

      'Marginal pricing: the price is the marginal unit\'s cost, it changes every hour, and it is nothing '
      + 'like average cost. Everything cheaper than the marginal unit earns rent, the marginal unit earns '
      + 'nothing, and that is how plant gets paid for.',

      'Availability versus capacity: `p_nom` is the machine, `p_max_pu` is the weather, and for a '
      + 'renewable the second one decides everything. When free energy exceeds what the system can take, '
      + 'the surplus is curtailed and the price goes to zero.',

      'And one negative result, which matters as much: this model has no opinion about investment. '
      + 'Capacity was fixed at every step, unused capacity was free, and the peaker exactly broke even. '
      + 'Ask this model whether to build more wind and it cannot answer — not because it is small, but '
      + 'because it has no capital costs in it.',
    ],
    explain: [
      'Three limits to name explicitly, each of which is a later module.',

      'One bus, so every unit competes on equal terms and there is one price. Add a second bus and a line '
      + 'between them and both stop being true: power flows are constrained, the two buses can carry '
      + 'different prices, and the cheapest generator may be unable to reach the demand. That is module 3.',

      'No storage, so every hour is independent — the model solves three separate problems that happen to '
      + 'share a fleet. Storage is what couples hours together, and it is the only thing here that could '
      + 'have used the 14 MWh curtailed in hour 1. Module 4.',

      'Fixed capacity, so the model chooses operation and never investment. Give it capital costs and the '
      + 'freedom to change `p_nom` and the same machinery answers a completely different question. Module 5.',

      'Before you go, export the project — Model → Export project. Module 3 ships a checkpoint of this '
      + 'exact model, but a file you exported yourself is the one you will trust, and being able to put a '
      + 'model down and pick it up again is worth practising on something small.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: '8,980 to serve 290 MWh across a four-unit fleet, from a model that answered 12,000 with one '
          + 'unit at the start of this module. Same demand throughout — every bit of the difference came '
          + 'from giving the optimiser something to choose between.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project writes the whole workbook to a file. Module 3 ships this model as a '
          + 'checkpoint anyway, but a model you saved yourself is the one you will trust when the two '
          + 'disagree — and they will, if you experimented.',
      },
      {
        selector: '.activity-bar',
        title: 'What is still untouched',
        note: 'Most of the activity bar has gone unused so far. Forge, Market & Policy and Post-analysis all '
          + 'act on the model you have just built — the next modules are largely about those views, not '
          + 'about building more sheets.',
      },
    ],
    verify: [
      'You can explain the merit order, the marginal unit and inframarginal rent without notes',
      'You can say why a dispatch model cannot tell you whether to build a plant',
      'You can name the one thing that would have used the curtailed wind, and which module adds it',
      'You have exported the project and know where the file is',
    ],
    pitfalls: [
      'Taking the price levels seriously. They come from four made-up marginal costs on a three-hour '
      + 'model. What transfers to a real study is the mechanism, not the numbers.',
      'Concluding wind is worth 2,720. That is its value against THIS fleet, in THESE three hours, with '
      + 'no capital cost counted anywhere. Value is always relative to the alternative, which is why '
      + 'module 6 compares scenarios rather than reading one.',
    ],
  },
];
