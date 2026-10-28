/**
 * Module 17 — Batteries in depth (11 steps).
 *
 * Module 4 taught what a battery is: a StorageUnit, a state of charge that couples
 * hours, power and energy as separate limits, one round-trip efficiency, and why
 * the same 20 MW is worth three times more on one side of a constraint than the
 * other. It did so on three snapshots and a lossless-then-0.9 battery. This module
 * does not repeat any of that. It asks the questions a developer or a planner asks
 * once the battery exists: how long should it be, what does each loss cost, what
 * should happen at the edges of the horizon, what is it worth and to whom, what
 * does it add to reliability, and when is a StorageUnit the wrong component.
 *
 * The system is `training_m17_start`: a single bus, three days, 700 MW of solar
 * against a 393 MW evening peak (the middle day overcast), a 300 MW CCGT at 80 and
 * a 200 MW peaker at 140. Prices are 0 while solar is surplus, 80 behind the CCGT
 * and 140 behind the peaker. Every figure below is pinned in
 * ``backend/tests/test_training_checkpoints.py`` (``test_module_17_*``) and solved
 * through the app's own build path:
 *
 *   no battery                  total cost 997,894; 4,463 of 11,245 MWh of solar thrown away
 *   100 MW / 4 h, 0.95 each way 872,718 (saves 125,176); the 140 hours disappear
 *   duration 1 / 2 / 4 / 8 h    957,994 / 918,876 / 872,718 / 818,989 - and 8 h = 16 h
 *   round trip typed twice      877,713 against 872,718 (0.8145 instead of 0.9025)
 *   standing loss 1% an hour    876,704
 *   initial energy 200 MWh      857,518: 15,200 of energy nobody paid for
 *   rolling, terminal SOC       final state of charge 200.0 with it, 0.0 without
 *   three answers, one battery  price-taker 159,379 / its own revenue 60,800 / system saving 125,176
 *   ELCC, 100 MW                20.0 / 20.0 / 24.2 / 45.6 / 93.0 % at 1 / 2 / 4 / 6 / 8 h
 *   StorageUnit vs Store+Link   92.96 MW / 371.8 MWh against 401.4 MWh with 53.6 in and 97.9 out
 *
 * The window is three days of summer, annualised by 8760/72 wherever a result is
 * quoted per year. The module says so each time that matters: a sunny three-day
 * sample is not a year, and several of its headline per-year figures are
 * deliberately shown as the red flags they are.
 */
import { TutorialStep } from '../types';

const SECTION = '17 · Batteries in depth';

export const MODULE_17_BESS: TutorialStep[] = [
  {
    id: 'm17-the-surplus',
    section: SECTION,
    title: 'The midday surplus a battery is for',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    startOptions: {
      prebuiltExampleId: 'training_m17_start',
      completeExampleId: 'training_m17',
      note:
        'Module 17 uses its own small system rather than module 16\'s or the module 7 year: 700 MW of solar, '
        + 'a 300 MW CCGT, a 200 MW peaker and a 393 MW evening peak, over three summer days with the middle one '
        + 'overcast. The prebuilt option has no battery; the finished one has a 100 MW / 4 h battery at 0.95 each '
        + 'way. A learner who has done module 4 knows how to add one — this module reads it, not builds it.',
    },
    concept: [
      'Module 4 put a battery into a network and showed that it removes the peaker. It did not ask what '
      + 'makes a battery worth buying, because three snapshots cannot. The questions need a real day: a '
      + 'surplus that is only there at noon, a peak that is only there at night, and enough of both '
      + 'repeating for a pattern to appear.',

      'That is what this system has. Solar is 700 MW against a peak of 393, so at midday the free output '
      + 'exceeds demand and the surplus is thrown away. At dusk the sun is gone and the CCGT, then the '
      + 'peaker, carry the load. Prices follow the marginal unit: zero in the surplus hours, 80 behind the '
      + 'CCGT, 140 behind the peaker.',

      'A battery earns on the spread between those prices, not their level. Everything in the module is a '
      + 'way of asking how big that spread is, how much of it the battery can keep once losses and '
      + 'limits are counted, and how much of it disappears when the battery is large enough to move the '
      + 'prices it is trading on.',
    ],
    explain: [
      'Load the prebuilt model. Settings → Simulation window should cover all 72 snapshots, and the '
      + 'resolution stays 1 h. Validate and run; one solve of a three-day LP is instant.',

      'Read it before changing anything. Total cost 997,894. The KPI strip\'s Min · Max price reads 0 · '
      + '140 and the load-weighted average 71.4. Renewables supply 36.4% of the energy served.',

      'On the price chart count the hours: 23 at zero, 37 at 80, 12 at 140 — the three marginal units. '
      + 'Curtailment is the other half of the story: 4,463 MWh of the 11,245 MWh the solar could have made, '
      + 'about 40%, is thrown away, all of it in the zero-price hours. The peaker runs for 831 MWh and the '
      + 'CCGT for 11,019 MWh.',

      'Those two facts — 4,463 MWh discarded at noon and 831 MWh bought from the dearest plant at night — '
      + 'are the whole business case. Whether a battery can carry the first into the second is what the '
      + 'next steps measure.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Three prices in one strip',
        tab: 'Analytics',
        note: 'Min · Max 0 · 140 and a load-weighted average of 71.4. The whole spread a battery could '
          + 'earn is the gap between those two ends; the average hides it.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Who sets the price',
        tab: 'Analytics',
        note: 'Solar sets it at zero while there is a surplus, the CCGT at 80 and the peaker at 140. Three '
          + 'marginal units, three prices, repeating each day: the pattern a battery is built to exploit.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="curtailment"]',
        title: 'The surplus, thrown away',
        tab: 'Analytics',
        note: 'Solar output that no one took, concentrated in the middle of each day and largest on the '
          + 'sunny days. 4,463 MWh over the three days is the raw material a battery has to work with.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: ['72 snapshots, one bus, no storage — an instant solve.'],
      expect: 'Total cost 997,894; prices 0 · 140; 4,463 MWh of solar curtailed; the peaker runs 831 MWh.',
    },
    verify: [
      'The KPI strip reads Total cost 997,894 and Min · Max 0 · 140',
      'Prices take exactly three values: 0 (23 hours), 80 (37 hours) and 140 (12 hours)',
      'About 4,463 MWh of solar is curtailed, in the zero-price hours',
      'You can say why the gap between the two ends of the price range, not the average, is what a battery earns',
    ],
    pitfalls: [
      'Judging the system from its average price. 71.4 is a blend of three very different hours and says '
      + 'nothing about whether storage pays.',
      'Starting from module 4\'s model. Its three snapshots have no noon and no night; none of the '
      + 'steps below would give the numbers here.',
    ],
  },

  {
    id: 'm17-add-the-battery',
    section: SECTION,
    title: 'Add the battery and read what it did to the prices',
    tab: 'Analytics',
    where: 'Build → Storage, then Analytics → Result',
    concept: [
      'Module 4 covers how to add a StorageUnit: the sheet, the five numbers, the cyclic switch. Do it the '
      + 'same way here with one different choice of numbers: 100 MW, 4 hours, 0.95 charging and 0.95 '
      + 'discharging, no standing loss, cyclic on. That is 400 MWh behind a 100 MW inverter — a typical '
      + 'grid battery.',

      'What is new is what to look for. The saving is 125,176, 12.5% of the system\'s cost. But the more '
      + 'instructive change is in the prices. The 140 hours are GONE: the peaker never runs, Min · Max reads '
      + '0 · 80, and the average falls from 71.4 to 58.9. A battery of 100 MW has changed the price in hours '
      + 'when it is not even the marginal unit — it removed the unit that was.',

      'And it did so by thinning its own spread. Before the battery the spread between the cheapest and '
      + 'dearest hour was 140; after it, 80. A second battery would find less to earn than the first. That '
      + 'self-limiting is the central economic fact about storage, and steps 8 and 10 return to it.',
    ],
    explain: [
      'Build → Storage, add a row and fill it as in module 4: name batt, bus grid, carrier battery, p_nom '
      + '100, max_hours 4, efficiency_store 0.95, efficiency_dispatch 0.95, standing_loss 0, '
      + 'cyclic_state_of_charge on. Leave the rest. Or load the finished checkpoint, which has it.',

      'Run. Total cost 872,718 against 997,894. The battery charged 1,042.9 MWh and discharged 941.2 — a ratio '
      + 'of exactly 0.9025, the product of the two efficiencies — which is 2.35 equivalent full cycles in '
      + 'three days, about 0.8 a day. The KPI strip\'s Dispatch rises by 101.7 MWh: that is the round-trip '
      + 'loss, generated and not delivered.',

      'Look at the state of charge: it reaches 400 MWh, the battery\'s capacity, on each sunny day around '
      + 'mid-afternoon and is run down through the evening. On the cloudy middle day it only reaches '
      + 'about 292 MWh because there is less surplus to take.',

      'The schedule is not unique. Several are equally good, and the solver reports one — the same '
      + 'degeneracy module 4 met. It can hold some energy overnight in one run and none in another at the same '
      + 'cost. Conclude from the cost and the prices, not from a particular hour\'s dispatch.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'The same sheet as module 4',
        tab: 'Build',
        note: 'One row, eight columns. The numbers differ from module 4\'s; the mechanics do not. What to '
          + 'check is bus grid, p_nom 100, max_hours 4 and both efficiencies at 0.95.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The 140 is gone',
        tab: 'Analytics',
        note: 'Total cost 872,718 and Min · Max 0 · 80. The peaker no longer runs, so the dearest price in '
          + 'the system fell by 60 — a price effect far larger than the energy the battery moved. The '
          + 'average falls from 71.4 to 58.9.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Full on sunny days, half on the cloudy one',
        tab: 'Analytics',
        note: 'The state of charge climbs to 400 MWh by mid-afternoon (16:00) on the two sunny days and only to about '
          + '292 on the overcast one. The battery\'s cycling follows the surplus, not the clock.',
      },
    ],
    entries: [
      {
        field: 'storage_units.name / bus / carrier',
        label: 'identity',
        value: 'batt / grid / battery',
        why: 'The carrier is what the reliability study in step 9 groups the battery under, so give it its '
          + 'own carrier rather than AC. The bus is the only electrical bus in the model.',
      },
      {
        field: 'storage_units.p_nom and max_hours',
        label: 'power and duration',
        value: '100 MW and 4 h',
        why: 'Energy is p_nom x max_hours: 400 MWh. Four hours is the typical grid battery, and it fits this '
          + 'system: long enough to cover the evening peak, short enough that the midday surplus fills it.',
      },
      {
        field: 'storage_units.efficiency_store and efficiency_dispatch',
        label: 'charging and discharging efficiency',
        value: '0.95 and 0.95',
        why: 'Each leg keeps 95%, so the round trip is 0.9025. Step 4 is about exactly this: how the two '
          + 'legs combine, and what goes wrong when a quoted round-trip figure is typed into both.',
      },
      {
        field: 'storage_units.standing_loss and cyclic_state_of_charge',
        label: 'losses while idle, and the ends of the horizon',
        value: '0 and true',
        why: 'No standing loss yet; step 5 adds one. Cyclic means it must finish where it began — the '
          + 'convention steps 6 and 7 examine from both sides.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['The same 72 snapshots with a state-of-charge coupling across all of them — still instant.'],
      expect: 'Total cost 872,718; Min · Max 0 · 80; discharged 941.2 MWh against 1,042.9 drawn.',
    },
    verify: [
      'The Storage step has one row and a tick; batt is on grid with 100 MW, 4 h, 0.95 and 0.95',
      'Total cost reads 872,718 and the price range reads 0 · 80',
      'The state of charge peaks at 400 MWh on the first and third days and at about 292 on the second',
      'You can say why the average price fell 12.5 even though the battery only moved 941 MWh',
    ],
    pitfalls: [
      'Comparing the saving with the battery\'s own revenue. The first (125,176) is what the whole system '
      + 'saved; the second is smaller, and step 8 explains the difference.',
      'Reading one hour\'s dispatch as the strategy. The optimum is degenerate; an idle hour in one run '
      + 'may be a discharge hour in another at the same cost.',
    ],
  },

  {
    id: 'm17-power-and-duration',
    section: SECTION,
    title: 'How long should it be?',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'Module 4 showed that power and energy are separate limits. The question now is how to CHOOSE the '
      + 'ratio between them — the duration — and the answer is that each extra hour is worth less than '
      + 'the last, until it is worth nothing.',

      'Fix the power at 100 MW and vary max_hours. One hour saves 39,900. Two hours save 79,019 — another '
      + '39,119, nearly as good, because the second hour also shaves the 140 peak. Four hours save 125,176, '
      + 'but the two extra hours added only 46,158: 23,079 an hour. Eight hours save 178,906 and the four '
      + 'extra hours added 53,729: 13,432 an hour. Sixteen hours save the same as eight.',

      'The curve falls because of what each added hour displaces. The first hours of storage replace the '
      + 'peaker at 140; once the peak is shaved, further hours replace the CCGT at 80; and eventually the '
      + 'surplus itself runs out — there is only so much free midday energy to put in. At eight hours the '
      + 'battery is no longer full at its peak (it reaches 783 of 800 MWh), which is why sixteen hours is '
      + 'identical to eight.',

      'Power is the mirror image. Hold the energy at 400 MWh and give it 400 MW for one hour, 200 for two '
      + 'or 100 for four, and every one costs 872,718 — power above 100 MW is worth nothing here because '
      + 'the evening peak is wide rather than sharp. Cut the power to 50 MW with eight hours (still 400 MWh) and the '
      + 'cost rises to 890,040: now power binds, and the battery cannot empty itself fast enough.',
    ],
    explain: [
      'Build → Storage: click the batt row and, in the form on the right, change `max_hours` to 1. Run and read Total cost: 957,994. The Min · Max price '
      + 'still reads 0 · 140 — an hour of storage cannot reach beyond the peak.',

      'Set it to 2 (918,876, still 0 · 140), then 8 (818,989 — and now 0 · 80). Put it back to 4 and check '
      + '872,718. The Comparison tab holds all four runs; the saving per added hour of duration is the number '
      + 'worth tabulating, and it falls from 39,900 to 13,432.',

      'Then the power experiment. Set p_nom to 50 and max_hours to 8 — still 400 MWh — and run: 890,040, '
      + '17,322 worse than 100 MW and 4 hours at the same energy. Restore p_nom 100 and max_hours 4 before you '
      + 'continue.',

      'One caution: the evening peak here is wide, about four hours a day of demand above the CCGT. A system '
      + 'with a spiky peak would pay for short, powerful batteries; this one pays for medium-length ones. '
      + 'The duration that is right belongs to the load shape, not the battery.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'Two cells',
        tab: 'Build',
        note: 'max_hours for the duration sweep (1, 2, 8, then back to 4), then p_nom 50 with max_hours 8 '
          + 'for the power test. Everything else in the row stays.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Four durations side by side',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Total cost for 1, 2, 4 and 8 hours: 957,994, 918,876, 872,718 and 818,989. Subtract each from '
          + 'the no-battery 997,894 and divide by the hours: the saving per hour of duration falls with every step.',
      },
    ],
    entries: [
      {
        field: 'storage_units.max_hours (the sweep)',
        label: 'hours at full power',
        value: '1, then 2, then 8',
        unit: 'h',
        why: 'Three runs at 100 MW. Each moves only the energy capacity, so the change in cost is the value of '
          + 'duration alone — the controlled experiment module 3 introduced.',
      },
      {
        field: 'storage_units.p_nom and max_hours (the power test)',
        label: 'same energy, half the power',
        value: '50 MW and 8 h',
        why: '400 MWh either way, but now the inverter is the limit. It costs 17,322 more than 100 MW and 4 h, '
          + 'which is what the missing 50 MW of discharge was worth.',
      },
      {
        field: 'storage_units.p_nom and max_hours (restore)',
        label: 'the module\'s battery, back',
        value: '100 MW and 4 h',
        why: 'Returns the model to 872,718. Steps 4 to 9 all start from this battery.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (five runs)',
      detail: ['Hours 1, 2, 8 at 100 MW; then 50 MW at 8 hours; then restore. Seconds each.'],
      expect: 'Total cost 957,994 / 918,876 / 818,989 at 1 / 2 / 8 hours; 890,040 at 50 MW and 8 h; 872,718 restored.',
    },
    verify: [
      'The three durations read 957,994, 918,876 and 818,989, with 0 · 140 at one and two hours and 0 · 80 at eight',
      '50 MW at eight hours reads 890,040',
      'The model is back at 100 MW and 4 h, and Total cost reads 872,718',
      'You can say why sixteen hours would cost exactly what eight does',
      'You can say which limit — power or energy — binds in each run',
    ],
    pitfalls: [
      'Choosing duration from the first hours of the curve. One hour looks nearly as good per MW as two; '
      + 'the economics change at the peak, which a short battery only half reaches.',
      'Forgetting to restore. The next four steps measure one change each against 872,718.',
    ],
  },

  {
    id: 'm17-efficiency-split',
    section: SECTION,
    title: 'Round trip is two legs, and efficiency is applied twice',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'Module 4 gave the efficiencies their meaning. Here is what they cost, and the one mistake that '
      + 'costs the most. A StorageUnit applies efficiency_store to the energy going in and '
      + 'efficiency_dispatch to the energy coming out. The round trip is the PRODUCT: 0.95 x 0.95 = 0.9025.',

      'Datasheets quote the round trip. Typing that into the model means taking its square root for each '
      + 'leg. A 90% round trip is 0.9487 on each side. Type 0.9 into both and you have modelled 0.81, a '
      + 'battery with 10% more loss than the one you meant — and nothing warns you, because both are '
      + 'legitimate numbers.',

      'Take the round trip the model already has, 0.9025, and type it into both legs. The battery then '
      + 'returns 0.8145 of what it takes, and Total cost rises from 872,718 to 877,713: 4,995 of value '
      + 'lost to a unit error. The lossless case, both legs at 1, costs 867,952, so the whole loss of the '
      + 'real battery is only 4,766 — and the typing error more than doubles it.',

      'Losses also set the spread a cycle needs. Charging at price c and discharging at d is worth doing only '
      + 'if d x 0.9025 > c. Here charging is nearly free, so the threshold hardly binds; on a system '
      + 'with a flat price curve and a 0.81 battery it would decide whether the battery ever runs.',
    ],
    explain: [
      'Build → Storage. Set both efficiencies to 1 and run: Total cost 867,952, the lossless bound. Then both '
      + 'to 0.9025 and run: 877,713, the Min · Max price reads 0 · 98.2 (the loss lifts the price the '
      + 'battery discharges into). Then back to 0.95 and 0.95 and confirm 872,718.',

      'Check the arithmetic on the double-counted run: energy drawn, 1,123.7 MWh; delivered, 915.2 MWh; '
      + 'ratio 0.8145 = 0.9025^2. On the correct run it is 1,042.9 and 941.2, ratio 0.9025. The ratio of '
      + 'delivered to drawn is always the product, whatever the two factors are.',

      'The habit to take away: when a battery is specified by one round-trip figure, write the square '
      + 'root down. sqrt(0.9) = 0.9487; sqrt(0.85) = 0.9220. And when a model has been built by someone '
      + 'else, read the efficiency columns before you trust the cost.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'Two efficiency cells',
        tab: 'Build',
        note: 'efficiency_store and efficiency_dispatch. The product is the round trip. The test is to '
          + 'change both from 0.95 to 0.9025 and watch the cost move 4,995 for what looks like a rounding.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Cost and the top of the price range',
        tab: 'Analytics',
        note: '867,952 lossless, 872,718 at 0.95 each, 877,713 with the round trip typed twice. The last also '
          + 'lifts the maximum price from 80 to 98.2, because a lossier battery has to discharge into a '
          + 'dearer hour to break even.',
      },
    ],
    entries: [
      {
        field: 'storage_units.efficiency_store and efficiency_dispatch (lossless bound)',
        label: 'both legs lossless',
        value: '1 and 1',
        why: 'The upper bound on what a battery here could save. The gap from this to the real battery, 4,766, '
          + 'is the total cost of its losses over three days.',
      },
      {
        field: 'storage_units.efficiency_store and efficiency_dispatch (double-counted)',
        label: 'the round trip typed into both legs',
        value: '0.9025 and 0.9025',
        why: 'The mistake: 0.9025 is already the round trip, so each leg at 0.9025 gives 0.8145. It costs '
          + '4,995 and is invisible unless you check the product.',
      },
      {
        field: 'storage_units.efficiency_store and efficiency_dispatch (restore)',
        label: 'the correct legs, back',
        value: '0.95 and 0.95',
        why: 'Returns the model to 872,718. Leaving 0.9025 in would quietly overstate every loss in the '
          + 'steps after this one.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (three runs)',
      detail: ['Lossless, double-counted, then restored. Seconds each.'],
      expect: 'Total cost 867,952 lossless; 877,713 with 0.9025 on both legs; 872,718 at 0.95 each.',
    },
    verify: [
      'Lossless reads 867,952; double-counted reads 877,713 with the price range at 0 · 98.2',
      'On the double-counted run, delivered divided by drawn is 0.8145',
      'The model is back at 0.95 and 0.95, and Total cost reads 872,718',
      'You can say what to type into each leg for a 90% round-trip battery',
    ],
    pitfalls: [
      'Typing a datasheet\'s round-trip figure into both legs. It is the commonest battery-modelling '
      + 'error and the model accepts it in silence.',
      'Setting an efficiency above 1. The LP creates energy from nothing and the cost drops below the '
      + 'lossless bound — a sign the unit is wrong, not that the battery is wonderful.',
    ],
  },

  {
    id: 'm17-standing-loss',
    section: SECTION,
    title: 'Standing loss: the cost of holding energy',
    tab: 'Analytics',
    where: 'Build → Storage, then run again',
    concept: [
      'The efficiencies cost energy when it moves. Standing loss costs energy when it sits. A StorageUnit\'s '
      + 'standing_loss is the fraction of the STORED energy lost every hour: next hour\'s state of charge is '
      + 'this hour\'s times (1 - loss), before anything is added or removed.',

      'It is a different kind of loss and has a different effect on the schedule. The efficiencies tax '
      + 'every cycle, so they make small spreads not worth chasing. Standing loss taxes the TIME between '
      + 'charging and discharging, so it favours the battery that fills just before it empties and '
      + 'penalises one that carries energy overnight.',

      'Take 1% an hour. That sounds small and is 21.4% a day: 1 - 0.99^24. Total cost rises from 872,718 to '
      + '876,704, and the Min · Max price reads 0 · 93.2 — the battery cannot afford to be as full at the '
      + 'start of the evening. Even 0.2% an hour, about 4.7% a day, costs 1,000. Doubling to 2% an hour costs '
      + '7,211 over no loss at all.',

      'Real lithium-ion batteries lose far less than this while idle, and the right value for a given '
      + 'system comes from its datasheet; for a pumped store or a thermal store it can be much larger. '
      + 'The value here is chosen to be visible, not to be typical.',
    ],
    explain: [
      'Build → Storage. Set `standing_loss` to 0.01 and run. Total cost 876,704 — up 3,986 — and the Min · '
      + 'Max price 0 · 93.2.',

      'Check the physics on the state of charge. Find an hour where the battery neither charges nor '
      + 'discharges but holds energy: the next hour\'s state of charge is 0.99 times this hour\'s. Pick one '
      + 'and divide.',

      'Then try 0.002 (873,718) and 0.02 (879,929) to see the cost grow roughly in proportion. Put it back '
      + 'to 0 and re-run to confirm 872,718.',

      'Standing loss lives in the same row as the efficiencies but is easy to forget because it is '
      + 'blank in most models. A blank is a zero: the battery then holds energy for free for as long as it '
      + 'likes, which flatters every result where the battery carries energy overnight.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'standing_loss',
        tab: 'Build',
        note: 'A per-hour fraction, not a percentage and not a per-day figure: 0.01 means 1% an hour. The '
          + 'column sits next to the efficiencies. A wrong unit here is a factor-of-24 error.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Energy leaks while it waits',
        tab: 'Analytics',
        note: 'Look at an idle stretch: the state of charge no longer holds flat but decays, by 1% a hour. '
          + 'The schedule shifts to charge later and hold for less time.',
      },
    ],
    entries: [
      {
        field: 'storage_units.standing_loss (the experiment)',
        label: 'fraction of stored energy lost each hour',
        value: '0.01',
        why: '1% of the stock an hour is 21.4% a day. It is far larger than a real lithium-ion battery loses '
          + 'idle, chosen so its effect shows in the answer. It costs 3,986 over three days.',
      },
      {
        field: 'storage_units.standing_loss (restore)',
        label: 'no standing loss, back',
        value: '0',
        why: 'Returns the model to 872,718, the baseline for steps 6 to 9.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (two runs)',
      detail: ['0.01, then back to 0.'],
      expect: 'Total cost 876,704 at 0.01 with a price range of 0 · 93.2; 872,718 restored.',
    },
    verify: [
      'At 0.01 Total cost reads 876,704 and the price range reads 0 · 93.2',
      'In an idle hour the state of charge falls by exactly 1%',
      'standing_loss is back to 0 and Total cost reads 872,718',
      'You can say why standing loss and conversion loss change the schedule differently',
    ],
    pitfalls: [
      'Entering a percentage. standing_loss 1 means 100% of the stock is lost every hour; the battery '
      + 'then never holds energy and the run looks like the battery was deleted.',
      'Applying the loss in the same cell as an efficiency. They are separate columns with separate '
      + 'meanings; putting a standing loss into an efficiency taxes every cycle instead of every hour.',
    ],
  },

  {
    id: 'm17-state-of-charge-edges',
    section: SECTION,
    title: 'Where the horizon starts and ends',
    tab: 'Analytics',
    where: 'Build → Storage and Settings → Simulation window',
    concept: [
      'Module 4 turned cyclic state of charge on because without it the battery starts the run full of '
      + 'energy nobody paid for. This is the quantity: with the battery non-cyclic and a starting charge of '
      + '200 MWh, Total cost falls from 872,718 to 857,518 — 15,200 less, which is 190 MWh delivered at 80. '
      + 'At 400 MWh it falls 30,400. The model has handed over free fuel.',

      'The two options are two ways to close the loop. Cyclic forces the end state to equal the start, '
      + 'whatever it is. Non-cyclic leaves the end free — and the optimiser empties the battery by the last '
      + 'hour, since leftover energy is worth nothing — but takes the START from state_of_charge_initial. '
      + 'Non-cyclic from zero costs exactly what cyclic does here, 872,718: this system\'s best schedule needs '
      + 'no energy carried across the end of the horizon, so closing the loop costs nothing.',

      'A short window turns the edges into a large share of the answer. Solve day 1 alone and the battery '
      + 'saves 47,027 against the same day without it; day 2, the overcast one, saves 30,293; day 3 saves '
      + '47,027. Extrapolate from the sunny day and you overstate the three-day average (41,725) by 12.7%. '
      + 'Solving the three days separately, each closed on itself, costs 873,547: 829 more than the joint '
      + 'three-day solve, which is what forbidding the battery to carry energy across midnight is worth.',

      'None of this is wrong; each is a different question. What goes wrong is not noticing which one you '
      + 'asked. A cyclic day answers "what is a typical day worth"; a non-cyclic run from empty answers "what '
      + 'does the first stretch cost"; and a non-cyclic run from a non-zero start answers a question about the '
      + 'battery\'s previous owner.',
    ],
    explain: [
      'Build → Storage. First the free energy. Select a row, then in the form on the right set `cyclic_state_of_charge` to false and '
      + '`state_of_charge_initial` to 200, then run: Total cost 857,518. Set the initial charge to 0 and run '
      + 'again: back to 872,718, the same as cyclic. Restore cyclic on and the initial charge to 0.',

      'Then the short window. Settings → Simulation window: set Start 0 and End 24 and run (day 1 only): '
      + 'Total cost 271,976. Then Start 24, End 48: 326,985; then Start 48, End 72: 274,586. Their sum is 873,547. '
      + 'On the same windows with no battery the days cost 319,003, 357,278 and 321,613, so the battery saves '
      + '47,027, 30,293 and 47,027.',

      'Note the Min · Max price on day 2: 80 · 88.6. With almost no midday surplus there is no zero-price hour, '
      + 'and a battery on a cloudy day has nothing cheap to charge from — which is the case for a window long '
      + 'enough to include one.',

      'Put the window back to the full 72 snapshots (Start 0, End 72) before you move on.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'cyclic_state_of_charge and the initial charge',
        tab: 'Build',
        note: 'Two columns decide the edges: cyclic_state_of_charge (end = start) and state_of_charge_initial '
          + '(the start, when not cyclic). Cyclic on makes the initial charge irrelevant; cyclic off makes it '
          + 'a gift.',
      },
      {
        selector: '[data-settings-section="window"]',
        title: 'Shorten the horizon',
        tab: 'Settings',
        note: 'Start and End select the snapshots solved. 0 to 24 is day 1, a sunny day; 24 to 48 is the '
          + 'overcast one. Three one-day windows each close the battery on itself — the edge effect made visible.',
      },
    ],
    entries: [
      {
        field: 'storage_units.cyclic_state_of_charge and state_of_charge_initial (free energy)',
        label: 'a free 200 MWh at the start',
        value: 'false and 200',
        unit: 'MWh',
        why: 'The battery begins the run with 200 MWh that nobody charged and need not return. It is worth '
          + '190 MWh x 80 = 15,200 — the reason cyclic is the safe default for a short model.',
      },
      {
        field: 'Settings → Simulation window → Start and End (day 1)',
        label: 'one sunny day only',
        value: '0 and 24',
        why: 'Solves 24 snapshots with the battery closed on itself. Run again with 24 / 48 and 48 / 72 to see '
          + 'the three days one at a time; each saving is its own sample of what a day is worth.',
      },
      {
        field: 'Settings → Simulation window and storage_units (restore)',
        label: 'the full window and the cyclic battery, back',
        value: '0 and 72; cyclic true, initial 0',
        why: 'Returns the model to 872,718 over all 72 snapshots, the baseline for the remaining steps.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (several runs)',
      detail: ['Non-cyclic with 200 MWh; the three one-day windows; then restore. Seconds each.'],
      expect: '857,518 with 200 MWh free; 271,976 / 326,985 / 274,586 for the three days; 872,718 restored.',
    },
    verify: [
      'Non-cyclic from 200 MWh reads 857,518 and from 0 reads 872,718',
      'The three one-day windows read 271,976, 326,985 and 274,586, which add to 873,547',
      'Day 2\'s price range reads 80 · 88.6',
      'You can say what a non-zero state_of_charge_initial is worth, and why cyclic is the safe default',
      'The window is back to 72 snapshots, cyclic is on and the initial charge is 0',
    ],
    pitfalls: [
      'Leaving a non-zero initial charge in the model. It is a gift of energy that makes every later '
      + 'cost lower and is easy to forget because it is in a column off to the right.',
      'Extrapolating one sunny day. It overstates the three-day average by about 13%; a representative '
      + 'sample has to include the dull days.',
    ],
  },

  {
    id: 'm17-rolling-terminal-soc',
    section: SECTION,
    title: 'Rolling horizon and the terminal state of charge',
    tab: 'Settings',
    where: 'Settings → Rolling horizon',
    concept: [
      'Module 6 introduced rolling horizon: solve a window, carry its end state into the next, repeat. For '
      + 'storage this has a built-in weakness. Each window sees only itself, so it empties the battery by '
      + 'its last hour — leftover energy has no value inside the window — and the next window begins empty. '
      + 'The battery is run as if every window were the end of the world.',

      'Ragnarok does two things about the edges. Because a cyclic constraint inside a window would be '
      + 'infeasible against the carried-over state, it forces storage non-cyclic during a rolling run. And, new '
      + 'in Ragnarok, it adds a soft TERMINAL STATE OF CHARGE to the last window: the battery must end the '
      + 'horizon with at least the energy it started with, and any shortfall is charged at a penalty per MWh. '
      + 'The penalty defaults to twice the dearest marginal cost in the system — here 280, from the 140 peaker '
      + '— so refilling is always cheaper than paying the shortfall.',

      'It is a soft constraint and it is only on the LAST window. The earlier windows still empty the battery, '
      + 'and the target is the battery\'s state_of_charge_initial — a battery that starts empty has no target to '
      + 'return to. The option is on by default, exposed as `rollingConfig.terminalSoc` in the API and by '
      + 'MCP, and has no switch in Settings.',

      'The numbers show what it does. Three 24-hour windows over the battery, non-cyclic, starting with 200 '
      + 'MWh: with the terminal target the run ends with 200.0 MWh and costs 875,602; with it off (the API '
      + 'option) it ends with 0.0 and costs 858,347 — 17,255 cheaper, because the free energy was simply '
      + 'spent rather than held back. The windows before the last both end at 0.0 in either case.',
    ],
    explain: [
      'Build → Storage. Set `cyclic_state_of_charge` to false and `state_of_charge_initial` to 200 in the form on the right. Settings → '
      + 'Rolling horizon: turn it On. It arrives with 2 chunks and an overlap of 24, which is 2 windows of 60; set '
      + 'Overlap 0 first and then Chunks 3. The summary line should read 3 windows, horizon 24, step 24, over 72 '
      + 'snapshots. Run.',

      'Total cost 875,602. Open the state-of-charge chart: it falls to 0 at the end of day 1 and day 2 — '
      + 'each window drains the battery — and finishes day 3 at exactly 200 MWh, the terminal target. Holding '
      + '200 MWh back at the end is energy that does not displace the evening\'s gas, which is the 17,255 it costs.',

      'Now set `state_of_charge_initial` back to 0 and run: 873,547, the same as the three separate days of '
      + 'step 6, and 829 above the joint solve. The terminal condition is silent because there is nothing to '
      + 'return to.',

      'The off-switch is not in Settings. Through the API or MCP, `rollingConfig.terminalSoc: false` '
      + 'reproduces the run without it: ends at 0.0, cost 858,347. If you ever see a rolling-horizon battery '
      + 'finish exactly empty, that is what happened.',

      'Restore the battery (cyclic on, initial 0) and turn Rolling horizon Off before the next step: the '
      + 'ESS business case cannot run alongside it.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="rolling"]',
        title: 'Three windows of 24',
        tab: 'Settings',
        note: 'Chunks 3, Overlap 0 over 72 snapshots gives three windows of 24. The timeline shows them side by '
          + 'side with nothing shared. An overlap would let each window see a little past its own end and '
          + 'empty the battery less.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Empty twice, then refilled once',
        tab: 'Analytics',
        note: 'The state of charge is 0 at the end of days 1 and 2 and 200 MWh at the end of day 3. The first '
          + 'two windows cannot see the terminal target; only the last window is held to it.',
      },
    ],
    entries: [
      {
        field: 'storage_units.cyclic_state_of_charge and state_of_charge_initial',
        label: 'non-cyclic with a starting charge',
        value: 'false and 200',
        unit: 'MWh',
        why: 'The terminal target is the state_of_charge_initial; with 0 there is nothing to restore and the '
          + 'option is silent. 200 MWh is half the battery.',
      },
      {
        field: 'Settings → Rolling horizon → Mode, Chunks, Overlap',
        label: 'three non-overlapping windows',
        value: 'On, 3, 0',
        why: 'Each window is 24 snapshots, one day. No overlap means no window sees any of the next, which is '
          + 'what makes each one drain the battery and makes the terminal condition visible.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (twice)',
      detail: ['Initial charge 200, then 0. A rolling run is three small solves; seconds in total.'],
      expect: '875,602 ending at 200 MWh with an initial charge of 200; 873,547 with 0.',
    },
    verify: [
      'The Rolling horizon summary reads 3 windows, horizon 24, step 24, over 72 snapshots',
      'With an initial charge of 200 the run costs 875,602 and the state of charge ends at 200 MWh',
      'The state of charge is 0 at the end of the first two days',
      'With an initial charge of 0 the cost is 873,547',
      'Rolling horizon is Off again, cyclic is back on and the initial charge is 0',
    ],
    pitfalls: [
      'Expecting the terminal target to hold the battery full in every window. It binds the last window '
      + 'only; the windows before it still drain.',
      'Reading a rolling-horizon battery that ends empty as optimal. Without the terminal condition it '
      + 'ends empty because nothing values what is left, not because empty is best.',
    ],
  },

  {
    id: 'm17-what-is-it-worth',
    section: SECTION,
    title: 'Three answers to what a battery is worth',
    tab: 'Market',
    where: 'Market & Policy → ESS business case, then Analytics',
    concept: [
      'The question has three honest answers and they are not the same number.',

      'The PRICE-TAKER answer asks what a battery would earn trading against today\'s prices. Ragnarok\'s ESS '
      + 'business case does exactly that: it sweeps battery sizes against the prices of the base run, with no '
      + 'battery in it. At 100 MW and four hours it makes 159,379 over the three days, charging at an '
      + 'average price of 0.0 and discharging at 140.0 — a spread of 140.0 — through 2.85 equivalent full cycles.',

      'The PRICE-MAKER answer asks what the battery earns at the prices it creates. In the model with the '
      + 'battery inside it, the 140 hours are gone, and a 100 MW battery receives 60,800: charging at '
      + 'zero, discharging at 80 or less, 2.35 cycles. Less than half the price-taker figure, because the '
      + 'battery has eaten most of its own spread.',

      'The SYSTEM answer asks what the battery saves everyone: 125,176, from step 2. It sits between the '
      + 'two, and the gap is not an error. The saving is fuel not burnt; the revenue is a price times a '
      + 'volume; a lower price on the volume it did not move is a transfer to the consumers who pay '
      + 'it, not income to the battery.',

      'The ESS sweep is the optimistic one and its limits matter. Revenue is exactly linear in size (79,689 at '
      + '50 MW, 159,379 at 100, 239,068 at 150, 318,758 at 200) because a price taker cannot move the price; the NPV rises with '
      + 'size to the top of the sweep and never turns over. And the window is three days: the per-year '
      + 'figures are the window scaled by 8760/72 = 121.7, so the 346.3 full cycles a year it reports is '
      + 'almost one every day of the year with no cloudy week, and the payback of 3.2 years is a three-day sample '
      + 'multiplied up.',
    ],
    explain: [
      'Settings → Rolling horizon must be Off. For a clean base run set the battery\'s `p_nom` to 0 (or load '
      + 'the prebuilt no-battery model) so the base prices are the no-battery ones. Then Market & Policy → ESS '
      + 'business case.',

      'Switch the mode to Size sweep and set Capital cost (/MW/yr) 60000, Min size 50, Max size 200, Sweep '
      + 'steps 4. Leave the rest at its defaults: bus auto, duration 4 hours, round trip 90%, lifetime blank (15 years '
      + 'is assumed and a note on the card says so). Run.',

      'Run, then History → tick the run → View result. The ESS business case card (Result tab) reads Best size '
      + '200 MW and NPV at best size $277.99M, and its table has the 100 MW row: Revenue (72 h window) $159.4k '
      + '(159,379), Revenue (per year) $19.39M, Capex (per year) $6.00M, NPV $138.99M, IRR 30.6%, Payback 3.21 '
      + 'yr, Full cycles / yr 346.3, Throughput 1,138.4 MWh, Avg charge price $0, Avg discharge price $140, '
      + 'Spread $140. The best size is the top of the sweep.',

      'Now put the battery back (p_nom 100, ESS mode Off) and run: Total cost 872,718. Compare the three '
      + 'numbers — 159,379 (price taker), 60,800 (its own revenue, read from the price and dispatch series) '
      + 'and 125,176 (the system saving) — and the cycle counts, 2.85 against 2.35.',

      'One more result is available and has no card of its own: the storage energy-balance dual. In the run\'s '
      + 'output series `storage_units-mu_energy_balance` (/api/runs/{name}/series/storage_units-mu_energy_balance) '
      + 'it is 76.0 in 54 of the 72 hours and 0 in the other 18. It is the value of one more MWh in the '
      + 'store: 0.95 x 80 when the next discharge displaces the CCGT, and zero in the free midday hours when '
      + 'there is nothing cheaper to charge from.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="ess"]',
        title: 'ESS business case',
        tab: 'Market',
        note: 'A separate study from the battery in your model: it builds its own price-taking battery from '
          + 'these settings and sweeps its size against the run\'s prices. It does not read your storage_units '
          + 'row — which is why the model should have no battery of its own for this run.',
      },
      {
        selector: '[data-card="ess-business-case"]',
        title: 'Spread, cycles and NPV by size',
        tab: 'Analytics',
        note: 'Avg charge 0.0, avg discharge 140.0, spread 140.0 at every size; revenue doubling as size doubles; '
          + 'NPV rising to the largest size. A flat spread and a linear revenue are the signature of a price '
          + 'taker, and neither survives a large battery.',
      },
    ],
    entries: [
      {
        field: 'storage_units.p_nom (batt, for the price-taker run)',
        label: 'a battery of size zero',
        value: '0',
        unit: 'MW',
        why: 'The ESS sweep trades against the base run\'s prices, so those prices must not already contain a '
          + 'battery. A 0 MW row is the same as no row. Put it back to 100 for the comparison run.',
      },
      {
        field: 'Market & Policy → ESS business case → Mode',
        label: 'switch the sweep on',
        value: 'Size sweep',
        why: 'Turns the study on. Disabled while rolling horizon, stochastic, SCLOPF, sampling, power flow or '
          + 'N-1 is on — these reshape the LP in ways the sweep cannot follow.',
      },
      {
        field: 'Market & Policy → ESS business case → Capital cost (/MW/yr), Min size, Max size, Sweep steps',
        label: 'cost and the sizes to try',
        value: '60000, 50, 200, 4',
        why: 'The capital cost is ANNUAL, per MW, on the same basis as everything in the model: 6,000,000 a year '
          + 'for 100 MW. Four sizes from 50 to 200 MW show the linearity without ten re-solves.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (ESS sweep), then again with the battery in',
      detail: ['The sweep is four small LPs after the base solve — seconds.'],
      expect: 'At 100 MW: window revenue 159,379, spread 140, 346.3 cycles a year, NPV 138,994,900. With the battery inside: Total cost 872,718.',
    },
    verify: [
      'The ESS card reads 159,379 window revenue and a spread of 140 at 100 MW, and revenue doubles from 50 to 100 MW',
      'Best size is 200 MW, the top of the sweep',
      'With the battery inside the model, Total cost is 872,718, and its own revenue at the new prices is 60,800',
      'You can say why the system saving lies between the other two numbers',
      'You can say why 346.3 full cycles a year is a warning, not a result',
    ],
    pitfalls: [
      'Taking the NPV as a forecast. It is a price taker\'s NPV, on a three-day sample multiplied by '
      + '121.7. The IRR of 30.6% is far above what real storage projects report.',
      'Running the ESS sweep with the battery already in the model. The base prices then already have the '
      + 'battery\'s effect in them and the sweep adds a second battery on top.',
      'Reading the ESS settings as the model\'s battery. They are a separate study: the round trip, '
      + 'duration and cost you type there never reach the storage_units sheet.',
    ],
  },

  {
    id: 'm17-capacity-value',
    section: SECTION,
    title: 'Capacity value rises with duration',
    tab: 'Settings',
    where: 'Settings → Solve → ELCC, then Analytics',
    concept: [
      'Arbitrage is one revenue stream. The other is being there when the system is short. Module 12 measured '
      + 'it as ELCC — the firm MW that would make the system as reliable as the battery does — and found a '
      + '20 MW battery worth 11% of its rating, because its energy ran out. Here is the same study asked '
      + 'with duration as the variable.',

      'A battery\'s capacity credit is limited by its energy, not its power. A 100 MW battery that can '
      + 'deliver for one hour covers only the first hour of a shortfall; a shortfall that lasts a day needs '
      + 'a battery that lasts a day. Run the outage Monte Carlo at 200 members, seed 42, a 5% forced-outage '
      + 'rate and a 48-hour repair time and the credit of the 100 MW battery is 20.0% at one hour, 20.0% at '
      + 'two, 24.2% at four, 45.6% at six and 93.0% at eight.',

      'The flat start and the steep end tell different things. Outages last days, not hours, so a battery '
      + 'worth anything at a thermal outage has to last through the evening peaks of several days, and '
      + 'only the long ones do. The system\'s baseline LOLE falls as it does: 326 hours a year at one hour of '
      + 'storage, 246 at four, 97 at eight. These absolute figures are the three-day window scaled up and '
      + 'mean little; the comparison between durations is the result.',

      'The lesson for a business case: capacity value and arbitrage value prefer the same battery only '
      + 'up to a point. Arbitrage stopped paying beyond eight hours here (step 3); capacity value is still '
      + 'rising there. A market that pays for capacity would value a longer battery than one that pays for '
      + 'energy alone.',
    ],
    explain: [
      'Restore the battery to 100 MW and 4 hours (cyclic on, initial 0, no standing loss, 0.95 each way) and '
      + 'turn the ESS business case Off. Settings → Solve → ELCC / capacity credit: Mode On. The panel already holds '
      + 'samples 200, seed 42, forced outage rate 5 and mean time to repair 48 — check them — and Carriers is blank, '
      + 'meaning every variable renewable and storage; type battery. Module 12 covers each setting.',

      'Run at max_hours 4 and read the ELCC card: battery 24.2 MW of 100 (24.2%), baseline LOLE 246.4 h/yr.',

      'Change max_hours to 1 and run: 20.0 MW (20.0%), baseline 326.1. Change it to 8: 93.0 MW (93.0%), '
      + 'baseline 97.3. The pinned set also has two hours (20.0%, 304.2) and six (45.6%, 173.4) if you want to fill '
      + 'in the curve.',

      'The percentages come from a Monte Carlo and have a sampling error — module 12 step 8 measured how '
      + 'much — so read them to the nearest point or two. Set max_hours back to 4 afterwards.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="elcc"]',
        title: 'ELCC / capacity credit',
        tab: 'Settings',
        note: 'The same sampler as module 12. Naming the carrier battery restricts the study to the one '
          + 'resource you are changing, which keeps each run to a second or two.',
      },
      {
        selector: '[data-card="elcc"]',
        title: 'Credit by duration',
        tab: 'Analytics',
        note: 'The battery row reads 24.2% at four hours. Re-run at 1 and 8 hours for 20.0% and 93.0%. Each '
          + 'card also reports the baseline LOLE it measured the battery against, which falls as duration rises.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → ELCC → Mode, samples, seed, forced outage rate, repair time',
        label: 'the reliability study',
        value: 'On, 200, 42, 5, 48',
        why: 'The same settings as module 12 so the numbers are comparable: 200 synthetic years, a fixed '
          + 'seed so a re-run repeats, 5% of the time broken and two days to fix.',
      },
      {
        field: 'Settings → Solve → ELCC → Carriers',
        label: 'which carriers to evaluate',
        value: 'battery',
        why: 'The battery is the only thing whose duration changes between runs. Solar\'s ELCC is only 3.2% '
          + 'at one hour and ties up a bisection search each run for no insight here.',
      },
      {
        field: 'storage_units.max_hours (the sweep)',
        label: 'hours at full power',
        value: '1, then 8, then 4',
        unit: 'h',
        why: 'Three runs of the same 100 MW inverter with a different amount of energy behind it. Duration is '
          + 'the only thing that changes, so the credit it earns is duration\'s alone.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (three runs)',
      detail: ['The Monte Carlo behind the ELCC samples 200 synthetic years — a couple of seconds each.'],
      expect: 'Battery ELCC 24.2% at four hours, 20.0% at one, 93.0% at eight.',
    },
    verify: [
      'The ELCC card reads 24.2% for the battery at four hours with a baseline LOLE of 246.4',
      'At one hour it reads 20.0% and at eight hours 93.0%',
      'You can say why capacity credit is limited by energy and not by power',
      'You can say where arbitrage value and capacity value stop agreeing about the best duration',
      'max_hours is back at 4 and the ELCC study is off',
    ],
    pitfalls: [
      'Quoting a battery\'s capacity credit without its duration. "20%" and "93%" describe the same 100 MW '
      + 'inverter; the difference is the energy behind it.',
      'Reading the baseline LOLE as a reliability finding about this system. It is three summer days '
      + 'annualised by 121.7 and a deliberately fragile toy; only the changes between runs mean anything.',
    ],
  },

  {
    id: 'm17-sizing-the-components',
    section: SECTION,
    title: 'Letting the model size it: StorageUnit or Store and Links',
    tab: 'Analytics',
    where: 'Build → Storage, then load the Store + Link checkpoint',
    concept: [
      'Every step so far fixed the battery and read the result. The model can also choose its size. A '
      + 'StorageUnit can be extendable: set p_nom_extendable, an overnight_cost and a p_nom_max, and the '
      + 'optimiser buys the power. The energy follows automatically, because a StorageUnit holds energy = '
      + 'p_nom x max_hours — the duration is a number YOU fixed, and it does not get chosen.',

      'That is the limitation, and it has a price. Give the unit an overnight cost of 1,000,000 per MW and four '
      + 'hours and the model buys 92.96 MW and 371.8 MWh; Total cost 950,780. Cost per MW includes the '
      + 'energy: spread over 4 hours that is 250,000 per MWh. Change max_hours to 2 without changing the cost and '
      + 'the energy is suddenly 500,000 a MWh; the model buys 95.4 MW, 190.7 MWh, and Total cost is 997,308 — '
      + 'barely better than no battery. At 8 hours it is 125,000 a MWh and the model buys 218.4 MW and '
      + '1,747.5 MWh for 882,154. Nothing was wrong with the optimiser. The two settings answered '
      + 'different questions.',

      'A Store plus two Links sizes three things independently. The Store is a tank with an energy capacity and '
      + 'a cost per MWh; one Link charges it, with its own power and cost per MW; another discharges, with its '
      + 'own. The same unit costs as before — 100,000 per MW on each link and 200,000 per MWh — give an '
      + 'optimum with a store of 401.4 MWh, 53.6 MW going in and 97.9 MW coming out. The charge is slower than the '
      + 'discharge, which fits the shapes: the surplus spreads over most of the day while the peak is confined to '
      + 'a few hours.',

      'That freedom is worth 2,052 here (948,727 against 950,780), a small number in this system, and it is the '
      + 'right order: a StorageUnit is a good approximation when charging and discharging are about '
      + 'symmetric and duration is a design choice. Reach for a Store and Links when the rates differ, when '
      + 'the thing stored is not electricity, or when the energy cost deserves its own number — as it does '
      + 'for hydrogen or heat in module 5.',
    ],
    explain: [
      'Put the model in its module state: batt at 100 MW, 4 h, cyclic. Build → Storage. Make the unit extendable: '
      + 'set `p_nom_extendable` on, `p_nom` 0, `p_nom_min` 0, `p_nom_max` 400, `overnight_cost` 1000000, `lifetime` 15, `discount_rate` 0.05 (Settings → Project defaults → "Fill discount_rate" writes it). '
      + 'Total cost reads 950,780 and the Capacity Expansion card shows batt at 93.0 MW.',

      'Note the arithmetic. PyPSA annuitises the overnight 1,000,000 at 5% over 15 years — factor 0.0963423, '
      + 'so 96,342 a MW-year — and scales it by n.nyears, 72/8760 for the 72-hour window. The cost breakdown (Analytics → Comparison, '
      + 'or the run\'s costBreakdown in the API) reads "Capital cost (periodised, modelled horizon)": 73,611 — PyPSA\'s own n.statistics.capex. That scaling is why a three-day window '
      + 'still prices a battery against three days of savings, and why those savings are not a year\'s.',

      'Now the trap. Change `max_hours` to 2 and run (997,308), then to 8 (882,154), each time with the same '
      + 'capital cost. The energy price changed; the optimiser answered the new problem. Restore 4.',

      'Finally load the checkpoint Training: module 17 Store + Link battery (step 10) from Welcome → Start with '
      + 'Examples: a Store batt_store on its own bus with two Links and no StorageUnit. Run: Total cost 948,727. The Capacity '
      + 'Expansion card shows batt_store 401.4 MWh, batt_charge 53.6 MW and batt_discharge 97.9 MW.',

      'Both units are valid models of a battery; the second is closer to how its parts are priced. What '
      + 'neither fixes is that a three-day window sizes a battery for three summer days.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'The extendable StorageUnit',
        tab: 'Build',
        note: 'p_nom_extendable, p_nom_max and capital_cost are all that sizing needs. max_hours stays: it is the '
          + 'fixed ratio between the energy and the power the model buys. Change it and you have changed the '
          + 'price of energy without touching the cost column.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'What it bought',
        tab: 'Analytics',
        note: 'The StorageUnit buys 93.0 MW (371.8 MWh). The Store and Links buy 401.4 MWh, 53.6 MW in and 97.9 MW '
          + 'out: three independent numbers where the StorageUnit has one.',
      },
      {
        selector: '[data-build-step="links"]',
        buildStep: 'links',
        title: 'Two links, one store',
        tab: 'Build',
        note: 'In the Store checkpoint the Links step holds the charge and discharge converters, each with its '
          + 'own capital cost and efficiency 0.95. The Store sits on a bus of its own, which is what lets '
          + 'the in and out rates differ.',
      },
    ],
    entries: [
      {
        field: 'storage_units.p_nom_extendable, p_nom, p_nom_max',
        label: 'let the model buy the power',
        value: 'true, 0, 400',
        unit: 'MW',
        why: 'Extendable with nothing installed and an upper bound. A StorageUnit without a p_nom_max and with '
          + 'a zero capital cost would be free unbounded storage; the bound is what makes the answer finite.',
      },
      {
        field: 'storage_units.overnight_cost and lifetime',
        label: 'overnight cost per MW, at four hours, and life',
        value: '1000000 and 15',
        unit: 'per MW; years',
        why: 'Overnight, as a cost database quotes it; PyPSA annuitises it. At four hours it contains 250,000 '
          + 'per MWh of energy, a figure that silently changes if you change max_hours.',
      },
      {
        field: 'storage_units.max_hours (the trap)',
        label: 'hours, with the same capital cost',
        value: '2, then 8, then 4',
        unit: 'h',
        why: 'Same cost per MW, different energy per MW: the price of energy halves or doubles without '
          + 'a number in the cost column moving. 997,308 and 882,154 differ by 115,000 for exactly that reason.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (four runs, then the Store checkpoint)',
      detail: ['Extendable at 4, 2 and 8 hours, then training_m17_store. Seconds each.'],
      expect: 'Total cost 950,780 (93.0 MW); 997,308 at 2 h; 882,154 at 8 h; 948,727 for the Store + Links.',
    },
    verify: [
      'With the extendable StorageUnit the Capacity Expansion card shows batt at 93.0 MW and Total cost reads 950,780',
      'At max_hours 2 and 8 the cost is 997,308 and 882,154 with the same overnight_cost',
      'The Store checkpoint reads Total cost 948,727 with 401.4 MWh, 53.6 MW in and 97.9 MW out',
      'You can say why the charging link is smaller than the discharging one',
      'You can say two situations where a StorageUnit is the wrong component',
    ],
    pitfalls: [
      'Changing max_hours on an extendable StorageUnit and treating the new answer as a comparison. You '
      + 'changed the energy cost per MWh too, so the two runs are not the same question.',
      'Giving an extendable unit a capital cost and no p_nom_max. The model buys as much as is worth '
      + 'buying, which may be more than the window can justify; the bound is part of the model.',
      'Using the Store without the efficiency on the Links. Each leg carries its own 0.95; leave one at 1 and '
      + 'the round trip is 0.95, not 0.9025.',
    ],
  },

  {
    id: 'm17-what-changed',
    section: SECTION,
    title: 'What module 17 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Five things are now yours, beyond module 4\'s.',

      'Duration is chosen against the load shape and the surplus. Each hour of energy is worth less than the '
      + 'last, down to nothing; power is worth something only until the peak is shaved. Losses cost '
      + 'conversion twice and holding every hour, and a quoted round trip belongs under a square root.',

      'The edges of the horizon are modelling choices with prices. Initial energy is free energy; cyclic '
      + 'closes the loop at the cost of forbidding a carry; a rolling window empties the battery unless a terminal '
      + 'target holds the last one to where it began.',

      'A battery has three values that disagree. As a price taker it earns the spread of today\'s prices; as a '
      + 'price maker it earns the smaller spread it leaves behind; as a system asset it saves fuel. And it has a '
      + 'capacity value that rises with duration long after the arbitrage value has stopped.',

      'And a StorageUnit is the right component when the rates are symmetric and the duration is a design '
      + 'choice. When they are not, a Store and two Links price power and energy separately — at the cost of '
      + 'three components in place of one.',
    ],
    explain: [
      'Three limits to name.',

      'Three summer days. The surplus and the evening peak are real here and the winter is absent; a battery '
      + 'sized on a sunny week will be oversized for a dull one. The per-year figures in this module — 346 cycles, '
      + 'a 3-year payback, a 30% IRR — are the three days multiplied, and each one is a flag rather than a finding. '
      + 'Module 6 is the cure: a representative year, not a sample.',

      'One bus. A battery\'s value depends on where it sits; module 4 found a threefold difference across one '
      + 'constraint, and nothing here has a network. Real siting and sizing is both.',

      'No degradation, no reserve value, no ancillary revenue. A battery loses capacity with every cycle, '
      + 'and the 286 or 346 cycles a year the window implies would age one in a few years. The ESS business '
      + 'case says in its own note that it counts energy arbitrage only.',

      'Export the project before you go — Model → Export project.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: 'Restored: Total cost 872,718 with the 100 MW / 4 h battery at 0.95 each way. Every experiment in '
          + 'this module was one change from it; the final state is the checkpoint.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. The bundled checkpoint holds the same model, but a file you saved '
          + 'yourself is the one you will trust when the two disagree.',
      },
    ],
    verify: [
      'The model reads: batt 100 MW, 4 h, 0.95 each way, no standing loss, cyclic, initial charge 0, full 72-snapshot window',
      'Total cost reads 872,718',
      'You can say the three values a battery has and why they differ',
      'You can name two things a three-summer-day model cannot say about a battery',
      'You have exported the project',
    ],
    pitfalls: [
      'Carrying a leftover experiment forward: a non-zero initial charge, a standing loss, a shortened '
      + 'window or an extendable row. Check each against the module\'s final state before you reuse the model.',
      'Generalising the 4-hour answer. It belongs to this load shape, this surplus and this three-day '
      + 'sample; a different system\'s best duration could be two hours or twelve.',
    ],
  },
];
