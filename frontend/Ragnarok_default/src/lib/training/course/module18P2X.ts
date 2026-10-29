/**
 * Module 18 — Power-to-X (9 steps).
 *
 * Module 5 drew a fuel bus and a conversion Link by hand. This module adds a whole
 * power-to-hydrogen chain the way Ragnarok builds one — one composite from the Composites
 * tab — reads what it costs per kilogram, and then applies the
 * rule that decides whether that hydrogen counts as renewable: RFNBO matching under
 * Commission Delegated Regulation (EU) 2023/1184. The question it answers is the one a
 * developer asks: what does hourly matching do to the electrolyser, the storage and
 * the levelised cost, compared with matching the volume over a longer period?
 *
 * The system is `training_m18_start`: one bus, one March week of 2030, 120 MW of
 * solar and 100 MW of wind (both built in 2029) and 400 MW of gas at 70 against
 * 150-205 MW of demand. Gas sets the price in every one of the 168 hours. Every figure
 * below is pinned in ``backend/tests/test_training_checkpoints.py``
 * (``test_module_18_*``), solved through the app's own path (``run_pypsa``) and read
 * back through the P2X results (``p2x/results.py``) at a 5% discount rate:
 *
 *   no electrolyser            total cost 1,163,072; price 70 in all 168 hours; 6,646.1 tCO2
 *   P2X plant, no matching     1,819,359; 51.30 MW at 94.0%; no H2 store; LCOH 4.34 per kg
 *   monthly matching           identical: the week's 11,036 designated MWh cover the 8,100 drawn
 *   hourly matching            1,898,786; 66.43 MW at 72.6%; 651.5 MWh store; LCOH 4.87 (+12.1%)
 *   emissions, all three       9,886.1 tCO2: +3,240 t, 21.4 kg CO2 per kg of hydrogen
 *   ammonia, hourly / none     LCOA 1,070.4 / 989.9 per t; the store moves to a 622.5 MWh NH3 tank
 *
 * Technology numbers come from `backend/app/p2x/technologies.json` (PyPSA
 * technology-data v0.15.0 and the Danish Energy Agency catalogue, EUR2025, technology
 * year 2030), each with its source and a `verified` flag the Composites tab shows.
 */
import { TutorialStep } from '../types';

const SECTION = '18 · Power-to-X';

export const MODULE_18_P2X: TutorialStep[] = [
  {
    id: 'm18-the-grid',
    section: SECTION,
    title: 'A grid where gas sets every price',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    startOptions: {
      prebuiltExampleId: 'training_m18_start',
      completeExampleId: 'training_m18',
      note:
        'Module 18 starts from its own small grid rather than module 17\'s: one bus over one March week of 2030 '
        + 'with 120 MW of solar, 100 MW of wind and 400 MW of gas. The prebuilt option has no P2X chain; the '
        + 'finished one has the P2X plant this module adds. The RFNBO matching setting is a Composites → Rules setting, not '
        + 'part of the workbook, so neither checkpoint carries it.',
    },
    concept: [
      'Power-to-X is electricity turned into a molecule. An electrolyser splits water into hydrogen using '
      + 'electricity; the hydrogen can be stored, sold, or turned into something easier to ship — ammonia, '
      + 'methanol, a synthetic liquid fuel. In a power-system model the electrolyser is a LOAD on the grid and a '
      + 'SUPPLY on a new hydrogen bus, and the one question that decides almost everything about its cost is '
      + 'what electricity it runs on.',

      'So read the grid before adding anything to it. Demand here runs between 150 and 205 MW. Solar (120 MW) '
      + 'and wind (100 MW) never produce more than that, so every renewable MWh is used and gas is the marginal '
      + 'unit in all 168 hours. The price is 70 in every hour. That is deliberate: it makes the electricity price '
      + 'flat, so whatever changes in this module is caused by the hydrogen rules, not by the price.',

      'It also means something easily missed. Any EXTRA MWh this grid is asked for comes from gas. An '
      + 'electrolyser connected to it adds gas generation in every hour it runs, whatever contract it signs. '
      + 'Step 7 comes back to this.',
    ],
    explain: [
      'Load the prebuilt model. Settings → Simulation window should cover all 168 snapshots at 1 h. Press Run '
      + 'and Run model; one week of a one-bus LP solves in about a second.',

      'Read it. Total cost 1,163,072. The KPI strip\'s Min · Max price reads 70 · 70, peak load 200 MW, and '
      + 'renewables supply 39.9% of the energy. The 11,036 MWh the wind and solar could make over the week are '
      + 'all used — none is curtailed — and the system emits 6,646.1 tCO2 (the Emissions breakdown card totals it as 6.6 '
      + 'ktCO2e; its per-generator table gives gas, the only emitter, to the tonne).',

      'Note the two renewable generators\' build_year: 2029. It does nothing to this single-period solve. It is '
      + 'there because the RFNBO additionality rule in step 6 tests when a renewable plant came into operation.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'One price all week',
        tab: 'Analytics',
        note: 'Min · Max 70 · 70: gas is the marginal unit in every hour, because the renewables never cover the '
          + 'demand on their own. Any electricity added to this grid is gas-fired at the margin.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Who sets the price',
        tab: 'Analytics',
        note: 'Gas, in all 168 hours. Wind and solar are inframarginal: they run whenever they can and never set '
          + 'the price. Keep this in mind when the electrolyser is "matched" to them later.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['168 snapshots, one bus, no P2X yet — about a second.'],
      expect: 'Total cost 1,163,072; Min · Max 70 · 70; renewables 39.9%; 6,646.1 tCO2.',
    },
    verify: [
      'The KPI strip reads Total cost 1,163,072 and Min · Max 70 · 70',
      'No solar or wind is curtailed: all 11,036 MWh are used',
      'You can say which unit supplies an extra MWh in any hour of this week, and why',
    ],
    pitfalls: [
      'Starting from module 17\'s model. Its noon surplus at zero price would make the electrolyser\'s answer a '
      + 'question about free electricity, which is a different lesson.',
      'Reading the renewable share (39.9%) as the share of renewable electricity an electrolyser here would get. '
      + 'The share is an average; the electrolyser\'s marginal MWh is gas in every hour.',
    ],
  },

  {
    id: 'm18-technology-data',
    section: SECTION,
    title: 'Where the electrolyser\'s numbers come from',
    tab: 'Composites',
    where: 'Composites → Add a composite → Technology data used',
    concept: [
      'A P2X chain is a handful of conversions, and each conversion is a few numbers: how much electricity per '
      + 'kilogram, what it costs to build, how long it lasts, how often it is available. Ragnarok keeps them in '
      + 'one data file, backend/app/p2x/technologies.json, and never in the code. Every value carries its source '
      + '(document, sheet or row, year) and a verified flag: file (read from the source file), derived (computed '
      + 'from file values), literature-recalled (a published value not re-read in this build).',

      'The alkaline electrolyser (AEC, 100 MW plant, technology year 2030, Danish Energy Agency via PyPSA '
      + 'technology-data v0.15.0, EUR2025): 53.57 kWh of electricity per kg of hydrogen; 691.5 EUR per kW '
      + 'overnight; fixed O&M 4% of that a year; 25 years. With hydrogen\'s lower heating value of 33.33 kWh/kg '
      + 'the efficiency is 33.33 / 53.57 = 0.6222 — 62% of the electricity ends up as hydrogen energy.',

      'Three smaller numbers become the electrolyser\'s marginal cost. The stack (145.2 EUR/kW) wears out after '
      + '92,500 hours: 145,159 / 92,500 = 1.569 per MWh of electricity. It uses 185.2 kg of water per MWh at '
      + '0.7285 per m3: 0.135 per MWh. Together 1.704 per MWh. Availability 0.9399 (derived from a 3% forced and '
      + '11 days a year planned outage) caps the output in every hour. The compressed-hydrogen tank, compressor '
      + 'included, costs 60.05 EUR per kWh of hydrogen stored, 1.11% a year, 30 years.',

      'Not every value is file-verified. The minimum load (15% of nominal input) is literature-recalled, and is '
      + 'only enforced on a fixed-size electrolyser — this module lets the solver size it, so it is not.',
    ],
    explain: [
      'Open the Composites tab (in the activity bar, right after Model) and its Add a composite section. Choose '
      + 'Composite type P2X chain. Below the form, Technology data used lists the technologies the chain reads, one '
      + 'table each, with the source document, the locator, the year and the verified flag in every row.',

      'Find the Alkaline electrolyser (AEC) table and check: specific energy 53.565843, capex 691.534046, fom 4, '
      + 'lifetime 25, stack capex 145.159019, stack lifetime hours 92500, water use 185.169748, availability '
      + '0.939863 (derived) and min load 15 (literature-recalled). Then the Compressed H2 tank: capex 60.0469, '
      + 'fom 1.1133, lifetime 30.',

      'You will not type any of these. The same form reads the same file. A value is overridden under Advanced → '
      + 'Parameter overrides; that does not change the file.',

      'Note the basis line above the tables: EUR, 2025 prices. Ragnarok applies no exchange rate, and labels '
      + 'money with the Settings → Project defaults → Currency symbol ($ unless you changed it). The P2X results '
      + 'in this module are therefore EUR figures whatever symbol they wear.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Composites"]',
        title: 'The Composites tab',
        note: 'The composites in the model and their connections, Add a composite, the rules and the results. Everything it builds is ordinary PyPSA components merged '
          + 'into the working model; there is no separate engine.',
      },
      {
        selector: '[data-testid="technology-data"]',
        title: 'Technology data, with sources',
        tab: 'Composites',
        note: 'Each row names its source document, sheet or row, and year. The chip is the verified flag: file, '
          + 'derived or literature-recalled. Check the flag before you quote a number from it.',
      },
    ],
    verify: [
      'You found specific energy 53.565843 kWh/kg and capex 691.534046 EUR/kW for the alkaline electrolyser',
      'You can derive the efficiency 0.6222 from 33.33 and 53.57',
      'You can say which two numbers make up the electrolyser\'s 1.704 per MWh marginal cost',
      'You can name one parameter that is not file-verified and say what that means',
    ],
    pitfalls: [
      'Quoting an efficiency without its heating value. 33.33 kWh/kg is the LOWER heating value, and every '
      + 'hydrogen MW in the chain is on that basis; an efficiency quoted on the higher heating value describes the '
      + 'same machine with a bigger number.',
      'Reading the dollar sign on a P2X result as dollars. The technology data is EUR2025 and no exchange rate '
      + 'is applied.',
    ],
  },

  {
    id: 'm18-add-the-chain',
    section: SECTION,
    title: 'Add the P2X chain as a composite',
    tab: 'Composites',
    where: 'Composites → Add a composite',
    concept: [
      'Ragnarok builds a P2X chain from ordinary PyPSA components, and the Composites tab adds one as ONE composite. '
      + 'For hydrogen it is four things. A new BUS for hydrogen, carrier H2, where energy is counted in MW of '
      + 'hydrogen on the LHV basis. The ELECTROLYSER, a Link from the grid bus to the hydrogen bus with '
      + 'efficiency 0.6222: one MW of electricity in, 0.6222 MW of hydrogen out. A STORE on the hydrogen bus, the '
      + 'tank. And the OFFTAKE, a Load on the hydrogen bus — the customer.',

      'The derivatives add steps after the hydrogen bus. Ammonia, methanol and e-fuel synthesis each take '
      + 'hydrogen and something else (nitrogen, CO2) plus some electricity: several inputs, one output. Those are '
      + 'PyPSA Processes, with rate0 = -1 on the hydrogen input and one rate per further port. Step 8 adds one.',

      'Three choices in the picker shape the answer. Letting the solver size it makes the electrolyser '
      + 'extendable: the model buys the MW it is worth, so its utilisation becomes a RESULT, not an input. The '
      + 'tank is extendable too. And the offtake is flat: 30 MW of hydrogen every hour, which is 0.9 t an hour, '
      + '151.2 t over the week. The customer does not care when the hydrogen was made; the tank decouples the two.',

      'The chain also needs to know which renewable generators the electrolyser buys from — its PPA — before any '
      + 'matching rule can be applied. The Connections section of the form has them as a list of the model\'s '
      + 'generators to tick. It also asks which bus the electrolyser draws from and which bus the hydrogen goes to.',
    ],
    explain: [
      'Composites → Add a composite: Composite type P2X chain. Under Connections leave Electricity bus blank (the first '
      + 'electricity bus, grid) and H2 bus blank (a new one), and tick solar and wind under Renewable supply matched '
      + 'to. Leave Plant name blank (it becomes p2x). Tick Let the solver size it. Product H2, H2 storage tank, '
      + 'Product offtake 30.',

      'The schematic under the form draws grid to the electrolyser to the new hydrogen bus, with the offtake and the '
      + 'store on it. Advanced holds the discount rate, which already reads 0.05, from Settings.',

      'The preview line reads Creates: 1 buses, 3 carriers, 1 links, 1 stores, 1 loads. The warning under it says '
      + 'fom_cost is written per modelled horizon (fixed O&M a year x 0.0191781 years for 168 hours): re-apply the plant '
      + 'if you change the snapshots. Press Add P2X chain.',

      'The In this model table below now has p2x. Expand it: p2x_bus_h2, the carriers, p2x_electrolyser (links), '
      + 'p2x_h2_store (stores) and p2x_load_H2 (loads). Open the Links step and find p2x_electrolyser: bus0 grid, '
      + 'bus1 p2x_bus_h2, efficiency 0.62222488, marginal_cost 1.704183, overnight_cost 691534.046, p_max_pu '
      + '0.939863, p_nom_extendable true. Every number is the data file\'s.',
    ],
    spotlights: [
      {
        selector: '[data-testid="composite-form"]',
        title: 'Connections first, then a few fields',
        tab: 'Composites',
        note: 'P2X chain with a bus, a capacity choice, the product, the storage and the offtake. Everything else is '
          + 'derived from the technology file; Advanced holds the discount rate and the escape-hatch overrides.',
      },
      {
        selector: '[data-testid="composite-table"]',
        title: 'The chain is one composite',
        tab: 'Composites',
        note: 'Edit re-derives every component from the stored spec; Delete removes them all and keeps any bus or '
          + 'carrier another component still uses. Step 8 uses Edit to switch the product.',
      },
      {
        selector: '[data-build-step="links"]',
        buildStep: 'links',
        title: 'The electrolyser is a Link',
        tab: 'Build',
        note: 'p2x_electrolyser draws from grid at bus0 and delivers 0.6222 of it to the hydrogen bus at bus1. A '
          + 'Link, not a Generator, because it consumes one carrier to make another.',
      },
    ],
    entries: [
      {
        field: 'Composites → Add a composite → Composite type, Let the solver size it',
        label: 'what to add, and who sizes it',
        value: 'P2X chain; ticked',
        why: 'An extendable electrolyser lets the model choose the MW, so the capacity factor and the storage are '
          + 'answers the matching rule can change. A fixed size would hide most of what step 6 shows.',
      },
      {
        field: 'Composites → Add a composite → Product, H2 storage, Product offtake',
        label: 'the product and its customer',
        value: 'H2, tank, 30',
        unit: 'MW (LHV)',
        why: 'A flat 30 MW of hydrogen, 151.2 t over the week. The tank is extendable and cyclic: it may be built if '
          + 'storing hydrogen is cheaper than more electrolyser, and must end the week where it started.',
      },
      {
        field: 'Composites → Add a composite → Connections → Renewable supply matched to',
        label: 'the designated renewable generators',
        value: 'solar and wind ticked',
        why: 'The generators the electrolyser is matched to under the RFNBO rules. Without them a solve with '
          + 'matching switched on is refused before it starts, with a message saying why.',
      },
    ],
    verify: [
      'The In this model table shows p2x with 7 rows, solver-sized',
      'p2x_electrolyser is a Link from grid to p2x_bus_h2 with efficiency 0.62222488 and p_max_pu 0.939863',
      'p2x_load_H2 is 30 MW on p2x_bus_h2',
      'You can say why the electrolyser is a Link and the ammonia synthesis will be a Process',
    ],
    pitfalls: [
      'Leaving Let the solver size it unticked. The picker then builds a fixed 100 MW electrolyser and the '
      + 'numbers in the next steps will not match.',
      'Forgetting the designated generators. Matching has nothing to match to, and the solve with matching on is '
      + 'refused with a 400 before it starts — which is the right behaviour, not a bug.',
    ],
  },

  {
    id: 'm18-solve-without-a-rule',
    section: SECTION,
    title: 'Solve with no rule, and read the levelised cost',
    tab: 'Composites',
    where: 'Run dialog, then Composites → Results',
    concept: [
      'With no matching rule the electrolyser buys whatever is cheapest. Here every hour costs 70, so the cheapest '
      + 'way to make 30 MW of hydrogen is the SMALLEST electrolyser that can: run it at its availability limit in '
      + 'every hour and build no tank at all. That is 51.30 MW, running at 94.0% — its availability, 0.9399. '
      + '8,233 full-load hours a year.',

      'The levelised cost of hydrogen (LCOH) is everything the chain costs over the window divided by the '
      + 'kilograms it made: 4.34 per kg. It splits into 3.75 for electricity, 0.32 for the electrolyser\'s capital, '
      + '0.18 fixed O&M, 0.08 stack wear and 0.01 water. The electricity term is easy to check by hand: 70 per MWh x '
      + '53.57 kWh/kg / 1,000 = 3.75. Electricity is 86% of the cost, which is why the rest of this module is about '
      + 'which electricity.',

      'Capital is charged as PyPSA charges it: the overnight 691,534 per MW annuitised at 5% over 25 years and '
      + 'pro-rated to the 168-hour window. The P2X results read that effective cost back from the network, so the '
      + 'LCOH is the model\'s own number and not a separate calculation.',
    ],
    explain: [
      'Run. Total cost 1,819,359: the chain adds 656,287 to the week.',

      'Open Composites → Results and pick the run you just made in Stored run (Electricity cost: Nodal price x '
      + 'consumption). The KPI cards read LCOH 4.34 per kg (151.2 t H2 · electricity nodal) and Electrolyser '
      + 'capacity factor 94% (8,233 full-load h/yr · 51.3 MW). The H2 store state of charge is flat at zero: no tank '
      + 'was built.',

      'The Cost waterfall (Product Hydrogen) shows the five steps adding to 4.34. Hover them: 3.75, 0.32, 0.18, '
      + '0.08, 0.01.',

      'Then the last KPI, Hourly compliant hours: 64.9%, 1,327.9 MWh unmatched · matching off. The compliance '
      + 'table is computed from the dispatch whether or not matching was on: in 109 of the 168 hours solar and wind '
      + 'together produced at least the electrolyser\'s 48.2 MW, and in the other 59 they did not. On the monthly '
      + 'row it is 100%: over the week the designated plant made more than the electrolyser drew.',
    ],
    spotlights: [
      {
        selector: 'nav[aria-label="Composites sections"]',
        title: 'Open Results',
        tab: 'Composites',
        note: 'Results reads a stored run: pick it in Stored run. Every number on the panel is computed by the '
          + 'backend from that run\'s model and series; the panel only draws it.',
      },
      {
        selector: '.p2x-kpis',
        title: 'LCOH and capacity factor',
        tab: 'Composites',
        note: 'LCOH 4.34 per kg; capacity factor 94%, which is the availability: the electrolyser runs flat out '
          + 'every hour because nothing makes one hour cheaper than another.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['The same week with the chain in it — still about a second.'],
      expect: 'Total cost 1,819,359; LCOH 4.34 per kg; electrolyser 51.3 MW at 94%; no tank.',
    },
    verify: [
      'Total cost reads 1,819,359',
      'Composites → Results shows LCOH 4.34 and an electrolyser capacity factor of 94% at 51.3 MW',
      'The waterfall\'s electricity step is 3.75, and you can derive it from 70 and 53.57',
      'Hourly compliant hours reads 64.9% with matching off',
    ],
    pitfalls: [
      'Reading Composites → Results with no run selected, or an older run. It reads the stored run picked in Stored run, '
      + 'not the model on screen.',
      'Taking 94% as a design choice. Nobody chose it: it is what a flat price and a free choice of size produce. '
      + 'Change the price shape and it changes.',
    ],
  },

  {
    id: 'm18-monthly-matching',
    section: SECTION,
    title: 'Match the volume: monthly matching',
    tab: 'Composites',
    where: 'Composites → Rules, then Run dialog',
    concept: [
      'Hydrogen counts as a renewable fuel of non-biological origin (RFNBO) in the EU only if its electricity meets '
      + 'the Delegated Regulation\'s rules. Its Article 6 is TEMPORAL correlation: in each matching period the '
      + 'electrolyser may not use more electricity than its designated renewable generators produced in the same '
      + 'period. Until the end of 2029 the period may be a calendar month; from 1 January 2030 it is one hour '
      + '(a Member State may bring that forward to 1 July 2027).',

      'In the model it is one inequality per period: the sum over the period of the electrolyser\'s weighted '
      + 'electricity is at most the same sum of the designated generators\' output. Hourly means one row per '
      + 'snapshot; monthly one row per calendar month. The regulation has no annual option. But on a one-week window '
      + 'a month is the whole window, so monthly matching here is exactly a VOLUME match — the kind of matching an '
      + 'annual certificate scheme does.',

      'And a volume match costs nothing here. Over the week solar and wind made 11,036 MWh; the electrolyser drew '
      + '8,100. The constraint is slack, so the solution is unchanged: same cost, same 51.30 MW, same LCOH. A rule '
      + 'that does not bind does not change the answer, however good it sounds.',
    ],
    explain: [
      'Composites → Rules. Tick RFNBO matching on, set Temporal correlation to Monthly (calendar month), leave the rest, '
      + 'and press Save settings. The settings are stored for this session and ride with the next solve.',

      'A warning appears: the model starts in 2030, so monthly matching is no longer accepted from 1 January 2030. '
      + 'The tool lets you run it anyway — that is the comparison — but a monthly result would not demonstrate '
      + 'compliance for a 2030 plant.',

      'The right-hand card, Checks before the solve, lists p2x_electrolyser and the designated solar and wind, and '
      + 'passes both on additionality and geography. Step 7 says what those passes do and do not mean.',

      'Run. Total cost 1,819,359 — identical. Composites → Results for the new run: LCOH 4.34, 51.3 MW, 94%.',
    ],
    spotlights: [
      {
        selector: 'nav[aria-label="Composites sections"]',
        title: 'Open RFNBO',
        tab: 'Composites',
        note: 'Matching rules on the left, the checks before the solve on the right. Save settings stores them for '
          + 'the session; a run that sets its own rfnboConfig through the API ignores them.',
      },
    ],
    entries: [
      {
        field: 'Composites → Rules → RFNBO matching on, Temporal correlation',
        label: 'switch matching on, monthly',
        value: 'ticked; Monthly (calendar month)',
        why: 'Adds one constraint for the whole window: electrolyser MWh at most designated MWh. On a one-week model '
          + 'that is a volume match, the loosest form of the rule.',
      },
      {
        field: 'Composites → Rules → Save settings',
        label: 'store the settings for the next solve',
        value: 'press it',
        why: 'The settings are a run option kept outside the workbook. Without saving, the next solve runs with '
          + 'whatever was saved before — possibly nothing.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One extra constraint row; the solve time does not change.'],
      expect: 'Total cost 1,819,359, the same as with no matching; LCOH 4.34.',
    },
    verify: [
      'RFNBO shows matching on, Monthly, and the 2030 warning',
      'Total cost reads 1,819,359, unchanged',
      'You can say why monthly matching on this window is a volume match, and why it does not bind',
    ],
    pitfalls: [
      'Concluding that monthly matching is free in general. It is free here because the week had more renewable '
      + 'energy than the electrolyser needed; a dark week, or a bigger electrolyser, would make it bind.',
      'Forgetting Save settings. The RFNBO panel edits a draft until it is saved.',
    ],
  },

  {
    id: 'm18-hourly-matching',
    section: SECTION,
    title: 'Hourly matching: more electrolyser, a tank, a higher LCOH',
    tab: 'Composites',
    where: 'Composites → Rules, Run dialog, then Composites → Results',
    concept: [
      'Hourly matching applies the same inequality in every hour. The electrolyser may now run only as hard as '
      + 'solar and wind are producing in that hour. At night with little wind it must slow down or stop — but the '
      + 'customer still wants 30 MW every hour.',

      'The model answers in two ways at once. It buys a BIGGER electrolyser, so that it can make more hydrogen '
      + 'in the hours when the wind and sun are there: 66.43 MW instead of 51.30. And it builds a TANK to carry '
      + 'hydrogen from those hours to the others: 651.5 MWh, about 21.7 hours of the 30 MW offtake. The same 8,100 MWh '
      + 'of electricity now flows through more MW, so the capacity factor falls from 94.0% to 72.6% (6,358 '
      + 'full-load hours a year).',

      'The LCOH rises from 4.34 to 4.87 per kg: +0.53, or 12.1%. Read the waterfall to see where. Electricity is '
      + 'unchanged at 3.75 — the price is 70 in every hour, matched or not. Electrolyser capital goes from 0.32 to '
      + '0.41 and fixed O&M from 0.18 to 0.23, because there are more MW; the tank adds 0.38. Hourly matching is paid '
      + 'for in hardware.',

      'On a real grid the electricity term would move too: matched hours tend to be windy and sunny ones, which '
      + 'are cheaper. Here the flat price isolates the hardware effect on purpose. Total cost rises 79,427 for the week.',
    ],
    explain: [
      'Composites → Rules: Temporal correlation Hourly (every snapshot), Save settings. Run.',

      'Total cost 1,898,786. Composites → Results for the new run: LCOH 4.87; capacity factor 72.6% at 66.4 MW (6,358 '
      + 'full-load h/yr); Hourly compliant hours 100%, 0 MWh unmatched.',

      'Look at the two charts. Electrolyser dispatch against the designated RES: the electrolyser line never rises '
      + 'above solar plus wind — the constraint, hour by hour. H2 store state of charge: the tank fills on the windy, '
      + 'sunny days and empties through the calm middle of the week (days 3 and 4, when the wind is at its weakest). Its '
      + 'peak is 651.5 MWh on day 2, about 19.5 t of hydrogen; it is empty on day 4 and refills from day 5.',

      'Compare the waterfalls of the two runs side by side: the same 3.75 of electricity, a bigger capital block, and '
      + 'a storage block that was not there.',
    ],
    spotlights: [
      {
        selector: '.p2x-kpis',
        title: 'LCOH 4.87, capacity factor 72.6%',
        tab: 'Composites',
        note: 'The same hydrogen, the same electricity, more electrolyser and a tank. Utilisation falls because the '
          + 'MW grew, not because the electricity fell: 8,100 MWh either way.',
      },
    ],
    entries: [
      {
        field: 'Composites → Rules → Temporal correlation',
        label: 'match every hour',
        value: 'Hourly (every snapshot); Save settings',
        why: 'One constraint per snapshot. The electrolyser follows the designated output; the tank carries the '
          + 'hydrogen to the hours it cannot run. This is the rule for a plant producing from 2030.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['168 matching rows instead of one — still about a second.'],
      expect: 'Total cost 1,898,786; electrolyser 66.43 MW at 72.6%; tank 651.5 MWh; LCOH 4.87.',
    },
    verify: [
      'Total cost reads 1,898,786',
      'Composites → Results shows LCOH 4.87, capacity factor 72.6% at 66.4 MW, and 100% hourly compliance',
      'The H2 store peaks at 651.5 MWh',
      'You can say which waterfall steps grew and why the electricity step did not',
    ],
    pitfalls: [
      'Comparing LCOHs from runs with a different offtake or product. The comparison is fair only because the '
      + 'customer, the price and the technology are identical across the three runs.',
      'Reading the 12.1% as a general cost of hourly matching. It depends on how the renewable output is shaped '
      + 'over the week; a steadier designated fleet would need less tank and less extra electrolyser.',
    ],
  },

  {
    id: 'm18-what-matching-does-not-do',
    section: SECTION,
    title: 'What matching changes, and what it does not',
    tab: 'Analytics',
    where: 'Analytics → Result (emissions), then Composites → Results',
    concept: [
      'Look at the system emissions across the three runs: 9,886.1 tCO2 with no matching, 9,886.1 with monthly, '
      + '9,886.1 with hourly. Identical. The chain added 3,240 t to the week (from 6,646.1), which is the 8,100 MWh '
      + 'it drew times 0.4 t per MWh — the gas plant\'s 0.20 t per MWh of fuel at 50% efficiency. Per kilogram of '
      + 'hydrogen that is 21.4 kg of CO2.',

      'Hourly matching changed WHEN the electrolyser ran, not WHERE its electricity came from. Solar and wind were '
      + 'already fully used by the grid before the electrolyser arrived — nothing was curtailed in step 1 and nothing '
      + 'is now — so every MWh the electrolyser takes, in any hour, is replaced by gas. The match is an accounting '
      + 'statement about a contract; the physics is the marginal unit.',

      'That is what the regulation\'s ADDITIONALITY rule (Article 5) is for: the designated plant should be new, '
      + 'built for the electrolyser, so that its output is additional to what the grid already had. Ragnarok checks it '
      + 'as a date test: the designated plant came into operation no earlier than 36 months before the electrolyser. '
      + 'Here both pass — 2029 is within three years of 2030. The model, which knows the plant was already serving '
      + 'the grid, shows the date test is not the same thing as system additionality.',

      'Article 4 offers a different route — grid electricity counts as renewable if the zone is above 90% '
      + 'renewable. The Additionality, geography and grid alternatives card reports it: 30.9%, fail.',
    ],
    explain: [
      'Open Analytics on each of the three runs (History → tick the run → View result) and read the Emissions '
      + 'breakdown card: Total emissions 9.9 ktCO2e every time, and the gas row of its per-generator table 9,886.1 t, '
      + 'against 6,646.1 with no chain.',

      'Composites → Results, the Additionality, geography and grid alternatives card: solar and wind pass Additionality '
      + '(Art. 5(a)) and Geographic correlation (Art. 7(1)(a)); Art. 4(1) renewable share 30.9%, fail. Read the Why '
      + 'column of the additionality rows: it names the years it compared.',

      'Nothing to change in the model. The experiment that would test real additionality — a NEW wind farm built '
      + 'for the electrolyser and designated in place of the existing ones — is a two-line change you can try on '
      + 'your own copy; it is not part of the checkpoint.',
    ],
    spotlights: [
      {
        selector: '[data-card="emissions-breakdown"]',
        title: 'Emissions, three runs',
        tab: 'Analytics',
        note: 'The same 9,886.1 t from gas with no matching, monthly and hourly. The rule moved the electrolyser in '
          + 'time; the grid still burned gas for every MWh it took.',
      },
    ],
    verify: [
      'All three runs emit 9,886.1 tCO2, 3,240 t more than the grid without the chain',
      'You can say why hourly matching did not reduce emissions in this model',
      'You can say the difference between the additionality date test and system additionality',
    ],
    pitfalls: [
      'Calling matched hydrogen zero-carbon because the matching table is green. The table checks a contract; '
      + 'the emissions are on the Analytics side.',
      'Concluding that hourly matching never cuts emissions. On a grid with curtailed renewables, or with a new '
      + 'designated plant, the electrolyser\'s MWh can be genuinely additional — the next experiment to run.',
    ],
  },

  {
    id: 'm18-ammonia',
    section: SECTION,
    title: 'Ammonia: two Processes, and the storage moves downstream',
    tab: 'Composites',
    where: 'Composites → In this model → p2x → Edit, then Build → Processes',
    concept: [
      'Hydrogen is hard to store and ship; ammonia is easier. Switching the product turns the chain into an ammonia '
      + 'plant. The electrolyser and hydrogen bus stay; three things are added. An AIR SEPARATION UNIT makes '
      + 'nitrogen from electricity: a Process from grid to a nitrogen bus, rate1 = 4.0 t of N2 per MWh. The '
      + 'HABER-BOSCH synthesis takes hydrogen, electricity and nitrogen and makes ammonia: a Process with rate0 = -1 '
      + 'on hydrogen, rate1 = 0.8708 MWh of ammonia, rate2 = -0.2153 MWh of electricity and rate3 = -0.1391 t of '
      + 'nitrogen per MWh of hydrogen in (from 1.1484 MWh H2, 0.2473 MWh electricity and 0.1597 t N2 per MWh NH3 in '
      + 'the data file). And an ammonia TANK and offtake on the new NH3 bus.',

      'The levelised cost of ammonia (LCOA) is the ammonia\'s share of the hydrogen cost plus the synthesis, the '
      + 'nitrogen, the electricity the synthesis draws and the tank, divided by the tonnes. 30 MW of ammonia (LHV) '
      + 'for a week is 974.85 t. With no matching it is 989.9 per t; with hourly matching 1,070.4 per t, 8.1% more.',

      'The interesting change is where the storage goes. Under hourly matching the model builds only a 107.8 MWh '
      + 'hydrogen tank and a 622.5 MWh AMMONIA tank: it runs the synthesis with the electrolyser and stores the '
      + 'product. Per MWh stored the hydrogen tank costs 60,046.9 overnight and the ammonia tank 211.8 — 283 times '
      + 'less. The electrolyser grows to 89.35 MW at 62.0%.',

      'One honest limit: the Haber-Bosch loop is free to ramp from zero to full in an hour here. The data file '
      + 'records a 20% minimum load for it, and the chain does not enforce it. A real ammonia plant run under hourly '
      + 'matching needs more buffer than this model builds.',
    ],
    explain: [
      'Composites → In this model: Edit on p2x. The form opens with the stored spec; change Product to '
      + 'NH3 and press Save changes. The offtake (30 MW) now applies to ammonia.',

      'Build → Processes: p2x_asu and p2x_synth_NH3, with the rates above. Build → Stores: p2x_h2_store and '
      + 'p2x_store_NH3. Build → Loads: p2x_load_NH3, 30 MW.',

      'RFNBO matching is still Hourly from step 6. Run: Total cost 2,206,577. Composites → Results: LCOA 1,070 per t NH3 '
      + '(974.9 t produced); electrolyser capacity factor 62% at 89.4 MW.',

      'Composites → Rules: untick RFNBO matching on, Save settings, run: 2,128,063; LCOA 990 per t; electrolyser 58.9 MW at '
      + '94%; no tank of either kind.',

      'Put the model back to the checkpoint: Edit p2x, Product H2, Save changes. The chain is re-derived exactly as '
      + 'step 3 built it. Leave RFNBO matching off.',
    ],
    spotlights: [
      {
        selector: '[data-plant="p2x"]',
        title: 'Edit the composite, not its rows',
        tab: 'Composites',
        note: 'Edit re-derives every component from the stored spec with your change laid over it, and removes what '
          + 'no longer belongs. Editing the rows by hand would leave the registry describing a different chain.',
      },
      {
        selector: '[data-build-step="processes"]',
        buildStep: 'processes',
        title: 'Two Processes',
        tab: 'Build',
        note: 'p2x_asu (grid to nitrogen) and p2x_synth_NH3 (hydrogen, electricity and nitrogen to ammonia). rate0 is '
          + '-1 on the main input; the other rates are per unit of it, negative for inputs.',
      },
    ],
    entries: [
      {
        field: 'Composites → In this model → p2x → Edit → Product',
        label: 'the product the chain makes',
        value: 'NH3, then back to H2',
        why: 'Re-derives the chain with an air separation unit, Haber-Bosch synthesis and an ammonia tank. Switching '
          + 'back restores the module\'s checkpoint exactly.',
      },
      {
        field: 'Composites → Rules → RFNBO matching on',
        label: 'the comparison run',
        value: 'unticked; Save settings',
        why: 'The second ammonia run is without matching, so the LCOA can be compared like for like. It also leaves '
          + 'the session in the state the checkpoint assumes.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (twice)',
      detail: ['Hourly matching on, then off. Three more buses and two Processes — still about a second each.'],
      expect: '2,206,577 with LCOA 1,070.4 per t under hourly matching; 2,128,063 and 989.9 per t without.',
    },
    verify: [
      'Build → Processes shows p2x_asu and p2x_synth_NH3; rate1 of the synthesis is 0.87077673',
      'Under hourly matching LCOA reads 1,070 per t and the ammonia tank peaks at 622.5 MWh',
      'Without matching LCOA reads 990 per t',
      'The plant is back to Product H2 and RFNBO matching is off',
    ],
    pitfalls: [
      'Reading the Haber-Bosch flexibility as real. The model lets the synthesis follow the electrolyser hour by '
      + 'hour; a real loop has a minimum load, and this model does not enforce the 20% the data file records.',
      'Comparing an LCOA with an LCOH. One is per tonne of ammonia, the other per kilogram of hydrogen; the ammonia '
      + 'figure contains the hydrogen\'s cost already.',
    ],
  },

  {
    id: 'm18-what-changed',
    section: SECTION,
    title: 'What module 18 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'A P2X chain is ordinary components: a bus per energy carrier, a Link for the electrolyser, Processes for the '
      + 'multi-input syntheses, Stores for the tanks and Loads for the customers. The Composites tab writes them from a '
      + 'data file whose every number has a source and a verified flag.',

      'The levelised cost is a decomposition of the model\'s own costs, and on a grid like this one electricity '
      + 'is most of it: 3.75 of 4.34 per kg.',

      'Hourly matching is paid for in electrolyser MW and storage, not in electricity price, on a flat-price grid: '
      + 'capacity factor 94.0% to 72.6%, a 651.5 MWh tank, LCOH +12.1%. A volume match over a long enough window '
      + 'need not bind at all.',

      'And matching is not emissions. A contract with existing renewables that the grid already used changes when '
      + 'the electrolyser runs, not what the grid burns: 21.4 kg of CO2 per kg of hydrogen in all three runs here.',
    ],
    explain: [
      'Three limits to name.',

      'One week, one bus, one price. A real case needs a year — the calm weeks decide the tank — and a price that '
      + 'moves, which would let matched hours be cheaper hours.',

      'Flexibility the model gives for free: the electrolyser and the synthesis ramp from zero to full in an hour, '
      + 'with no minimum load, no start cost and no degradation from cycling.',

      'The rules are partly checks, not constraints: additionality and geography are tested and reported, and '
      + 'Article 5(b) (no operating or investment aid) cannot be read from a model at all.',

      'Export the project before you go — Model → Export project.',
    ],
    spotlights: [
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. The bundled checkpoint holds the same workbook; the RFNBO settings are a '
          + 'session setting and are not in either.',
      },
    ],
    verify: [
      'The model holds the p2x plant with Product H2, solver-sized, a tank and a 30 MW offtake',
      'Total cost reads 1,819,359 with RFNBO matching off',
      'You can say what hourly matching changed in the electrolyser, the storage and the LCOH, and what it did not change',
      'You have exported the project',
    ],
    pitfalls: [
      'Generalising the 12.1%. It belongs to this week\'s wind and sun, this flat price and this offtake.',
      'Leaving RFNBO matching on for an unrelated model in the same session. The saved setting rides with every '
      + 'solve until it is switched off.',
    ],
  },
];
