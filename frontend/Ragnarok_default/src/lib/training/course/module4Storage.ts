/**
 * Module 4 — Storage and time coupling (9 steps).
 *
 * Every model so far has solved each hour independently. Three snapshots meant
 * three separate problems that happened to share a fleet: nothing carried from
 * one to the next, which is why module 2 could throw away 14 MWh of free wind in
 * the first hour and still run an oil peaker in the third. Storage is the first
 * component that couples them, and the moment it exists the model stops solving
 * hours and starts solving a schedule.
 *
 * Built on module 3's congested two-bus network (9,400). Every figure verified
 * against a real HiGHS solve before the prose was written:
 *
 *   step 4  ideal battery, 20 MW / 1 h at bus_2   7,540   peak price 120 -> 50
 *   step 6  realistic 90% each way                7,730   losses cost 190
 *   step 7  half the energy (max_hours 0.5)       8,320   curtailment returns
 *   step 8  same battery moved to bus_1           8,773   worth ~1,000 less
 *
 * The closing comparison is the point of the module. An identical battery is
 * worth 1,670 at the demand end and 627 behind the constraint — where you put
 * storage matters roughly as much as how much of it you buy, and nothing in a
 * single-bus model can tell you that.
 */
import { TutorialStep } from '../types';

const SECTION = '4 · Storage and time coupling';

export const MODULE_4_STORAGE: TutorialStep[] = [
  {
    id: 'm4-why-storage',
    section: SECTION,
    title: 'The first component that couples hours',
    tab: 'Build',
    where: 'Build → Storage step',
    startOptions: {
      prebuiltExampleId: 'training_m3',
      completeExampleId: 'training_m4',
      note:
        'Module 4 continues module 3\'s two-bus network — cheap coal and wind at bus_1, the demand and '
        + 'the expensive plant at bus_2, joined by a 60 MW line that fills up in the middle hour. It '
        + 'answered 9,400. If your line is not still at 60 MW, load the prebuilt data: the congestion is '
        + 'what makes storage interesting here.',
    },
    concept: [
      'Look back at what module 2 did and did not do. In the first hour it curtailed 14 MWh of free '
      + 'wind. In the third it burned oil at 120 per MWh. Those two facts sat in the same answer, and '
      + 'nothing in the model could connect them, because each snapshot was solved as its own balance '
      + 'with no memory of the last.',

      'Storage is what connects them. It is the first component whose behaviour in one hour constrains '
      + 'what it can do in the next: energy put in now is energy available later, and only later. That '
      + 'single link turns a set of independent hourly problems into one problem across time.',

      'The variable that carries the link is the state of charge — how much energy is in the store at '
      + 'the end of each snapshot. It is not something you set; the optimiser chooses it, subject to the '
      + 'store\'s size and to the arithmetic that what comes out must have gone in.',

      'And storage earns its living on the SPREAD, not the level. A battery does not care that prices '
      + 'average 50; it cares that they are 0 in one hour and 120 in another. Flat prices are worthless '
      + 'to it however high they are — which is why storage revenue collapses in exactly the systems '
      + 'that are easiest to operate.',
    ],
    explain: [
      'The model you are starting from is module 3\'s: two buses, four generators, a 60 MW line that is '
      + 'full in the middle hour, and prices of 0 / 20 / 120 at bus_1 and 0 / 50 / 120 at bus_2. It '
      + 'answered 9,400.',

      'That model has a 120 per MWh hour and a zero per MWh hour, three hours apart. Storage exists to '
      + 'exploit exactly that gap, and by the end of this module a single 20 MW battery will have removed '
      + 'the peaker from the answer entirely.',

      'The Storage step has been in the strip since module 1, blank, and skipping it was correct — an '
      + 'empty optional sheet is not an error. It is this module\'s step.',

      'One thing to have in mind before you build anything: WHERE the battery goes is a real decision '
      + 'here, not a detail. Module 3 put a constraint in the middle of the network, and a battery on the '
      + 'wrong side of a constraint is worth a fraction of the same battery on the right side. Step 8 '
      + 'measures exactly that.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'The Storage step',
        tab: 'Build',
        note: 'Blank for three modules and skipped every time, correctly — optional sheets are allowed to '
          + 'be empty. The map is here because storage sits at a bus and inherits its position, so you can '
          + 'see which end of the network a battery is on — which turns out to matter a great deal by step 8.',
      },
      {
        selector: '.build-step-strip',
        title: 'What is still blank',
        tab: 'Build',
        note: 'After this module only Links, Processes and Constraints stay empty. Links are module 5, '
          + 'where a bus stops being electric; Constraints are module 8, where policy arrives.',
      },
    ],
    verify: [
      'The session holds module 3\'s model: 2 buses, 4 generators, 1 line at 60 MW',
      'You can say why module 2 curtailed wind in one hour and burned oil in another',
      'You can say what a state of charge is, and who decides it',
      'You can say what kind of price pattern makes storage valuable',
    ],
    pitfalls: [
      'Starting from an uncongested model. If you left the line at 100 MW at the end of module 3, put it '
      + 'back to 60 — or load the prebuilt data. Storage on a copper plate still arbitrages, but the '
      + 'placement lesson in step 8 disappears entirely.',
    ],
  },

  {
    id: 'm4-unit-vs-store',
    section: SECTION,
    title: 'StorageUnit or Store — which one you want',
    tab: 'Build',
    where: 'Build → Storage step',
    concept: [
      'PyPSA offers two ways to model storage and they are not interchangeable.',

      'A StorageUnit is a self-contained device: one component with a power rating and an energy '
      + 'capacity, connected to one bus, able to charge and discharge. A battery, a pumped-hydro scheme, '
      + 'a flywheel. Its energy capacity is expressed as `max_hours` — how many hours it could run at '
      + 'full power — so a 20 MW unit with max_hours 1 holds 20 MWh.',

      'A Store is just a tank. It holds energy and has no power rating of its own and no connection to '
      + 'an electrical bus; you wire it up yourself with Links, which set the charge and discharge '
      + 'rates separately. That is more work, and it is what you need when the two rates differ, when '
      + 'the thing being stored is not electricity, or when several converters share one tank — a '
      + 'hydrogen cavern feeding both a turbine and a pipeline, for instance.',

      'Rule of thumb: if it is a battery and it plugs into one bus, use a StorageUnit. Reach for a Store '
      + 'when the storage is a fuel rather than electricity, which is exactly what happens in module 5.',
    ],
    explain: [
      'Nothing to build in this step — it is a decision, and it is worth making deliberately because '
      + 'converting between the two later is real work.',

      'This module uses a StorageUnit. The device is a grid battery, it sits on one electrical bus, and '
      + 'its charge and discharge ratings are the same — which is precisely the case a StorageUnit is '
      + 'built for.',

      'On the Storage step you will see the `storage_units` sheet as the main table, with `stores` '
      + 'available alongside it. Both are optional and both can be empty; you are about to fill the '
      + 'first and leave the second alone.',

      'One consequence of choosing a StorageUnit that matters later: its power rating applies to charging '
      + 'and discharging alike, and `max_hours` ties its energy to that rating. You cannot independently '
      + 'set 20 MW in, 30 MW out and 45 MWh of capacity — that combination needs a Store and two Links.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'Two sheets, one step',
        tab: 'Build',
        note: 'The step carries storage_units and stores together, because they are two answers to the '
          + 'same question. You are filling storage_units and leaving stores empty — an empty optional '
          + 'sheet is not an error.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'storage',
        title: 'The columns to expect',
        tab: 'Build',
        note: 'Scan the headers before you add a row: p_nom, max_hours, efficiency_store, '
          + 'efficiency_dispatch, cyclic_state_of_charge. Those five are the whole physics of a battery, '
          + 'and the next step fills them.',
      },
    ],
    verify: [
      'You can say in one sentence when to use a Store rather than a StorageUnit',
      'You can say how a StorageUnit expresses its energy capacity, and what 20 MW at max_hours 1 holds',
      'You can name one thing a StorageUnit cannot represent',
    ],
    pitfalls: [
      'Reaching for a Store because it sounds more general. It is more general, and it needs two Links '
      + 'and a bus of its own before it does anything. For a battery on an electrical bus that is all '
      + 'cost and no benefit.',
    ],
  },

  {
    id: 'm4-add-the-battery',
    section: SECTION,
    title: 'Add the battery',
    tab: 'Build',
    where: 'Build → Storage step',
    concept: [
      'Five numbers describe a battery well enough to schedule it, and it is worth knowing what each one '
      + 'does before you type it.',

      'Power (`p_nom`) is how fast energy moves, in MW. Energy (`max_hours` × `p_nom`) is how much it '
      + 'holds, in MWh. These are independent choices in reality and the ratio between them is the '
      + 'defining characteristic of a storage technology: a frequency-response battery might be 0.25 '
      + 'hours, a grid battery 1 to 4, a pumped-hydro scheme 8 or more, and a seasonal store hundreds.',

      'Efficiency comes in two halves — what fraction survives going in, and what fraction survives '
      + 'coming out. Their product is the round-trip efficiency, and it is what makes arbitrage cost '
      + 'something. This step sets both to 1 deliberately: a lossless battery first, so the arithmetic '
      + 'is checkable, then the real thing in step 6.',

      'And `cyclic_state_of_charge` decides what happens at the ends of the horizon. With it on, the '
      + 'battery must finish where it started — it cannot begin the run full and coast, or end empty and '
      + 'call that a saving. On a three-hour model that constraint is the difference between an honest '
      + 'answer and a free 20 MWh.',
    ],
    explain: [
      'Build → Storage, "+ Add storage unit", and fill the row with the values below. It goes on bus_2, '
      + 'the demand end — step 8 tests whether that was the right call.',

      'One practical note: `cyclic_state_of_charge` is the last of the eight columns, so you will need to '
      + 'scroll the table sideways to reach it — or use the Columns button above the grid, which lists '
      + 'every column and lets you jump straight to the ones you want. It is a checkbox rather than a '
      + 'number, and it should already be ticked.',

      'Both efficiencies are 1 for now. That is not realistic and you will fix it in step 6; it is here '
      + 'so the first run produces numbers you can verify on paper, which is the habit this course keeps '
      + 'insisting on.',

      'Leave `stores` empty. Leave `marginal_cost` alone too — a battery has no fuel, and giving it a '
      + 'running cost here would confuse the arbitrage you are about to read.',

      'The Storage step should pick up a tick once the row has a name, a bus and a power rating.',
    ],
    spotlights: [
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'storage',
        title: 'Add the row',
        tab: 'Build',
        note: 'Same two-step pattern as every sheet since module 1: create the row, then fill the cells. '
          + 'With eight columns the attribute form on the right is easier than scrolling the table — and it '
          + 'is the only place all of them are visible at once.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'storage',
        title: 'Five numbers',
        tab: 'Build',
        note: 'p_nom and max_hours give power and energy; the two efficiencies give the round trip; '
          + 'cyclic_state_of_charge closes the loop at the ends of the horizon — it is the last column, so '
          + 'scroll right for it. Check bus reads exactly bus_2: a battery on the wrong bus is the mistake '
          + 'step 8 is built around.',
      },
      {
        selector: '.build-step-strip',
        title: 'Storage ticks',
        tab: 'Build',
        note: 'Seven steps ticked now. Storage was the last of the physical components this course '
          + 'needs — everything after module 5 is attributes and constraints on what you have already built.',
      },
    ],
    entries: [
      {
        field: 'storage_units.name',
        label: 'battery name',
        value: 'batt_1',
        why: 'Identifies the unit in results — its charge, discharge, state of charge and revenue all '
          + 'report under this name. It is also the column header if you ever give it a time-varying '
          + 'availability, the same as a generator.',
      },
      {
        field: 'storage_units.bus',
        label: 'which bus it connects to',
        value: 'bus_2',
        why: 'The demand end, next to the expensive plant and on the load side of the congested line. '
          + 'This single cell is worth about a thousand currency units against the alternative — step 8 '
          + 'moves it to bus_1 and measures the difference rather than asserting it.',
      },
      {
        field: 'storage_units.carrier',
        label: 'carrier',
        value: 'AC',
        why: 'What it stores and returns, as far as the network is concerned — electricity. A battery '
          + 'that charged on one carrier and discharged another would be a converter, which is a Link, '
          + 'and that is module 5.',
      },
      {
        field: 'storage_units.p_nom',
        label: 'power rating',
        value: '20',
        unit: 'MW',
        why: 'How fast energy can move, in or out. It caps both directions for a StorageUnit. 20 MW is '
          + 'sized against the 40 MW of demand in the quiet hour — enough to matter, small enough that '
          + 'it cannot single-handedly flatten the problem.',
      },
      {
        field: 'storage_units.max_hours',
        label: 'hours at full power',
        value: '1',
        unit: 'h',
        why: 'Energy capacity, expressed as a duration: 20 MW for 1 hour is 20 MWh. This is the number '
          + 'that decides whether the battery can actually complete the shift you want — step 7 halves it '
          + 'and the whole strategy falls apart, which is the fastest way to see that power and energy are '
          + 'different limits.',
      },
      {
        field: 'storage_units.efficiency_store',
        label: 'charging efficiency',
        value: '1',
        why: 'The fraction of energy drawn from the grid that actually reaches the store. Set to 1 for '
          + 'now so the first answer is hand-checkable — a real battery is nearer 0.95, and step 6 puts '
          + 'that in and measures what it costs.',
      },
      {
        field: 'storage_units.efficiency_dispatch',
        label: 'discharging efficiency',
        value: '1',
        why: 'The fraction of stored energy that reaches the grid on the way out. The two efficiencies '
          + 'multiply to give the round trip, so 1 and 1 means every MWh in comes back out — briefly, and '
          + 'only for teaching.',
      },
      {
        field: 'storage_units.cyclic_state_of_charge',
        label: 'must end as it started',
        value: 'true',
        why: 'Forces the state of charge at the end of the horizon to equal the state at the beginning. '
          + 'Without it the optimiser starts the run with a free full battery and ends empty, which looks '
          + 'like a saving and is really just borrowing 20 MWh from outside the model. On a three-hour '
          + 'horizon that fiction would be most of the answer.',
      },
    ],
    verify: [
      'The `storage_units` sheet has exactly 1 row, and `stores` is still empty',
      '`bus` reads exactly bus_2',
      '`p_nom` is 20 and `max_hours` is 1, so the battery holds 20 MWh',
      'Both efficiencies are 1 and `cyclic_state_of_charge` is true',
      'The Storage step shows a tick',
    ],
    pitfalls: [
      'Putting it on bus_1. That is the experiment for step 8, not the starting point — and running it '
      + 'now would spoil the comparison.',
      'Reading `max_hours` as a duration limit on how long it may run. It is an energy capacity written '
      + 'as a duration: max_hours 1 on a 20 MW unit means 20 MWh, which it could also deliver as 10 MW '
      + 'for two hours.',
      'Leaving `cyclic_state_of_charge` off. The answer will be lower and wrong, because the model will '
      + 'have started with energy nobody paid for.',
    ],
  },

  {
    id: 'm4-run-ideal',
    section: SECTION,
    title: 'Run: the peaker never runs again',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Predict it first. The battery holds 20 MWh, moves at 20 MW, loses nothing, and must end where it '
      + 'started. Prices at bus_2 were 0, 50 and 120.',

      'The obvious play is to charge in hour 1 and discharge in hour 3. Charging 20 MW in hour 1 adds '
      + '20 MW of demand at bus_2, which has to come over the line — and there is room, because the line '
      + 'was carrying 40 of its 60. So bus_2 draws 60: wind gives 54 free and coal makes up 6, at a cost '
      + 'of 120. The 14 MWh module 2 curtailed is now in the battery instead of thrown away.',

      'Hour 2 is unchanged: demand 80, line full at 60, gas covers 20. Cost 1,720.',

      'Hour 3 is where it pays. Demand is 170; the battery returns 20, so only 150 must be generated. '
      + 'The line brings 56 and gas covers 94 — and oil, which used to make 14 MW at 120, makes nothing '
      + 'at all. Cost 1,000 + 4,700 = 5,700 against 7,680 before.',

      'Total 120 + 1,720 + 5,700 = 7,540, against module 3\'s 9,400. And the price in the peak hour '
      + 'falls from 120 to 50, because the marginal unit is no longer the peaker. A battery that holds '
      + '20 MWh removed a 40 MW generator from the answer.',
    ],
    explain: [
      'Validate, then run. Reconcile against 7,540 before reading anything else.',

      'Then look at what happened to oil_1. It is at zero in every snapshot. Nothing retired it and '
      + 'nothing forbade it — 20 MWh of stored energy arriving in the right hour simply made it '
      + 'unnecessary, which is the clearest demonstration in this course of storage and peaking plant '
      + 'being substitutes.',

      'Check the price series at bus_2: 20, 50, 50. The 120 is gone. Storage does not just save fuel, it '
      + 'caps the price, and the two effects are the same thing seen from different sides.',

      'And check curtailment: zero. The 14 MWh that module 2 threw away and module 3 still threw away is '
      + 'now in the battery. That is the answer to the question step 15 of module 2 left open.',
    ],
    spotlights: [
      {
        selector: '.sg-scenario-summary',
        title: 'Same window again',
        runDialog: 'open',
        note: 'Still 3 snapshots at 1h. Every objective in this course is comparable only because this '
          + 'line has not changed since module 1 — check it before every run and the comparisons stay honest.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile 7,540',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Three hours by hand: 120 + 1,720 + 5,700. If it reads 9,400 the battery is contributing '
          + 'nothing — check its bus, its p_nom, and that cyclic_state_of_charge did not end up false.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'And the peak price',
        tab: 'Analytics',
        note: 'MIN · MAX should now read 0 · 50 rather than 0 · 120. The peak price collapsed because the '
          + 'unit that used to set it never runs — the same fact as the fuel saving, read off the price '
          + 'side instead of the cost side.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'The peaker, unused',
        tab: 'Analytics',
        note: 'Oil is still in the stack — it exists, it is available, it is simply never reached. Compare '
          + 'with module 2 step 10, where an unused peaker cost nothing to keep: that is still true, and it '
          + 'is still why this model cannot tell you whether to close it.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'One fewer price-setter',
        tab: 'Analytics',
        note: 'Oil has dropped out of the price-setting table entirely. Three carriers set prices in '
          + 'module 2 and only two do now — storage removed the most expensive one from the margin.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the new storage row and its bus reference — a second or two.',
        'The solve now couples the three snapshots through the battery, so it is a slightly bigger problem. Still instant.',
      ],
      expect: 'An objective of 7,540, oil_1 at zero in every hour, and a peak price of 50 rather than 120.',
    },
    verify: [
      'Analytics → Result shows an objective of 7,540',
      'oil_1 produces nothing in any snapshot',
      'The bus_2 price series reads 20, 50, 50 — no 120 anywhere',
      'Wind curtailment is zero',
      'You can say where the 1,860 saving came from, hour by hour',
    ],
    pitfalls: [
      'An objective of 9,400 means the battery did nothing. Check `p_nom` is not blank and `bus` reads '
      + 'bus_2 — a storage unit with no power rating is a row that changes nothing.',
      'An objective below 7,540 usually means cyclic_state_of_charge is off, so the model started with a '
      + 'free full battery. Check the state of charge in the next step: if it starts high and ends at '
      + 'zero, that is what happened.',
    ],
  },

  {
    id: 'm4-state-of-charge',
    section: SECTION,
    title: 'Reading the state of charge',
    tab: 'Analytics',
    where: 'Analytics → Result → storage state-of-charge chart',
    concept: [
      'The state of charge is the variable that carries information between snapshots, and reading it is '
      + 'how you check that a storage schedule is physically possible rather than merely cheap.',

      'For this run it rises to 20 MWh after hour 1 and is empty at the end. Charging shows as negative '
      + 'power (the battery is a load), discharging as positive (it is a generator). The same device '
      + 'appears on both sides of the balance depending on the hour, which is what makes it different '
      + 'from everything you have built so far.',

      'The middle value may surprise you, and it is worth understanding why. With no losses, hours 2 and '
      + '3 both price at 50 — so it costs exactly the same whether the battery discharges in one, the '
      + 'other, or splits between them. Several schedules are optimal, the objective is 7,540 for all of '
      + 'them, and the solver returns whichever it happens to reach first. That is a DEGENERATE optimum, '
      + 'and it is not a defect: it is the model telling you the choice does not matter.',

      'It matters for how you read results, though. If two runs of the same model give different '
      + 'schedules at the same cost, nothing is wrong — but any conclusion you draw from the schedule '
      + 'rather than the cost is not robust. Add the losses in the next step and the tie breaks, because '
      + 'holding energy stops being free.',

      'The loop closes because you asked it to. Cyclic state of charge forces the end to match the start, '
      + 'so the 20 MWh that came out in hour 3 is exactly the 20 MWh that went in during hour 1. Turn that '
      + 'constraint off and the optimiser will happily begin full — an extra 20 MWh from nowhere, which on '
      + 'a three-hour horizon would be a large fraction of the answer.',

      'On a real 8,760-hour model the same constraint matters far less at the ends and far more in the '
      + 'middle, where the shape of the state-of-charge curve tells you what the storage is actually '
      + 'doing: a daily sawtooth is arbitrage, a slow seasonal arc is something else entirely.',
    ],
    explain: [
      'Nothing to run. The Result dashboard gained a storage state-of-charge chart the moment the run '
      + 'contained storage — it was absent from every previous module because there was nothing to draw.',

      'Read the shape: up in hour 1, then down to empty by the end. Check the arithmetic that is '
      + 'guaranteed — 20 MWh in, 20 MWh out, ends equal — rather than the exact middle, which the '
      + 'concept block above explains is not determined here.',

      'Look at the charge and discharge series too. The battery is a load in hour 1 and a generator in '
      + 'hour 3, and it is the only component in the model that is both.',

      'A sanity check worth forming as a habit: state of charge should never exceed p_nom × max_hours '
      + '(20 MWh here) and never go below zero. If it does, something is wrong with the model rather than '
      + 'interesting about the answer.',
    ],
    spotlights: [
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'State of charge',
        tab: 'Analytics',
        note: 'A chart that did not exist in any earlier module, because the dashboard only builds it when '
          + 'the run contains storage. It fills in hour 1 and is empty by the end — the loop the cyclic '
          + 'constraint closed. How it comes down is not determined while hours 2 and 3 price the same.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Energy served is unchanged',
        tab: 'Analytics',
        note: 'Still 290 MWh. Storage moved energy between hours; it did not create any. Everything this '
          + 'module saves comes from serving the same demand with cheaper hours\' generation.',
      },
    ],
    verify: [
      'The state of charge reaches 20 MWh after hour 1 and is zero at the end',
      'It never exceeds 20 MWh and never goes below zero',
      'The end matches the start, and you can say which setting forced that',
      'You can say why the battery counts as a load in one hour and a generator in another',
      'You can say why the discharge schedule is not uniquely determined in this particular run',
    ],
    pitfalls: [
      'A state of charge that starts high and falls to zero without ever charging. That is the cyclic '
      + 'constraint being off, and the resulting objective is not comparable with anything.',
      'Reading a degenerate schedule as THE answer. When several schedules cost the same, the one you '
      + 'were shown is an arbitrary pick among them — check whether a conclusion survives a re-run '
      + 'before you rely on it.',
      'Reading state of charge in MW. It is energy, in MWh — the stock, not the flow. Charge and '
      + 'discharge are the flows, and they are the ones in MW.',
    ],
  },

  {
    id: 'm4-losses',
    section: SECTION,
    title: 'Make it real — round-trip efficiency',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'No battery returns what it takes. Some of the energy becomes heat going in, some coming out, and '
      + 'the product of the two efficiencies is the round trip. At 0.9 each way that is 0.81 — for every '
      + '10 MWh drawn from the grid, 8.1 come back.',

      'That changes the arbitrage arithmetic in a way worth stating precisely. Storage is only worth '
      + 'running when the price it discharges into is greater than the price it charged at DIVIDED by the '
      + 'round-trip efficiency. At 81% round trip, charging at 20 needs a discharge price above 24.7 '
      + 'before it breaks even.',

      'It also means the battery must draw more than it returns, so a system with storage in it always '
      + 'generates slightly more energy than one without — for the same demand served. Storage is a '
      + 'consumer of energy and a producer of value, and confusing the two produces some very strange '
      + 'claims about efficiency.',

      'Real numbers: lithium-ion grid batteries are around 0.92 to 0.95 each way, pumped hydro nearer '
      + '0.87, hydrogen round-trips at 0.35 to 0.45 and is only worth it when the alternative is '
      + 'curtailment or a very long duration.',
    ],
    explain: [
      'Build → Storage. Change both efficiencies from 1 to 0.9 and re-run. Two cells.',

      'The objective goes from 7,540 to 7,730 — losses cost 190 over three hours. The strategy does not '
      + 'change: charge in the cheap hour, discharge in the expensive one, oil still never runs. Losses '
      + 'made it slightly worse, not different.',

      'Look at the state of charge now: 18 rather than 20 after hour 1. The battery drew 20 MW from the '
      + 'grid and only 18 MWh reached the store, because 10% was lost on the way in. Coming out, 18 MWh '
      + 'of stored energy delivers 16.2 to the grid.',

      'You will also see the battery discharge a little in hour 2 as well as hour 3. That is the '
      + 'optimiser doing something subtler than the story you predicted: with losses, holding energy has '
      + 'an opportunity cost, and spreading the discharge slightly beats saving it all for the peak. Not '
      + 'a mistake — a reminder that once losses are in, the schedule stops being obvious. This is the '
      + 'last module where hand-checking is realistic, and this is the step where it starts to strain.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'Two cells',
        tab: 'Build',
        note: 'efficiency_store and efficiency_dispatch, both from 1 to 0.9. Nothing else changes, so the '
          + 'difference in the answer is attributable to losses alone — the same controlled-experiment '
          + 'discipline as module 3\'s line uprate.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '7,730',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Up from 7,540. Losses cost 190 over three hours — about 10% of what the battery was '
          + 'saving, which is roughly what a 19% round-trip loss on a 20 MWh cycle should cost.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: '18, not 20',
        tab: 'Analytics',
        note: 'The battery drew 20 MW for an hour and 18 MWh arrived. The missing 2 MWh is the charging '
          + 'loss, and it is why a storage schedule always draws more than it returns.',
      },
    ],
    entries: [
      {
        field: 'storage_units.efficiency_store',
        label: 'charging efficiency',
        value: '0.9',
        why: 'Nine tenths of what is drawn from the grid reaches the store. Slightly pessimistic for a '
          + 'modern lithium-ion battery — 0.95 is typical — and chosen here because a round number makes '
          + 'the loss visible in the state of charge at a glance.',
      },
      {
        field: 'storage_units.efficiency_dispatch',
        label: 'discharging efficiency',
        value: '0.9',
        why: 'Nine tenths of what leaves the store reaches the grid. Together with the charging '
          + 'efficiency this gives a round trip of 0.81, which sets the price ratio the battery needs '
          + 'before a cycle is worth doing at all: discharge price above charge price divided by 0.81.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: [
        'One solve. Validation is optional here — you changed two numbers, not a reference.',
      ],
      expect: 'An objective of 7,730 — 190 more than the lossless battery, with the same overall strategy.',
    },
    verify: [
      'The objective is 7,730',
      'The state of charge peaks at 18 MWh rather than 20',
      'oil_1 still produces nothing, and the peak price is still 50',
      'You can state the price ratio a battery needs before a cycle is worth running',
      'You can say why a system with storage generates more energy than one without, for the same demand',
    ],
    pitfalls: [
      'Expecting the strategy to change. Losses made arbitrage more expensive, not pointless — the '
      + 'spread from 20 to 50 is far wider than the 24.7 break-even, so the battery still cycles.',
      'Setting the efficiencies above 1. The model will happily solve and will create energy from '
      + 'nothing, which is exactly the kind of error a validation pass cannot catch for you.',
    ],
  },

  {
    id: 'm4-energy-vs-power',
    section: SECTION,
    title: 'Energy and power are different limits',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'A battery has two sizes and they bind in different situations. Power decides how much it can do in '
      + 'any single hour; energy decides how much it can do in total before it needs refilling.',

      'So far power has been the binding limit: 20 MW was the most it could charge, and it had more than '
      + 'enough energy capacity to absorb an hour of that. Halve the energy — max_hours from 1 to 0.5, so '
      + '10 MWh — and the roles swap. The battery can still move 20 MW for an instant but can no longer '
      + 'sustain it for the hour, so it charges only about 11 MW and delivers only 9.',

      'The consequences cascade. Wind curtailment comes back, because there is no longer room for all the '
      + 'surplus. Oil returns to the answer at 5 MW in the peak hour. And the peak price jumps back to '
      + '120, because the peaker is once again the marginal unit. Objective 8,320 against 7,730.',

      'That is why storage is always quoted as two numbers, and why "100 MW of storage" is not a '
      + 'specification. A 100 MW / 15-minute battery and a 100 MW / 8-hour battery do completely '
      + 'different jobs, and only one of them can replace a peaking plant.',
    ],
    explain: [
      'Build → Storage. Change `max_hours` from 1 to 0.5 — the power rating stays at 20 MW, so the '
      + 'battery now holds 10 MWh instead of 20. Run it.',

      'Read the objective: 8,320. Then check the three things that came back: curtailment is non-zero '
      + 'again, oil_1 produces in the peak hour, and the price series at bus_2 ends at 120 rather than 50.',

      'Look at the state of charge: it peaks at 10, which is the new capacity. The battery is full and '
      + 'still cannot help — that is an energy-limited machine, and no amount of extra power rating would '
      + 'fix it.',

      'Now set `max_hours` back to 1 and re-run to confirm you are back at 7,730. That is the state the '
      + 'module ends in and the one module 5 starts from.',

      'Worth noticing before you move on: going the other way, from 1 hour to 2, would have changed '
      + 'nothing at all — the battery never used more than 20 MWh. Past the point where a limit stops '
      + 'binding, more of it is worth nothing, exactly as with module 3\'s line.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'One cell, twice',
        tab: 'Build',
        note: 'max_hours from 1 to 0.5, run, then back to 1 and run again. The second run matters: the '
          + 'module ends at 7,730 and module 5 assumes it.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '8,320',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Halving the energy cost 590 — far more than the 190 the losses cost. Duration was the more '
          + 'valuable half of this battery, which is not what most people guess.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The 120 is back',
        tab: 'Analytics',
        note: 'MIN · MAX returns to 0 · 120. An energy-limited battery cannot cap the peak price, because '
          + 'it runs out before the peak hour is over — which is precisely the failure mode short-duration '
          + 'storage has in real systems.',
      },
    ],
    entries: [
      {
        field: 'storage_units.max_hours (the experiment)',
        label: 'hours at full power, halved',
        value: '0.5',
        unit: 'h',
        why: '10 MWh instead of 20, with the power rating untouched. It makes energy rather than power '
          + 'the binding limit, which brings curtailment, the peaker and the 120 price all back at once — '
          + 'the fastest demonstration that the two ratings do different jobs.',
      },
      {
        field: 'storage_units.max_hours (restore)',
        label: 'hours at full power, back',
        value: '1',
        unit: 'h',
        why: 'Returns the model to 7,730, which is the state module 5 starts from. Leaving it at 0.5 '
          + 'would quietly hand the next module a worse battery and a different baseline.',
      },
    ],
    verify: [
      'At max_hours 0.5 the objective is 8,320',
      'Curtailment is non-zero again and oil_1 produces in the peak hour',
      'The peak price is back to 120',
      'The state of charge peaks at 10 MWh — the battery is full and still cannot help',
      'After restoring max_hours to 1, the objective is 7,730 again',
    ],
    pitfalls: [
      'Concluding the battery is too small. It is too SHORT — its power rating was never the problem, '
      + 'and adding MW would not have helped at all.',
      'Forgetting the second run. The module ends at 7,730; module 5\'s prebuilt checkpoint assumes it, '
      + 'and a learner carrying a half-size battery forward will not match any number in it.',
    ],
  },

  {
    id: 'm4-placement',
    section: SECTION,
    title: 'Where you put it matters as much as how big it is',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'Module 3 ended by saying that once there is a constraint in the network, WHERE storage sits '
      + 'matters. This step measures it.',

      'Move the identical battery from bus_2 to bus_1 — the generation end, behind the congested line — '
      + 'and re-run. Nothing else changes: same 20 MW, same 20 MWh, same 90% each way, same demand.',

      'The answer is 8,773 against 7,730. The same battery is worth 627 at bus_1 and 1,670 at bus_2: '
      + 'roughly a third as much, purely from which side of the wire it sits on.',

      'The reason is that a battery helps by being able to deliver energy WHERE and WHEN it is needed. '
      + 'At bus_1 it can soak up surplus wind easily enough, but in the peak hour it has to push its '
      + 'energy through the same line that is already the constraint — so it cannot displace the peaker. '
      + 'At bus_2 it discharges directly into the demand, behind no wires at all.',

      'This generalises well beyond batteries and it is one of the most practically useful things in the '
      + 'course: in a constrained network, the value of any asset depends on where it is, and a model '
      + 'without a network cannot tell you. Siting studies exist for exactly this reason.',
    ],
    explain: [
      'Build → Storage, change `bus` from bus_2 to bus_1, and run. One cell.',

      'Read the objective: 8,773. Then put it back to bus_2 and re-run to return to 7,730 — the module '
      + 'ends there.',

      'While you are on the bus_1 run, look at the price series: bus_2 still peaks at 120. The peaker is '
      + 'back, because the battery cannot reach the demand when it matters. Compare that against the '
      + 'bus_2 placement, where the 120 disappeared entirely.',

      'Also look at the line flow in the peak hour. With storage at bus_1 the line runs at its full 60 '
      + 'MW in hour 3 instead of 56 — the battery filled the last of the headroom and then had nowhere '
      + 'else to go. That is what "behind the constraint" looks like in the data.',

      'Then compare the two runs properly in Analytics → Comparison rather than from memory. Two runs '
      + 'that differ in one cell is the cleanest kind of experiment there is, and it is worth practising '
      + 'the habit on a case this small.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'One cell again',
        tab: 'Build',
        note: 'bus from bus_2 to bus_1, run, then back to bus_2 and run again. The battery is byte-for-byte '
          + 'identical in both runs — only its address changes.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '8,773 against 7,730',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The same battery, worth 1,670 at the demand end and 627 behind the constraint. Nothing '
          + 'about the device changed; the network decided its value.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Two runs, one cell apart',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both runs are in History. Comparing them here rather than remembering the first is the '
          + 'habit worth forming — on a real model you will run dozens and remember none of them accurately.',
      },
    ],
    entries: [
      {
        field: 'storage_units.bus (the experiment)',
        label: 'moved behind the constraint',
        value: 'bus_1',
        why: 'The generation end. The battery can still charge from surplus wind, but its energy has to '
          + 'cross the congested line to reach the demand — so in the peak hour it cannot displace the '
          + 'peaker, and the 120 price returns.',
      },
      {
        field: 'storage_units.bus (restore)',
        label: 'back to the demand end',
        value: 'bus_2',
        why: 'Returns the model to 7,730, the state this module ends in and the one module 5 starts from. '
          + 'It is also the right answer on the merits: at the demand end the battery discharges behind no '
          + 'constraint at all.',
      },
    ],
    verify: [
      'At bus_1 the objective is 8,773; at bus_2 it is 7,730',
      'With the battery at bus_1, the bus_2 price still peaks at 120 and oil_1 runs again',
      'With the battery at bus_1, the line is fully loaded in the peak hour rather than at 56 MW',
      'You can explain the difference in terms of what the battery can reach and when',
      '`bus` is back to bus_2 before you move on',
    ],
    pitfalls: [
      'Concluding that storage always belongs at the demand end. It belongs where the constraint is not, '
      + 'which in this network is the demand end — in a system whose constraint is elsewhere the answer '
      + 'flips, and the only way to know is to model it.',
      'Comparing against remembered numbers. Use Analytics → Comparison; both runs are stored, and the '
      + 'whole point of a controlled experiment is lost if the baseline is approximate.',
    ],
  },

  {
    id: 'm4-what-changed',
    section: SECTION,
    title: 'What module 4 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'Storage couples hours. It is the first component whose state in one snapshot constrains the next, '
      + 'and its presence turns a set of independent hourly balances into a single scheduling problem. '
      + 'The state of charge is the variable carrying that link, and cyclic operation is what stops the '
      + 'model borrowing energy from outside the horizon.',

      'Power and energy are separate limits, and they fail differently. A battery short of power cannot '
      + 'act fast enough; one short of energy cannot act for long enough. Halving the duration here cost '
      + 'three times what the round-trip losses cost, which is not the intuition most people start with.',

      'Storage and peaking plant are substitutes. 20 MWh in the right place removed a 40 MW oil unit from '
      + 'the answer entirely and took the peak price from 120 to 50 — and put it in the wrong place and '
      + 'it did neither.',

      'And location is value. The same asset was worth roughly three times as much on one side of a '
      + 'constraint as the other. No single-bus model can produce that result, which is a reason to build '
      + 'the network before drawing conclusions about what to buy.',
    ],
    explain: [
      'Three limits to name, each a later module.',

      'Three hours is not a storage horizon. A daily cycle needs a day, a weekly pattern needs a week, '
      + 'and a seasonal store needs the whole year — and the cyclic constraint that is a reasonable '
      + 'assumption over 8,760 hours is doing a lot of work over three. Module 7 is about time itself: '
      + 'resolution, representative periods, and how to run a year without waiting all afternoon.',

      'The battery is still free. It cost nothing to have, so the model will always use it and can never '
      + 'tell you whether it was worth building — the same gap module 2 found with the peaker. Module 6 '
      + 'adds capital costs and lets the model choose the size and the site itself, which is the proper '
      + 'answer to the question this module answered by hand.',

      'And everything here is still electricity. The battery stores the same carrier it returns. Module 5 '
      + 'breaks that assumption: a bus that carries gas, a Link that converts one carrier into another, '
      + 'and a Store that holds fuel rather than power.',

      'Export the project before you go — Model → Export project.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: '7,730 to serve the same 290 MWh of demand that cost 12,000 in module 1 and 9,400 in module '
          + '3. Note DISPATCH reads 294, not 290: the extra 4 MWh is the round-trip loss from step 6, and '
          + 'the gap between energy generated and demand served is the clearest sign there is storage in a '
          + 'model. Demand has not changed once in four modules — every saving came from better choices.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'The chart that only exists now',
        tab: 'Analytics',
        note: 'It appeared the moment the model contained storage and will disappear again if you remove '
          + 'it. The dashboard is built from what the run actually produced, which is worth remembering '
          + 'when a card you expected is missing.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. Module 5 ships this model as a checkpoint, but a file you saved '
          + 'yourself is the one you will trust when the two disagree.',
      },
    ],
    verify: [
      'You can explain why storage is the first component that couples snapshots',
      'You can say which of power and energy was binding in each of this module\'s runs',
      'You can say what a battery and a peaking plant have in common, and what this model cannot say about choosing between them',
      'You can say why the same battery was worth three times as much at one bus as the other',
      'The model reads 7,730 with the battery at bus_2, 20 MW, 1 hour, 0.9 each way',
      'You have exported the project',
    ],
    pitfalls: [
      'Generalising the three-hour result. A battery that looks valuable across three chosen hours may '
      + 'be worth very little across 8,760 real ones, and the cyclic constraint is doing far more work '
      + 'on a short horizon than a long one.',
      'Reading 1,670 as the value of storage. It is the value of THIS battery, in THIS network, over '
      + 'three hours, with no capital cost anywhere. Every one of those qualifiers matters, and module 6 '
      + 'removes the last of them.',
    ],
  },
];
