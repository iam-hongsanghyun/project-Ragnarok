/**
 * Module 16 — The multi-year pathway (13 steps).
 *
 * Module 7 sized a system for one year. A transition is a sequence: plant retires
 * on a date, wind and batteries get cheaper every decade, a carbon cap tightens,
 * and money spent in 2030 does not weigh what money spent in 2050 does. This
 * module turns the one-year model into a three-period pathway — 2030, 2040, 2050
 * — solved as ONE problem, and teaches what the period weightings, `build_year`,
 * `lifetime` and the `years` weight each do, and what each does when it is wrong.
 *
 * The system is `training_m16_start`: one bus, three coal/gas units that retire on
 * their `build_year` + `lifetime`, and wind, solar and a 4-hour battery offered as
 * one VINTAGE per period at falling overnight cost. Each period is ONE
 * representative day (24 snapshots) standing for a year: snapshot weights 365 on
 * `objective` and `generators`, 1 on `stores`. Every figure below is pinned in
 * ``backend/tests/test_training_checkpoints.py`` (``test_module_16_*``), solved
 * through the app's own build path at a 5% discount rate:
 *
 *   weights (discounted decades)    8.1078 / 4.9775 / 3.0558, ratio 1.05^-10 = 0.6139
 *   no policy                       total cost 589,565,227; builds nothing in 2030;
 *                                   emissions 11,893 / 9,673 / 591 kt per period
 *   coal_old kept to 2045           2040 emissions 13,372 kt; cap plan unchanged
 *   carbon price 20 / 60 / 120      emissions 5,709 / 1,235 / 0 kt; total cost 872,790,016
 *   cap 10 / 4 / 0.3 Mt a period    total cost 626,611,134; shadow price 12.0533
 *   years weight left at 1          the caps are 10x too loose and never bind: 589,565,227
 *   annual tonnes, years = 10       caps 10x too tight: 907,496,654 (+45%)
 *   only a 2050 cap                 2040 battery 39.6 -> 97.7 MW: perfect foresight
 *
 * Ragnarok solves one perfect-foresight problem. It has no myopic mode (each
 * period decided without seeing the next), and step 12 says what that means
 * rather than pretending otherwise.
 */
import { TutorialStep } from '../types';

const SECTION = '16 · The multi-year pathway';

export const MODULE_16_PATHWAY: TutorialStep[] = [
  {
    id: 'm16-one-problem-three-dates',
    section: SECTION,
    title: 'From one year to a sequence of decades',
    tab: 'Build',
    where: 'Build → Snapshots and Generators steps',
    startOptions: {
      prebuiltExampleId: 'training_m16_start',
      completeExampleId: 'training_m16',
      note:
        'Module 16 starts from a new system rather than module 15\'s: one bus, three investment periods '
        + '(2030, 2040, 2050) and nothing configured — no pathway settings and no CO2 cap. The finished '
        + 'checkpoint also restores the Settings → Multi-year planning table and the three caps. Do not start '
        + 'from the single-period year of modules 7 to 15: its snapshots have no period column, and a pathway '
        + 'needs one.',
    },
    concept: [
      'Module 7 answered "what should we build" for one year. The honest version of that question has '
      + 'dates in it. A coal unit built in 1985 will not be there in 2040. Wind that costs 1.6 million per MW '
      + 'today costs 1.0 million in 2050. A cap that is loose now is tight later. And a decision to build is '
      + 'not one decision but a schedule — what goes in when, given that everything it will meet changes.',

      'PyPSA models this with INVESTMENT PERIODS. A period is a decision date. Each carries its own '
      + 'operational snapshots, and the whole thing is solved as one linear programme: capacity bought in a '
      + 'period stays available in later periods until it retires, and the optimiser sees every period at '
      + 'once. That joint view has a name — perfect foresight — and step 12 says what it does and does not '
      + 'buy you.',

      'Three things have to be said about each period, and they are three different columns: WHEN it is '
      + '(the period label, a year), HOW MUCH it counts in the objective (an objective weight), and HOW MANY '
      + 'real years it stands for (a years weight). Most pathway mistakes come from setting one of those '
      + 'and assuming it did the work of another.',

      'To keep a three-decade model small, each period here is one representative day — 24 hourly snapshots '
      + 'each weighted 365 — standing for a whole year. That is module 6\'s representative-period idea, '
      + 'now once per period. The battery\'s own `stores` weight stays 1, so its state of charge still '
      + 'integrates real hours.',
    ],
    explain: [
      'Load the prebuilt model, then read what is in it before changing anything. Build → Snapshots: 72 '
      + 'rows, 24 for each of 2030, 2040 and 2050, with a `period` column the single-period models never had '
      + 'and weight columns of 365, 365 and 1.',

      'Build → Generators: nine rows. Three existing units (coal_old, coal_new, gas_ccgt), and three '
      + 'vintages each of wind, solar and — on the Storage step — a 4-hour battery. Every vintage is '
      + 'extendable with a `build_year` equal to its period, so it only becomes available when its decade '
      + 'starts. Their overnight capital costs fall: wind 1.6, 1.3, 1.0 million per MW; solar 900, 650, 450 '
      + 'thousand; battery 500, 350, 250 thousand per MW of a 4-hour unit.',

      'Demand grows 20% a decade: a 200 MW peak in 2030, 240 in 2040, 280 in 2050. The coal units burn at '
      + '20 per MWh of electricity, gas at 55, and the wind and solar profiles are the same in every period.',

      'Nothing is configured yet. Opening Run now would solve a single period across all 72 snapshots as if '
      + 'they were consecutive hours across twenty years — the settings in step 2 are what turn the period '
      + 'column into a pathway.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="snapshots"]',
        buildStep: 'snapshots',
        title: 'A period column on the snapshots',
        tab: 'Build',
        note: 'Seventy-two rows: 24 hours for each of 2030, 2040 and 2050. The period column is the join '
          + 'between a snapshot and a decision date, and the weight columns (objective and generators 365, '
          + 'stores 1) turn each representative day into a year. Without a period column the pathway '
          + 'settings in the next step would have nothing to attach to.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Vintages, not one wind farm',
        tab: 'Build',
        note: 'wind_2030, wind_2040 and wind_2050 are three rows because a cost that changes with time '
          + 'cannot live in one cell. Each has a build_year, so it exists only from its own decade on — '
          + 'that is how a falling cost curve is written into a model whose columns hold single numbers.',
      },
    ],
    verify: [
      'The snapshots sheet has 72 rows and a `period` column reading 2030, 2040 and 2050 (24 rows each)',
      'The weight columns read 365 (objective), 365 (generators) and 1 (stores) on every row',
      'The generators sheet has 9 rows: coal_old, coal_new, gas_ccgt and a wind, solar vintage for each period',
      'You can say what the three per-period columns — label, objective weight, years weight — are each for',
    ],
    pitfalls: [
      'Starting from a single-period checkpoint. The pathway needs a `period` column on the snapshots; '
      + 'without it Ragnarok refuses the run with a validation message rather than guessing the decades.',
      'Reading each period as a day. It is a day standing for a year: the weights of 365 are what make '
      + 'the energy, the cost and an annual emissions figure mean a year.',
    ],
  },

  {
    id: 'm16-periods-and-weights',
    section: SECTION,
    title: 'Periods, objective weights and years',
    tab: 'Settings',
    where: 'Settings → Setup → Multi-year planning',
    concept: [
      'The objective weight answers one question: how much does a unit of cost in this period count '
      + 'against a unit of cost in the first? It is a discounting device. Cost in period p is multiplied '
      + 'by w_p and the solver minimises the sum, so a bigger weight means "this period matters more".',

      'The right weight for a period that stands for Y years is the discounted number of those years: '
      + 'w_p = sum over k = 0 to Y-1 of (1 + r)^-(p - p0 + k), with r the discount rate and p0 the first '
      + 'period. At 5% and ten years a decade, that is 8.1078 for 2030 (almost ten years, slightly '
      + 'discounted), 4.9775 for 2040 and 3.0558 for 2050 — each decade worth 1.05^-10 = 0.6139 of the '
      + 'one before it.',

      'The years weight is a different thing. It says how many calendar years a period represents, and in '
      + 'PyPSA it multiplies energy-sum constraints — a CO2 cap above all — not cost. Cost is carried by '
      + 'the objective weight alone. A 2040 cap on a period that stands for ten years is a cap on ten '
      + 'years of emissions, and step 10 shows what happens to a cap typed as if it were one.',

      'Only the RATIOS between objective weights change the plan; their absolute size scales the '
      + 'reported cost and nothing else. Step 11 proves that, and shows what is lost by leaving the '
      + 'discounting out.',
    ],
    explain: [
      'Settings → Setup → Multi-year planning. Click Pathway. Ragnarok fills in two periods for you — 2030 '
      + 'and 2040, weight 1 — with years of 5 and 10. Those are placeholders and neither is right for this '
      + 'model: the 2030 row\'s years are 5, not 10, and a weight of 1 is no discounting at all.',

      'Set the 2030 row to objective weight 8.1078 and years 10; the 2040 row to 4.9775 and 10; then click '
      + 'Add period, which appends 2050 with years 10 already filled in, and set its objective weight to '
      + '3.0558. Leave the snapshot mapping on "Use snapshots.period column": the example has a period '
      + 'column, so every snapshot already knows its decade.',

      'Then Settings → Project defaults and confirm Discount rate reads 0.05, as it has since '
      + 'module 7. It does two jobs here and they are separate: it is the rate written into each row\'s `discount_rate`, '
      + 'which PyPSA annuitises `overnight_cost` with (step 7), and — in the weights you just typed — it '
      + 'discounts the future. Ragnarok does not tie the two together; if you change the rate, recompute the '
      + 'three weights yourself and refill the rows.',


      'Open the Run dialog and check the planning summary: it should read 3 pathway periods rather than '
      + 'a snapshot window, and the simulation-window slider disappears — a pathway runs every snapshot of '
      + 'every period.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="planning"]',
        title: 'Multi-year planning',
        tab: 'Settings',
        note: 'Mode, the period table and the snapshot mapping. Three columns per period: the label, the '
          + 'objective weight (how much this period counts) and the years (how long it lasts). Clicking '
          + 'Pathway fills in 2030 and 2040 with weight 1 and years 5 and 10 — edit them, do not trust them.',
      },
      {
        selector: '[data-settings-section="projectDefaults"]',
        title: 'The discount rate',
        tab: 'Settings',
        note: 'Still 0.05. It is written into each row\'s discount_rate, which PyPSA annuitises overnight_cost with '
          + '(step 7); the weights you typed already contain the same 5% as a discount. They are two uses of one '
          + 'number that Ragnarok does not link.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'Three periods, not a window',
        runDialog: 'open',
        note: 'The planning summary reads "3 pathway periods" instead of a snapshot window. If it still '
          + 'shows a window the mode is off, and the run would treat 72 snapshots as consecutive hours.',
      },
    ],
    entries: [
      {
        field: 'Settings → Multi-year planning → Mode',
        label: 'planning mode',
        value: 'Pathway',
        why: 'Switches the solve from one period to a set of investment periods optimised together. It '
          + 'also changes what the results mean: money in a period view is weighted, and capacity that '
          + 'is not yet built or already retired is masked.',
      },
      {
        field: 'Settings → Multi-year planning → period 1 (Period / Obj. weight / Years)',
        label: 'first period',
        value: '2030 / 8.1078 / 10',
        why: 'Ten years starting at the base year, discounted at 5%: 1 + 1.05^-1 + ... + 1.05^-9 = 8.1078. '
          + 'The pre-filled row says years 5; with a cap in the model that would not just mislabel the '
          + 'period, it would halve the cap\'s grip on it.',
      },
      {
        field: 'Settings → Multi-year planning → period 2',
        label: 'second period',
        value: '2040 / 4.9775 / 10',
        why: 'The same ten-year sum, started a decade later: 8.1078 x 1.05^-10 = 4.9775. A cost in 2040 is '
          + 'worth about 61% of the same cost in 2030 — the single number discounting boils down to.',
      },
      {
        field: 'Settings → Multi-year planning → period 3 (Add period)',
        label: 'third period',
        value: '2050 / 3.0558 / 10',
        why: 'Another decade later: 4.9775 x 1.05^-10 = 3.0558. Add period inserts 2050 with weight 1 and '
          + 'years 10; the weight is the cell to change. Leaving it at 1 would make the last decade count '
          + 'for a third of a year.',
      },
      {
        field: 'Settings → Multi-year planning → Snapshot mapping',
        label: 'how snapshots map to periods',
        value: 'Use snapshots.period column',
        why: 'The example carries a period on every snapshot row, so each timestamp already belongs to one '
          + 'decade. The other option repeats one set of snapshots for every period — handy when the '
          + 'periods differ only in costs, wrong here because demand grows.',
      },
    ],
    verify: [
      'Mode reads Pathway and the table has three rows: 2030, 2040, 2050',
      'Objective weights read 8.1078, 4.9775 and 3.0558; the years weight is 10 in all three rows',
      'Settings → Project defaults → Discount rate reads 0.05',
      'The Run dialog\'s planning summary reads 3 pathway periods',
      'You can say which of the two weights a cost uses and which an emissions cap uses',
    ],
    pitfalls: [
      'Leaving the placeholder weights of 1. Each period then counts as one undiscounted year: the model '
      + 'values 2050 exactly as much as 2030, and every cost it reports is about a tenth of a decade.',
      'Setting years to 10 on 2040 and 2050 but leaving the 2030 row at its pre-filled 5. Nothing '
      + 'complains. It only shows up when a cap on 2030 turns out half as tight as you meant.',
    ],
  },

  {
    id: 'm16-build-year-and-lifetime',
    section: SECTION,
    title: 'build_year and lifetime: who is there when',
    tab: 'Build',
    where: 'Build → Generators step (read, then continue)',
    concept: [
      'An asset takes part in a period only if it exists in it: build_year <= period < build_year + '
      + 'lifetime. Before its build year it has not been built; from build_year + lifetime on it has '
      + 'retired. The optimiser applies that mask to both capacity and cost — a retired plant contributes '
      + 'neither output nor a capital charge.',

      'The rule is applied per PERIOD, not per year. coal_old was built in 1985 with a 50-year life, so '
      + 'it retires in 2035 — but the model only looks at 2030, 2040 and 2050, so what it sees is "there in '
      + '2030, gone in 2040". The retirement date inside a decade is invisible; a unit retiring in 2039 and '
      + 'one retiring in 2031 behave identically.',

      'The same rule governs new capacity. A vintage with build_year 2040 is unavailable in 2030 and then '
      + 'active until its lifetime ends — wind_2040 (25 years) is active in 2040 and 2050 and would be '
      + 'until 2065, beyond the model\'s last period. Anything it would earn after 2059 is outside the '
      + 'horizon and counts for nothing, so the model undervalues long-lived assets built late.',
    ],
    explain: [
      'Build → Generators and read the build_year and lifetime columns. coal_old: 1985 and 50, so active '
      + 'in 2030 only. coal_new: 2000 and 45, so active in 2030 and 2040 (it retires in 2045). gas_ccgt: 2010 '
      + 'and 45, active throughout (it runs to 2055). The nine rows have nothing to change.',

      'Work out by hand which units are active in each period. 2030: the three existing units, 450 MW. '
      + '2040: coal_new and gas_ccgt, 300 MW, plus whatever the optimiser builds in 2040. 2050: only the gas '
      + 'unit, 150 MW, plus every vintage built so far that is still alive. Step 5 checks your table against '
      + 'the result views.',

      'Notice that nothing here says a plant must retire at its lifetime — the model treats the '
      + 'retirement as a fact about the asset, which is a modelling choice. Real owners extend lives; step '
      + '6 does exactly that and measures what it does to the answer.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'build_year and lifetime',
        tab: 'Build',
        note: 'Scroll right to the build_year and lifetime columns. Both are plain PyPSA attributes that the '
          + 'single-period modules left at their defaults (0 and infinite), where they do nothing. In a '
          + 'pathway they are the retirement and availability schedule.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'Two numbers decide presence',
        tab: 'Build',
        note: 'coal_old reads 1985 and 50: 1985 + 50 = 2035, so it is gone by the 2040 period. coal_new '
          + 'reads 2000 and 45 (retires 2045), gas_ccgt 2010 and 45 (retires 2055). A vintage reads its '
          + 'own period as build_year and 25 as lifetime.',
      },
    ],
    verify: [
      'You have written out which units are active in each of 2030, 2040 and 2050',
      'You can say why coal_old is absent in 2040 although it was built only 55 years before then',
      'You can say why a retirement in 2031 and one in 2039 give the same result',
      'You can say what the model does not count for wind_2040 after 2059',
    ],
    pitfalls: [
      'Treating build_year as when the optimiser chooses to build. For a vintage it is when the asset '
      + 'EXISTS; the optimiser decides how much of it to buy, and buying zero is a perfectly good answer.',
      'Leaving a vintage\'s build_year blank or 0. PyPSA reads 0 as "always existed", so a wind_2040 with '
      + 'no build year is available in 2030 at its 2040 price.',
    ],
  },

  {
    id: 'm16-run-the-baseline',
    section: SECTION,
    title: 'Run it: the system waits',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Predict before you run. In 2030 coal at 20 per MWh is the cheapest plant on the bus and nothing '
      + 'forces it out; a new wind farm costs 1.6 million per MW today and 1.3 million in ten years. '
      + 'Coal_old retires before 2040, so something must replace 150 MW by then — and gas does at 55 per MWh, '
      + 'which new wind and solar undercut.',

      'The plan that follows is an old idea in capital planning: do not buy until you must, and buy the '
      + 'cheaper vintage when you do. Nothing is built in 2030. In 2040 the model builds wind, a little '
      + 'solar and some battery; in 2050 it builds a lot more, up to the p_nom_max it was given. It is not '
      + 'being slow. Waiting is the optimum while the price of the thing you would buy keeps falling.',

      'The cost of that delay is carbon: with no policy in the model, the units that are still alive '
      + 'burn fuel. The pathway emits about 1.19 million tonnes a year in 2030, 0.97 in 2040 and 0.06 in '
      + '2050 — the 2050 figure low only because coal_new retires and cheap wind and solar have arrived.',
    ],
    explain: [
      'Run dialog → Validate, then Run model. Validation should report no errors; a pathway run checks '
      + 'that every period you configured appears on the snapshots sheet.',

      'The run is queued: when it finishes, History → tick the run → View result opens Analytics → Result. '
      + 'The page shows ONE period at a time and opens on 2030 — the KPI strip there reads Total cost 226,889,583 and '
      + 'Emissions 11,893 ktCO2e. Click 2040 and 2050 for the others. Throughout this module the RUN TOTAL means the '
      + 'three period views added: 226,889,583 + 205,870,256 + 156,805,389 = 589,565,228 (the run reads 589,565,227: each view is rounded to a whole unit on its own), and 11,893 + 9,673 + 591 = '
      + '22,158 ktCO2e. The API gives the same sums directly: /api/runs/{run name}/kpis, with the run name from '
      + 'History. That emissions total is NOT 22 million tonnes a year — it is the three decades added together, '
      + 'each multiplied by its ten years. Step 5 takes it apart.',

      'Look at the Capacity Expansion card for what was built. Nothing in 2030. In 2040: wind_2040 183.4 '
      + 'MW, solar_2040 7.6 MW, batt_2040 39.6 MW. In 2050: wind_2050 200 MW and solar_2050 250 MW — both at '
      + 'their p_nom_max — and batt_2050 100 MW, also at its limit. Three bounds binding in the last period '
      + 'is a flag: the system wanted more, and the answer there is set by the limits you were given, not by economics.',

      'That is a lesson about p_nom_max rather than about pathways: a bound that binds is a result you '
      + 'wrote yourself. Raise wind_2050\'s limit and the plan changes — worth trying once you have finished '
      + 'the module.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: 'Reconcile the three periods',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The period views add to a run total of 589,565,227, in 2030 money: fuel 365,027,989 plus capital '
          + '224,537,238. It is a present value of three decades, not a year — so it is much larger than any '
          + 'single-period number in this course, and cannot be compared with them.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Emissions are x years',
        tab: 'Analytics',
        note: 'The 2030 view reads 11,893 ktCO2e: the period\'s annual emissions multiplied by its ten years. '
          + 'The three periods add to 22,158. Read it as "tonnes over the decade", never as a rate.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'What was built, and when',
        tab: 'Analytics',
        note: 'Nothing is bought in 2030. The 2040 vintages are partial builds; the 2050 ones hit their '
          + 'p_nom_max. A vintage appears here under its own name, which is how the build year shows up in '
          + 'a table that has no time column.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'A pathway run solves three periods of 24 snapshots jointly — about a second.',
        'Nothing outside the pathway settings has changed since the checkpoint.',
      ],
      expect: 'Run total 589,565,227; nothing built in 2030; wind_2040 183.4 MW and wind_2050 200 MW; emissions 22,158 ktCO2e.',
    },
    verify: [
      'The three period views read Total cost 226,889,583, 205,870,256 and 156,805,389 (run total 589,565,227)',
      'Nothing with a 2030 name has a non-zero build; wind_2040 is about 183 MW and wind_2050 is 200 MW',
      'solar_2050 and batt_2050 sit at their p_nom_max (250 and 100 MW)',
      'You can say why the optimiser builds nothing in 2030',
    ],
    pitfalls: [
      'A total cost near 589,565,227 but a build in 2030. Check the objective weights: with weight 1 on '
      + 'every period the future is undiscounted and early builds look better than they should.',
      'An error about periods not matching. The period numbers in the Settings table must be exactly the '
      + 'values in the snapshots period column — 2030, not 2031.',
      'Reading 11,893 ktCO2e as an annual rate. It is years-weighted: 2030 emits 1.19 Mt a year and the view shows '
      + 'that x 10.',
    ],
  },

  {
    id: 'm16-period-views',
    section: SECTION,
    title: 'Reading one period at a time',
    tab: 'Analytics',
    where: 'Analytics → Result → Pathway period selector',
    concept: [
      'A pathway has one solution and several ways to look at it. The period selector re-reads the same '
      + 'run for one investment period: the server extracts that period\'s slice and applies three rules '
      + 'so the views stay honest.',

      'First, INACTIVE ASSETS ARE MASKED. In the 2040 view coal_old does not appear in capacity or '
      + 'generation even though its row is still in the workbook — it has retired. Without the mask the '
      + 'capacity chart would count 641 MW in 2040 instead of 491, and curtailment and capital would be '
      + 'computed over plant that does not exist.',

      'Second, ENERGY IS SUMMED AND MONEY IS WEIGHTED. Generation, emissions and prices describe what '
      + 'happens in the period. Cost is multiplied by that period\'s objective weight, because the '
      + 'objective is. So the three period views of "Total cost" add up to the whole-run number; they are '
      + 'each period\'s contribution to the present value, not that year\'s outlay.',

      'Third, EMISSIONS ARE YEARS-WEIGHTED. The KPI strip\'s emissions in a period view is the annual '
      + 'figure times the period\'s years weight — 11,893 kt for 2030, though the system emits 1.19 Mt in a '
      + 'year. That is the quantity a cap on the period is written against, so it is the one worth '
      + 'seeing.',
    ],
    explain: [
      'Analytics → Result. The "Pathway period" card has one button per period. Click 2030, then 2040, then '
      + '2050, and read the KPI strip each time. The page reloads each period from the server.',

      'Capacity is on the capacity-by-period card, which stacks every period at once: hover each stack for '
      + '450 MW in 2030, 491 MW in 2040 and 791 MW in 2050 — against 641 MW in 2040 if coal_old were wrongly '
      + 'counted. The KPI strip\'s Total cost for the three views reads 226,889,583, 205,870,256 and '
      + '156,805,389, which add to 589,565,227 (give or take a unit of rounding).',

      'Emissions: 11,893, 9,673 and 591 ktCO2e. Renewable share: 0%, 33.8%, 92.5%. The price range shows '
      + 'the fuel on the margin changing — 20 flat in 2030 (coal), up to 34 in 2040, and 8 to 55 in 2050, when '
      + 'gas sets the evening peak and surplus renewables can push the price below coal.',

      'The period route is the same one an agent or a script would call: '
      + 'GET /api/runs/{name}/period/{period} returns the full result for that period, and '
      + '/api/runs/{name}/kpis?period= the KPI strip. The selector is only a button on top of it.',
    ],
    spotlights: [
      {
        selector: '.period-pill-row',
        title: 'The period selector',
        tab: 'Analytics',
        note: 'One button per investment period. Everything below it re-reads from the server for the '
          + 'period you pick, with inactive assets masked and money weighted by that period\'s objective '
          + 'weight. It is the only thing on the page that changes when you click.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Per-period totals add up',
        tab: 'Analytics',
        note: 'Total cost reads 226,889,583 in 2030, 205,870,256 in 2040 and 156,805,389 in 2050 — these '
          + 'sum to the whole run\'s 589,565,227. Emissions are years-weighted: 11,893 kt in 2030, not 1,189.',
      },
      {
        selector: '[data-card="capacity-by-period"]',
        title: 'Capacity by period',
        tab: 'Analytics',
        note: 'Installed capacity per period, stacked by carrier, applying the same activity rule as the '
          + 'optimiser: 450, 491 and 791 MW. coal_old is in 2030 and absent from 2040 on; the vintages appear '
          + 'in their own decade.',
      },
    ],
    verify: [
      'The capacity-by-period card stacks 450, 491 and 791 MW for 2030, 2040 and 2050',
      'The three Total cost figures add up to 589,565,227, give or take a unit of rounding',
      'Emissions read 11,893, 9,673 and 591 ktCO2e in the three views',
      'You can say why the 2040 capacity is 491 MW and not 641 MW',
      'You can say why a period\'s Total cost is not that decade\'s annual spend',
    ],
    pitfalls: [
      'Reading a period\'s Total cost as money spent in that year. It is weighted by the period\'s '
      + 'objective weight (4.9775 for 2040), so it is the discounted worth of ten years of cost, in 2030 money.',
      'Comparing the run total of Emissions with a single-period run from an earlier module. That figure '
      + 'covers thirty years; the single-period ones covered one.',
      'Expecting the selector to re-solve. It does not: it re-reads one run. A different answer needs a '
      + 'different run.',
    ],
  },

  {
    id: 'm16-retirement',
    section: SECTION,
    title: 'Retirement is an input, and sometimes it does not matter',
    tab: 'Analytics',
    where: 'Build → Generators, then run again',
    concept: [
      'Keeping a plant alive is a modelling decision with a number attached. Take coal_old and change its '
      + 'lifetime from 50 to 60 years: it now retires in 2045 instead of 2035, so it is still there in the '
      + '2040 period. One cell.',

      'With no policy in the model, the effect is large and a little perverse. 2040 emissions rise from '
      + '9,673 to 13,372 kt, because 150 MW of cheap coal is back and the system builds almost nothing in '
      + '2040 (42 MW of solar, no wind, no battery) to replace it. The total cost FALLS, from 589,565,227 to 581,972,357 — keeping the old '
      + 'plant is cheaper, which is exactly why plants are not retired just because a table says they '
      + 'should be.',

      'The same change under a binding cap does nothing at all. With the emission caps of step 9, coal_old '
      + 'is not used in 2040 either way and the total cost is identical to the dollar. A policy that '
      + 'binds hard enough overrides the plant\'s retirement date: the date matters when the market is '
      + 'free to choose, and not when something else already chose.',
    ],
    explain: [
      'Build → Generators: click the coal_old row and, in the form on the right, change its `lifetime` from 50 to 60. Run again. Read period 2040 on '
      + 'the selector: coal_old is back in the capacity-by-period stack (492 MW in all), the Capacity '
      + 'Expansion card shows no battery built, and Emissions read 13,372 ktCO2e. The run total (the three period views '
      + 'added, as in step 4) is 581,972,357 and its Emissions 27,827 ktCO2e.',

      'Check 2050 too: emissions 2,562 kt against 591 before. Delaying the build-out in 2040 means less '
      + 'renewable capacity is alive in 2050, and gas covers more of the evening.',

      'Now set lifetime back to 50 and re-run. The module\'s later steps all assume it.',

      'In step 9, once the caps are in, you can come back to this cell once more: lifetime 60 with the '
      + 'caps gives 626,611,134 — the same objective as lifetime 50, because the caps leave coal_old '
      + 'nothing to do in 2040.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'One cell',
        tab: 'Build',
        note: 'coal_old.lifetime from 50 to 60. A single number moves the retirement from 2035 to 2045 and '
          + 'so changes which period it is active in. Note it before you leave: the next step assumes 50.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: '13,372 kt, and a cheaper pathway',
        tab: 'Analytics',
        note: 'In the 2040 view, Emissions reads 13,372 ktCO2e against 9,673 before and Total cost 166,349,676. '
          + 'The whole run is cheaper (581,972,357) and dirtier (27,827 kt). Retiring a plant early is '
          + 'something the optimiser has no reason to do on cost alone.',
      },
    ],
    entries: [
      {
        field: 'generators.lifetime (coal_old, the experiment)',
        label: 'coal_old service life',
        value: '60',
        unit: 'years',
        why: 'Moves coal_old\'s retirement from 1985 + 50 = 2035 to 1985 + 60 = 2045, so it is still '
          + 'active in the 2040 period. The cheapest possible demonstration that retirement is a number '
          + 'you chose.',
      },
      {
        field: 'generators.lifetime (coal_old, restore)',
        label: 'coal_old service life, back',
        value: '50',
        unit: 'years',
        why: 'Returns the model to the checkpoint. Every later number assumes coal_old retires between '
          + '2030 and 2040; leaving 60 would quietly change them all.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (twice: lifetime 60, then 50)',
      detail: [
        'Each run is about a second. Use Analytics → Comparison to put the two side by side.',
      ],
      expect: 'At lifetime 60: run total 581,972,357, 2040 emissions 13,372 kt. At 50: back to 589,565,227.',
    },
    verify: [
      'At lifetime 60 the 2040 stack in the capacity-by-period card reads 492 MW and the 2040 view 13,372 ktCO2e',
      'The run total reads 581,972,357 and Emissions 27,827 ktCO2e',
      'After restoring 50 the run is 589,565,227 again',
      'You can say why a longer-lived coal plant makes the pathway cheaper and dirtier',
    ],
    pitfalls: [
      'Forgetting to restore 50. The module continues from the checkpoint; with coal_old alive in 2040 the '
      + 'caps of step 9 bind differently and none of its numbers match.',
      'Concluding a retirement date never matters because step 9 shows it vanishing under a cap. It '
      + 'vanishes because THAT cap is tight enough to overrule the plant; a looser cap would let it matter again.',
    ],
  },

  {
    id: 'm16-annuity-and-overnight',
    section: SECTION,
    title: 'Overnight cost, annuity, and being charged every period',
    tab: 'Analytics',
    where: 'Analytics → Result → Capacity Expansion card',
    concept: [
      'The workbook\'s `overnight_cost` is what building a megawatt costs up front. The objective needs a '
      + 'figure it can set against fuel, so PyPSA converts it to an annuity: overnight x r / (1 - (1 + r)^-L), '
      + 'with L the asset\'s `lifetime` and r its `discount_rate`, times n.nyears for each period (1 here: each '
      + 'period is one representative year). At 5% a 25-year wind farm at 1.3 million per MW becomes 92,238 per '
      + 'MW per year; the factor is 0.0709525. `capital_cost` is the other column: PyPSA takes it as already '
      + 'periodised and does nothing to it.',


      'The annual charge is then applied in EVERY period the asset is active, each time multiplied by that '
      + 'period\'s objective weight. wind_2040 is active in 2040 and 2050, so it is charged twice — 92,238 '
      + 'per MW-year x 183.4 MW = 16.9 million a year, in each of two periods. A battery of lifetime 15 uses '
      + 'a different factor, 0.0963423, so 350,000 overnight is 33,720 a year.',

      'Two traps follow. The first is entering a cost that is already annual into `overnight_cost`: PyPSA would '
      + 'annuitise it again and the asset would look about 14 times too cheap (1 / 0.0709525). The second is subtler. '
      + 'Charging whole periods means an asset is paid for in every period it touches: solar built in 2030 with '
      + 'a 25-year life is active in 2030, 2040 and 2050 and is charged for thirty years of annuity — five more '
      + 'than it lives. Granularity has a price, and the price is biggest for assets whose life is not a '
      + 'multiple of the period.',
    ],
    explain: [
      'Analytics → Result. The Capacity Expansion card covers every period at once. In its Asset detail table, find wind_2040: '
      + 'Optimised 183.4 MW and CAPEX per year 16,915,470. Divide: 16,915,470 / 183.4 = 92,238 per MW-year, which '
      + 'is 1,300,000 x 0.0709525. That annual charge is levied in each of the two periods the asset is alive, '
      + 'so the objective carries 16,915,470 x (4.9775 + 3.0558), about 135.9 million, for this one vintage.',

      'Compare batt_2040: CAPEX per year 1,334,226 on 39.6 MW is 33,720 per MW-year (350,000 x 0.0963423), also '
      + 'alive in 2040 and 2050. And wind_2050, alive only in 2050 and charged once: 14,190,491 on 200 MW is '
      + '70,952 per MW-year — 1.0 million x 0.0709525.',

      'Total cost in each period view is fuel plus a line the cost breakdown labels "Capital cost (periodised, '
      + 'investment-period weighted)": nothing in 2030 (nothing was built), 92,583,128 in the 2040 view and '
      + '131,954,111 in 2050 — 224,537,238 over the run. The split is on Analytics → Comparison\'s cost panel '
      + '(with two runs) and at /api/runs/{name}/period/2040?fields=costBreakdown.',

      'The end-of-horizon effect is the one thing no card shows. Everything built in 2050 lasts past '
      + '2059 and earns nothing there, while its annuity is charged for the whole period. A pathway '
      + 'therefore penalises late, long-lived investment a little more than a real owner would be.',
    ],
    spotlights: [
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'Annuity, active periods, weighted capex',
        tab: 'Analytics',
        note: 'wind_2040: Optimised 183.4 MW, CAPEX per year 16,915,470 — that is 92,238 a MW-year, 1.3 million x '
          + '0.0709525. The same figure is charged in every period the asset is alive, which is how a lump-sum '
          + 'investment becomes a stream the objective can add up.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Total cost by period',
        tab: 'Analytics',
        note: 'Select 2030, 2040 and 2050 in turn: Total cost is 226.9, 205.9 and 156.8 million, of which the '
          + 'capital part is 0, 92.6 and 132.0 million. 2030 has none because nothing was built; 2050 carries the '
          + '2040 vintages AND its own.',
      },
    ],
    verify: [
      'wind_2040\'s CAPEX per year divided by its 183.4 MW is about 92,238 per MW-year',
      'wind_2050\'s CAPEX per year divided by its 200 MW is about 70,952 per MW-year, charged in one period only',
      'You can say why 350,000 overnight for a 15-year battery annualises to 33,720 and not 24,833',
      'You can say what would go wrong if a pre-annualised cost were typed into overnight_cost',
    ],
    pitfalls: [
      'Typing an annualised cost into overnight_cost. PyPSA annuitises whatever it finds there; a '
      + 'cost already annual comes out roughly fourteen times too small and the optimiser builds '
      + 'everything it is allowed to.',

      'Expecting the capital charge to stop at the battery\'s 15-year life. Periods are ten years wide, '
      + 'so a 15-year asset is charged in the second period it touches in full — the model has no half-periods.',
    ],
  },

  {
    id: 'm16-carbon-price-schedule',
    section: SECTION,
    title: 'A carbon price that rises with the decades',
    tab: 'Market',
    where: 'Market & Policy → Carbon price → Schedule',
    concept: [
      'The cheaper policy to write is a price. Ragnarok takes a year-to-price schedule and adds '
      + 'price x emission factor to each emitting generator\'s marginal cost. In a pathway the "year" it '
      + 'reads is the PERIOD label: a snapshot in the 2040 period uses the most recent schedule entry '
      + 'whose year is at or below 2040.',

      'Take 20 in 2030, 60 in 2040 and 120 in 2050. Emissions fall to 570,936 t a year in 2030, 123,492 in '
      + '2040 and 0 in 2050 — the price in 2050 prices fossil generation out of the market altogether. The '
      + 'builds move forward: wind_2030 128.9 MW and solar_2030 133.2 MW appear, which the no-policy run '
      + 'never builds. Part of the reason is that these vintages are alive in the decades with the highest '
      + 'prices, so they earn their cost back later as well as now.',

      'A price does not pin emissions. It fixes a price and lets the system choose a quantity — and here '
      + 'the quantity it chooses is nowhere near the caps of step 9 (570,936 against 1,000,000 in 2030). '
      + 'Which policy is "tighter" depends on the number you wrote, not the instrument.',

      'And the cost is not comparable. The objective now INCLUDES the carbon payments — 129.5 million of '
      + 'them — so the run\'s Total cost, 872,790,016, is not a resource cost. Module 8 made the same point '
      + 'for a single period: a price moves money between the emitter and the treasury.',
    ],
    explain: [
      'Market & Policy → Carbon price. The schedule is a chart. Click empty space to add a point, select '
      + 'it, and type its year and price in the two boxes under the chart. Add three points: 2030 at 20, '
      + '2040 at 60, 2050 at 120. While the schedule has points, the scalar price above it is greyed out.',

      'Click Apply to model: Ragnarok checks that carriers have co2_emissions and that something emits, and '
      + 'confirms the schedule will price those generators. Then run.',

      'Read the three periods. 2030: Emissions 5,709 ktCO2e, renewable share 52%. 2040: 1,235 kt, 91%. '
      + '2050: 0 kt, 100%. The run total reads 872,790,016 and Emissions 6,944 kt.',

      'Now remove the schedule — delete the three points — so the next steps start from no price. A '
      + 'cap and a price at once is a different experiment from the one step 9 sets up.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Market & Policy"]',
        title: 'Market & Policy → Carbon price',
        note: 'The schedule lives here, not in Settings, because a price changes what the solve optimises '
          + 'rather than how. In a pathway the schedule\'s year is matched to each investment period.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'The price shows in the emissions',
        tab: 'Analytics',
        note: 'Per period: 5,709, 1,235 and 0 ktCO2e, down from 11,893, 9,673 and 591. The 2050 figure is '
          + 'zero: at 120 per tonne no gas runs. Cost is not comparable with the no-policy run because it '
          + 'now contains the carbon payments.',
      },
    ],
    entries: [
      {
        field: 'Market & Policy → Carbon price → schedule point 1 (Year / Price)',
        label: 'first schedule point',
        value: '2030 / 20',
        unit: 'per tCO2',
        why: 'The price in force for the 2030 period. A modest starting price: it does not reorder coal and gas '
          + '(coal 20 + 0.85 x 20 = 37 per MWh against gas 55 + 0.4 x 20 = 63) but it makes wind and solar '
          + 'worth building, which is what cuts 2030 emissions.',
      },
      {
        field: 'Market & Policy → Carbon price → schedule point 2',
        label: 'second schedule point',
        value: '2040 / 60',
        unit: 'per tCO2',
        why: 'The price from 2040 until the next entry. Each snapshot uses the most recent entry at or '
          + 'below its period, so every 2040 snapshot is priced at 60 whatever its date inside the decade.',
      },
      {
        field: 'Market & Policy → Carbon price → schedule point 3',
        label: 'third schedule point',
        value: '2050 / 120',
        unit: 'per tCO2',
        why: 'High enough that fossil generation clears nothing in the last period — gas at 55 + 0.4 x 120 '
          + 'is 103 per MWh against wind and solar near zero. It is a policy choice, not a forecast.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One pathway solve. The schedule is read at build time, so no validation is needed beyond Apply to model.'],
      expect: 'Emissions 5,709 / 1,235 / 0 kt by period; run total 872,790,016 (it includes carbon payments).',
    },
    verify: [
      'The schedule has three points: 2030 at 20, 2040 at 60, 2050 at 120, and the scalar box is greyed out',
      'The period views show Emissions of 5,709, 1,235 and 0 ktCO2e',
      'wind_2030 and solar_2030 are now built (about 129 and 133 MW)',
      'You can say why this run\'s Total cost cannot be compared with the no-policy run\'s',
      'You have deleted the schedule again before the next step',
    ],
    pitfalls: [
      'Leaving the schedule in place for step 9. The caps would then sit on top of a price and the cap '
      + 'plan would not match the numbers there.',
      'Typing 2040 as the year and expecting 2040 snapshots to be priced from January. The year is the '
      + 'period label, so the whole 2040 period carries the 2040 entry.',
    ],
  },

  {
    id: 'm16-a-cap-trajectory',
    section: SECTION,
    title: 'The other policy: a cap that tightens',
    tab: 'Market',
    where: 'Market & Policy → Standard Constraints → PyPSA global_constraints sheet',
    concept: [
      'A cap states the quantity directly. In PyPSA it is a global constraint of type primary_energy on '
      + 'co2_emissions with an investment_period — one row per period, each its own limit. Tightening the '
      + 'cap over time is just three rows with falling numbers.',

      'The number you type is TONNES PER PERIOD, not per year. PyPSA multiplies the period\'s emissions '
      + 'by its years weight before comparing them with the constant, so a period that stands for ten years '
      + 'is capped at ten years of emissions. A target of 1.0 million tonnes a year in 2030 is typed '
      + '10,000,000. Step 10 shows what happens when it is not.',

      'The trajectory here is 1.0, 0.4 and 0.03 Mt a year: 10,000,000, 4,000,000 and 300,000 tonnes per '
      + 'period. Against the no-policy pathway\'s 1.19, 0.97 and 0.06 Mt a year that is a 16% cut in 2030, a '
      + '59% cut in 2040 and a 49% cut in 2050 — the last one small only because 2050 is nearly clean already.',

      'What the cap costs shows up in two places: the total (626,611,134, up 37 million from no policy) and the '
      + 'shadow price of the binding constraint. The CO2 shadow card reports one number, the '
      + 'largest in magnitude — 2030\'s, 12.05 — and it is in DISCOUNTED currency per period-tonne. In '
      + '2030 money per annual tonne that is 12.0533 x 10 / 8.1078 = 14.87. Compare it with a price '
      + 'only after converting.',
    ],
    explain: [
      'Market & Policy → Standard Constraints. The lower table, "PyPSA global_constraints sheet", is the '
      + 'global_constraints sheet itself (Build → Constraints only summarises it). Press + Add global constraint '
      + 'three times and fill each row: names co2_cap_2030, co2_cap_2040, co2_cap_2050; investment_period 2030, '
      + '2040, 2050; sense <=; constants 10000000, 4000000, 300000. A new row arrives with type primary_energy and '
      + 'carrier_attribute co2_emissions already filled, and sense set to ==: change it to <= from its drop-down. '
      + 'The investment_period box suggests your configured periods once pathway mode is on.',

      'Check the carbon schedule from step 8 is gone, then run. Run total 626,611,134. Read the period '
      + 'views: Emissions are exactly 10,000, 4,000 and 300 ktCO2e — each cap binds to the tonne, because '
      + 'emitting less costs more and nothing rewards it.',

      'Builds: solar_2030 89.3 MW appears — the only vintage the 2030 cap calls for — then wind_2040 200 MW '
      + '(its p_nom_max), solar_2040 154.6 MW and batt_2040 89 MW; and in 2050 wind_2050 200, solar_2050 41.6 '
      + 'and batt_2050 100.',

      'The CO2 shadow card is not in the default Result layout. Analytics → Analytics sub-tab → Edit layout → '
      + '+ Add row, then the + in the new empty cell, CO₂ shadow price (that sub-tab keeps your layout; Result '
      + 'rebuilds its own every time). It reads Binding, co2_cap_2030, shadow price $12.053 per tonne. The 2040 cap has '
      + 'a dual of 8.39 and the 2050 cap 0.69, in the same discounted units — the card shows only the largest.',

      'Optional: go back to step 6 and set coal_old\'s lifetime to 60 once more. Total cost stays '
      + '626,611,134. Set it back to 50.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="constraints"]',
        title: 'global_constraints',
        tab: 'Market',
        note: 'Three rows, one per period. The investment_period column is what ties a row to a decade; a '
          + 'row with it blank would be one cap across the whole run. Every attribute is a plain PyPSA '
          + 'global-constraint column.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Binding to the tonne',
        tab: 'Analytics',
        note: 'Per-period Emissions read 10,000, 4,000 and 300 ktCO2e — exactly the caps. The three Total costs add '
          + 'to 626,611,134, 37 million above the no-policy run: the price of the 16%, 59% and 49% cuts.',
      },
      {
        selector: '[data-card="co2-shadow"]',
        title: 'One shadow price of three',
        tab: 'Analytics',
        note: 'Binding, co2_cap_2030, $12.053 per tonne. It is the dual of the objective, '
          + 'which is discounted: in 2030 dollars per annual tonne it is 14.87. Two other caps also bind '
          + 'and are not shown.',
      },
    ],
    entries: [
      {
        field: 'global_constraints.name / investment_period (row 1)',
        label: 'first cap: name and period',
        value: 'co2_cap_2030 / 2030',
        why: 'One row per period. The name is free text but is what the shadow-price card reports; the '
          + 'investment_period is the part that matters, tying the limit to the 2030 decade only.',
      },
      {
        field: 'global_constraints.type / carrier_attribute / sense (every row)',
        label: 'what the constraint limits',
        value: 'primary_energy / co2_emissions / <=',
        why: 'primary_energy limits the sum over generators of fuel burnt x emission factor — the module 1 '
          + 'column, put to work. carrier_attribute co2_emissions selects that factor. Both come pre-filled; sense '
          + 'does not — it starts at ==, and <= is what makes it a ceiling.',
      },
      {
        field: 'global_constraints.constant (rows 1 to 3)',
        label: 'the three caps',
        value: '10000000 / 4000000 / 300000',
        unit: 'tCO2 per period',
        why: 'Annual tonnes x the years weight of 10: 1.0, 0.4 and 0.03 Mt a year. They are written per '
          + 'period because PyPSA multiplies a period\'s emissions by its years before comparing, so the '
          + 'constant and the years weight are one decision.',
      },
      {
        field: 'global_constraints.name / investment_period (rows 2 and 3)',
        label: 'second and third caps',
        value: 'co2_cap_2040 / 2040 and co2_cap_2050 / 2050',
        why: 'The same three columns repeated with the later decades. If you add them one at a time and run '
          + 'between, you can watch each cap pull the plan earlier — step 12 does that deliberately.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One pathway solve with three extra constraints — about a second.'],
      expect: 'Run total 626,611,134; period emissions exactly 10,000 / 4,000 / 300 kt; shadow price about 12.05.',
    },
    verify: [
      'global_constraints has three rows, each with its own investment_period and the constants above',
      'The period views read Emissions of 10,000, 4,000 and 300 ktCO2e',
      'Run total reads 626,611,134, and solar_2030 is built at about 89 MW',
      'The CO2 shadow card (added from the Analytics sub-tab) reads binding, co2_cap_2030, about 12.05',
      'You can convert that shadow price to 2030 dollars per tonne',
    ],
    pitfalls: [
      'Typing annual tonnes (1000000, 400000, 30000) with years 10. Step 10 does that on purpose; here it '
      + 'would make every cap ten times too tight and the run far more expensive.',
      'Leaving sense at its default ==. Here every cap binds, so the plan comes out the same; with a cap the '
      + 'system would not reach on its own, an equality becomes a requirement to emit that much.',
      'Leaving investment_period blank. The row becomes one cap across the entire pathway, which is a '
      + 'different and much looser policy than three separate ceilings.',
      'Comparing 12.05 with a carbon price directly. It is a dual of a discounted objective, per '
      + 'period-tonne; only 14.87 is in 2030 money per tonne.',
    ],
  },

  {
    id: 'm16-years-weight',
    section: SECTION,
    title: 'The years weight scales the cap, in both directions',
    tab: 'Settings',
    where: 'Settings → Multi-year planning, then run again',
    concept: [
      'A cap constant and a years weight are one decision. The constraint reads (annual emissions) x '
      + '(years) <= constant. Move either and you have moved the cap, and nothing flags it.',

      'There are two mistakes, and they are mirror images. Set the years weight to 1 with the per-period '
      + 'constants still in place and the model sees annual emissions against a ten-year constant: the caps '
      + 'are ten times too loose, none of them binds, and the run is the no-policy run — run total 589,565,227, '
      + 'period emissions 1,189 / 967 / 59 kt.',

      'The other is the more expensive one. Type the ANNUAL tonnes (1,000,000 / 400,000 / 30,000) with a '
      + 'years weight of 10, and the caps are ten times too tight. The model complies — it builds heavily in '
      + 'every period (wind_2030 and wind_2040 at their 200 MW limit, a 100 MW battery in all three) and emits '
      + '100,000 t a year in 2030 — at a '
      + 'Run total of 907,496,654, forty-five per cent more than the intended plan\'s 626,611,134. Both '
      + 'runs solve. Neither warns.',

      'The remedy is to read the result against what you meant: the period views show the cap as emissions '
      + 'x years, so 2030 should read about 10,000 ktCO2e when you intended 1.0 Mt a year. A figure ten '
      + 'times off is the signature.',
    ],
    explain: [
      'First the loose direction. Settings → Multi-year planning: set the Years column to 1 in all three '
      + 'rows and run, with the caps from step 9 still in the model. Run total 589,565,227 — exactly the '
      + 'no-policy number. The period views read Emissions 1,189 / 967 / 59 kt and the CO2 shadow card '
      + 'says the constraint is slack.',

      'Put Years back to 10 in all three rows. Then the tight direction: Market & Policy → Standard Constraints, retype the three '
      + 'constants as annual tonnes — 1000000, 400000, 30000 — and run. Run total 907,496,654; period '
      + 'Emissions 1,000, 400 and 30 kt (which is 100,000, 40,000 and 3,000 tonnes a year). Renewables are '
      + '88%, 96% and 99.6% of generation.',

      'Finally the matching pair that is right: with Years back at 1 and these annual constants, the plan '
      + 'is the intended one again, 626,611,134 to the dollar. It is the same constraint written two ways. '
      + 'Restore the module\'s state — years 10, constants 10000000 / 4000000 / 300000 — before going on.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="planning"]',
        title: 'The Years column',
        tab: 'Settings',
        note: 'Set it to 1 and the per-period caps stop binding, with no message. Years is the number a '
          + 'cap multiplies by; cost does not use it, which is why the objective is unchanged in the '
          + 'first experiment until a cap is present to notice.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Read the cap as emissions x years',
        tab: 'Analytics',
        note: 'A 2030 period that should read about 10,000 ktCO2e reads 1,189 (caps ten times too loose) or '
          + '1,000 (ten times too tight). Learn the signature: if the strip is a factor of ten from what you '
          + 'meant, the years weight and the constant disagree.',
      },
    ],
    entries: [
      {
        field: 'Settings → Multi-year planning → Years (all rows), experiment 1',
        label: 'years, set too low',
        value: '1',
        unit: 'years',
        why: 'Makes each period weigh a single year in every energy-sum constraint. With the caps typed per '
          + 'period they become ten times too loose and stop binding. Restore 10 afterwards.',
      },
      {
        field: 'global_constraints.constant (experiment 2, with Years back at 10)',
        label: 'annual tonnes typed as caps',
        value: '1000000 / 400000 / 30000',
        unit: 'tCO2',
        why: 'The intended annual limits, typed without the years factor. With Years 10 each constant is '
          + 'ten times too tight. The run is feasible and far costlier — the expensive way to learn the '
          + 'units of a constraint.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (three runs)',
      detail: ['Years 1 with the module caps; Years 10 with annual caps; then restore everything.'],
      expect: 'Years 1: run total 589,565,227 (cap slack). Annual caps at Years 10: 907,496,654.',
    },
    verify: [
      'With Years 1 and the module caps, run total reads 589,565,227 and period emissions 1,189 / 967 / 59 kt',
      'With Years 10 and annual caps, run total reads 907,496,654 and period emissions 1,000 / 400 / 30 kt',
      'You have restored Years 10 and the constants 10000000 / 4000000 / 300000',
      'You can say which direction of error is more expensive, and why neither is flagged',
    ],
    pitfalls: [
      'Forgetting to restore. The later steps assume Years 10 and the module caps; a leftover annual cap '
      + 'turns step 12\'s numbers into ones from a different problem.',
      'Concluding that a slack cap means the policy is working. It may mean the policy is ten times too weak '
      + 'to notice — the shadow-price card reads slack in both cases.',
    ],
  },

  {
    id: 'm16-only-ratios-matter',
    section: SECTION,
    title: 'Objective weights: only the ratios matter',
    tab: 'Settings',
    where: 'Settings → Multi-year planning, then run again',
    concept: [
      'The objective weights are multipliers on every cost in a period. Multiply all three by the same '
      + 'number and the optimiser\'s answer does not move — the same plan, a total cost scaled by that number. '
      + 'Weights of 10, 10, 10 and weights of 1, 1, 1 are the same problem; the second just prints a cost ten '
      + 'times smaller.',

      'What changes the plan is the RATIO between periods, which is the discounting. 8.1078 : 4.9775 : '
      + '3.0558 says 2050 costs count for 38% as much as 2030\'s. Drop the discounting (1 : 1 : 1) and the '
      + 'future counts in full: the plan shifts (solar_2030 85.9 MW against 89.3, solar_2040 165.7 against 154.6, '
      + 'batt_2040 100 MW against 89) and the 2050 cap, which binds when future costs are discounted, stops '
      + 'binding at all.',

      'The practical rule: the weights\' absolute size is a reporting convention, so choose one that makes '
      + 'the cost mean something — discounted years, so it reads as a present value. And write the formula '
      + 'down, because Ragnarok will accept any three numbers and give a plausible-looking answer.',
    ],
    explain: [
      'Settings → Multi-year planning. Set all three objective weights to 1 (keep Years at 10) and run '
      + 'with the module caps. Run total reads 128,682,062; solar_2030 is 85.9 MW and the 2050 period emits '
      + 'less than its cap (about 112 kt against 300).',

      'Now set all three to 10 and run again: run total 1,286,820,624, ten times the previous '
      + 'and with identical builds. The plan depends on the weights\' ratios only.',

      'Finally restore 8.1078, 4.9775 and 3.0558 and confirm 626,611,134 returns. The discounted plan is '
      + 'the only one of the three whose Total cost is a present value in 2030 money.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="planning"]',
        title: 'Obj. weight',
        tab: 'Settings',
        note: 'The middle column. 1 / 1 / 1 and 10 / 10 / 10 are the same problem at different units; '
          + '8.1078 / 4.9775 / 3.0558 is a different one, because it discounts the future. Only the '
          + 'discounted set makes Total cost a present value.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Compare the three runs',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Put the 1 / 1 / 1, 10 / 10 / 10 and discounted runs side by side: the first two have '
          + 'identical capacities and a cost ratio of exactly ten; the third differs in the capacities.',
      },
    ],
    entries: [
      {
        field: 'Settings → Multi-year planning → Obj. weight (all rows), experiment 1',
        label: 'objective weights, no discounting',
        value: '1 / 1 / 1',
        why: 'Every period counts as one undiscounted year. The plan changes only because the ratios did: '
          + 'the future is no longer cheaper than the present. It is also what the pre-filled rows hold.',
      },
      {
        field: 'Settings → Multi-year planning → Obj. weight (all rows), experiment 2',
        label: 'objective weights, scaled by ten',
        value: '10 / 10 / 10',
        why: 'The same ratios as 1 / 1 / 1, ten times the size: identical capacities, a Total cost exactly '
          + 'ten times larger. Proof that only the ratios between periods change the decision.',
      },
      {
        field: 'Settings → Multi-year planning → Obj. weight (restore)',
        label: 'the discounted weights, back',
        value: '8.1078 / 4.9775 / 3.0558',
        why: 'The checkpoint\'s values. Leaving 1 / 1 / 1 would hand step 12 a different plan.',
      },
    ],
    run: {
      label: 'Run dialog → Run model (three runs)',
      detail: ['Weights 1 / 1 / 1, then 10 / 10 / 10, then restore.'],
      expect: '128,682,062 at 1 / 1 / 1; 1,286,820,624 at 10 / 10 / 10 with the same builds; 626,611,134 restored.',
    },
    verify: [
      'At 1 / 1 / 1 the run total is 128,682,062 and at 10 / 10 / 10 it is 1,286,820,624',
      'Capacities are identical across those two runs, and solar_2030 is 85.9 MW, not 89.3',
      'After restoring the weights the run total is 626,611,134 again',
      'You can say why the weights\' size is a convention and their ratios are a decision',
    ],
    pitfalls: [
      'Comparing a cost from a 1 / 1 / 1 run with one from the discounted run. Both are right in their '
      + 'own units; they cannot be subtracted.',
      'Treating the pre-filled weight of 1 as "neutral". It is neutral only between periods of equal '
      + 'weight; applied to three decades of unequal discount factors it is a decision to ignore discounting.',
    ],
  },

  {
    id: 'm16-perfect-foresight',
    section: SECTION,
    title: 'Perfect foresight: a 2050 cap acts in 2040',
    tab: 'Analytics',
    where: 'Market & Policy → Standard Constraints, then run again',
    concept: [
      'Ragnarok solves one problem across all periods, so every decision sees every later one. That is '
      + 'PERFECT FORESIGHT: when the model chooses what to build in 2040 it already knows the 2050 cap. '
      + 'It has no myopic mode — each period decided with no view of the next — and the run options reference '
      + 'lists no such switch.',

      'You can see foresight at work. Keep only the 2050 cap and make the other two non-binding. Nothing '
      + 'constrains 2040, yet 2040 changes: batt_2040 goes from 39.6 MW to 97.7 MW and solar_2040 from 7.6 to '
      + '63.9 MW, because those vintages are still alive in 2050 and are the cheap way to meet the cap there. '
      + '2040 emissions rise slightly, 9,673 to 10,043 kt, as wind_2040 is cut back — the plan trades a '
      + 'little 2040 carbon for a cheaper 2050.',

      'A myopic planner would not do this. It would decide 2040 against 2040\'s conditions only and meet '
      + '2050\'s cap with whatever 2050 builds can do. Any such plan is also feasible in the joint problem, so '
      + 'perfect foresight can never cost more — it is a lower bound on cost, not a forecast of what an '
      + 'owner without the cap in view would do.',

      'That makes foresight the assumption to state, not a neutral default. A pathway tells you the best '
      + 'schedule for someone who knew the whole trajectory; it understates what an uncertain, '
      + 'year-by-year decision-maker would spend. Emulating myopia means separate runs per period with the '
      + 'earlier builds fixed as p_nom_min — possible by hand, not something Ragnarok does for you.',
    ],
    explain: [
      'Market & Policy → Standard Constraints. Set co2_cap_2030 and co2_cap_2040 to 100000000 (slack by a wide margin) and '
      + 'leave co2_cap_2050 at 300000. Run.',

      'Run total 591,142,245. Read the 2040 view: batt_2040 is about 98 MW on the Capacity Expansion card '
      + '(against 40 before), solar_2040 about 64 (against 8), and Emissions read 10,043 kt (against 9,673). '
      + 'Nothing constrains 2040, and its plan still moved.',

      'Compare with the no-policy run (Analytics → Comparison): the difference is a plan made in 2040 for a '
      + 'rule that applies in 2050. Then restore co2_cap_2030 and co2_cap_2040 to 10000000 and 4000000 for '
      + 'the closing step.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="constraints"]',
        title: 'Two caps made slack',
        tab: 'Market',
        note: 'Set 2030 and 2040 to 100,000,000 so they cannot bind, and leave 2050 at 300,000. The '
          + 'experiment has to leave the rows in place: deleting them changes the model, loosening them only '
          + 'removes their effect.',
      },
      {
        selector: '[data-card="capacity-by-period"]',
        title: '2040 prepares for 2050',
        tab: 'Analytics',
        note: 'The 2040 vintages are bigger than in the no-policy run — more storage and more solar — '
          + 'though 2040 itself has no cap. They are alive in 2050 and cheaper to buy a decade earlier.',
      },
    ],
    entries: [
      {
        field: 'global_constraints.constant (co2_cap_2030 and co2_cap_2040, the experiment)',
        label: 'two caps made slack',
        value: '100000000',
        unit: 'tCO2 per period',
        why: 'Far above any emission the system can produce, so those two rows exist but do nothing. '
          + 'Only the 2050 cap binds. A cleaner test than deleting rows, which also changes the model\'s shape.',
      },
      {
        field: 'global_constraints.constant (co2_cap_2030 and co2_cap_2040, restore)',
        label: 'the two caps, back',
        value: '10000000 / 4000000',
        unit: 'tCO2 per period',
        why: 'The checkpoint\'s values. The module\'s closing state has all three caps in force.',
      },
    ],
    run: {
      label: 'Run dialog → Run model',
      detail: ['One pathway solve with only the 2050 cap binding.'],
      expect: 'Run total 591,142,245; batt_2040 about 98 MW (was 40); 2040 emissions 10,043 kt (was 9,673).',
    },
    verify: [
      'Run total reads 591,142,245 with only the 2050 cap binding',
      'batt_2040 is about 98 MW and the 2040 view reads 10,043 ktCO2e',
      'You can say why a cap that applies only in 2050 changes the 2040 plan',
      'You can say what a myopic planner would do differently, and why Ragnarok cannot show it directly',
      'co2_cap_2030 and co2_cap_2040 are back to 10000000 and 4000000',
    ],
    pitfalls: [
      'Reading a pathway as a forecast of what will be built. It is the least-cost schedule for a planner '
      + 'who knows every later period; real decisions are made with less information and cost more.',
      'Deleting the two caps instead of loosening them. A global_constraints sheet with one row is a '
      + 'different model, and the checkpoint\'s three-row structure is what the closing step expects.',
    ],
  },

  {
    id: 'm16-what-changed',
    section: SECTION,
    title: 'What module 16 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Five things are now yours.',

      'A pathway is one joint problem over investment periods. Capacity bought in a period stays until it '
      + 'retires, every decision sees every later one, and the answer is the least-cost schedule for a '
      + 'planner with perfect foresight.',

      'Two weights, two jobs. The objective weight discounts cost — set it to discounted years and only '
      + 'its ratios matter. The years weight counts calendar years in energy-sum constraints, and a cap '
      + 'constant and the years weight are a single decision that can go wrong in either direction without '
      + 'a warning.',

      'build_year and lifetime are a schedule, applied per period. Retirement is something you set, it '
      + 'is invisible inside a decade, and it matters when the market is free and not when a binding '
      + 'policy has already chosen. Period views mask inactive assets, weight money and sum energy.',

      'And capital is an annuity charged in every period an asset is active — so an overnight cost must '
      + 'go into `overnight_cost`, and a 25-year asset built in 2030 is charged thirty years in a three-decade model.',
    ],
    explain: [
      'Three limits to name.',

      'Three representative days are not three years. Each period is one day of weather standing for 365 '
      + 'of them, so the plan never sees a dry year, a calm week or a heat wave — and module 12 showed what '
      + 'those do to adequacy. A real pathway uses many days per period, or weeks, and a reliability '
      + 'check on top.',

      'The horizon ends in 2059. Assets built late pay for a period they live through and are credited '
      + 'for nothing beyond it; a long-lived asset built in 2050 is undervalued. The usual remedy is a terminal '
      + 'value or a longer final period, and Ragnarok offers neither.',

      'And it is one policy path on one cost path. The cap trajectory and the falling costs are assumptions '
      + 'the answer is conditional on; module 9\'s habit of re-running under alternatives applies with '
      + 'more force here, because a wrong cost curve is wrong for thirty years.',

      'Export the project before you go — Model → Export project. The pathway table is stored in it.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Where the model ended up',
        tab: 'Analytics',
        note: 'With three caps in force: run total 626,611,134 and period emissions 10,000, 4,000 and 300 '
          + 'ktCO2e. It is the discounted cost of the cheapest schedule that meets a tightening cap with '
          + 'every decision seen in advance.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. The pathway periods and the carbon schedule library travel with '
          + 'it, so a re-opened project restores the Settings → Multi-year planning table.',
      },
    ],
    verify: [
      'The model reads: pathway on, weights 8.1078 / 4.9775 / 3.0558, years 10, caps 10 / 4 / 0.3 Mt, coal_old life 50',
      'Run total reads 626,611,134',
      'You can say what the years weight does that the objective weight does not',
      'You can name two things a three-representative-day pathway cannot see',
      'You have exported the project',
    ],
    pitfalls: [
      'Generalising the 2040 and 2050 builds. They hit p_nom_max in several places; a different bound '
      + 'or a different cost curve changes the plan, and the answer says as much about the limits as about '
      + 'the economics.',
      'Reading Total cost as a budget. It is a present value of three decades in 2030 money — useful for '
      + 'comparing plans, not for sizing next year\'s spend.',
    ],
  },
];
