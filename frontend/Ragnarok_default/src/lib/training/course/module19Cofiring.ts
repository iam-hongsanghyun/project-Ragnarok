/**
 * Module 19 — Gas + H2 co-firing and CCGT operations (10 steps).
 *
 * Module 5 drew a CCGT as a Link from a gas bus; module 11 committed a coal unit by
 * hand. This module uses the thermal composites of the Composites tab: a CCGT, then a gas + H2
 * co-firing plant whose fuel is a blend the solver chooses within limits, and then
 * the operating detail a CCGT is now modelled with — minimum load, minimum up and
 * down times stated in hours, part-load efficiency and start costs that depend on how
 * long the unit was off.
 *
 * The co-firing plant follows PyPSA's multi-input pattern: a gas bus and an H2 bus each
 * feed a turbine-fuel bus through a Link at efficiency 1 (MW on the LHV basis), and the
 * turbine is a Link from that fuel bus to the grid. The blend limit is a constraint on
 * the two feeder Links (`backend/app/plants/cofiring.py`), entered as a volume share or
 * an energy share, hourly or over the period.
 *
 * The system is `training_m19_start`: one bus, three June days, 250 MW of solar against
 * a 297 MW evening peak, a 400 MW oil peaker at 160 and an `h2` bus with a 50 MW
 * pipeline at 100 per MWh. Every figure below is pinned in
 * ``backend/tests/test_training_checkpoints.py`` (``test_module_19_*``), solved through
 * ``run_pypsa`` and read through the plant results (``plants/results.py``):
 *
 *   no turbine                 total cost 1,747,786; prices 0 (6 h) and 160 (66 h)
 *   gas-only CCGT, 200 MW      720,242; 4,234.15 tCO2; 9,749.3 MWh at 67.7%
 *   co-firing, cap 30 vol%     720,242 again: no hydrogen is burned
 *   30 vol% min and max        857,775; 11.43% of the energy; 380.41 t avoided; 361.5 per t
 *   0.3 typed as energy        1,367,673; 58.7 vol%; the pipeline caps the turbine
 *   25 MW pipeline             hourly 1,108,100 and 5,139.97 t; period 932,632, pure H2 at noon
 *   unit commitment            904,948; 2 starts; off 5 h at noon on the sunny days
 *   part-load 0.52             917,524; no-load fuel 26.5 MW_th
 *   warm start 120 after 5 h   926,779; the stop shortens to 4 h and both starts stay hot
 *
 * Technology numbers come from `backend/app/plants/technologies.json` (PyPSA
 * technology-data v0.15.0 and the Danish Energy Agency catalogues, EUR2025), each with
 * a source and a verified flag. The values the file does not have — efficiency at
 * minimum load, warm-start costs — are typed by the learner and called assumptions.
 */
import { TutorialStep } from '../types';

const SECTION = '19 · Gas + H2 co-firing and CCGT operations';

export const MODULE_19_COFIRING: TutorialStep[] = [
  {
    id: 'm19-the-system',
    section: SECTION,
    title: 'Solar, an expensive peaker and a hydrogen pipeline',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    startOptions: {
      prebuiltExampleId: 'training_m19_start',
      completeExampleId: 'training_m19',
      note:
        'Module 19 starts from its own small system: one bus over three June days with 250 MW of solar, a 400 MW '
        + 'oil peaker at 160 and a separate h2 bus with a 50 MW hydrogen pipeline at 100 per MWh. The prebuilt '
        + 'option has no gas turbine; the finished one has the committed 200 MW co-firing CCGT the module ends with.',
    },
    concept: [
      'A gas turbine can burn hydrogen mixed into its gas. How much depends on the combustion system, and the '
      + 'limit is usually quoted as a share of the fuel by VOLUME. The question this module asks is what a blend '
      + 'does to cost and emissions, and how to tell the model about it correctly — because a volume share and an '
      + 'energy share of the same fuel are very different numbers.',

      'The system is built to make the turbine matter. Solar covers the middle of the day; the evening peak of 297 '
      + 'MW is carried by an oil peaker at 160 per MWh. A CCGT on gas at 28.4 would displace it. The h2 bus holds a '
      + 'pipeline: up to 50 MW of hydrogen at 100 per MWh. Nothing can burn it yet.',
    ],
    explain: [
      'Load the prebuilt model, press Run and Run model: 72 snapshots, an instant solve.',

      'Total cost 1,747,786. Prices take two values: 0 in the 6 hours when solar is in surplus, 160 in the other 66. '
      + 'The load-weighted average is 148.4; peak load 297 MW; renewables supply 27.5% of the energy; the system '
      + 'emits 8,426.8 tCO2. The pipeline delivers nothing: no component on the h2 bus asks for hydrogen.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Two prices',
        tab: 'Analytics',
        note: 'Min · Max 0 · 160. Solar sets zero at the noon surplus, the peaker sets 160 everywhere else. Any '
          + 'plant cheaper than 160 that can run in the evening will be worth having.',
      },
    ],
    run: {
      label: 'Run → Run model',
      detail: ['72 snapshots, one bus, no turbine — instant.'],
      expect: 'Total cost 1,747,786; prices 0 (6 h) and 160 (66 h); 8,426.8 tCO2.',
    },
    verify: [
      'The KPI strip reads Total cost 1,747,786 and Min · Max 0 · 160',
      'The h2_pipeline generator delivers 0 MWh',
    ],
    pitfalls: [
      'Starting from module 18\'s grid. It has no h2 bus with a pipeline, and its flat price would hide every '
      + 'operating effect this module looks for.',
      'A run refused with "RFNBO matching is on but the model has no electrolyser". Module 18\'s matching setting is '
      + 'stored for the session, not the workbook: untick RFNBO matching on in Composites → Rules and Save settings.',
    ],
  },

  {
    id: 'm19-gas-only-ccgt',
    section: SECTION,
    title: 'A gas-only CCGT from the Composites tab',
    tab: 'Composites',
    where: 'Composites → Add a composite',
    concept: [
      'The Composites tab\'s CCGT is three components. A GAS BUS, a gas SUPPLIER on it (a generator at the gas price, '
      + 'sized by the solver), and the turbine: a Link from the gas bus to the grid with the CCGT\'s efficiency. The '
      + 'Link\'s p_nom is measured on its INPUT, so 200 MW of electricity at 0.58 is 200 / 0.58 = 344.8 MW of fuel, '
      + 'and its variable O&M is written per MWh of fuel: 5.61 x 0.58 = 3.254.',

      'The numbers come from backend/app/plants/technologies.json. From PyPSA technology-data v0.15.0 and the Danish '
      + 'Energy Agency (file-verified): efficiency 0.58, overnight 1,108.7 EUR/kW, fixed O&M 3.35% a year, VOM 5.61 '
      + 'per MWh, 25 years, minimum load 0.4, ramp 15% of capacity a minute; gas at 28.4158 per MWh and 0.198 tCO2 '
      + 'per MWh of gas. Flagged as Ragnarok ASSUMPTIONS, because the pinned data files have no value: a start-up '
      + 'cost of 60 per MW, minimum up and down times of 4 hours, and a hydrogen price of 100 per MWh.',

      'The CCGT\'s marginal cost is 28.4158 / 0.58 + 5.6104 = 54.60 per MWh. That is the new price wherever it is '
      + 'the marginal unit.',
    ],
    explain: [
      'Composites → Add a composite: Composite type CCGT (gas combined cycle), Plant name ccgt, Capacity 200, leave '
      + 'Let the solver size it and Unit commitment unticked. Press Add CCGT.',

      'The Links step now has ccgt from ccgt_bus_gas to grid, efficiency 0.58, p_nom 344.827586, marginal_cost '
      + '3.254032; the Generators step has ccgt_gas_supply at 28.4158.',

      'Run. Total cost 720,242. Prices: 0 in 6 hours, 54.60 in 47, 160 in 19 (the evening hours above 200 MW). '
      + 'System emissions 4,234.15 tCO2: the Emissions breakdown card totals them to 0.1 kt (4.2 ktCO2e) and its '
      + 'per-generator table gives the gas supplier and the peaker to the tonne. This module quotes the sum.',

      'Analytics → Result has a Composites card with one row per composite, and Composites → Results shows the same '
      + 'table for any stored run (the API read is /api/build/plant/results/{run name}; the MCP tool get_plant_results '
      + 'returns the same). For ccgt it reports '
      + 'generationMwh 9,749.3, capacityFactor 0.677 and starts 3, counted from the dispatch because the unit is '
      + 'not committable.',
    ],
    spotlights: [
      {
        selector: '[data-testid="composite-form"]',
        title: 'CCGT (gas combined cycle)',
        tab: 'Composites',
        note: 'Connections, a capacity and a few fields; Advanced shows the defaults come from the ccgt technology entry. '
          + 'The preview lists what it will create before anything is applied.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The peaker mostly gone',
        tab: 'Analytics',
        note: 'Total cost 720,242. Min · Max still 0 · 160: the peaker still sets the price in the 19 evening hours '
          + 'the 200 MW CCGT cannot cover.',
      },
    ],
    entries: [
      {
        field: 'Composites → Add a composite → Composite type, Plant name, Capacity',
        label: 'the gas-only reference plant',
        value: 'CCGT (gas combined cycle), ccgt, 200',
        unit: 'MW',
        why: 'Fixed 200 MW of electrical output. This run is the reference every blend is compared with: same turbine, '
          + 'same size, gas only.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One gas bus, one supplier, one Link more — instant.'],
      expect: 'Total cost 720,242; 4,234.15 tCO2; ccgt 9,749.3 MWh at a capacity factor of 0.677.',
    },
    verify: [
      'ccgt is a Link with p_nom 344.827586 and efficiency 0.58',
      'Total cost reads 720,242 and the CCGT sets 54.60 in 47 hours',
      'You can derive 54.60 from the gas price, the efficiency and the VOM',
    ],
    pitfalls: [
      'Reading the Link\'s p_nom as electrical MW. It is fuel in; electrical output is p_nom x efficiency.',
      'Quoting the 60 per MW start cost or the 4-hour minimum times as data. The file marks them as assumptions.',
    ],
  },

  {
    id: 'm19-cofiring-cap',
    section: SECTION,
    title: 'The co-firing plant, and a cap that does nothing',
    tab: 'Composites',
    where: 'Composites → In this model, then Add a composite',
    concept: [
      'The co-firing plant (fuel network) keeps gas and hydrogen as separate fuels until the turbine. A gas bus and '
      + 'the h2 bus each feed a TURBINE-FUEL bus through a Link at efficiency 1 — a gas feeder and an H2 feeder — '
      + 'and the turbine is a Link from the fuel bus to the grid. That is PyPSA\'s multi-input pattern: a bus where '
      + 'two fuels meet, so the solver chooses the blend hour by hour, and the blend limit is a constraint on the '
      + 'two feeders.',

      'Set only a MAXIMUM hydrogen share of 30 vol% and run, and the answer is the gas-only CCGT\'s to the unit: '
      + '720,242, and no hydrogen at all. A cap allows hydrogen; it does not require it. Hydrogen at 100 per MWh is '
      + 'dearer than gas at 28.4, and nothing in the objective rewards the 0.198 t of CO2 each MWh of gas emits.',

      'How much would have to? The gap is 100 - 28.4158 = 71.58 per MWh of fuel, and a MWh of hydrogen burned '
      + 'instead of gas avoids 0.198 t. A carbon price of 71.58 / 0.198 = 361.5 per tonne closes it. Below that, '
      + 'hydrogen is burned only if something forces it.',
    ],
    explain: [
      'Composites → In this model: Delete on ccgt and confirm (Delete composite). Then Add a composite: Composite type Gas + H2 '
      + 'co-firing (fuel network), Plant name cofire, Capacity 200, H2 bus h2, Maximum H2 share 0.3, Share basis '
      + 'vol, Applies hourly. Leave Minimum H2 share blank.',

      'The preview reads Creates: 5 carriers, 2 buses, 1 generators, 3 links. The two buses are cofire_bus_gas and '
      + 'cofire_bus_fuel; the generator is the gas supplier; the links are cofire_gas_feed, cofire_h2_feed and the '
      + 'turbine cofire. The h2 bus is the existing one, already fed by the pipeline, so no H2 supplier is added. '
      + 'Press Add Gas + H2 co-firing.',

      'Run. Total cost 720,242. The plant results report fuel h2MwhTh 0.',
    ],
    spotlights: [
      {
        selector: '[data-testid="composite-table"]',
        title: 'Delete the CCGT as one composite',
        tab: 'Composites',
        note: 'Delete removes the plant\'s Link, supplier, bus and carriers together. The confirmation lists what '
          + 'goes and what stays because another component still uses it.',
      },
      {
        selector: '[data-build-step="links"]',
        buildStep: 'links',
        title: 'Two feeders and a turbine',
        tab: 'Build',
        note: 'cofire_gas_feed and cofire_h2_feed carry fuel into cofire_bus_fuel at efficiency 1; cofire burns it at '
          + '0.58. The blend constraint is written on the two feeders, not on the turbine.',
      },
    ],
    entries: [
      {
        field: 'Composites → Add a composite → Composite type, Plant name, Capacity, H2 bus',
        label: 'the co-firing turbine',
        value: 'Gas + H2 co-firing (fuel network), cofire, 200, h2',
        why: 'The same 200 MW turbine as the CCGT, now able to draw from the pipeline\'s bus as well as from a gas bus. '
          + 'Blank H2 bus would create a new one with its own supplier at the H2 price.',
      },
      {
        field: 'Composites → Add a composite → Maximum H2 share, Share basis, Applies',
        label: 'the combustor limit',
        value: '0.3, vol, hourly',
        why: 'A fraction in the basis chosen: 0.3 vol is 30% of the fuel by volume. Hourly makes it hold in every '
          + 'snapshot, which is what a combustion system needs.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['Two fuel buses and three Links instead of one — instant.'],
      expect: 'Total cost 720,242, the gas-only answer; no hydrogen burned.',
    },
    verify: [
      'The In this model table holds cofire only, with 11 rows',
      'Total cost reads 720,242',
      'You can say why a maximum share alone burns no hydrogen, and what carbon price would change that',
    ],
    pitfalls: [
      'Adding the co-firing plant without deleting the CCGT. Two 200 MW turbines would compete and none of the '
      + 'numbers below would match.',
      'Leaving H2 bus blank. The plant then makes its own hydrogen supplier with no pipeline limit, and step 6\'s '
      + 'experiment has nothing to bind.',
    ],
  },

  {
    id: 'm19-blend-mandate',
    section: SECTION,
    title: 'Force 30 vol%: what it costs and what it avoids',
    tab: 'Composites',
    where: 'Composites → In this model → cofire → Edit',
    concept: [
      'Set the minimum share to 0.3 as well and the blend is fixed: 30% of the fuel by volume, every hour. In '
      + 'energy that is much less. A normal cubic metre of hydrogen carries 10.78 MJ and one of methane 35.8 MJ — '
      + 'the data file\'s lower heating values — so the energy share is 0.3 x 10.78 / (0.3 x 10.78 + 0.7 x 35.8) = '
      + '3.234 / 28.294 = 0.1143. Thirty per cent by volume is 11.43% of the energy, and only that 11.43% of the '
      + 'gas, and of its CO2, is displaced.',

      'The file is open about those two constants: 10.78 is DERIVED (hydrogen\'s 119.96 MJ/kg times its normal '
      + 'density) and 35.8 is LITERATURE (pure methane); neither was re-read from a source in this build, and a '
      + 'real natural gas carries a little more energy per cubic metre than pure methane. The conversion is only as '
      + 'good as those two numbers.',

      'The result. Total cost 857,775: 137,533 more than gas alone. The turbine runs exactly as before — 9,749.3 '
      + 'MWh — but burns 1,921.3 MWh of hydrogen (57,644 kg) in 16,809.1 MWh of fuel. The plant results report the '
      + 'CO2 avoided as 0.198 x 1,921.3 = 380.41 t, and the system\'s emissions fall by exactly that, from 4,234.15 '
      + 'to 3,853.74, because nothing else in the dispatch moved.',

      'Divide the two: 137,533 / 380.41 = 361.5 per tonne avoided. It is the same 361.5 as step 3\'s break-even '
      + 'carbon price, as it must be: every tonne avoided costs one MWh of hydrogen swapped for 1 / 0.198 MWh of gas.',
    ],
    explain: [
      'Build → Generators → Plants: Edit on cofire. Set Minimum H2 share 0.3 and press Save changes.',

      'Run. Total cost 857,775. Wherever the turbine is the marginal unit the price is now 68.71, not 54.60: '
      + '(0.8857 x 28.4158 + 0.1143 x 100) / 0.58 + 5.6104.',

      'Plant results (/api/build/plant/results/{run name}): fuel h2EnergyShare 0.1143, h2VolShare 0.30, h2MwhTh '
      + '1,921.3, h2KgEquivalent 57,644; emissions avoidedT 380.41 against a gasOnlyBaselineT of 3,328.2; cofiring '
      + 'minHourlyVolShare and maxHourlyVolShare both 0.30 over the 66 hours the turbine runs.',
    ],
    spotlights: [
      {
        selector: '[data-plant="cofire"]',
        title: 'Edit the composite',
        tab: 'Composites',
        note: 'The form opens with the stored spec. Set Minimum H2 share and Save changes: the plant is re-derived '
          + 'with the new blend limits stored with it, and the next solve applies them.',
      },
    ],
    entries: [
      {
        field: 'Composites → In this model → cofire → Edit → Minimum H2 share',
        label: 'the blend mandate',
        value: '0.3',
        why: 'With the maximum also at 0.3 the share is fixed at 30 vol% in every hour. It is what a supply contract '
          + 'or a policy target would impose; the turbine limit alone never would.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['Two blend rows per snapshot — instant.'],
      expect: 'Total cost 857,775; 11.43% of the energy is hydrogen; 380.41 t avoided.',
    },
    verify: [
      'Total cost reads 857,775',
      'The plant results show h2VolShare 0.30 and h2EnergyShare 0.1143',
      'You can compute 11.43% from 30 vol% and the two LHVs, by hand',
      'You can say why the cost per tonne avoided equals the break-even carbon price',
    ],
    pitfalls: [
      'Reporting "30% hydrogen" as 30% less CO2. It is 11.43% less from this plant.',
      'Reading avoidedT as a system figure. It compares the plant with the same dispatch burnt on gas; here the two '
      + 'agree only because the dispatch did not change. Step 6 shows a case where they do not.',
    ],
  },

  {
    id: 'm19-wrong-basis',
    section: SECTION,
    title: 'The same 0.3 on the energy basis',
    tab: 'Composites',
    where: 'Composites → In this model → cofire → Edit',
    concept: [
      'The plant\'s Share basis decides what 0.3 means. Switch it from vol to energy and 0.3 is 30% of the ENERGY — '
      + 'which is (0.3 / 10.78) / (0.3 / 10.78 + 0.7 / 35.8) = 58.7% by volume. Nearly twice the volume share of '
      + 'step 4, and beyond what most turbine combustion systems accept.',

      'It costs 1,367,673, against 857,775. The turbine now needs 30% of its fuel energy from a pipeline that can '
      + 'deliver 50 MW, so its fuel is capped at 50 / 0.3 = 166.7 MW and its output at 96.7 MW. It burns 2,875.7 '
      + 'MWh of hydrogen but makes only 5,559.6 MWh (capacity factor 0.386) instead of 9,749.3, and the peaker '
      + 'comes back.',

      'Nothing warns you. Both are valid inputs; only one is what the turbine maker meant.',
    ],
    explain: [
      'Edit cofire: Share basis energy, Save changes, run. Total cost 1,367,673. Plant results: h2VolShare 0.5873, '
      + 'h2MwhTh 2,875.7, generationMwh 5,559.6, capacityFactor 0.386. The pipeline reaches its 50 MW limit in the '
      + 'evening hours, exactly when the turbine is needed most.',

      'Edit cofire back to Share basis vol, Save changes, and run once to confirm 857,775.',
    ],
    entries: [
      {
        field: 'Composites → In this model → cofire → Edit → Share basis',
        label: 'what the 0.3 is a share of',
        value: 'energy, then back to vol',
        why: 'The experiment shows the cost of a unit slip: the same 0.3 typed on the energy basis is 58.7 vol% and '
          + 'more than the pipeline can supply. Restore vol before the next step.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (twice)',
      detail: ['Energy basis, then vol again.'],
      expect: '1,367,673 on the energy basis; 857,775 restored.',
    },
    verify: [
      'On the energy basis Total cost reads 1,367,673 and h2VolShare 0.5873',
      'The plant is back on vol and Total cost reads 857,775',
      'You can convert 30 energy% to 58.7 vol% by hand',
    ],
    pitfalls: [
      'Copying a blend limit from a datasheet without its basis. Turbine limits are usually quoted by volume; '
      + 'policy targets are often by energy. The same number means very different things.',
    ],
  },

  {
    id: 'm19-hourly-or-period',
    section: SECTION,
    title: 'Hourly or over the period, with a pipeline that is too small',
    tab: 'Build',
    where: 'Build → Generators (h2_pipeline), then cofire → Edit',
    concept: [
      'Halve the pipeline to 25 MW and keep the hourly 30 vol% mandate. At full load the turbine needs 39.4 MW of '
      + 'hydrogen; it can only get 25, so its output is capped at 25 / 0.1143 x 0.58 = 126.86 MW. A blend '
      + 'requirement with a limited supply DERATES the plant. It now makes 7,007.2 MWh, the oil peaker makes up the '
      + 'rest, and Total cost is 1,108,100.',

      'And emissions RISE: 5,139.97 tCO2, 905.8 t more than the gas-only CCGT of step 2 — even though the plant '
      + 'results still report 273.42 t "avoided". Both are true. The avoided figure compares the plant with itself '
      + 'on gas; the system figure includes the oil that replaced the output the blend took away. Report the one '
      + 'that answers your question, and say which it is.',

      'Now change Applies to period. The 30 vol% must hold for the TOTAL fuel over the three days, not each hour. '
      + 'Total cost falls to 932,632 and emissions to 4,232.45. But read what the solver did: the pipeline runs at 25 '
      + 'MW in every hour, and in the noon hours, when solar covers the demand, the turbine burns that hydrogen '
      + 'ALONE — 100% hydrogen — just to bank the share it needs to burn more gas in the evening. The plant results\' '
      + 'maxHourlyVolShare reads 1.0.',

      'That is the difference between the two scopes. A period share is a fuel-accounting rule and suits a mandate '
      + 'or a target. A turbine\'s combustion limit is physical and must be HOURLY, or the model will burn a blend '
      + 'no turbine could. With the 50 MW pipeline the two scopes cost the same, 857,775 — hydrogen is equally dear '
      + 'in every hour, so the solver has no reason to move it — and that is exactly when the difference is easy to miss.',
    ],
    explain: [
      'Build → Generators: set h2_pipeline p_nom to 25. Run: Total cost 1,108,100; system emissions 5,139.97 tCO2. '
      + 'Plant results: generationMwh 7,007.2, avoidedT 273.42.',

      'Edit cofire: Applies period, Save changes, run: 932,632; 4,232.45 tCO2; fuel h2MwhTh 1,800.0 (25 MW x 72 h) '
      + 'and h2EnergyShare 0.1143 over the period; cofiring maxHourlyVolShare 1.0.',

      'Restore: Edit cofire, Applies hourly, Save changes; h2_pipeline p_nom back to 50. Run once to confirm 857,775.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'The pipeline is an ordinary generator',
        tab: 'Build',
        note: 'h2_pipeline on the h2 bus, p_nom 50, marginal cost 100. Its p_nom is the experiment: 25 MW is less '
          + 'than the 39.4 MW the turbine needs at full load at 30 vol%.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom (h2_pipeline)',
        label: 'hydrogen the pipeline can deliver',
        value: '25, then back to 50',
        unit: 'MW',
        why: 'At 25 MW an hourly 30 vol% blend caps the turbine at 126.86 MW, so the experiment shows what a blend '
          + 'requirement does when the hydrogen is not there.',
      },
      {
        field: 'Composites → In this model → cofire → Edit → Applies',
        label: 'where the share must hold',
        value: 'period, then back to hourly',
        why: 'Period lets some hours burn more hydrogen than 30 vol% if others burn less. Fine for a target, wrong for '
          + 'a combustor limit; the run shows hours of pure hydrogen.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (three runs)',
      detail: ['Hourly at 25 MW, period at 25 MW, then restored.'],
      expect: '1,108,100 hourly and 932,632 period at 25 MW; 857,775 restored.',
    },
    verify: [
      'At 25 MW hourly, Total cost reads 1,108,100 and emissions 5,139.97 tCO2, above the gas-only CCGT',
      'At 25 MW period, Total cost reads 932,632 and maxHourlyVolShare is 1.0',
      'The pipeline is back at 50 MW, the plant is back on hourly, and Total cost reads 857,775',
      'You can say which scope a turbine limit needs and which a fuel mandate can use',
    ],
    pitfalls: [
      'Taking "avoided" as the system\'s saving. With a supply limit the blend cut the plant\'s output and the '
      + 'system emitted more.',
      'Setting a combustor limit on the period scope because it is cheaper. It is cheaper because the turbine burns '
      + 'fuel it could not burn.',
    ],
  },

  {
    id: 'm19-commitment',
    section: SECTION,
    title: 'Unit commitment: a minimum load and minimum times in hours',
    tab: 'Composites',
    where: 'Composites → In this model → cofire → Edit, then Build → Links → Time units',
    concept: [
      'Every run so far let the turbine run at any output from 0 to 200 MW, and stop and start for free. Module 11 '
      + 'showed what a real plant adds. Tick Unit commitment on the plant and the picker writes three of them onto '
      + 'the turbine Link from the data file: committable, a minimum load p_min_pu of 0.4 (80 MW, file-verified), '
      + 'and a start-up cost of 60 per MW x 200 = 12,000 per start (an assumption).',

      'The minimum up and down times are written differently, and this is new since module 11. PyPSA counts them '
      + 'in SNAPSHOTS: a min_down_time of 4 means four snapshots, which is four hours at 1 h resolution and eight at '
      + '2 h. Ragnarok keeps them in HOURS, in the RAGNAROK_TimeUnits sheet, and converts them at every solve with '
      + 'that run\'s own snapshot length (times = ceil(hours / step)). The plant gets min_up_time and min_down_time 4 '
      + 'hours, up_time_before 4 hours, and a ramp of 0.15 per minute (15% of capacity a minute). At a 1-hour step '
      + 'that ramp is 9 times the capacity an hour — no limit at all — and the preview says so.',

      'The answer: 904,948, 47,173 more than the unconstrained blend. The turbine starts twice. On the two sunny '
      + 'days it stops for 5 hours at noon; on the cloudy second day it stays on at its 80 MW minimum through the '
      + 'middle of the day rather than pay for a stop and a start. It is a MILP now, so there are no prices: the KPI '
      + 'strip reads 0 · 0, for the reason module 11 gave.',
    ],
    explain: [
      'Edit cofire: tick Unit commitment (on/off, minimum load, starts), Save changes. The warning lists the time '
      + 'units: minimum up / down time 4 h / 4 h and a ramp of 15 %/min, stored in hours and per minute.',

      'Build → Links step, then the Time units button: five rows for cofire. Press Preview per-snapshot values: '
      + 'min_up_time, min_down_time and up_time_before read 4 at a step of 1 h; the two ramps read blank (no limit).',

      'Run. Total cost 904,948. On the Generation · dispatch by carrier chart the CCGT band drops to zero for 5 hours '
      + 'around noon on days 1 and 3 and never below 80 MW otherwise: 62 hours online. The plant results report starts 2, '
      + 'startsBasis solved (committable).',

      'Now the minimum down time. In the Time units drawer set cofire\'s min_down_time to 6 and run: 908,725, '
      + 'each noon stop now 6 hours. Set it back to 4 before the next step — and note that the next plant Edit would '
      + 'have reset it anyway, because an edit re-derives the time-unit rows from the data file.',
    ],
    spotlights: [
      {
        selector: '[data-tour="time-units-open"]',
        buildStep: 'links',
        title: 'Time units',
        tab: 'Build',
        note: 'Minimum times in hours and ramps per minute, converted at each solve with the run\'s snapshot length. '
          + 'Preview per-snapshot values shows the converted table without solving.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="dispatch"]',
        title: 'Two noon stops',
        tab: 'Analytics',
        note: 'The CCGT band falls to zero for 5 hours around noon on the two sunny days and sits at its 80 MW minimum '
          + 'through the cloudy middle day: 2 starts, 62 hours online.',
      },
      {
        selector: '[data-card="commitment"]',
        title: 'The commitment card',
        tab: 'Analytics',
        note: 'The committed turbine is listed with its starts and online hours: 2 starts, and the on/off '
          + 'segments show the two noon stops.',
      },
    ],
    entries: [
      {
        field: 'Composites → In this model → cofire → Edit → Unit commitment',
        label: 'make the turbine a committed unit',
        value: 'ticked',
        why: 'Writes committable, p_min_pu 0.4 and a 12,000 start-up cost on the turbine and the time-unit rows for its '
          + 'minimum times. The solve becomes a MILP.',
      },
      {
        field: 'Build → Links → Time units → cofire min_down_time',
        label: 'minimum time offline, in hours',
        value: '6, then back to 4',
        unit: 'h',
        why: 'Typed in hours, converted to snapshots by the run. The 6-hour run shows the constraint binding: each '
          + 'stop lasts 6 hours instead of 5.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (twice)',
      detail: ['A MILP of 72 snapshots — under a second each.'],
      expect: 'Total cost 904,948 with 2 starts; 908,725 with a 6-hour minimum down time.',
    },
    verify: [
      'The Time units drawer shows min_up_time and min_down_time 4 hours, and the preview shows 4 snapshots at 1 h',
      'Total cost reads 904,948; the CCGT is off for 5 hours on days 1 and 3 and the plant results report 2 starts',
      'With min_down_time 6 Total cost reads 908,725',
      'min_down_time is back at 4',
    ],
    pitfalls: [
      'Typing a minimum time into the min_down_time column of the Links sheet. A time-unit row replaces it at the '
      + 'solve, and the column counts snapshots, not hours.',
      'Reading the 0 · 0 prices as free electricity. A commitment run has no duals to price with.',
    ],
  },

  {
    id: 'm19-part-load',
    section: SECTION,
    title: 'Part-load efficiency: fuel that is burned just to stay on',
    tab: 'Composites',
    where: 'Composites → In this model → cofire → Edit → Advanced',
    concept: [
      'A turbine is less efficient at part load. The data file says so — the DEA sheet notes low efficiency at low '
      + 'loads — but gives no number, so the value is plant data you supply. Use 0.52 at the 0.4 minimum load, '
      + 'against 0.58 at full load, as an illustrative assumption.',

      'Two points make a straight fuel line. At full load the unit burns 200 / 0.58 = 344.83 MW of fuel; at minimum '
      + 'load 80 / 0.52 = 153.85. The line through them has a slope — the INCREMENTAL heat rate — of (344.83 - '
      + '153.85) / 120 = 1.5915 MW of fuel per MW of electricity, and it does not pass through zero: it meets the '
      + 'axis at 344.83 - 1.5915 x 200 = 26.53 MW. That is NO-LOAD fuel, burned in every hour the unit is on '
      + 'whatever it produces.',

      'On a Link Ragnarok writes it as PyPSA\'s own piecewise efficiency curve, sheet links-efficiency-pw: '
      + 'breakpoints (0, 0), (0.4462, 0.52) and (1, 0.58), with p_min_pu set to the fuel at minimum load as a '
      + 'fraction of full-load fuel, 153.85 / 344.83 = 0.4462. Because the curve lives on the fuel input, the no-load '
      + 'fuel is real fuel: it flows through the feeders, it is blended at 30 vol%, and it emits CO2.',

      'The cost: 917,524, 12,576 more than with one efficiency at every load; emissions 4,012.96 t instead of '
      + '3,957.62. The schedule is the same — two starts, 5-hour noon stops — but every hour at low output now burns '
      + 'more.',
    ],
    explain: [
      'Edit cofire, open Advanced and set Efficiency at minimum load 0.52. The Derived values box reads: Part-load: '
      + 'fuel 153.8462 MW_th at minimum load (efficiency 0.52), 344.8276 MW_th at full load (0.58); no-load fuel '
      + '26.5252 MW_th, incremental heat rate 1.5915 MW_th/MW_el (incremental efficiency 0.6283). Written as PyPSA\'s '
      + 'piecewise efficiency curve on the Link (sheet links-efficiency-pw), with p_min_pu = 0.446154. Save changes.',

      'Run. Total cost 917,524.',
    ],
    spotlights: [
      {
        selector: '[data-testid="plant-derived"]',
        title: 'Derived values, before you save',
        tab: 'Composites',
        note: 'The heat-rate line the two efficiencies imply, and how it is written into PyPSA. Check the no-load fuel '
          + 'here: it is what makes running at minimum load expensive.',
      },
    ],
    entries: [
      {
        field: 'Composites → In this model → cofire → Edit → Advanced → Efficiency at minimum load',
        label: 'part-load efficiency (plant data)',
        value: '0.52',
        why: 'Not in the data file, so it is your assumption. With 0.58 at full load it gives 26.5 MW of no-load fuel '
          + 'and an incremental efficiency of 0.6283.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['The piecewise curve adds a few rows per snapshot — still under a second.'],
      expect: 'Total cost 917,524; two starts, as before.',
    },
    verify: [
      'links-efficiency-pw has three rows for cofire: (0, 0), (0.446154, 0.52), (1, 0.58)',
      'Total cost reads 917,524',
      'You can derive the 26.53 MW of no-load fuel from the two efficiencies',
    ],
    pitfalls: [
      'Entering a part-load efficiency above the full-load one, or at or below 0.4 x 0.58 = 0.232. The picker '
      + 'refuses both: the first makes the no-load fuel negative, the second leaves the line no positive slope.',
      'Expecting part-load efficiency on a turbine without unit commitment. It needs a committed, fixed-size unit; '
      + 'the picker says so and writes nothing.',
    ],
  },

  {
    id: 'm19-start-tiers',
    section: SECTION,
    title: 'Hot, warm and cold starts: the cost of having been off',
    tab: 'Composites',
    where: 'Composites → In this model → cofire → Edit → Advanced',
    concept: [
      'A CCGT that has been off for a short while is still hot and restarts cheaply; after longer it has cooled and '
      + 'a start wears it more and burns more. PyPSA has one start_up_cost per unit. Ragnarok adds TIERS: the native '
      + 'start_up_cost is the HOT cost, and a warm or cold start, defined by how many hours the unit was offline '
      + 'before it, adds the difference. The rows go in RAGNAROK_StartCosts; the hours are converted with the run\'s '
      + 'step like the minimum times.',

      'The data file has the hot cost (60 per MW, an assumption) and no warm or cold costs, so these are again yours. '
      + 'Use a warm start of 120 per MW after 5 hours offline: 24,000 per start against 12,000 hot.',

      'Watch what the model does with it. In step 7 the turbine stopped for 5 hours at noon — exactly long enough '
      + 'to make its restart warm. It now stops for 4 hours instead, the minimum down time, and runs an extra hour '
      + 'at its minimum load on each sunny day. Both starts stay HOT; no warm start is ever paid. Total cost 926,779, '
      + '9,256 more than step 8: the cost of the extra hours online, which is less than the 2 x 12,000 the warm '
      + 'starts would have added.',

      'Like module 11\'s start cost, the tier changed the schedule rather than the bill. The plant results show '
      + 'starts hot 2, warm 0, and a start cost of 24,000.',
    ],
    explain: [
      'Edit cofire, Advanced: Warm start cost 120, Warm start after 5. Leave Hot start cost blank (the data file\'s '
      + '60) and the cold fields blank. The Derived values box adds: Start costs per start: hot 12,000, warm 24,000 '
      + 'after 5 h offline. PyPSA\'s start_up_cost is the hot cost (12,000); warm and cold add the difference at solve '
      + 'time. Save changes.',

      'Run. Total cost 926,779. On the dispatch chart each noon stop is now 4 hours, with the CCGT at 80 MW in the hour '
      + 'it used to stop: 64 hours online, two more than before. The plant results\' startCosts read starts hot 2, warm 0, '
      + 'startCost 24,000, tierIncrement 0.',

      'This is the module\'s finished model; the checkpoint holds the same plant.',
    ],
    spotlights: [
      {
        selector: '[data-card="chart"][data-card-metric="dispatch"]',
        title: 'Two hours longer online',
        tab: 'Analytics',
        note: 'Each noon stop is 4 hours instead of 5, the extra hour run at the 80 MW minimum: 64 hours online '
          + 'instead of 62, still 2 starts, both hot.',
      },
    ],
    entries: [
      {
        field: 'Composites → In this model → cofire → Edit → Advanced → Warm start cost, Warm start after',
        label: 'the warm tier (assumed)',
        value: '120 and 5',
        unit: 'per MW; h offline',
        why: 'A start after at least 5 hours off costs 24,000 instead of 12,000. Five hours is the length of step 7\'s '
          + 'noon stop, so the tier is placed exactly where the schedule has to choose.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One extra variable per snapshot for the tier — under a second.'],
      expect: 'Total cost 926,779; 2 hot starts, no warm start; 64 hours online.',
    },
    verify: [
      'RAGNAROK_StartCosts has hot_cost 12,000, warm_cost 24,000 and warm_after 5 for cofire',
      'Total cost reads 926,779 and each noon stop on the dispatch chart is 4 hours',
      'You can say why no warm start appears although the warm tier is set',
    ],
    pitfalls: [
      'Setting a warm threshold below the minimum down time. Every stop is then at least that long, so every start is '
      + 'warm and the hot cost never applies.',
      'Reading the DEA warm and cold START TIMES (1 h and 2.5 h for a CCGT in the data file) as offline thresholds. '
      + 'They are how long a start takes, a different number.',
    ],
  },

  {
    id: 'm19-what-changed',
    section: SECTION,
    title: 'What module 19 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'A blend has two bases. Thirty per cent by volume is 11.43% of the energy, computed from two heating values '
      + 'whose provenance you can read in the data file; the plant\'s Share basis is where the difference is decided.',

      'A cap is not a mandate. With hydrogen dearer than gas a maximum share burns none; a minimum share forces it, '
      + 'and the cost per tonne avoided is the break-even carbon price. A blend limited by its supply derates the '
      + 'plant, and the plant\'s avoided CO2 can sit beside a system that emits more.',

      'Hourly and period are different rules. A combustor limit is hourly; a period share lets the solver burn pure '
      + 'hydrogen where it is cheapest to bank the share.',

      'And a CCGT is now operated, not just dispatched: a minimum load, minimum times stated in hours and converted '
      + 'per run, a no-load fuel from a two-point heat-rate line, and start costs that depend on time offline — each '
      + 'changing the schedule more than the bill.',
    ],
    explain: [
      'Three limits to name.',

      'No derate. Burning hydrogen changes a turbine\'s efficiency and sometimes its rating; the data file has no '
      + 'citable number for it, so the derate is a documented zero, off unless you enter your own figure.',

      'A pipeline at a fixed price. Real hydrogen would come from somewhere — module 18\'s electrolyser could feed '
      + 'this h2 bus, and its cost and its matching rules would then set what the blend costs.',

      'Three days. The starts, the stops and the 4-hour choice belong to this sample of sun and demand.',

      'Export the project before you go — Model → Export project.',
    ],
    spotlights: [
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. The bundled checkpoint holds the same model: cofire at a fixed 30 vol% hourly '
          + 'blend, committed, with a part-load efficiency and a warm-start tier.',
      },
    ],
    verify: [
      'The model reads: cofire 200 MW on h2, 0.3 vol min and max hourly, committed, 0.52 at minimum load, warm 120 after 5 h',
      'h2_pipeline is 50 MW and min_down_time is 4 hours',
      'Total cost reads 926,779',
      'You have exported the project',
    ],
    pitfalls: [
      'Carrying a leftover experiment forward: a 25 MW pipeline, a period scope, an energy basis or a 6-hour minimum '
      + 'down time. Check each against the finished state before reusing the model.',
      'Quoting the assumed values — 0.52 at minimum load, 120 per MW warm — as data. They are the module\'s inputs, '
      + 'chosen to make the mechanics visible.',
    ],
  },
];
