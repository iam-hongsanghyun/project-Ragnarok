/**
 * Module 5 — Sector coupling and fuel supply (11 steps).
 *
 * Every generator so far has burned fuel that appeared from nowhere at a fixed
 * price per MWh of electricity. That is a modelling convenience, and it hides
 * the thing that actually drives a gas plant's cost: the price of gas, and
 * whether you can get any.
 *
 * This module separates the two. Gas becomes a carrier on its own bus, bought
 * by an import, buffered by a store, and converted into electricity by a Link
 * that is what a CCGT physically is. Then run-of-river hydro and a pumped-hydro
 * scheme round the fleet out.
 *
 * Built on module 4's model (7,730). Every figure verified against a real HiGHS
 * solve before the prose was written:
 *
 *   step 5   rewired, fuel at 25/MWh_th          7,730     identical, by design
 *   step 6   fuel price raised to 40/MWh_th     11,264     power price 50 -> 80
 *   step 7   import capped at 150 MW_th          9,221.11  the peaker returns
 *   step 8   200 MWh gas store added             7,730     buy early, burn later
 *   step 9   run-of-river hydro added            7,145
 *   step 10  pumped hydro added at bus_1         7,099.59
 *
 * The rewire in step 5 is the module's keystone: 25 per MWh of gas through a 50%
 * converter IS 50 per MWh of electricity, so a correct rewire reproduces module
 * 4's objective exactly. Same physics, better structure — and the structure is
 * what makes steps 6 to 8 possible at all.
 *
 * Step 10 is the module's sharpest result. A 30 MW / 180 MWh pumped-hydro scheme
 * adds 45; module 4's 20 MWh battery at the demand end added 1,670. Nine times
 * the energy, three per cent of the value, because pumped hydro is where the
 * mountains are and the mountains are behind the constraint.
 */
import { TutorialStep } from '../types';

const SECTION = '5 · Sector coupling and fuel supply';

export const MODULE_5_SECTOR_COUPLING: TutorialStep[] = [
  {
    id: 'm5-why-sectors',
    section: SECTION,
    title: 'A bus is not always electric',
    tab: 'Build',
    where: 'Build → Buses step',
    startOptions: {
      prebuiltExampleId: 'training_m4',
      completeExampleId: 'training_m5',
      note:
        'Module 5 continues module 4\'s model — two electrical buses, a congested line, a battery at the '
        + 'demand end — and answered 7,730. This module adds a third bus that carries gas rather than '
        + 'electricity, and rebuilds the gas plant as what it physically is.',
    },
    concept: [
      'Look at what `gas_1` has been claiming. It produces electricity at 50 per MWh, has an efficiency '
      + 'of 0.5, and gets its fuel from nowhere in unlimited quantity at a price that never changes. Two '
      + 'of those three are fictions, and they are the fictions that matter most in a real study: gas '
      + 'prices move constantly, and supply can be limited.',

      'The fix is to stop treating fuel as an attribute of the generator and start treating it as a '
      + 'commodity with its own network. A bus does not have to carry electricity — it is just a place '
      + 'where something balances. Give gas its own bus and the same machinery you already know applies '
      + 'to it: supply attaches to it, storage attaches to it, and the balance must hold in every '
      + 'snapshot exactly as it does for power.',

      'What converts between the two is a Link: a component that takes energy off one bus and delivers a '
      + 'fraction of it to another. A gas turbine is a Link from gas to electricity. So is an electrolyser '
      + 'from electricity to hydrogen, and a heat pump from electricity to heat. Once you see conversion '
      + 'as a component rather than an attribute, sector coupling stops being a special topic and becomes '
      + 'the same five nouns you learnt in module 1.',

      'This is the structural idea behind every whole-energy-system model in use today. Power, gas, heat '
      + 'and hydrogen are buses; conversion between them is Links; and the optimiser decides which '
      + 'conversions are worth running, hour by hour, exactly as it decides which generators to dispatch.',
    ],
    explain: [
      'The model you are starting from is module 4\'s: two buses, a 60 MW line that congests, four '
      + 'generators, a 20 MW battery at bus_2. It answered 7,730 with the peaker never running.',

      'Over the next four steps you will add a gas bus, an import that supplies it, a Link that burns gas '
      + 'to make electricity, and then delete `gas_1` — because the Link and the import together ARE '
      + 'gas_1, expressed honestly.',

      'The test of a correct rewire is that the answer does not change. 25 per MWh of gas through a 50% '
      + 'converter costs 50 per MWh of electricity, which is exactly what gas_1 charged — so step 5 should '
      + 'return 7,730 to the currency unit. If it does not, something is wired wrong, and that is a far '
      + 'better check than reading the sheet back.',

      'Then the structure starts earning its keep: a fuel price you can change, an import you can limit, '
      + 'and a store you can fill in advance. None of those were expressible before.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="buses"]',
        buildStep: 'buses',
        title: 'Two buses, about to be three',
        tab: 'Build',
        note: 'bus_1 and bus_2, both carrying AC. The `carrier` column has been the same on every bus in '
          + 'this course so far, and it is the one you are about to use differently.',
      },
      {
        selector: '[data-build-step="links"]',
        buildStep: 'links',
        title: 'The Links step',
        tab: 'Build',
        note: 'Empty since module 1, and correctly skipped — with one carrier there was nothing to convert '
          + 'between. It is the step this module is built on, and the reason it sits next to Lines in the '
          + 'strip: a Line joins two buses of the SAME carrier, a Link joins two of any carriers.',
      },
      {
        selector: '.build-step-strip',
        title: 'What is left after this',
        tab: 'Build',
        note: 'Only Processes and Constraints stay empty after module 5. Constraints are module 8, where '
          + 'policy arrives as a limit on the whole system rather than a property of one component.',
      },
    ],
    verify: [
      'The session holds module 4\'s model and answers 7,730',
      'You can say what a Link does, and give two examples that are not gas turbines',
      'You can say why a fuel price cannot be represented properly as a generator\'s marginal cost',
      'You can predict what step 5 should answer, and why',
    ],
    pitfalls: [
      'Thinking of sector coupling as an advanced topic bolted on to a power model. It is the same five '
      + 'components you have used since module 1 — the only new idea is that a bus can carry something '
      + 'other than electricity.',
    ],
  },

  {
    id: 'm5-gas-bus',
    section: SECTION,
    title: 'The gas bus',
    tab: 'Build',
    where: 'Build → Buses step',
    concept: [
      'A bus is a balance constraint with a location. Nothing in that definition mentions electricity — '
      + 'the carrier attribute is what says which commodity balances there, and until now it has always '
      + 'been AC.',

      'A gas bus balances gas. What flows in is import and withdrawal from storage; what flows out is '
      + 'consumption by converters. It has a shadow price like any other bus, and that shadow price is '
      + 'the marginal value of gas at that point — which is the wholesale gas price the model is implying.',

      'Voltage means nothing here, so `v_nom` is left at zero. That is not a placeholder: it is the '
      + 'honest answer, and it is a small reminder that half the attributes on any component are '
      + 'carrier-specific.',
    ],
    explain: [
      'Build → Buses, "+ Add Bus", and fill the row. The name is `bus_gas`, the carrier is `gas` — the '
      + 'carrier you have had in the sheet since module 1 and have only ever used as a label on a '
      + 'generator.',

      'Give it coordinates roughly between the two electrical buses. Geography does nothing for a gas bus '
      + 'in this model, but the map draws it, and seeing the gas node sit alongside the power nodes makes '
      + 'the structure obvious at a glance.',

      'Leave `v_nom` at 0. A gas pipeline has a pressure, not a voltage, and PyPSA does not model pipeline '
      + 'hydraulics — the bus is a balance point, nothing more.',

      'The bus is isolated for the next two steps, exactly as bus_2 was in module 3. Validation will say '
      + 'so and it will be right until the Link arrives.',
    ],
    spotlights: [
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'buses',
        title: 'A third bus',
        tab: 'Build',
        note: 'Same control as always. The only cell that makes this bus different from the other two is '
          + '`carrier`, which is the whole idea of the module in one field.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'buses',
        title: 'Three nodes',
        tab: 'Build',
        note: 'The gas bus draws on the map like any other. It has no electrical meaning and no voltage, '
          + 'but it is a place where something balances, and that is all a bus has ever been.',
      },
    ],
    entries: [
      {
        field: 'buses.name (new row)',
        label: 'bus name',
        value: 'bus_gas',
        why: 'Named for what it carries rather than where it is, which is the convention once a model has '
          + 'more than one commodity. The import, the store and the CCGT will all point at this text.',
      },
      {
        field: 'buses.carrier (new row)',
        label: 'what balances here',
        value: 'gas',
        why: 'THE field of this module. It says this bus balances gas rather than electricity, which means '
          + 'only gas components may attach to it — and that a Line cannot join it to an electrical bus, '
          + 'because a line carries one carrier. Only a Link can cross between them.',
      },
      {
        field: 'buses.v_nom (new row)',
        label: 'nominal voltage',
        value: '0',
        unit: 'kV',
        why: 'Zero, because a gas bus has no voltage. Unlike the electrical buses, where a blank raised a '
          + 'warning and power flow needed the number, here it is genuinely meaningless — a useful '
          + 'reminder that attributes belong to carriers, not to components in general.',
      },
      {
        field: 'buses.x (new row)',
        label: 'longitude',
        value: '128.0',
        unit: 'degrees east',
        why: 'Between the two electrical buses, so the map reads clearly. Position does nothing in this '
          + 'model — there is no pipeline whose length matters — but a gas network with real geography '
          + 'would use it exactly as the electrical one does.',
      },
      {
        field: 'buses.y (new row)',
        label: 'latitude',
        value: '36.4',
        unit: 'degrees north',
        why: 'The other half of the position, chosen for legibility on the map rather than for any '
          + 'physical reason.',
      },
    ],
    verify: [
      'The `buses` sheet has 3 rows, and bus_gas reads `gas` in the carrier column',
      'A third marker appears on the map',
      'Validation warns that bus_gas has nothing attached — correct for two more steps',
      'You can say why a Line could not join bus_gas to bus_2',
    ],
    pitfalls: [
      'Giving the gas bus a carrier of AC. It would then balance electricity, the CCGT Link would be '
      + 'converting electricity into electricity, and the whole structure would be meaningless while '
      + 'still solving.',
      'Setting a voltage on it. Harmless, but it suggests the bus is electrical and will confuse anyone '
      + 'reading the model later.',
    ],
  },

  {
    id: 'm5-gas-supply',
    section: SECTION,
    title: 'Buying gas — a price per MWh of fuel',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'Supply attaches to a gas bus the same way it attaches to an electrical one: with a Generator. '
      + 'That word is doing unfamiliar work here — this generator does not generate electricity, it '
      + 'delivers gas — but the component is right, because a Generator is simply an injection with a '
      + 'cost and a limit.',

      'Its `marginal_cost` is the fuel price, in currency per MWh THERMAL. That is the unit fuel is '
      + 'actually traded in, and keeping it in thermal units is what makes the model honest: the '
      + 'conversion into cost-per-MWh-of-electricity is the CCGT\'s efficiency doing its job, not '
      + 'something you should be doing in your head.',

      'The arithmetic to keep hold of: fuel price divided by conversion efficiency is the electricity '
      + 'cost. 25 per MWh of gas through a 50% converter is 50 per MWh of electricity — which is exactly '
      + 'what gas_1 has been charging since module 2. That is why step 5 must return the same answer.',

      'And `p_nom` is now an import limit rather than a nameplate. How much gas can physically arrive per '
      + 'hour — pipeline capacity, terminal throughput, contract volume. Step 7 makes it bind.',
    ],
    explain: [
      'Build → Generators, "+ Add Generator", and fill the row. It goes on bus_gas, which means it '
      + 'injects gas rather than power.',

      'Leave `p_nom` generous for now — 10000 is fine, or any number far above what the model could use. '
      + 'The import limit is step 7\'s experiment and it should not bind yet.',

      'Set `efficiency` to 1. This component moves gas, it does not convert anything, so a unit in is a '
      + 'unit out. Efficiency belongs to the Link.',

      'Do not delete `gas_1` yet. Both will exist briefly, and the model will simply pick whichever is '
      + 'cheaper — which is a useful accident, because it means nothing breaks while the rewire is half '
      + 'done.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'A generator that makes no electricity',
        tab: 'Build',
        note: 'Five rows after this, and the new one sits on bus_gas. The `bus` column is what decides '
          + 'what a generator injects — the component does not know or care which commodity it is.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'Read the units differently',
        tab: 'Build',
        note: 'p_nom on this row is MW of gas, not MW of electricity, and marginal_cost is per MWh '
          + 'thermal. Same columns, different commodity — which is why a model with several carriers needs '
          + 'its units documented somewhere a reader will find them.',
      },
    ],
    entries: [
      {
        field: 'generators.name',
        label: 'generator name',
        value: 'gas_supply',
        why: 'Named for what it does rather than what it is. It represents the whole upstream chain — '
          + 'field, pipeline, terminal, contract — collapsed into one injection with a price and a limit, '
          + 'which is as much detail as a power-system model needs about it.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it injects at',
        value: 'bus_gas',
        why: 'The gas bus, so this component supplies gas. Point it at bus_2 by mistake and it becomes a '
          + 'suspiciously cheap electricity generator — the model will solve happily and the answer will '
          + 'be nonsense, which is the failure mode to watch for whenever a model has several carriers.',
      },
      {
        field: 'generators.carrier',
        label: 'commodity',
        value: 'gas',
        why: 'Matches the bus\'s carrier and groups the import in per-carrier results. It is also where '
          + 'the emission factor lives — 0.2 tCO2 per MWh of fuel, typed back in module 1 and finally '
          + 'attached to the thing that actually burns.',
      },
      {
        field: 'generators.p_nom',
        label: 'import limit',
        value: '10000',
        unit: 'MW thermal',
        why: 'Deliberately far above anything the model could use, so supply is effectively unlimited for '
          + 'now. This is not a nameplate — it is how much gas can arrive per hour, and step 7 cuts it to '
          + '150 to see what a supply constraint does to an electricity system.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'fuel price',
        value: '25',
        unit: 'currency per MWh thermal',
        why: 'The price of gas, in the units gas is traded in. Divided by the CCGT\'s 50% efficiency it '
          + 'gives 50 per MWh of electricity — exactly what gas_1 has charged since module 2, which is why '
          + 'the rewire in step 5 must reproduce 7,730 exactly.',
      },
      {
        field: 'generators.efficiency',
        label: 'conversion',
        value: '1',
        why: 'One, because this component converts nothing — it delivers gas as gas. All the conversion in '
          + 'this model happens in the Link, and putting an efficiency here as well would apply the loss '
          + 'twice.',
      },
    ],
    verify: [
      'The `generators` sheet has 5 rows, with gas_supply on bus_gas',
      '`marginal_cost` is 25 and you can say what unit that is in',
      'You can compute the electricity cost this implies, given a 50% converter',
      'Validation no longer warns that bus_gas is isolated — it has an injection now',
    ],
    pitfalls: [
      'Typing the fuel price as 50. That is the electricity cost, not the gas price, and putting it here '
      + 'doubles the real cost once the Link\'s efficiency is applied.',
      'Putting an efficiency of 0.5 on the supply as well as the Link. The loss would be applied twice '
      + 'and the model would need four units of gas per unit of power instead of two.',
    ],
  },

  {
    id: 'm5-the-link',
    section: SECTION,
    title: 'The Link — what a CCGT actually is',
    tab: 'Build',
    where: 'Build → Links step',
    concept: [
      'A Link takes power off `bus0` and delivers `efficiency` times that amount to `bus1`. The rest is '
      + 'lost. That is the entire component, and it is enough to represent every conversion in an energy '
      + 'system.',

      'A combined-cycle gas turbine is exactly this. Gas goes in, electricity comes out, and roughly half '
      + 'the energy leaves as heat — a gas turbine whose exhaust drives a steam turbine, which is where '
      + 'the "combined cycle" comes from and why it is the most efficient thermal plant in common use. '
      + 'Modern CCGTs reach about 0.60; this model uses 0.50 because it makes the arithmetic checkable '
      + 'and because it matches what gas_1 has been assuming all along.',

      'Contrast it with the oil peaker at bus_2. That is the open-cycle case — one turbine, no steam '
      + 'recovery, around 0.35 efficient, cheap to build and quick to start. The whole reason a system '
      + 'holds both is that a CCGT is efficient but slow and capital-heavy, while an OCGT is inefficient '
      + 'but cheap to keep for the few hours a year it is needed. Module 2 met that trade-off as two '
      + 'marginal costs; here it is two efficiencies and two technologies.',

      'The sign convention is worth getting right once: `p_nom` and the reported flow `p0` are measured '
      + 'at bus0, the INPUT side. A Link with p_nom 200 and efficiency 0.5 consumes up to 200 MW of gas '
      + 'and delivers up to 100 MW of electricity. Size it in fuel, read the output as fuel times '
      + 'efficiency.',
    ],
    explain: [
      'Build → Links, "+ Add Link", and fill the row. `bus0` is bus_gas, `bus1` is bus_2. Direction '
      + 'matters here in a way it did not for a Line: a Link is one-way by default, from bus0 to bus1.',

      'Set `p_nom` to 200. That is 200 MW of gas input, which at 50% efficiency is the same 100 MW of '
      + 'electrical output that gas_1 had — so the fleet\'s capability is unchanged and only its '
      + 'description has improved.',

      'The Links step shows the map, because a Link joins two buses and inherits their positions. You '
      + 'should see a new connection drawn from the gas node to bus_2, alongside the existing line.',

      'Do not run yet. The next step deletes gas_1 first, and running with both present would answer the '
      + 'same number for the wrong reason — the model would simply use whichever route was cheaper, and '
      + 'they cost exactly the same.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="links"]',
        buildStep: 'links',
        title: 'The Links step, at last',
        tab: 'Build',
        note: 'Blank for four modules. A Link is the only component that can cross between carriers, which '
          + 'is why nothing needed it until a second carrier existed.',
      },
      {
        selector: '[data-tour="add-row"]',
        buildStep: 'links',
        title: 'Add the CCGT',
        tab: 'Build',
        note: 'One row. bus0 is where the fuel comes from, bus1 is where the electricity goes, and the '
          + 'efficiency between them is what makes it a power station rather than a pipe.',
      },
      {
        selector: '.build-map-frame',
        buildStep: 'links',
        title: 'The conversion, drawn',
        tab: 'Build',
        note: 'A second connection appears, from the gas node to bus_2. If nothing is drawn, one of bus0 '
          + 'or bus1 does not match a bus name — the same fast check as module 3\'s line.',
      },
    ],
    entries: [
      {
        field: 'links.name',
        label: 'link name',
        value: 'ccgt_1',
        why: 'Named for the technology rather than the function, because in results this row IS the power '
          + 'station — its output, its fuel burn and its emissions all report under this name once gas_1 '
          + 'is gone.',
      },
      {
        field: 'links.bus0',
        label: 'input bus',
        value: 'bus_gas',
        why: 'Where the fuel is drawn from. This is also the side `p_nom` and the reported flow are '
          + 'measured on, so every number about this Link is in MW of gas unless you multiply by the '
          + 'efficiency yourself.',
      },
      {
        field: 'links.bus1',
        label: 'output bus',
        value: 'bus_2',
        why: 'Where the electricity is delivered — the demand end, which is where gas_1 sat. Reverse bus0 '
          + 'and bus1 and you have built a machine that burns electricity to make gas, which will solve '
          + 'and will be wrong.',
      },
      {
        field: 'links.efficiency',
        label: 'conversion efficiency',
        value: '0.5',
        why: 'MWh of electricity out per MWh of gas in. This single number turns the 25 fuel price into a '
          + '50 electricity cost, and it is what makes a CCGT a CCGT — a modern one reaches about 0.60, '
          + 'and 0.50 is used here to match what gas_1 assumed so the rewire is exactly comparable.',
      },
      {
        field: 'links.p_nom',
        label: 'capacity, measured on the input side',
        value: '200',
        unit: 'MW thermal',
        why: '200 MW of gas in, which at 50% is 100 MW of electricity out — the same capability gas_1 had. '
          + 'The commonest Link mistake is sizing this in output units: 100 here would have given a 50 MW '
          + 'power station and quietly halved the fleet.',
      },
    ],
    verify: [
      'The `links` sheet has 1 row and the map draws a connection from bus_gas to bus_2',
      '`p_nom` is 200 and you can say why that is a 100 MW power station',
      'You can say what distinguishes a CCGT from the open-cycle peaker at bus_2',
      'You can say which side of a Link `p_nom` is measured on',
    ],
    pitfalls: [
      'Sizing `p_nom` in electrical output. It is measured at bus0, the fuel side — 200 MW of gas gives '
      + '100 MW of power at 50% efficiency.',
      'Swapping bus0 and bus1. The model solves and represents a machine that consumes electricity to '
      + 'produce gas. Nothing errors; the answer is simply about a different world.',
      'Expecting a Link to be bidirectional. By default it is not — power flows bus0 to bus1 only, which '
      + 'is right for a turbine and wrong for an interconnector.',
    ],
  },

  {
    id: 'm5-rewire-and-run',
    section: SECTION,
    title: 'Delete gas_1 and run — the same answer, honestly',
    tab: 'Analytics',
    where: 'Build → Generators, then the Run dialog',
    concept: [
      'The rewire is complete once `gas_1` is gone, because the import and the Link together are exactly '
      + 'what it was: a source of gas at 25 per MWh thermal, and a machine that turns that gas into '
      + 'electricity at 50%.',

      'So the answer must not change. 25 divided by 0.5 is 50, which is what gas_1 charged; its capacity '
      + 'was 100 MW and the Link delivers 100 MW; the emission factor was on the gas carrier and still '
      + 'is. Every input the optimiser sees is the same, arranged differently.',

      'Expect 7,730 — module 4\'s objective, to the currency unit. A refactor that changes the answer is '
      + 'a refactor that changed the model, and on a real study that check is the difference between '
      + 'improving a model and quietly breaking it.',

      'What HAS changed is what you can now ask. The fuel price is a number in a cell rather than an '
      + 'assumption buried in a marginal cost; the import has a capacity; and gas can be stored. None of '
      + 'those existed ten minutes ago, and the next three steps use all three.',
    ],
    explain: [
      'Build → Generators. Delete the `gas_1` row — right-click the row for the delete option, or use the '
      + 'row menu. The fleet drops to four generators plus the import.',

      'Validate, then run. Reconcile the objective against 7,730.',

      'If it comes out higher, the most likely cause is the Link\'s p_nom being too small — 100 instead of '
      + '200 would halve the CCGT and force the peaker back in. If it comes out lower, check you have not '
      + 'left gas_1 in place alongside the Link.',

      'Then look at the gas bus price in the results. It reads 25 in every hour — the fuel price, '
      + 'unchanged, because supply is unlimited and nothing is competing for it. That number will start '
      + 'moving in step 7, and when it does it will tell you something the electricity price cannot.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Delete gas_1',
        tab: 'Build',
        note: 'The row that has carried the gas plant since module 2. Its job is now split between '
          + 'gas_supply on the gas bus and the ccgt_1 Link — deleting it is what makes the rewire real '
          + 'rather than duplicated.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile 7,730',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Module 4\'s answer, to the currency unit, from a structurally different model. A refactor '
          + 'that changes the answer changed the model — this is the check that tells you which you did.',
      },
      {
        selector: '[data-card="merit-order"]',
        title: 'A fleet with a hole in it',
        tab: 'Analytics',
        note: 'The merit order is built from generators, and the CCGT is no longer one — it is a Link. Its '
          + 'output still appears in dispatch and its cost still lands in the objective, but a chart keyed '
          + 'on generators cannot see it. Worth knowing before it surprises you on a sector-coupled model.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the Link\'s two bus references and the import\'s bus — the three places this rewire could be wrong.',
        'The solve now carries three buses, a Link and a Line. Still instant.',
      ],
      expect: 'An objective of 7,730 — identical to module 4, from a model that describes the gas plant honestly.',
    },
    verify: [
      'The objective is 7,730, matching module 4 exactly',
      'The `generators` sheet has 4 rows plus gas_supply; gas_1 is gone',
      'The gas bus price reads 25 in every snapshot',
      'You can say what would have gone wrong if the Link\'s p_nom were 100',
      'You can name three questions the new structure lets you ask that the old one did not',
    ],
    pitfalls: [
      'Leaving gas_1 in place. The model then has two identical routes to make power and picks either; '
      + 'the objective is right and the model is wrong, which is the worst combination.',
      'Expecting the merit-order card to show the CCGT. It is a Link, and that card reads generators — '
      + 'the energy is in the dispatch chart instead.',
    ],
  },

  {
    id: 'm5-fuel-price',
    section: SECTION,
    title: 'The fuel price propagates',
    tab: 'Analytics',
    where: 'Build → Generators, then run again',
    concept: [
      'Now the structure pays. Change one cell — the fuel price — and watch it travel through the '
      + 'converter into the electricity price.',

      'At 40 per MWh thermal, a 50% CCGT costs 80 per MWh of electricity. It stays below the oil peaker '
      + 'at 120, so the merit order does not reorder, but every hour the CCGT was marginal now clears at '
      + '80 instead of 50. The objective goes from 7,730 to 11,264.',

      'That is a 46% increase in system cost from a 60% increase in the price of one fuel, and it is the '
      + 'single most important sensitivity in most power systems: gas sets the price in a large fraction '
      + 'of hours in most liberalised markets, so the gas price effectively sets the electricity price '
      + 'whether or not much gas is burnt.',

      'It also shows why the rewire mattered. Before, changing the gas price meant recomputing a marginal '
      + 'cost by hand and typing the result. Now the model does the division, using the efficiency it '
      + 'already knows — and it would do the same for twenty gas plants with twenty different '
      + 'efficiencies, correctly, without anyone doing arithmetic.',
    ],
    explain: [
      'Build → Generators. Change gas_supply\'s `marginal_cost` from 25 to 40 and run.',

      'Read the objective: 11,264. Then look at the bus_2 price series — 20, 80, 80. The 50s have become '
      + '80s exactly as the arithmetic predicts, and the 20 in the first hour is unchanged because coal, '
      + 'not gas, was marginal then.',

      'That last detail is worth dwelling on. A fuel price change only moves the electricity price in the '
      + 'hours when that fuel is marginal. Hours set by coal, wind or storage are untouched — which is '
      + 'why "the gas price went up 60%" and "power prices went up 60%" are different claims, and why the '
      + 'fraction of hours a fuel sets the price is a number worth knowing about any system.',

      'Set the price back to 25 and re-run before moving on. The rest of the module assumes 7,730.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'One cell',
        tab: 'Build',
        note: 'gas_supply\'s marginal_cost, 25 to 40 and back again. No efficiency to recompute and no '
          + 'other row to touch — which is the practical payoff of separating fuel from conversion.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '11,264',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'A 60% rise in the gas price produced a 46% rise in system cost. The gap between those two '
          + 'numbers is everything that is not gas — and it is why a system with a diverse fleet is less '
          + 'exposed to one commodity.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Which hours moved',
        tab: 'Analytics',
        note: 'Only the hours where gas was the marginal unit reprice. The coal-set hour is unchanged at '
          + '20. This card is the fastest way to know how exposed a system\'s prices are to one fuel: it is '
          + 'the share of hours that fuel sets the price.',
      },
    ],
    entries: [
      {
        field: 'generators.marginal_cost (gas_supply, the experiment)',
        label: 'fuel price, raised',
        value: '40',
        unit: 'currency per MWh thermal',
        why: 'A 60% increase, which is a mild move by the standards of the 2021-22 European gas market. '
          + 'Through a 50% converter it becomes 80 per MWh of electricity, so every gas-set hour reprices '
          + 'from 50 to 80 while coal-set and storage-set hours do not move at all.',
      },
      {
        field: 'generators.marginal_cost (gas_supply, restore)',
        label: 'fuel price, back',
        value: '25',
        unit: 'currency per MWh thermal',
        why: 'Returns the model to 7,730, which the remaining steps assume. Leaving it at 40 would change '
          + 'every number in steps 7 to 10 and none of them would match the course.',
      },
    ],
    verify: [
      'At a fuel price of 40 the objective is 11,264',
      'The bus_2 price series reads 20, 80, 80',
      'You can say why the first hour did not reprice',
      'After restoring 25, the objective is 7,730 again',
    ],
    pitfalls: [
      'Assuming every hour reprices with the fuel. Only the hours that fuel is marginal in move, which is '
      + 'why the share of price-setting hours matters more than the fuel mix by energy.',
      'Forgetting to restore 25. Every figure from here on assumes it.',
    ],
  },

  {
    id: 'm5-import-limit',
    section: SECTION,
    title: 'Cap the import — the peaker comes back',
    tab: 'Analytics',
    where: 'Build → Generators, then run again',
    concept: [
      'Fuel is not only a price, it is a quantity. Pipelines have capacity, terminals have throughput, '
      + 'and contracts have volumes — and a system can be short of gas even when it can afford it.',

      'Cut the import to 150 MW thermal. In the peak hour the CCGT wants 200 MW of gas to make its 100 MW '
      + 'of electricity, and it can only get 150 — so it makes 75 MW instead, and the 25 MW shortfall has '
      + 'to come from somewhere. Oil, at 120.',

      'The objective goes to 9,221.11 and the peak electricity price returns to 120. Module 4 removed '
      + 'that peaker with a battery; a fuel constraint has just put it back, which is a good illustration '
      + 'that adequacy is about the whole chain and not just about installed capacity.',

      'The most interesting number, though, is on the gas bus. Its price jumps from 25 to 60 in the peak '
      + 'hour, even though the fuel price is still 25. That is scarcity: the shadow price of gas when '
      + 'there is not enough of it, and the extra 35 is what the system would pay for one more MWh of '
      + 'import capacity in that hour. A commodity price and a scarcity rent, told apart by the model.',
    ],
    explain: [
      'Build → Generators. Change gas_supply\'s `p_nom` from 10000 to 150 and run.',

      'Read the objective — 9,221.11 — and then check three things: oil_1 is producing again in the peak '
      + 'hour, the bus_2 price ends at 120, and the gas bus price is no longer flat.',

      'The gas price is the one to sit with. It reads 25, 25, 60. Nothing about the fuel got more '
      + 'expensive; the model is telling you what gas is WORTH at the margin in an hour when there is not '
      + 'enough. That is the same shadow-price idea from module 1, applied to a commodity instead of '
      + 'electricity — and it is how you would value an import contract or a terminal expansion.',

      'Leave the cap at 150. The next step fixes the problem properly, which is the point of the module.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'The import limit',
        tab: 'Build',
        note: 'gas_supply\'s p_nom, from effectively unlimited to 150 MW of gas per hour. It is a physical '
          + 'constraint on the fuel chain, and it is about to bind in exactly one hour.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '9,221.11',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Up 1,491 from 7,730, and the peaker is running again. Nothing about the power system '
          + 'changed — the shortage is upstream of it, which is a failure mode a power-only model cannot '
          + 'represent at all.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The 120 returns',
        tab: 'Analytics',
        note: 'MIN · MAX goes back to 0 · 120 — sorry, 20 · 120. The battery from module 4 is still there '
          + 'and still working; it simply cannot cover a shortfall this large on its own.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom (gas_supply)',
        label: 'import limit',
        value: '150',
        unit: 'MW thermal',
        why: 'Enough gas for 75 MW of electricity through the 50% CCGT, against the 100 MW it would want '
          + 'in the peak hour. The 25 MW gap is what the oil peaker fills, at 120 per MWh — and the '
          + 'resulting scarcity price on the gas bus is what the next step removes.',
      },
    ],
    verify: [
      'The objective is 9,221.11',
      'oil_1 produces again in the peak hour and the bus_2 price ends at 120',
      'The gas bus price reads 25, 25, 60',
      'You can say what the 60 means, given that the fuel price is still 25',
      'You can say what one more MWh of import capacity would be worth in that hour',
    ],
    pitfalls: [
      'Reading the gas price of 60 as a fuel price increase. The fuel still costs 25; the 60 is what gas '
      + 'is worth at the margin when supply binds, and the difference is a scarcity rent.',
      'Trying to fix this by raising the CCGT\'s p_nom. The converter is not the constraint — the fuel '
      + 'is, and a bigger turbine with nothing to burn changes nothing.',
    ],
  },

  {
    id: 'm5-gas-store',
    section: SECTION,
    title: 'A store of fuel — buy early, burn later',
    tab: 'Analytics',
    where: 'Build → Storage step, then run again',
    concept: [
      'The import is capped per hour, but the peak demand is only in one hour. That is precisely the '
      + 'shape a store fixes: buy gas in the hours you do not need it, keep it, and burn it when you do.',

      'This is where module 4\'s distinction earns its keep. A StorageUnit would be wrong here — it '
      + 'assumes a device that charges and discharges electricity at one bus. What you want is a Store: '
      + 'a tank on the gas bus, with an energy capacity and no power rating of its own, whose fill and '
      + 'draw rates are set by whatever is attached to it. Gas storage is a cavern or a tank, and that is '
      + 'exactly what a Store models.',

      'With 200 MWh of gas storage the constraint stops binding. The import runs flat out at 150 in the '
      + 'first hour, filling the store while demand is low, and the CCGT draws on it in the peak. The '
      + 'objective returns to 7,730 — the whole 1,491 penalty recovered — and the peaker goes back to '
      + 'never running.',

      'Note what that means: 200 MWh of a cheap commodity store did the job that would otherwise have '
      + 'needed either more pipeline or more peaking plant. Choosing between those three is a real '
      + 'planning question, and it is the kind of question only a model with both sectors in it can even '
      + 'pose.',
    ],
    explain: [
      'Build → Storage. On the right is a "Storage · sheets" switcher listing the two sheets this step '
      + 'owns: `storage_units`, which holds the battery, and `stores`, which module 4 told you to leave '
      + 'empty. Click `stores` and the table switches to it. Add the row there.',

      'A Store has far fewer attributes than a StorageUnit: a bus, an energy capacity `e_nom`, and '
      + '`e_cyclic` to close the loop over the horizon. There is no power rating, because how fast it '
      + 'fills and drains is decided by the import and the CCGT.',

      'Run it. The objective should return to 7,730 — exactly the value it had before the cap, which '
      + 'means the store has completely neutralised the import constraint.',

      'Then read the store\'s energy trace: 150, 110, 0. It fills to 150 in the first hour (the import '
      + 'running flat out while demand is low), gives back a little in the second, and empties in the '
      + 'peak. Cyclic operation forced it to start and end at the same level, exactly as it forced the '
      + 'battery in module 4.',
    ],
    spotlights: [
      {
        selector: '[data-tour="companion-sheets"]',
        buildStep: 'storage',
        title: 'The other sheet on this step',
        tab: 'Build',
        note: 'storage_units holds the battery; stores holds the gas tank. Module 4 drew the distinction '
          + 'and left stores empty — this is the case it was waiting for. Click stores and the table on '
          + 'the left switches to it.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'storage',
        title: 'Far fewer columns',
        tab: 'Build',
        note: 'A Store has a bus, an energy capacity and a cyclic flag. No power rating and no '
          + 'efficiencies, because a tank does not charge itself — whatever is wired to it sets those.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '7,730 again',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The entire 1,491 penalty from the import cap, recovered by 200 MWh of gas storage. The '
          + 'constraint is still there — it simply no longer binds, because the store moves the purchase '
          + 'to an hour when there is room.',
      },
    ],
    entries: [
      {
        field: 'stores.name',
        label: 'store name',
        value: 'gas_store',
        why: 'Identifies the tank in results — its energy trace reports under this name, and that trace is '
          + 'the evidence the strategy worked.',
      },
      {
        field: 'stores.bus',
        label: 'which bus it sits on',
        value: 'bus_gas',
        why: 'The gas bus, so it stores gas. A Store takes its commodity entirely from its bus — the same '
          + 'component on bus_2 would be an electricity store, and on a hydrogen bus a hydrogen cavern.',
      },
      {
        field: 'stores.e_nom',
        label: 'energy capacity',
        value: '200',
        unit: 'MWh thermal',
        why: 'How much gas the tank holds. Only 150 is ever used here, so it is deliberately not the '
          + 'binding limit — the lesson is that the import cap stops mattering, and a store sized exactly '
          + 'to the need would have muddled it with a second constraint.',
      },
      {
        field: 'stores.e_cyclic',
        label: 'must end as it started',
        value: 'true',
        why: 'The same discipline as the battery\'s cyclic_state_of_charge in module 4: the tank must '
          + 'finish at the level it began, so the model cannot start with free gas it never paid for. '
          + 'Without it the store would simply begin full and the saving would be fictional.',
      },
    ],
    verify: [
      'The `stores` sheet has 1 row on bus_gas, and `storage_units` still has just the battery',
      'The objective is back to 7,730',
      'oil_1 produces nothing again and the peak price is back to 50',
      'The store\'s energy trace reads 150, 110, 0 and ends where it started',
      'You can say why a StorageUnit would have been the wrong component here',
    ],
    pitfalls: [
      'Adding the row to `storage_units` instead of `stores`. A StorageUnit on a gas bus is a device that '
      + 'charges and discharges gas at a fixed power rating, which is not what a cavern is — and it will '
      + 'solve, so nothing tells you.',
      'Leaving `e_cyclic` off. The store starts full of gas nobody bought and the objective drops below '
      + '7,730, which looks like a better answer and is an accounting error.',
    ],
  },

  {
    id: 'm5-run-of-river',
    section: SECTION,
    title: 'Run-of-river hydro — variable but not volatile',
    tab: 'Analytics',
    where: 'Build → Carriers, Generators, then its p_max_pu profile',
    concept: [
      'Wind taught you variable generation: `p_max_pu` moving between 0.9 and 0.1 across three hours. '
      + 'Run-of-river hydro is variable in exactly the same mechanical sense and behaves nothing like it.',

      'A run-of-river scheme takes whatever the river is carrying and passes it through a turbine. It has '
      + 'little or no reservoir, so it cannot choose when to generate — but the flow of a river changes '
      + 'over weeks and seasons rather than minutes, so within a day it is close to constant. Here it '
      + 'runs at 0.60, 0.60, 0.55 against wind\'s 0.90, 0.40, 0.10.',

      'That distinction matters more than the label "renewable" does. Two zero-carbon, zero-marginal-cost, '
      + 'non-dispatchable technologies place completely different demands on a system: wind needs backup '
      + 'and flexibility, run-of-river mostly just displaces fuel. Grouping them as "variable renewables" '
      + 'and reasoning about the group is one of the commonest errors in energy commentary.',

      'The distinction it does NOT have is dispatchability. Run-of-river cannot be turned up when you need '
      + 'it — reservoir hydro can, and that is a different technology modelled differently. Steadiness and '
      + 'controllability are separate properties, and only one of them is about the reservoir.',
    ],
    explain: [
      'Three pieces, the same shape as adding wind in module 2. Build → Carriers for `hydro`. Build → '
      + 'Generators for the scheme itself, at bus_1. Then its `p_max_pu` profile.',

      'For the profile, open the Generators time-series panel, click `p_max_pu`, and add a ror_1 column '
      + 'next to the wind_1 one that is already there. The profile sheet has a column per generator, so '
      + 'you are filling a second column in the same three rows.',

      'Run it. The objective falls from 7,730 to 7,145 — 585 saved by 15 MW of hydro running at about '
      + '60%, which is roughly 26 MWh of free energy displacing coal and gas.',

      'Then compare the two profiles on the dispatch chart. Wind\'s output collapses from 54 MW to 6 MW '
      + 'across the three hours; hydro sits at 9, 9, 8.25. Same component type, same marginal cost, same '
      + 'carrier group in most published statistics, and entirely different behaviour.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'A sixth carrier',
        tab: 'Build',
        note: 'hydro, with a zero emission factor. It will carry the pumped-hydro scheme in the next step '
          + 'as well, which is conventional — the two are different technologies sharing a resource.',
      },
      {
        selector: '[data-tour="ts-seed"]',
        buildStep: 'generators',
        title: 'A second profile column',
        tab: 'Build',
        note: 'The p_max_pu sheet already has rows and a wind_1 column, so this control will not be here — '
          + 'you are adding a column to an existing profile rather than seeding a new one. Use the column '
          + 'menu on the grid if ror_1 does not appear automatically.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '7,145',
        tab: 'Analytics',
        runDialog: 'closed',
        note: '585 saved by about 26 MWh of free energy. Roughly 22 per MWh displaced, which sits between '
          + 'coal at 20 and the CCGT at 50 — exactly what you would expect from something that displaces '
          + 'a mix of both.',
      },
    ],
    entries: [
      {
        field: 'carriers.name (new row)',
        label: 'carrier name',
        value: 'hydro',
        why: 'Groups both hydro technologies in results. Real studies often split run-of-river from '
          + 'reservoir and pumped storage precisely because they behave so differently — here one carrier '
          + 'keeps the sheet readable, and the components stay distinct.',
      },
      {
        field: 'carriers.co2_emissions (new row)',
        label: 'emission factor',
        value: '0',
        unit: 'tCO2 per MWh of fuel',
        why: 'No fuel is burnt. Reservoir emissions from flooded vegetation are real and are a lifecycle '
          + 'question, not an operational one — this attribute is what the solver multiplies by fuel '
          + 'consumption, and there is none.',
      },
      {
        field: 'generators.name',
        label: 'generator name',
        value: 'ror_1',
        why: 'Named for the technology. It is also the column header its availability profile must use, '
          + 'and a mismatch there leaves the scheme running flat out in every hour — the same trap as '
          + 'wind in module 2.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'The upstream end, with the coal and the wind. Rivers are where the terrain is, which is the '
          + 'same reason the wind is there — and it means this free energy is behind the congested line, '
          + 'so some of it may not reach the demand.',
      },
      {
        field: 'generators.carrier',
        label: 'technology',
        value: 'hydro',
        why: 'Links it to the carrier you just added, so it groups with the pumped-hydro scheme in '
          + 'per-carrier results and counts as renewable in the renewable-share metric.',
      },
      {
        field: 'generators.p_nom',
        label: 'installed capacity',
        value: '15',
        unit: 'MW',
        why: 'Small, as run-of-river schemes usually are — they are limited by the river rather than by '
          + 'ambition. At about 60% availability it contributes roughly 9 MW steadily, which is enough to '
          + 'matter against a 40 MW minimum demand.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'cost per extra MWh',
        value: '0',
        unit: 'currency per MWh',
        why: 'Free at the margin, like wind — the water arrives whether or not you use it. That puts it at '
          + 'the bottom of the merit order alongside wind, and it is why it displaces fuel rather than '
          + 'competing with it.',
      },
      {
        field: 'generators-p_max_pu.ror_1 (hour 1)',
        label: 'availability, hour 1',
        value: '0.6',
        why: 'A steady 60% of nameplate — the river\'s flow. Compare with wind\'s 0.9 in the same hour: '
          + 'the wind farm is having an exceptional hour, the river is having an ordinary one, and that '
          + 'is the difference this step exists to show.',
      },
      {
        field: 'generators-p_max_pu.ror_1 (hour 2)',
        label: 'availability, hour 2',
        value: '0.6',
        why: 'Unchanged, while wind falls from 0.9 to 0.4. River flow does not vary hour to hour in any '
          + 'meaningful way — its variability is seasonal, and a three-hour model cannot see it at all.',
      },
      {
        field: 'generators-p_max_pu.ror_1 (hour 3)',
        label: 'availability, hour 3',
        value: '0.55',
        why: 'A very slight decline while wind collapses to 0.1. In the hour the system is most stretched, '
          + 'run-of-river is still delivering essentially everything it had — which is precisely the '
          + 'property that makes it more valuable per MWh than its capacity factor suggests.',
      },
    ],
    verify: [
      'The `carriers` sheet has 6 rows and `generators` has 5 (plus the import)',
      'The `generators-p_max_pu` profile has both a wind_1 and a ror_1 column',
      'The objective is 7,145',
      'ror_1 produces about 9, 9, 8.25 MW while wind_1 produces 54, 24, 6',
      'You can say why "variable renewables" is a misleading grouping',
    ],
    pitfalls: [
      'Giving run-of-river a flat p_max_pu of 1. Steady is not the same as full — a river runs at a '
      + 'fraction of turbine capacity almost all the time, and 100% would overstate it by two thirds.',
      'Treating it as dispatchable because it is steady. It cannot be turned up on demand; steadiness and '
      + 'controllability are different properties, and only a reservoir gives you the second.',
    ],
  },

  {
    id: 'm5-pumped-hydro',
    section: SECTION,
    title: 'Pumped hydro — storage where the mountains are',
    tab: 'Analytics',
    where: 'Build → Storage step, then run again',
    concept: [
      'Pumped hydro is the oldest and by far the largest form of grid storage: two reservoirs at different '
      + 'heights, a pump to lift water when power is cheap and a turbine to drop it when power is dear. '
      + 'Round-trip efficiency around 0.75 to 0.80, durations of six to twenty hours, and lifetimes '
      + 'measured in generations.',

      'It is a StorageUnit, exactly like the battery — same component, different numbers. 30 MW and six '
      + 'hours gives 180 MWh, nine times the battery\'s energy, at 0.87 each way against the battery\'s '
      + '0.9.',

      'And there is one thing you do not get to choose. Pumped hydro needs height, water and geology, '
      + 'which means it is built where the mountains are. In this model that is bus_1 — the upstream end, '
      + 'behind the congested line. You cannot site it at the demand end, because the demand end is a '
      + 'plain.',

      'Module 4 measured what that costs: an identical battery was worth 1,670 at bus_2 and 627 at bus_1. '
      + 'Here the same lesson arrives as a fact of geography rather than a choice, and the result is '
      + 'stark. Watch what 180 MWh buys you.',
    ],
    explain: [
      'Build → Storage. Add a second row to `storage_units` — the battery stays exactly as it is.',

      'Run it. The objective falls from 7,145 to 7,099.59: the pumped-hydro scheme is worth 45.',

      'Sit with that number. It has nine times the energy of the battery module 4 added, and the battery '
      + 'was worth 1,670. This one is worth 45 — about three per cent — and the only difference is which '
      + 'side of a 60 MW line it sits on.',

      'The reason is the same as module 4 step 8. To be useful in the peak hour, energy stored at bus_1 '
      + 'has to cross a line that is already carrying everything it can. The scheme can absorb surplus '
      + 'upstream easily enough, but it cannot deliver into the hour that matters.',

      'The practical conclusion is not "pumped hydro is worthless" — it is that storage and transmission '
      + 'are complements, and a storage business case computed without the network is not a business '
      + 'case. If you want this scheme to earn, you build the line as well, and module 3 already showed '
      + 'you how to measure whether that is worth it.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'A second storage unit',
        tab: 'Build',
        note: 'Two rows now: the 20 MW battery at bus_2 and the 30 MW pumped-hydro scheme at bus_1. Same '
          + 'component type, an order of magnitude apart in energy, and about to be two orders apart in '
          + 'value.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: '7,099.59',
        tab: 'Analytics',
        runDialog: 'closed',
        note: '45 for 180 MWh of storage, against 1,670 for the battery\'s 20 MWh in module 4. If you take '
          + 'one number away from this module, take these two side by side.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Two stores, two behaviours',
        tab: 'Analytics',
        note: 'The chart groups by carrier, so the AC battery and the hydro scheme appear separately. The '
          + 'battery cycles hard; the pumped hydro barely moves, because there is nothing useful for it to '
          + 'do from where it stands.',
      },
    ],
    entries: [
      {
        field: 'storage_units.name (new row)',
        label: 'scheme name',
        value: 'phs_1',
        why: 'Identifies the pumped-hydro scheme separately from the battery in every result. Keeping the '
          + 'two distinct is what lets you compare their value per MWh, which is the point of the step.',
      },
      {
        field: 'storage_units.bus (new row)',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'The upstream end — not a choice, but a consequence of needing mountains. This is the cell '
          + 'that costs the scheme almost all of its value, and unlike module 4\'s battery you cannot '
          + 'simply move it.',
      },
      {
        field: 'storage_units.carrier (new row)',
        label: 'carrier',
        value: 'hydro',
        why: 'Groups it with the run-of-river scheme in per-carrier results. It is still storing and '
          + 'returning electricity — the carrier here is a technology label, which is why the state-of-'
          + 'charge chart separates it from the AC battery.',
      },
      {
        field: 'storage_units.p_nom (new row)',
        label: 'power rating',
        value: '30',
        unit: 'MW',
        why: 'Larger than the battery\'s 20 MW, as pumped hydro usually is. Power was never this scheme\'s '
          + 'limitation, which is worth noting before concluding it needed to be bigger — module 4 showed '
          + 'that past the binding limit, more is worth nothing.',
      },
      {
        field: 'storage_units.max_hours (new row)',
        label: 'hours at full power',
        value: '6',
        unit: 'h',
        why: 'Six hours at 30 MW is 180 MWh — nine times the battery. Typical of a real scheme, and the '
          + 'number that makes the result shocking: nine times the energy, three per cent of the value.',
      },
      {
        field: 'storage_units.efficiency_store (new row)',
        label: 'pumping efficiency',
        value: '0.87',
        why: 'Slightly worse than a battery each way, giving a round trip near 0.76. Pumped hydro trades '
          + 'efficiency for scale, duration and a working life measured in generations rather than years.',
      },
      {
        field: 'storage_units.efficiency_dispatch (new row)',
        label: 'generating efficiency',
        value: '0.87',
        why: 'The turbine half of the round trip. Together with pumping it means about a quarter of the '
          + 'energy is lost per cycle — acceptable when the energy being stored would otherwise be spilled.',
      },
      {
        field: 'storage_units.cyclic_state_of_charge (new row)',
        label: 'must end as it started',
        value: 'true',
        why: 'Same discipline as everything else with a state: the reservoir must finish where it began, '
          + 'so the model cannot start the run with a free full upper lake.',
      },
    ],
    verify: [
      'The `storage_units` sheet has 2 rows, and the battery is unchanged at bus_2',
      'The objective is 7,099.59',
      'You can state what the pumped-hydro scheme was worth, and compare it with module 4\'s battery',
      'You can say why it could not simply be built at bus_2',
      'You can say what would have to change for it to be worth more',
    ],
    pitfalls: [
      'Concluding pumped hydro is a bad technology. It is a very good technology in the wrong place for '
      + 'this network — and the model is telling you the network is the problem, not the scheme.',
      'Sizing it bigger to compensate. Power and energy were both ample; the constraint is the line, and '
      + 'no amount of reservoir fixes a full wire.',
    ],
  },

  {
    id: 'm5-what-changed',
    section: SECTION,
    title: 'What module 5 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'A bus is a balance point for any commodity, and a Link is a converter between two of them. Those '
      + 'two ideas together are the whole of sector coupling: gas, heat, hydrogen and power are the same '
      + 'machinery with different labels, and a CCGT, an electrolyser and a heat pump are the same '
      + 'component with different efficiencies.',

      'Fuel is a price AND a quantity. Separating it from the generator let you reprice it in one cell '
      + 'and watch the electricity price follow, cap it and watch a peaker return, and store it and watch '
      + 'the problem disappear. None of those were expressible while the fuel price was buried in a '
      + 'marginal cost.',

      'A scarcity price is not a commodity price. The gas bus read 25 when supply was ample and 60 in the '
      + 'hour it bound, with the fuel price unchanged throughout — and that 35 difference is what an '
      + 'extra MWh of import capacity would have been worth.',

      'And technologies are not their categories. Run-of-river and wind share a carrier group, a marginal '
      + 'cost and a lack of dispatchability, and behave completely differently. Pumped hydro and a battery '
      + 'are the same component type, and one was worth thirty-seven times more per MWh than the other '
      + 'because of where it could be built.',
    ],
    explain: [
      'Three limits to name.',

      'Everything is still fixed. The CCGT\'s size, the import limit, the store, both storage schemes and '
      + 'the line are all given, so the model can tell you what each is worth but never what to build. '
      + 'Module 6 adds capital costs and lets it choose — and it is worth noticing how many "what should '
      + 'we build" questions this module raised: more pipeline, more storage, more peaking plant, or more '
      + 'wire, all substitutes for the same problem.',

      'Three hours is still not a horizon, and it is now doing real damage. A gas store that cycles daily '
      + 'is being represented over three hours; a seasonal store could not be represented at all; and '
      + 'run-of-river\'s variability is seasonal, so this model literally cannot see it. Module 7 is about '
      + 'time — resolution, representative periods and rolling horizon — and it is the module that makes '
      + 'the rest of them credible.',

      'And there is still no policy. The carbon numbers you typed in modules 1 and 2 have sat unused for '
      + 'five modules; the gas carrier has an emission factor of 0.2 and it has never once changed an '
      + 'answer. Module 8 turns them on, and the sector-coupled structure you built here is what makes a '
      + 'carbon price work properly — it lands on the fuel, where the carbon actually is.',

      'Export the project before you go.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: '7,099.59 to serve the same 290 MWh of demand that cost 12,000 in module 1. Five modules, '
          + 'one unchanged demand profile, and every saving from giving the optimiser a better description '
          + 'of the world rather than asking less of it.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Who sets the price now',
        tab: 'Analytics',
        note: 'Compare with module 2, where oil, gas and wind each set the price a third of the time. A '
          + 'store, a network, a battery and two hydro schemes later, the expensive units barely appear — '
          + 'and that shift is what all this structure bought.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. Module 6 ships this model as a checkpoint, but a file you saved '
          + 'yourself is the one you will trust when the two disagree.',
      },
    ],
    verify: [
      'You can explain what a Link is and give three examples from different sectors',
      'You can say why a fuel price belongs on a gas bus rather than in a generator\'s marginal cost',
      'You can tell a commodity price from a scarcity rent, and say what each one means',
      'You can name two technology pairs from this module that look alike and behave differently',
      'The model reads 7,099.59, and you have exported it',
    ],
    pitfalls: [
      'Reading the pumped-hydro result as a verdict on the technology. It is a verdict on this network, '
      + 'and the fix is a wire rather than a different reservoir.',
      'Assuming sector coupling always lowers cost. It lowered the cost here because it revealed a store '
      + 'that was worth having. Modelled honestly, it just as often reveals constraints a power-only '
      + 'model was pretending did not exist.',
    ],
  },
];
