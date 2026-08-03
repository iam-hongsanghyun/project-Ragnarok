/**
 * Module 8 — Policy instruments (12 steps).
 *
 * The emission factors were typed in module 1 and have not changed an answer
 * since. `carriers.co2_emissions` has sat in the sheet for seven modules doing
 * nothing, because nothing in the model ever cared what a fuel emitted. This is
 * where it starts to.
 *
 * Built on module 7's year with expansion. Every figure verified against a real
 * HiGHS solve through the app's own build path, at a 5% discount rate:
 *
 *   no policy         272,288 tCO2   coal 316 GWh   wind 150  solar  24  batt 20
 *   cap 150,000 t     150,000 tCO2   coal 172 GWh   wind 179  solar  44  batt 20
 *   price 3.46/t      150,093 tCO2   coal 172 GWh   wind 179  solar  44  batt 20
 *   price 100/t         4,376 tCO2   coal   0 GWh   wind 203  solar 133  batt 82
 *
 * The middle two rows are the module. A cap of 150,000 tonnes has a shadow price
 * of 3.46, and setting a carbon price to 3.46 reproduces the capped system to
 * three significant figures — the same capacities, the same coal, the same
 * emissions. A price and a quantity limit are duals, and seeing that as an
 * experiment rather than a claim is worth more than any amount of theory.
 *
 * The last row carries the other lesson. A price of 100 removes coal entirely,
 * cuts emissions 98%, and — for the first time in the course — makes the battery
 * worth building, from 20 MW to 82. Module 7 declined more storage; a carbon
 * price changes what flexibility is worth.
 */
import { TutorialStep } from '../types';

const SECTION = '8 · Policy instruments';

export const MODULE_8_POLICY: TutorialStep[] = [
  {
    id: 'm8-price-or-constraint',
    section: SECTION,
    title: 'Policy is either a price or a limit',
    tab: 'Market',
    where: 'Market & Policy → Carbon price',
    startOptions: {
      prebuiltExampleId: 'training_m7',
      completeExampleId: 'training_m7',
      note:
        'Module 8 works on module 7\'s model — a full year, four extendable assets, answering 18,115,684 '
        + 'with 272,288 tonnes of CO2. Nothing is added to the model here: policy is applied as run '
        + 'settings and one constraint row, so the same checkpoint serves as both the start and the end.',
    },
    concept: [
      'Almost every climate policy a model can represent is one of two things. A PRICE puts a cost on '
      + 'each tonne emitted and lets the quantity fall out. A LIMIT caps the quantity and lets the cost '
      + 'fall out. Everything else — trading schemes, offsets, technology mandates — is a variation on '
      + 'one of those or a combination of both.',

      'In a model the difference is where the policy lands. A price is added to the marginal cost of '
      + 'anything that emits, so it changes the merit order and the optimiser responds. A limit is a '
      + 'constraint over the whole system, so the optimiser must satisfy it and reports what it cost.',

      'They are duals of each other, and this module proves it rather than asserting it: a cap has a '
      + 'shadow price, and setting a carbon price to that number reproduces the capped system exactly. '
      + 'Which is not a curiosity — it is the reason economists say a carbon tax and a cap-and-trade '
      + 'scheme are the same instrument seen from two sides.',

      'What differs is what you are certain about. A cap gives certainty of quantity and leaves the cost '
      + 'to the market. A price gives certainty of cost and leaves the quantity to the market. Since you '
      + 'never know the abatement cost curve in advance, that choice is the whole policy design question '
      + 'and step 9 comes back to it.',
    ],
    explain: [
      'The carbon numbers have been in the model since module 1 and have never done anything. '
      + '`carriers.co2_emissions` reads 0.34 for coal, 0.2 for gas, 0.27 for oil, zero for wind, solar '
      + 'and hydro — typed in modules 1, 2 and 5 with a note each time that it would matter later.',

      'That is deliberate, and worth noticing as a modelling habit: describe the system fully even where '
      + 'the current question does not need it, because the next question usually will. A model where '
      + 'emission factors were left blank would need every carrier row revisited before it could answer '
      + 'anything about policy.',

      'Nothing to change in this step. Run the model once as it stands so you have the no-policy baseline '
      + 'in History — 18,115,684, and 272,288 tonnes — because every comparison in this module is against '
      + 'it and you will want it side by side rather than remembered.',

      'One caution before you start. This module changes what the model BUILDS as well as how it runs, '
      + 'because module 7 left four assets extendable. That is deliberate — the interesting effects of '
      + 'carbon policy are mostly investment effects — but it does mean each run takes about a minute.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'Seven carriers, and the column that has been waiting',
        tab: 'Build',
        note: 'co2_emissions: coal 0.34, oil 0.27, gas 0.2, and zero for wind, solar and hydro. Typed in '
          + 'module 1 and untouched since, because until now nothing in the model cared what a fuel emitted.',
      },
      {
        selector: '[data-card="emissions-breakdown"]',
        title: 'The baseline emissions',
        tab: 'Analytics',
        note: '272,288 tonnes, and almost all of it coal. Note how lopsided it is — the CCGT contributes '
          + 'about 3,400 tonnes against coal\'s 269,000, because coal is cheap and runs constantly while '
          + 'the gas plant barely runs at all.',
      },
    ],
    verify: [
      'The baseline run is in History at 18,115,684 with 272,288 tonnes',
      'You can say what distinguishes a price instrument from a quantity instrument',
      'You can say which of cost and quantity each one leaves uncertain',
      'You can find `co2_emissions` in the carriers sheet and read the four non-zero values',
    ],
    pitfalls: [
      'Expecting policy to be a new component. It is a run setting and, for a cap, a single constraint '
      + 'row — the model itself barely changes.',
      'Forgetting the assets are still extendable. Most of what carbon policy does in this module is '
      + 'change what gets BUILT, not just what runs.',
    ],
  },

  {
    id: 'm8-the-arithmetic',
    section: SECTION,
    title: 'What a tonne of CO2 costs a generator',
    tab: 'Build',
    where: 'Build → Carriers and Generators',
    concept: [
      'A carbon price is charged per tonne emitted, but a generator is dispatched on cost per MWh of '
      + 'ELECTRICITY. Converting between them is where the efficiency finally earns its place.',

      'Coal has an emission factor of 0.34 tonnes per MWh of FUEL and an efficiency of 0.4, so producing '
      + 'one MWh of electricity burns 2.5 MWh of fuel and emits 0.85 tonnes. Gas through the CCGT is 0.2 '
      + 'per MWh of fuel at 50% efficiency, so 0.4 tonnes per MWh of electricity.',

      'Coal is therefore more than twice as carbon-intensive per unit of useful output — worse than the '
      + 'raw factors suggest, because it is also less efficient. That compounding is why efficiency and '
      + 'emission factor must be kept separate in a model rather than merged into one number.',

      'Now the merit order. Coal costs 20 per MWh plus 0.85 times the carbon price; the CCGT costs 50 '
      + 'plus 0.40 times it. They are equal when 20 + 0.85p = 50 + 0.40p, which is p = 66.67 per tonne. '
      + 'Below that coal runs first; above it, gas does.',
    ],
    explain: [
      'Nothing to enter. Do the arithmetic, because a number you derived is worth more than one you were '
      + 'given, and this one is the hinge of the whole module.',

      'Work out coal at 0.85 and gas at 0.40 tonnes per MWh of electricity, then solve for the price at '
      + 'which their costs cross. You should get 66.67.',

      'That number is a prediction. Below it a carbon price makes electricity more expensive without '
      + 'changing which plant runs — it is purely a transfer. Above it the merit order flips and the '
      + 'system physically changes. Policies that sit below a switching point raise bills and abate '
      + 'nothing, which is a real and common failure.',

      'Keep one caution in mind, and step 10 returns to it: this arithmetic assumes the only response is '
      + 'switching between EXISTING plant. This model can also build, and building turns out to be a much '
      + 'cheaper way to abate — so the actual switching point matters far less than it looks here.',
    ],
    spotlights: [
      {
        selector: '.tables-grid-wrap',
        buildStep: 'carriers',
        title: 'Factors are per MWh of FUEL',
        tab: 'Build',
        note: 'Not per MWh of electricity. The generator\'s efficiency converts between them, which is why '
          + 'a 40%-efficient coal unit emits 0.85 t/MWh_e from a 0.34 t/MWh_th factor.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Where the efficiency lives',
        tab: 'Build',
        note: 'coal_1 at 0.4 and the CCGT link at 0.5. Two numbers on two different sheets combine to give '
          + 'the carbon intensity of a MWh — which is why neither sheet alone tells you how dirty a plant is.',
      },
    ],
    verify: [
      'You can compute 0.85 tCO2 per MWh of electricity for coal, and say where both inputs come from',
      'You can compute 0.40 for the CCGT',
      'You can derive the 66.67 switching price yourself',
      'You can say what a carbon price below a switching point achieves',
    ],
    pitfalls: [
      'Comparing emission factors without efficiencies. Coal looks 1.7 times gas on the raw factors and '
      + 'is more than twice as intensive per MWh delivered.',
      'Assuming the switching price is the whole story. It only covers switching between plant that '
      + 'exists — and this model can build.',
    ],
  },

  {
    id: 'm8-apply-a-price',
    section: SECTION,
    title: 'Apply a carbon price of 100',
    tab: 'Analytics',
    where: 'Market & Policy → Carbon price, then run',
    concept: [
      'A hundred per tonne is comfortably above the 66.67 switching point, so the arithmetic says coal '
      + 'should give way to gas. Watch how much more than that happens.',

      'The carbon price enters as an addition to marginal cost, computed per generator from its carrier '
      + 'factor and its efficiency. Nothing else about the model changes: the same demand, the same '
      + 'network, the same capital costs, the same discount rate.',

      'Predict before you run. Coal at 20 + 85 = 105 per MWh is now the most expensive thermal plant in '
      + 'the fleet, above the CCGT at 90 and only just below the oil peaker at 148. Something has to '
      + 'replace 316 GWh of it.',
    ],
    explain: [
      'Market & Policy → Carbon price. Set the scalar price to 100 and run. About a minute.',

      'The section also offers a year-indexed schedule and a library of published scenarios, which is what '
      + 'you would use for a real study — carbon prices are rarely flat, and a pathway model wants a '
      + 'trajectory rather than a number. A single scalar is right for this module because it keeps the '
      + 'comparison clean.',

      'Read the objective, the emissions and the four capacities. Then read them again, because the size '
      + 'of the response is the point.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Market & Policy"]',
        title: 'Carbon price',
        note: 'A scalar price, a year-indexed schedule, and a searchable library of published scenarios. '
          + 'The scalar is enough here; a real pathway study wants the trajectory.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'The summary reports it',
        runDialog: 'open',
        note: 'The planning summary names the carbon price the run will use. Worth checking, because a '
          + 'price left over from a previous experiment is invisible in the model itself.',
      },
    ],
    entries: [
      {
        field: 'Market & Policy → Carbon price',
        value: '100',
        unit: 'currency per tonne CO2',
        why: 'Well above the 66.67 switching point, so the merit order must flip. Roughly the level of '
          + 'the EU ETS in the mid-2020s, and high enough that the response is investment rather than '
          + 'just fuel switching — which is what makes the next step interesting.',
      },
    ],
    verify: [
      'The planning summary reports a carbon price of 100',
      'The run completes and lands in History alongside the baseline',
      'You predicted coal\'s new marginal cost as 105 per MWh before looking',
    ],
    pitfalls: [
      'Leaving a carbon price set from a previous run. It is a scenario setting and does not appear '
      + 'anywhere in the model sheets, so the planning summary is the only place it is visible.',
      'Expecting a proportional response. A price below every switching point does almost nothing; a '
      + 'price above several does a great deal. The response is a staircase, not a slope.',
    ],
  },

  {
    id: 'm8-read-the-price',
    section: SECTION,
    title: 'Coal disappears — and the battery finally gets built',
    tab: 'Analytics',
    where: 'Analytics → Result',
    concept: [
      'Emissions fall from 272,288 tonnes to 4,376 — a 98% cut. Coal generation goes from 316 GWh to '
      + 'zero. Not reduced: gone.',

      'And the fleet is different. Wind rises from 150 to 203 MW, solar from 24 to 133 — more than five '
      + 'times as much — and the battery from 20 to 82 MW.',

      'That battery is worth stopping on. Module 7 offered exactly the same battery at exactly the same '
      + 'cost and the model declined it, taking not one MW above the 20 that already existed. A carbon '
      + 'price has now made 62 MW of it worth building, and nothing about the battery changed.',

      'What changed is what flexibility is FOR. In module 7 the system had cheap coal to lean on whenever '
      + 'wind and solar were short, so storage competed against coal and lost. Price the coal out and the '
      + 'shortfall has to be covered by moving renewable energy through time instead — which is what a '
      + 'battery does. Carbon policy is a storage policy, indirectly, and this is the cleanest '
      + 'demonstration of it this course can give.',

      'The objective rises from 18,115,684 to 21,330,678. Some of that is real resource cost — more '
      + 'capital, less cheap coal — and some is the carbon payment itself, which is a transfer from '
      + 'consumers to whoever collects it rather than a cost to society. Distinguishing the two is step 11.',
    ],
    explain: [
      'Read the emissions first, from the emissions breakdown card. 4,376 tonnes, all of it the CCGT, '
      + 'which still runs a little because 21.9 GWh of gas is cheaper than the alternative even at 100 '
      + 'per tonne.',

      'Then the expansion card. Compare the four capacities against module 7\'s run side by side in '
      + 'Analytics → Comparison; the solar and battery numbers are the ones that should surprise you.',

      'Then ask what it cost. 3.2 million more per year for 268,000 tonnes avoided is about 12 per tonne '
      + 'on average — far below the 100 per tonne price that caused it. That gap is normal and important: '
      + 'a price of 100 does not mean abatement costs 100, it means the last tonne abated costs up to '
      + '100 and everything before it cost less.',

      'Finally, notice what did not change: demand. Nobody used less electricity. Every tonne came from '
      + 'changing how it was produced, because this model has no demand response — which module 9 lists '
      + 'among the things it cannot see.',
    ],
    spotlights: [
      {
        selector: '[data-card="emissions-breakdown"]',
        title: '4,376 tonnes',
        tab: 'Analytics',
        note: 'Down from 272,288 — a 98% cut, and all that remains is the CCGT. Coal has left the answer '
          + 'entirely rather than being reduced.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The battery, at last',
        tab: 'Analytics',
        note: '82 MW against module 7\'s 20. The same battery at the same cost was declined one module '
          + 'ago; pricing coal out is what made flexibility worth paying for.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'A different fleet',
        tab: 'Analytics',
        note: 'Solar more than five times larger, wind a third larger, coal at zero output. The carbon '
          + 'price did not tune this system — it replaced it.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Against the baseline',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both runs are in History. Read the capacities side by side rather than from memory — the '
          + 'solar and storage changes are the ones worth being precise about.',
      },
    ],
    verify: [
      'Emissions are 4,376 tonnes and coal generates nothing',
      'Wind is about 203 MW, solar about 133 and the battery about 82',
      'You can say why the battery became worth building when nothing about it changed',
      'You can compute the average cost per tonne abated and say why it is far below 100',
      'You can say what did NOT change about demand, and why',
    ],
    pitfalls: [
      'Reading the average abatement cost as the carbon price. The price sets the margin; almost all '
      + 'abatement costs less than the price that triggered it.',
      'Treating the whole objective increase as a cost to society. Much of it is the carbon payment, '
      + 'which is a transfer — step 11 separates them.',
    ],
  },

  {
    id: 'm8-a-cap',
    section: SECTION,
    title: 'The other instrument — an emissions cap',
    tab: 'Market',
    where: 'Market & Policy → Advanced Constraints',
    concept: [
      'A cap does not price anything. It states that total emissions must not exceed a number, and lets '
      + 'the optimiser find the cheapest way to comply.',

      'Ragnarok offers two routes and they are not equivalent for our purposes. The `global_constraints` '
      + 'sheet — reachable from Build → Constraints or Market & Policy → Standard Constraints — writes a native '
      + 'PyPSA global constraint, which is the conventional way to express a cap. The Advanced '
      + 'Constraints box takes a small constraint language instead: `emissions <= 150000` is a complete '
      + 'and valid line.',

      'Use the constraint language here, for one specific reason: Ragnarok reports the SHADOW PRICE of '
      + 'constraints written this way and not of native PyPSA ones. Since the next two steps are entirely '
      + 'about reading that shadow price, the route that surfaces it is the one to learn. It is worth '
      + 'knowing as a property of the tool — a cap written the other way solves identically and tells you '
      + 'nothing about what it cost.',

      'The cap you are about to set is 150,000 tonnes — a 45% cut from the 272,288 baseline, which is a '
      + 'plausible national target for a decade out. Deliberately not near-zero, because the interesting '
      + 'question is what a moderate cap costs.',
    ],
    explain: [
      'First set the carbon price back to 0. A price and a cap together is a different experiment, and '
      + 'step 10 does it deliberately — for now you want the cap alone.',

      'Market & Policy → Advanced Constraints. In the DSL box type a single line: `emissions <= 150000`.',

      'Open the "DSL cheatsheet" disclosure above the box while you are there. `emissions(carrier)` '
      + 'limits one fuel, '
      + '`gen` and `cap` limit energy and capacity, `cf` limits a capacity factor, and constraints can be '
      + 'combined — `emissions <= 0.4 * gen` is an intensity target rather than an absolute one, which is '
      + 'how many real policies are written.',

      'Then run. The cap should bind exactly — the model will emit 150,000 tonnes, not less, because '
      + 'emitting less costs more and nothing rewards it.',

      'Predict the cost first. The carbon price of 100 cut emissions 98% for 3.2 million a year. This cap '
      + 'asks for 45%, so the cost should be much lower than half of that — abatement gets more expensive '
      + 'as you do more of it, so the first half is far cheaper than the second.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Market & Policy"]',
        title: 'Advanced Constraints',
        note: 'Market & Policy holds the whole policy layer: Carbon price, Standard Constraints — which edits the '
          + 'global_constraints table — and Advanced '
          + 'Constraints takes the constraint language. Both cap emissions; only the second reports what '
          + 'the cap cost.',
      },
      {
        selector: '[data-build-step="constraints"]',
        buildStep: 'constraints',
        title: 'The other route',
        tab: 'Build',
        note: 'The Build strip has carried a Constraints step since module 1 and this course has never '
          + 'filled it. It edits the same global_constraints sheet as Market & Policy → Standard Constraints — '
          + 'the conventional route, and the one whose shadow price is not surfaced.',
      },
    ],
    entries: [
      {
        field: 'Market & Policy → Carbon price (reset first)',
        value: '0',
        why: 'A price and a cap at the same time is a different experiment — and a common real-world one, '
          + 'which step 10 runs deliberately. Comparing the cap against the baseline needs the price off.',
      },
      {
        field: 'Market & Policy → Advanced Constraints → DSL box',
        value: 'emissions <= 150000',
        why: 'A complete emissions cap in one line. `emissions` accumulates every carrier\'s '
          + 'co2_emissions factor over the fuel burnt — the column typed in module 1 and unused until '
          + 'now. 150,000 tonnes is a 45% cut from the 272,288 baseline: a plausible national target, and '
          + 'deliberately not near-zero, because what a MODERATE cap costs is the more commonly asked '
          + 'question. Written this way rather than as a global_constraints row because Ragnarok reports '
          + 'the shadow price of DSL constraints and not of native PyPSA ones.',
      },
    ],
    verify: [
      'The carbon price is back to 0',
      'The DSL box holds one line reading `emissions <= 150000` with no error beneath it',
      'You can write a line that caps emissions per MWh rather than in total',
      'You can say why this route was chosen over the global_constraints sheet',
    ],
    pitfalls: [
      'Leaving the carbon price at 100. The cap would then be slack — emissions are already 4,376 — and '
      + 'the run would tell you nothing.',
      'Setting the cap above the baseline. A non-binding constraint changes nothing and reports no shadow '
      + 'price, which looks like a broken model rather than a slack limit.',
      'Writing the cap in the global_constraints sheet and then looking for its shadow price. It solves '
      + 'correctly and the dual is never reported — which is exactly why this step uses the DSL.',
    ],
  },

  {
    id: 'm8-cap-shadow-price',
    section: SECTION,
    title: 'The cap binds, and its shadow price is a carbon price',
    tab: 'Market',
    where: 'Analytics → Result, then Market & Policy → Advanced Constraints',
    concept: [
      'The cap binds exactly: emissions are 150,000 tonnes. The objective rises from 18,115,684 to '
      + '18,349,092 — 233,408 a year to cut emissions by 45%.',

      'And the constraint has a shadow price of about 3.46 per tonne — reported as λ −3.46, because a '
      + 'less-than-or-equal constraint carries a negative dual by convention: relaxing it by a unit '
      + 'REDUCES the objective. Read the magnitude and let the sign tell you the direction. It is the same '
      + 'kind of number as the electricity prices in module 2 — the cost of tightening the constraint by '
      + 'one more unit.',

      'It is also, exactly, the carbon price that would produce this outcome without any cap at all. A '
      + 'constraint has a price and a price has a quantity; they are two ways of writing the same '
      + 'optimisation. The next step tests that claim rather than trusting it.',

      'Note how far below the 100 per tonne of step 3 this is — and how far below the 66.67 switching '
      + 'point. At 3.46 no plant switches fuel at all. Something else is doing the abating, and step 8 '
      + 'is where that gets explained.',
    ],
    explain: [
      'Read the emissions first and confirm they are exactly 150,000 — a binding constraint sits on its '
      + 'limit, and a model reporting 149,000 would mean the cap was not the thing constraining you.',

      'Then find the shadow price, which is not on the dashboard. Market & Policy → Advanced '
      + 'Constraints, under the DSL box: "Applied constraints (last run)" lists every custom, DSL and '
      + 'plugin constraint from the last solve with its dual beside it. Yours should read `dsl_1` with '
      + 'λ −3.46.',

      'Then compute the average: 233,408 divided by 122,288 tonnes avoided is about 1.91 per tonne. The '
      + 'marginal is 3.46. Marginal above average is what a rising abatement cost curve looks like, and '
      + 'it is why the next tonne always costs more than the last.',

      'Write the 3.46 down. The next step uses it.',
    ],
    spotlights: [
      {
        selector: '[data-card="emissions-breakdown"]',
        title: 'Exactly at the limit',
        tab: 'Analytics',
        note: '150,000 tonnes, not 149,000. A binding constraint sits on its bound — anything less would '
          + 'mean something else was the binding limit and the cap was slack.',
      },
      {
        selector: '[data-tour="applied-constraints"]',
        title: 'The shadow price',
        note: 'Under the DSL box in Market & Policy → Advanced Constraints, and nowhere else in the app. `dsl_1` '
          + 'with λ −3.46: the marginal abatement cost, and the carbon price that would produce the same '
          + 'system with no cap at all. The sign is the convention for a <= constraint; read the magnitude.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'What 45% cost',
        tab: 'Analytics',
        note: '233,408 a year more than the baseline. Against 122,288 tonnes avoided that is 1.91 per '
          + 'tonne on average, while the marginal tonne costs 3.46 — the gap is the abatement cost curve '
          + 'sloping upwards.',
      },
    ],
    verify: [
      'Emissions are exactly 150,000 tonnes',
      'The objective is 18,349,092',
      'Market & Policy → Advanced Constraints shows `dsl_1` with λ −3.46',
      'You can say why the dual is negative and what its magnitude means',
      'You can compute the average abatement cost and say why it is below the marginal',
      'You can say why no plant switched fuel at this price',
    ],
    pitfalls: [
      'Expecting the shadow price to resemble a real carbon price. It is the marginal cost of abatement '
      + 'in THIS system with THESE options, and step 8 explains why it comes out so low.',
      'Reading a slack constraint as an error. If the cap is above what the system would emit anyway, it '
      + 'binds nothing and has no shadow price — which is information, not a failure.',
    ],
  },

  {
    id: 'm8-duality',
    section: SECTION,
    title: 'Set the price to 3.46 and get the same system',
    tab: 'Analytics',
    where: 'Market & Policy → Carbon price, then run',
    concept: [
      'The claim is that a cap and a price are the same instrument. Here is the test: remove the cap, set '
      + 'a carbon price equal to the cap\'s shadow price, and see whether the system comes back the same.',

      'It does. A price of 3.46 gives 150,093 tonnes against the cap\'s 150,000. Wind 178.91 MW against '
      + '178.94. Solar 44.02 against 44.02. Coal 172.4 GWh against 172.3. The same system, reached from '
      + 'the opposite direction.',

      'That is duality, demonstrated rather than asserted, and it is the theoretical heart of carbon '
      + 'policy design. A cap-and-trade scheme discovers a price; a carbon tax discovers a quantity. In a '
      + 'model with perfect information they land in the same place.',

      'The objectives differ, and that difference is instructive rather than a discrepancy. Under the cap '
      + 'the system pays nothing for the tonnes it still emits. Under the price it pays 3.46 on every one '
      + 'of the 150,093 — about 520,000 a year that leaves the electricity sector and arrives somewhere '
      + 'else. Same physical system, same resource cost, very different cash flows.',
    ],
    explain: [
      'Clear the DSL box — or comment the line out with a leading `#`, which the language supports and '
      + 'is tidier than deleting it. Then set the carbon price to 3.46 and run.',

      'Compare the four capacities, the coal output and the emissions against the capped run in '
      + 'Analytics → Comparison. They should agree to three significant figures.',

      'The small residual — 150,093 against 150,000 — is not error in the sense of a mistake. The cap '
      + 'forces exactly its bound; the price lets the quantity settle wherever marginal abatement cost '
      + 'equals 3.46, and 3.46 was itself rounded from the dual. Set the price to more decimal places and '
      + 'the gap shrinks.',

      'This is worth doing once by hand because it is a claim you will meet constantly and it is usually '
      + 'presented as theory. You have just run the experiment.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Cap against price',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Two runs, two instruments, one system. Capacities agreeing to three significant figures is '
          + 'what duality looks like when you stop taking it on trust.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'Identical build',
        tab: 'Analytics',
        note: 'Wind 178.9, solar 44.0 — the same investment decisions the cap produced. The instrument '
          + 'chosen did not change what the system should look like, only who pays whom.',
      },
    ],
    entries: [
      {
        field: 'Market & Policy → Carbon price',
        value: '3.46',
        unit: 'currency per tonne CO2',
        why: 'The cap\'s shadow price, applied as a price with the cap removed. If duality holds this '
          + 'must reproduce the capped system — and it does, to three significant figures, which is the '
          + 'single most useful experiment in this module.',
      },
      {
        field: 'Market & Policy → Advanced Constraints → DSL box',
        label: 'the cap, commented out',
        value: '# emissions <= 150000',
        why: 'A leading # comments the line out, so the cap is inactive but the text is still there to '
          + 'restore in step 10. The price and the cap must not both bind, or you are testing something '
          + 'else entirely.',
      },
    ],
    verify: [
      'A carbon price of 3.46 with no cap gives about 150,093 tonnes',
      'Wind, solar and coal output match the capped run to three significant figures',
      'You can explain the residual 93 tonnes without calling it an error',
      'You can say what differs between the two runs even though the physical system is identical',
    ],
    pitfalls: [
      'Leaving the cap in place alongside the price. Both would bind, and the result is neither '
      + 'experiment.',
      'Expecting exact equality. The price is a rounded dual and the cap is exact; the residual is the '
      + 'rounding, not a modelling error.',
    ],
  },

  {
    id: 'm8-why-so-cheap',
    section: SECTION,
    title: 'Why the implied price is so low',
    tab: 'Analytics',
    where: 'Analytics → Result',
    concept: [
      'Step 2 derived a switching price of 66.67 per tonne — the point where coal gives way to gas. The '
      + 'cap achieved a 45% cut at a shadow price of 3.46, which is nowhere near it. No plant switched '
      + 'fuel, and yet 122,000 tonnes went away.',

      'The reason is that this model can BUILD. Between the baseline and the capped run, wind went from '
      + '150 to 179 MW and solar from 24 to 44. The cheapest way to emit less was not to run the existing '
      + 'fleet differently — it was to add renewable capacity that displaced coal generation outright.',

      'That is a general and under-appreciated result. Marginal abatement cost curves computed from fuel '
      + 'switching alone are far too pessimistic, because they hold capacity fixed. Once investment is on '
      + 'the table the cheapest tonnes are usually structural rather than operational.',

      'It also explains why the same policy question gets wildly different answers from different models. '
      + 'A dispatch model with fixed capacity would have reported an abatement cost near 66.67 for this '
      + 'system. An expansion model reports 3.46. Neither is wrong — they answer different questions, and '
      + 'the one you want depends on the time horizon of the decision.',
    ],
    explain: [
      'Compare the capped run against the baseline in the expansion card. The abatement came from about '
      + '29 MW of wind and 20 MW of solar, not from the merit order.',

      'Then look at coal output rather than coal capacity. It falls from 316 GWh to 172 — nearly halved '
      + 'without the plant being closed, priced out or switched. It simply had less to do.',

      'Then try the counterfactual if you have the patience: fix the capacities at their baseline values, '
      + 're-apply the cap, and see what the shadow price becomes. It should jump towards the switching '
      + 'price, because the only remaining lever is which plant runs.',

      'The practical lesson: when someone quotes a carbon price needed to hit a target, ask whether the '
      + 'model behind it could build anything. The answer changes the number by an order of magnitude.',
    ],
    spotlights: [
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'Abatement by building',
        tab: 'Analytics',
        note: '+29 MW wind and +20 MW solar against the baseline. That is where the 122,000 tonnes went — '
          + 'not into a different merit order, but into capacity that displaced coal generation.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'Coal, halved without switching',
        tab: 'Analytics',
        note: '316 GWh to 172, with the plant still in the fleet and still first in the merit order. It '
          + 'has less to do because something cheaper arrived, which is a different mechanism from being '
          + 'priced out.',
      },
    ],
    verify: [
      'You can say where the 122,000 tonnes of abatement actually came from',
      'You can explain why 3.46 is so far below the 66.67 switching price',
      'You can say how a fixed-capacity model would answer the same question differently',
      'You can say what to ask when someone quotes a carbon price needed to hit a target',
    ],
    pitfalls: [
      'Generalising 3.46 to any system. It is low because this system had cheap renewable options and '
      + 'headroom to build them; a system already saturated with renewables would report far more.',
      'Assuming a low implied price means the target is easy. It means the target is cheap to hit WITH '
      + 'investment — which requires the investment actually to happen.',
    ],
  },

  {
    id: 'm8-choosing',
    section: SECTION,
    title: 'So why choose one over the other?',
    tab: 'Analytics',
    where: 'Analytics → Comparison',
    concept: [
      'If a price and a cap produce the same system, the choice between them is not about outcomes in a '
      + 'model with perfect information. It is about what you are certain of when you do not have it.',

      'A cap fixes the quantity and leaves the cost unknown. If abatement turns out dearer than expected, '
      + 'you still hit the target and the price rises — which is what happened in the EU ETS in 2021-22. '
      + 'Good if the environmental outcome is what matters; painful if the cost lands somewhere '
      + 'politically intolerable.',

      'A price fixes the cost and leaves the quantity unknown. If abatement is dearer than expected you '
      + 'simply get less of it, and the target is missed quietly. Good for planning and for industry; bad '
      + 'if the target is the point.',

      'Everything in between is an attempt to have both. Price floors and ceilings inside a cap, market '
      + 'stability reserves, banking and borrowing — all of them are ways to bound the uncertainty the '
      + 'chosen instrument leaves open. Ragnarok can express a cap, a price, and a price schedule; the '
      + 'interactions between them are what Market & Policy is for.',

      'And there is a distributional difference the model does show. Under a price the emitters pay for '
      + 'every remaining tonne — about 520,000 a year here. Under a cap they pay nothing for them unless '
      + 'the allowances were auctioned. Same physical system, and a large transfer that exists or does '
      + 'not depending on a design choice nobody has to make explicit.',
    ],
    explain: [
      'Nothing to run. Put the two runs side by side in Analytics → Comparison and read what is the same '
      + 'and what is not.',

      'The same: every capacity, all generation, total emissions, the physical resource cost.',

      'Different: the objective, because one includes carbon payments and the other does not. That '
      + 'difference is not a cost to society — it is a transfer, and whether it flows to a treasury, back '
      + 'to consumers, or to incumbent emitters holding free allowances is a policy design question the '
      + 'model has no opinion on.',

      'Worth carrying forward: when a model says two policies are equivalent, it usually means equivalent '
      + 'in real resources. Who pays is almost always outside the model, and it is almost always what the '
      + 'argument is actually about.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Same system, different money',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Identical capacities and emissions, different objectives. The gap is the carbon payment — '
          + 'a transfer, not a resource cost, and the thing most policy arguments are really about.',
      },
    ],
    verify: [
      'You can say which uncertainty each instrument leaves open',
      'You can name one mechanism used to bound that uncertainty',
      'You can say why the two objectives differ when the physical systems are identical',
      'You can say what the model has no opinion about',
    ],
    pitfalls: [
      'Concluding the instruments are interchangeable. They are, under perfect information — which is '
      + 'exactly the assumption a real policy choice cannot make.',
      'Reading the objective difference as a cost. It is a transfer, and treating transfers as costs is '
      + 'one of the commonest errors in policy analysis.',
    ],
  },

  {
    id: 'm8-interactions',
    section: SECTION,
    title: 'A cap and a price together',
    tab: 'Analytics',
    where: 'Market & Policy → Carbon price and Advanced Constraints',
    concept: [
      'Real systems rarely have one instrument. A carbon price sits alongside a cap, a renewable target '
      + 'and a set of technology subsidies, and the interactions between them are where policy analysis '
      + 'gets interesting and where intuition fails.',

      'The governing rule is simple and unintuitive: when two instruments bind the same quantity, the '
      + 'tighter one determines the outcome and the other becomes irrelevant. Put a 100 per tonne price '
      + 'alongside a 150,000 tonne cap and the price alone takes emissions to 4,376 — far below the cap, '
      + 'so the cap never binds and has no shadow price. It is not adding anything.',

      'That is the "waterbed effect" that made European climate policy so contested for a decade. Under a '
      + 'binding EU-wide cap, a national measure that abated a tonne freed an allowance for someone else '
      + 'to emit it — so the national measure changed who emitted and not how much. Adding instruments '
      + 'does not add abatement when a quantity limit is already binding.',

      'The corollary matters for anyone reading a policy model: if you find a constraint with a zero '
      + 'shadow price, it is doing nothing at all, and its presence in the model is telling you something '
      + 'about the OTHER instruments rather than about itself.',
    ],
    explain: [
      'Put the `emissions <= 150000` line back in the DSL box and set the carbon price to 100 as well, '
      + 'then run.',

      'Read the emissions: 4,376, the same as the price alone. Then read the cap\'s shadow price: zero, '
      + 'or the constraint absent from the applied-constraints card entirely. It is slack.',

      'Then reverse it — price 0, cap 150,000 — and the cap binds with a shadow price of 3.46 again. '
      + 'Whichever instrument is tighter is the one doing the work, and the other is decoration.',

      'The practical habit: in any model with several policies, read the shadow prices before the '
      + 'headline. They tell you which instruments are actually binding, and that is frequently not the '
      + 'one the study is about.',
    ],
    spotlights: [
      {
        selector: '[data-tour="applied-constraints"]',
        title: 'A constraint doing nothing',
        note: 'With a 100 per tonne price also applied, the cap is slack: `dsl_1` still appears in the '
          + 'applied list but its λ is gone, because a dual below the display threshold is not shown. A '
          + 'constraint with no dual could be deleted without changing a single number.',
      },
      {
        selector: '[data-card="emissions-breakdown"]',
        title: 'Well under the limit',
        tab: 'Analytics',
        note: '4,376 tonnes against a 150,000 cap. The price alone did all of it, which is why the cap '
          + 'never entered the answer.',
      },
    ],
    entries: [
      {
        field: 'Market & Policy → Carbon price (with the DSL cap restored)',
        value: '100',
        unit: 'currency per tonne CO2',
        why: 'Applied alongside the 150,000 tonne cap so both are present. The price is far tighter, so '
          + 'it determines the outcome and the cap contributes nothing — which is the interaction rule in '
          + 'one experiment.',
      },
    ],
    verify: [
      'With both applied, emissions are 4,376 — the same as the price alone',
      'The cap appears in the applied list with no λ beside it — a zero dual',
      'You can state the rule for what happens when two instruments bind the same quantity',
      'You can explain the waterbed effect in one sentence',
    ],
    pitfalls: [
      'Assuming instruments add up. Two policies aimed at the same quantity do not abate twice; the '
      + 'tighter one abates and the other does nothing.',
      'Ignoring zero shadow prices. A constraint with no dual beside it is inert, and noticing that is '
      + 'often the most important finding in a multi-policy model.',
    ],
  },

  {
    id: 'm8-who-pays',
    section: SECTION,
    title: 'Who pays, and who earns',
    tab: 'Analytics',
    where: 'Analytics → Result → asset economics',
    concept: [
      'A carbon price changes prices as well as quantities, and the money involved is much larger than '
      + 'the resource cost of the abatement.',

      'The carbon payment itself is the obvious part: 150,093 tonnes at 3.46 is about 520,000 a year, or '
      + 'at 100 per tonne on 4,376 tonnes about 438,000. Consumers ultimately pay it, and where it goes '
      + 'depends on whether allowances are auctioned, given away, or the instrument is a tax.',

      'The less obvious part is what happens to electricity prices. A carbon price raises the marginal '
      + 'cost of whatever is setting the price, so it lifts the price in every hour a fossil plant is '
      + 'marginal — and every zero-carbon generator that was already running earns that higher price on '
      + 'output it was producing anyway. That is a transfer to existing renewables and nuclear, and it is '
      + 'usually far larger than the abatement cost.',

      'None of that is a criticism of the policy. It is the mechanism working: the price signal has to '
      + 'reach investors, and it reaches existing owners at the same time. But a study that reports only '
      + 'the resource cost of abatement has reported the smallest number in the analysis.',
    ],
    explain: [
      'Open the asset-economics card on the 100-per-tonne run and compare each generator\'s revenue '
      + 'against the baseline. The wind and hydro units should be earning substantially more without '
      + 'having changed at all.',

      'Then look at the price series. The average price rises, and it rises most in the hours the CCGT is '
      + 'marginal — which are now the expensive hours, because coal is gone.',

      'Then do the arithmetic that matters for a policy note: the resource cost of abatement (about 3.2 '
      + 'million a year), the carbon payments, and the change in what consumers pay for electricity. '
      + 'Those are three different numbers and only the first is a cost to society.',

      'This is the analysis most commonly done badly, and the model gives you all three if you ask for '
      + 'them separately.',
    ],
    spotlights: [
      {
        selector: '[data-card="generator-economics"]',
        title: 'Who gained',
        tab: 'Analytics',
        note: 'Revenue and margin per generator. The zero-carbon units earn more on unchanged output, '
          + 'because the carbon price lifted the price they are paid — a transfer that usually dwarfs the '
          + 'cost of the abatement itself.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'And why',
        tab: 'Analytics',
        note: 'The price-setting table after the carbon price. Whatever sets the price now carries a '
          + 'carbon charge, so every hour it is marginal clears higher — and everyone else is paid it.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Three different numbers',
        tab: 'Analytics',
        note: 'Resource cost of abatement, carbon payments, and consumer cost are not the same quantity. '
          + 'A note quoting only the first has quoted the smallest one.',
      },
    ],
    verify: [
      'You can name three distinct money flows a carbon price creates',
      'You can say which of them is a cost to society and which are transfers',
      'You can say why existing zero-carbon generators gain from a carbon price',
      'You can find at least one generator whose revenue rose without its output changing',
    ],
    pitfalls: [
      'Reporting abatement cost as "the cost of the policy". It is the smallest of the flows and rarely '
      + 'the one that decides whether a policy is politically survivable.',
      'Treating the transfer to existing renewables as a windfall to be clawed back without thinking it '
      + 'through. It is the same signal that makes new build happen; the two cannot be separated inside '
      + 'this model.',
    ],
  },

  {
    id: 'm8-what-changed',
    section: SECTION,
    title: 'What module 8 settled, and what a model cannot say',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Five things are now yours.',

      'Policy is a price or a limit, and in a model they are duals. A cap has a shadow price; set a '
      + 'carbon price to it and you get the same system, which you have now verified to three '
      + 'significant figures rather than read about.',

      'Emission intensity is a factor divided by an efficiency, and the switching price between two '
      + 'plants follows from it — 66.67 per tonne between this coal unit and this CCGT.',

      'But switching prices mislead when a model can build. The cheapest abatement here was structural, '
      + 'not operational: 45% of emissions went away at an implied price of 3.46, twenty times below the '
      + 'switching point, because new wind and solar displaced coal generation outright.',

      'Instruments do not add. When two bind the same quantity the tighter one determines the outcome and '
      + 'the other has a zero shadow price — which is the first thing to check in any multi-policy model.',

      'And a carbon price moves far more money than it costs in resources. Abatement cost, carbon '
      + 'payments and consumer cost are three different numbers, and only the first is a cost to society.',
    ],
    explain: [
      'What this model cannot say, which matters more here than in any previous module because policy '
      + 'analysis is where models get quoted.',

      'It cannot represent demand response. Every tonne abated came from changing supply; nobody used '
      + 'less electricity, and no price elasticity exists anywhere in the model. Real carbon prices reduce '
      + 'demand, and this one structurally cannot.',

      'It cannot represent anything outside the electricity sector. A carbon price applies economy-wide, '
      + 'and the interesting effects — industrial relocation, fuel switching in heat and transport, '
      + 'competitiveness — all happen outside these three buses. Module 5 showed how a gas sector is '
      + 'added; the same machinery extends further, and the boundary is always a choice you should state.',

      'It has one weather year, one demand year and perfect foresight. A policy that looks robust against '
      + 'this year might fail in a still, cold one, and module 6 showed how much a horizon choice can '
      + 'move an answer.',

      'And it has no politics, no lead times and no supply chains. The model builds 133 MW of solar '
      + 'instantly at a known price. Whether that can happen is not a question it is equipped to ask.',

      'Export the project. Module 9 is about turning any of this into something a decision-maker can act '
      + 'on — which starts by being honest about all of the above.',
    ],
    spotlights: [
      {
        selector: '[data-card="emissions-breakdown"]',
        title: 'Where it ended',
        tab: 'Analytics',
        note: 'From 272,288 tonnes to 4,376 at a carbon price of 100 — a 98% cut driven entirely by what '
          + 'the system chose to build, with no mandate and no demand reduction anywhere.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. Module 9 is about presenting results honestly, and it works best '
          + 'with the runs from this module still in History.',
      },
    ],
    verify: [
      'You can explain price/cap duality and say how you verified it',
      'You can compute a switching price and say when it is the wrong number to quote',
      'You can say what happens to a constraint that is not the tightest',
      'You can name three money flows and say which is a cost to society',
      'You can list four things this model cannot say about carbon policy',
      'You have exported the project',
    ],
    pitfalls: [
      'Quoting any number from this module as a policy finding. Synthetic profiles, one weather year, no '
      + 'demand response, one sector, perfect foresight — the mechanisms are real and the magnitudes are '
      + 'illustrative.',
      'Assuming a model settles a policy argument. It can settle what is physically consistent and what '
      + 'things cost in resources. Who pays, and whether it is worth it, are not questions it is '
      + 'equipped to answer.',
    ],
  },
];
