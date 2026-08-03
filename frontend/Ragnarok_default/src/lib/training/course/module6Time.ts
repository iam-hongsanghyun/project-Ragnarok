/**
 * Module 6 — Time: resolution, representative periods and rolling horizon (9 steps).
 *
 * Five modules have run on three snapshots. That axis was chosen to make dispatch
 * checkable by hand, and it has quietly limited every conclusion since: three
 * hours cannot contain a daily cycle, so nothing that depends on one could show
 * its value.
 *
 * The proof is in module 5. It measured the pumped-hydro scheme at 45 and the
 * course said, correctly for that model, that it was nearly worthless behind the
 * constraint. On a real day the same scheme is worth 1,026 — twenty-three times
 * as much. Nothing about the asset changed. The horizon was wrong, and a wrong
 * horizon does not produce a noisy answer, it produces a confident one that is
 * about a different question.
 *
 * Built on module 5's model. Every figure verified against a real HiGHS solve:
 *
 *   24 snapshots at  1h   52,663.98    the reference
 *   12 snapshots at  2h   53,172.05    +0.96%
 *    6 snapshots at  4h   50,958.74    -3.24%
 *    4 snapshots at  6h   65,797.36   +24.94%
 *    2 snapshots at 12h   31,968.00   -39.30%
 *
 * That error column is the module's centrepiece: it is not monotonic and it does
 * not decay gently. Coarsening looks free until it is catastrophic, and it errs
 * in BOTH directions, so you cannot even sign your own bias.
 */
import { TutorialStep } from '../types';

const SECTION = '6 · Time — resolution and horizon';

export const MODULE_6_TIME: TutorialStep[] = [
  {
    id: 'm6t-why-time',
    section: SECTION,
    title: 'Three hours has been limiting every answer',
    tab: 'Build',
    where: 'Build → Snapshots step',
    startOptions: {
      prebuiltExampleId: 'training_m5',
      completeExampleId: 'training_m6',
      note:
        'Module 6 continues module 5\'s model — three buses, a CCGT, a gas store, a battery, a '
        + 'pumped-hydro scheme — which answered 7,099.59 over three hours. This module replaces those '
        + 'three hours with a real day and shows how much of what you concluded was about the axis.',
    },
    concept: [
      'Every model in this course has had three snapshots. That was a deliberate teaching choice and it '
      + 'has been stated at the end of every module — but it is worth being precise about what it cost, '
      + 'because it is more than accuracy.',

      'A three-hour window cannot contain a daily cycle. Anything whose value comes from moving energy '
      + 'from one part of a day to another — storage above all — was being asked to prove itself in a '
      + 'window shorter than the pattern it exists to exploit.',

      'Module 5 measured the pumped-hydro scheme at 45 and concluded it was nearly worthless behind the '
      + 'constraint. Over a real day the same scheme, in the same place, at the same cost, is worth '
      + '1,026. The conclusion was not noisy — it was confidently about a question nobody asked.',

      'That is the general hazard, and it is worse than imprecision. A model with too short a horizon, '
      + 'or too coarse a resolution, does not return an uncertain answer. It returns a definite answer '
      + 'to a subtly different problem, and nothing in the output says so.',
    ],
    explain: [
      'This module does three things. First it builds a real 24-hour day — a proper axis with a proper '
      + 'demand shape and wind that fades as the evening peak arrives.',

      'Then it coarsens that day deliberately and measures the damage: 2-hourly, 4-hourly, 6-hourly, '
      + '12-hourly, against the hourly answer. The results are not what most people expect.',

      'Then it covers the two techniques for making a long horizon tractable — sampled representative '
      + 'blocks and rolling horizon — and, more importantly, what each of them breaks.',

      'A warning before you start: replacing the snapshot axis does NOT replace the profiles indexed '
      + 'against it. Module 1 said so and this is where it bites. Step 2 walks into that deliberately so '
      + 'you meet it under supervision rather than in your own work.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="snapshots"]',
        buildStep: 'snapshots',
        title: 'Three rows, five modules',
        tab: 'Build',
        note: 'The axis every conclusion in this course has rested on. Everything else has grown — three '
          + 'buses, two carriers, four storage and generation technologies — and this has not moved since '
          + 'module 1.',
      },
      {
        selector: '.snapshot-builder',
        buildStep: 'snapshots',
        title: 'The builder, used properly this time',
        tab: 'Build',
        note: 'Module 1 used it to make three snapshots and warned that a year would be 8,760. The horizon '
          + 'list goes up to exactly that — and the warning about solve time is not decorative.',
      },
    ],
    verify: [
      'The session holds module 5\'s model with 3 snapshots and answers 7,099.59',
      'You can say why a three-hour window cannot value a daily storage cycle',
      'You can state what a too-short horizon does to an answer, and why it is worse than noise',
      'You can predict what will happen to the profiles when the axis is replaced',
    ],
    pitfalls: [
      'Treating horizon length as a precision setting. It decides which questions the model is capable '
      + 'of answering at all, which is a different kind of choice.',
    ],
  },

  {
    id: 'm6t-replace-the-axis',
    section: SECTION,
    title: 'Replace the axis — and watch the profiles break',
    tab: 'Build',
    where: 'Build → Snapshots step',
    concept: [
      'The snapshot builder replaces the axis. It does not touch any profile indexed against that axis, '
      + 'and it cannot sensibly: it has no way to know whether your 3 values should be stretched, '
      + 'repeated, interpolated or discarded.',

      'So a model that had 3 snapshots and 3 rows of demand now has 24 snapshots and 3 rows of demand. '
      + 'The remaining 21 hours have no profile value at all.',

      'What happens then is the dangerous part. A missing profile value does not error — the component '
      + 'falls back to its STATIC attribute. The load reverts to its static p_set of 80 MW for those 21 '
      + 'hours, and wind reverts to a p_max_pu of 1, which means a 60 MW wind farm at full output all '
      + 'night. The model solves, cheerfully, and the answer is fiction.',

      'This is the single most likely way to break a model while believing you improved it, and it is '
      + 'why this step exists as its own step rather than a footnote.',
    ],
    explain: [
      'Build → Snapshots. In the builder set Start to 2030-01-01 00:00, Resolution to 1 hour and Horizon '
      + 'to "1 day". The summary should read 24 snapshots covering 24 h, and it will tell you it is about '
      + 'to replace 3 existing rows.',

      'Keep the "also set the run resolution" checkbox ticked, exactly as in module 1 — the weight must '
      + 'stay at 1 h per snapshot or every cost in the answer rescales.',

      'Press Replace axis and confirm. Then go and look at what you have done: Build → Loads, open the '
      + 'time-series panel, click p_set. Three rows against a 24-row axis.',

      'Run it if you like, before fixing anything. It will solve. The objective will be a number. That '
      + 'number is meaningless, and nothing on the screen says so — which is the entire lesson of this '
      + 'step, and worth seeing once rather than being told.',
    ],
    spotlights: [
      {
        selector: '[data-tour="snap-horizon"]',
        buildStep: 'snapshots',
        title: 'Horizon — 1 day',
        tab: 'Build',
        note: 'The list runs to 1 year (8,760 h). A day is what this module uses, because it is the '
          + 'shortest horizon containing a full daily cycle and the longest you can still read row by row.',
      },
      {
        selector: '[data-tour="snap-weight"]',
        buildStep: 'snapshots',
        title: 'Keep the weight matched',
        tab: 'Build',
        note: 'Same checkbox as module 1 and the same reason: weight is how many real hours a snapshot '
          + 'stands for, and it multiplies every cost and energy total in the answer.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'snapshots',
        title: '24 rows now',
        tab: 'Build',
        note: 'Midnight to 23:00. Check the first row is the start you asked for — the one-second check '
          + 'from module 1 that catches an off-by-one axis before it misaligns everything downstream.',
      },
      {
        selector: '.build-ts-panel',
        buildStep: 'loads',
        title: 'And 3 rows here',
        tab: 'Build',
        note: 'The panel reports the profile\'s row count. It says 3, against a 24-row axis. Nothing has '
          + 'errored and nothing will — the missing hours quietly fall back to the static p_set.',
      },
    ],
    entries: [
      {
        field: 'Snapshots → builder → Start',
        label: 'first snapshot',
        value: '2030-01-01 00:00',
        why: 'Midnight, so the day runs 00:00 to 23:00 and the overnight lull sits at the start where it '
          + 'is easy to read. The same start as every earlier module, so the first three hours are '
          + 'directly comparable with what you have been solving.',
      },
      {
        field: 'Snapshots → builder → Resolution',
        label: 'spacing between snapshots',
        value: '1 hour',
        why: 'Hourly is the reference this module measures every coarser choice against. It is also the '
          + 'resolution most market and planning data arrives in, which is not a coincidence.',
      },
      {
        field: 'Snapshots → builder → Horizon',
        label: 'total time covered',
        value: '1 day',
        why: '24 snapshots — the shortest window containing a complete daily cycle, so storage can '
          + 'finally do what storage does. A year would be more realistic and 8,760 rows is more than a '
          + 'learner can read; the techniques in steps 6 to 8 are how you get from one to the other.',
      },
    ],
    verify: [
      'The `snapshots` sheet has 24 rows running 00:00 to 23:00',
      'The run resolution is still 1 h per snapshot',
      '`loads-p_set` still has only 3 rows, and the time-series panel says so',
      'You can say what the model will use for the other 21 hours, for both the load and the wind',
    ],
    pitfalls: [
      'Assuming a longer axis is strictly an improvement. Until the profiles are rebuilt it is strictly '
      + 'worse — a 3-hour model was at least consistent.',
      'Not noticing. A model with stale profiles solves normally and reports normally. The row count in '
      + 'the time-series panel is the cheapest check there is, and it is the one to form a habit around.',
    ],
  },

  {
    id: 'm6t-rebuild-demand',
    section: SECTION,
    title: 'Rebuild the demand — a day with a shape',
    tab: 'Build',
    where: 'Build → Loads → time-series panel',
    concept: [
      'Demand over a day has a shape everyone in the industry recognises: a trough in the small hours, a '
      + 'morning ramp as people wake, a broad plateau through the working day, and an evening peak when '
      + 'domestic demand piles onto whatever industry is still running.',

      'The evening peak is the one that matters for planning. It is when demand is highest, and in a '
      + 'system with much solar or wind it is often when renewable output is falling — so the peak of '
      + 'net demand is sharper than the peak of demand, and later.',

      'The day you are about to build runs from 37 MW at 02:00 to 170 MW at 18:00. That 170 is the same '
      + 'peak the three-snapshot model used, so the extreme hour is unchanged and everything around it is '
      + 'new — which keeps the comparison against earlier modules meaningful.',
    ],
    explain: [
      'Build → Loads, open the time-series panel and click `p_set`. The grid shows the three stale rows '
      + 'against a 24-row axis.',

      'Clear it and start again: the grid\'s right-click menu has Clear table, and once the profile is '
      + 'empty the "Write from scratch" control returns. It seeds one row per snapshot — 24 now — with a '
      + 'blank load_1 column.',

      'Then fill the 24 values from the table below. It is tedious, and that is worth feeling once: this '
      + 'is why real studies import profiles rather than type them. Ragnarok\'s Data view has importers '
      + 'for exactly this (ENTSO-E, EIA and others give real hourly demand for a real country), and the '
      + 'Temporal panel takes a CSV. For 8,760 rows there is no other sane route.',

      'A faster route if you would rather not type 24 numbers: enter the values at 00:00, 06:00, 12:00, '
      + '18:00 and 23:00, leave the rest blank, and use Forge → Temporal → Interpolate gaps. You will get '
      + 'a smoother day than the table below and every lesson in this module still works.',
    ],
    spotlights: [
      {
        selector: '.build-ts-panel',
        buildStep: 'loads',
        title: 'The profile panel again',
        tab: 'Build',
        note: 'Click p_set to bring the profile into the grid. The row count beside it is what tells you '
          + 'whether it matches the axis — 3 now, 24 when you are done.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'loads',
        title: '24 rows to fill',
        tab: 'Build',
        note: 'Clear the stale rows first, then "Write from scratch" seeds one per snapshot. The snapshot '
          + 'column stays locked — the time index belongs to the snapshots sheet, as it always has.',
      },
    ],
    entries: [
      {
        field: 'loads-p_set.load_1 (hours 00:00–05:00)',
        label: 'the overnight trough',
        value: '40, 38, 37, 38, 42, 50',
        unit: 'MW',
        why: 'The daily minimum, bottoming at 02:00. Cheap hours with plenty of wind — this is where '
          + 'storage charges and where a system with too much inflexible baseload starts curtailing.',
      },
      {
        field: 'loads-p_set.load_1 (hours 06:00–11:00)',
        label: 'the morning ramp',
        value: '70, 90, 95, 100, 105, 110',
        unit: 'MW',
        why: 'Demand nearly triples in six hours. The RATE of change matters as much as the level: this '
          + 'is what ramp-rate limits and start-up times are for, and a 12-hourly model cannot see it at '
          + 'all.',
      },
      {
        field: 'loads-p_set.load_1 (hours 12:00–17:00)',
        label: 'the working-day plateau',
        value: '108, 105, 100, 100, 110, 130',
        unit: 'MW',
        why: 'Broadly flat, dipping slightly after lunch, then climbing into the evening. Unremarkable '
          + 'hours, which is exactly why a coarse resolution appears to work when it is tested here.',
      },
      {
        field: 'loads-p_set.load_1 (hours 18:00–23:00)',
        label: 'the evening peak and fall',
        value: '170, 165, 140, 110, 80, 55',
        unit: 'MW',
        why: 'The peak at 18:00 is the hour the whole system is sized for, and it is the same 170 MW the '
          + 'three-snapshot model used — so comparisons with earlier modules still mean something. Note '
          + 'it lasts two hours: a 6-hourly model will average it away entirely.',
      },
    ],
    verify: [
      '`loads-p_set` has 24 rows and the panel says so',
      'The values run 40 at midnight, 37 at 02:00, 110 at 11:00 and 170 at 18:00',
      'The static `loads` sheet still reads 80 and is still ignored',
      'You can say which hour the system is sized for, and how long it lasts',
    ],
    pitfalls: [
      'Typing the profile into the static `loads` sheet. There is one p_set cell there; the last value '
      + 'wins and demand goes flat.',
      'Leaving a blank row. A gap falls back to the static 80 MW for that hour, which on this day is '
      + 'wrong in both directions depending where it lands.',
    ],
  },

  {
    id: 'm6t-rebuild-wind',
    section: SECTION,
    title: 'Wind that fades as demand rises',
    tab: 'Build',
    where: 'Build → Generators → p_max_pu profile',
    concept: [
      'Wind and demand are not independent, and in many systems they are actively unhelpful to each '
      + 'other. Wind is often strongest overnight when demand is lowest, and lightest on the still, cold '
      + 'evenings when demand peaks.',

      'The day you are building has that shape: 0.90 at midnight falling to 0.10 by 18:00, the exact hour '
      + 'demand reaches 170 MW. That is not pessimism, it is the standard planning case — and it is why '
      + '"annual renewable share" tells you almost nothing about whether a system works.',

      'What matters is NET demand: demand minus must-take renewable output. On this day gross demand '
      + 'peaks at 170 and net demand peaks higher relative to the rest of the day, because the wind has '
      + 'gone. Every capacity and storage decision is really about net demand, and you cannot compute it '
      + 'without both profiles on the same axis.',

      'Run-of-river, by contrast, barely moves — 0.60 all day, easing to 0.55 in the evening. Module 5 '
      + 'made that point on three hours; here you can see it hold across a full day while wind swings by '
      + 'a factor of nine.',
    ],
    explain: [
      'Build → Generators, time-series panel, `p_max_pu`. Same routine: clear the stale rows, "Write from '
      + 'scratch" to seed 24, then fill the wind_1 and ror_1 columns. The thermal columns stay blank.',

      'Two columns and 24 rows is 48 values. Use the interpolation route if you would rather — the wind '
      + 'shape is smooth enough that five anchors capture it, and run-of-river needs two.',

      'When you have finished, look at the two columns side by side. Wind starts at 0.90 and ends the '
      + 'working day at 0.10; run-of-river sits at 0.60 throughout. Same carrier group in most published '
      + 'statistics, same zero marginal cost, same inability to be dispatched — and one of them is nine '
      + 'times more variable than the other.',
    ],
    spotlights: [
      {
        selector: '.build-ts-panel',
        buildStep: 'generators',
        title: 'p_max_pu, 24 rows this time',
        tab: 'Build',
        note: 'The same profile you built in module 2 with three values and extended in module 5 with a '
          + 'second column. Now it needs 24 rows, and the row count in the panel is how you know.',
      },
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'Two columns, blanks elsewhere',
        tab: 'Build',
        note: 'wind_1 and ror_1 get values; coal_1, oil_1 and gas_supply stay blank so they keep their '
          + 'static default of full availability. A zero in those columns would pin them off and the model '
          + 'would go infeasible in the peak.',
      },
    ],
    entries: [
      {
        field: 'generators-p_max_pu.wind_1 (hours 00:00–05:00)',
        label: 'windy overnight',
        value: '0.90, 0.85, 0.80, 0.75, 0.70, 0.60',
        why: 'Strong wind in the hours demand is lowest — the classic and unhelpful pairing. 54 MW '
          + 'available against 37 MW of demand at 02:00, which is where curtailment or storage charging '
          + 'has to absorb the surplus.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (hours 06:00–11:00)',
        label: 'falling through the morning',
        value: '0.50, 0.45, 0.40, 0.35, 0.30, 0.30',
        why: 'Wind halves exactly as demand doubles. Net demand therefore rises far faster than demand, '
          + 'which is what the thermal fleet and the storage actually have to follow.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (hours 12:00–17:00)',
        label: 'a weak afternoon',
        value: '0.35, 0.40, 0.40, 0.35, 0.25, 0.15',
        why: 'A small afternoon recovery, then a decline into the evening. The recovery is the kind of '
          + 'feature a 6-hourly model averages into nothing, which is why step 5 measures what coarsening '
          + 'costs rather than asserting it.',
      },
      {
        field: 'generators-p_max_pu.wind_1 (hours 18:00–23:00)',
        label: 'still at the peak',
        value: '0.10, 0.10, 0.15, 0.30, 0.50, 0.70',
        why: 'Six MW available in the 170 MW hour. This single row is why the system needs the CCGT, the '
          + 'battery and the peaker at all — and it is the hour every capacity decision in module 7 will '
          + 'turn on.',
      },
      {
        field: 'generators-p_max_pu.ror_1 (all 24 hours)',
        label: 'the river, barely moving',
        value: '0.60 until 18:00, then 0.55',
        why: 'Run-of-river across a whole day, for contrast: while wind swings from 0.90 to 0.10, the '
          + 'river changes by less than a tenth. Its variability is seasonal, and even 24 hours cannot '
          + 'show it.',
      },
    ],
    verify: [
      '`generators-p_max_pu` has 24 rows with wind_1 and ror_1 columns filled',
      'The thermal columns are blank',
      'wind_1 reads 0.90 at midnight and 0.10 at 18:00',
      'You can say what net demand is and why it peaks harder than demand on this day',
    ],
    pitfalls: [
      'Filling the thermal columns with 0. They would be pinned off and the peak hour becomes infeasible '
      + '— the same trap as module 2, now with 24 chances to make it.',
      'Making wind peak with demand. It would be a much happier system and it would not resemble any real '
      + 'one; the anti-correlation is the whole planning problem.',
    ],
  },

  {
    id: 'm6t-run-the-day',
    section: SECTION,
    title: 'Run the day — and watch pumped hydro wake up',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'The objective is 52,663.98. It is not comparable with module 5\'s 7,099.59 — eight times the hours '
      + 'and a different demand profile — and that incomparability is itself the point. Two runs over '
      + 'different windows answer different questions.',

      'The comparison that IS meaningful is what each asset now does. The battery cycles as before. The '
      + 'pumped-hydro scheme, which module 5 measured at 45 and effectively wrote off, discharges 51 MWh '
      + 'across the day and is worth 1,026.',

      'Twenty-three times more valuable, from the same 30 MW and 180 MWh, in the same place, behind the '
      + 'same congested line. What changed is that a day contains a cycle six hours of storage can '
      + 'complete, and three hours did not.',

      'So the course has just corrected itself, and it is worth being blunt about that. Module 5\'s '
      + 'finding was right about its model and wrong about the world, and nothing in module 5 could have '
      + 'told you which. Only running it on a horizon that fits the technology could.',
    ],
    explain: [
      'Validate, then run. Twenty-four snapshots still solve instantly.',

      'Read the objective — 52,663.98 — and then go looking for the storage. The state-of-charge chart '
      + 'now shows a real daily cycle rather than the three-point sketch of module 4: charging overnight '
      + 'while wind is strong and demand is low, discharging into the evening peak.',

      'Check the peak price and the peaker too. Neither the oil unit nor a 120 price appears anywhere in '
      + 'this day — with a full daily cycle available, the storage and the CCGT between them cover the '
      + 'evening. On three hours the peaker was unavoidable; over a day it is not.',

      'Then, if you want the number for yourself: delete phs_1, re-run, and compare. That is the '
      + 'run-relax-rerun technique from module 3, applied to an asset rather than a constraint, and it is '
      + 'how the 1,026 was measured.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: '52,663.98',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Not comparable with 7,099.59 — eight times the hours. Objectives are only comparable across '
          + 'runs with the same window, which is the discipline every module has repeated and the first '
          + 'time it has actually bitten.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'A real cycle at last',
        tab: 'Analytics',
        note: 'Charging through the windy small hours, discharging into the evening peak. Compare with '
          + 'module 4\'s three-point trace: the shape was always there, the axis just could not hold it.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'No 120 anywhere',
        tab: 'Analytics',
        note: 'The oil peaker does not run at any hour of this day. Given a full cycle to work with, the '
          + 'storage and the CCGT cover the evening between them — which module 5, on three hours, '
          + 'concluded was impossible without it.',
      },
      {
        selector: '[data-card="price-formation"]',
        title: 'Prices over a day',
        tab: 'Analytics',
        note: 'Twenty-four prices instead of three, so the price-setting table finally has enough hours to '
          + 'be a distribution rather than a list. This is the first run in the course where the share of '
          + 'hours a technology sets the price means anything.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation checks the two rebuilt profiles line up with the 24-row axis — the failure mode step 2 walked you into.',
        'Twenty-four snapshots with storage coupling them. Still effectively instant.',
      ],
      expect: 'An objective of 52,663.98, a full daily storage cycle, and no oil generation at all.',
    },
    verify: [
      'The objective is 52,663.98',
      'The state-of-charge chart shows a full charge/discharge cycle across the day',
      'oil_1 produces nothing and no price reaches 120',
      'You can say why this objective cannot be compared with module 5\'s',
      'You can say what module 5 got wrong about pumped hydro, and why it could not have known',
    ],
    pitfalls: [
      'Comparing 52,663.98 with 7,099.59. Different windows, different questions. If you want a '
      + 'comparable number, narrow the simulation window to the first three hours — which step 6 does.',
      'Concluding the peaker is unnecessary. It is unnecessary on THIS day; the day that justifies a '
      + 'peaker is a still, cold one in the depths of winter, and a 24-hour model chosen from a mild '
      + 'period will never contain it.',
    ],
  },

  {
    id: 'm6t-resolution',
    section: SECTION,
    title: 'Coarsen it, and measure the damage',
    tab: 'Analytics',
    where: 'Settings → Simulation window → Resolution',
    concept: [
      'Resolution is the first lever anyone reaches for when a model is too slow, because it is the '
      + 'easiest: halve the snapshots, halve the solve time. This step measures what it actually costs, '
      + 'and the numbers are not reassuring.',

      'Against the hourly answer of 52,663.98: 2-hourly gives +0.96%, 4-hourly −3.24%, 6-hourly +24.94%, '
      + '12-hourly −39.30%.',

      'Three things in that column matter more than the individual figures. The error is not monotonic — '
      + '4-hourly is closer than 6-hourly, which is closer than 12-hourly, but 4-hourly is worse than '
      + '2-hourly in a way that does not simply scale. It changes SIGN, so you cannot even assume your '
      + 'coarse model is conservative. And it does not decay gently: 2-hourly is almost free and 6-hourly '
      + 'is catastrophic, with nothing in the output to mark the transition.',

      'The mechanism is averaging. A 6-hour snapshot spanning 15:00–20:00 averages the 130 MW hour with '
      + 'the 170 MW peak and the 140 MW hour after it, so the peak the system is sized for simply stops '
      + 'existing. Sometimes that makes the model look cheaper — no peak to serve — and sometimes more '
      + 'expensive, because the averaged demand no longer lines up with the averaged wind.',
    ],
    explain: [
      'Settings → Simulation window. The Resolution row offers 1h through 24h. Change it to 2h and run; '
      + 'then 4h; then 6h; then 12h. Four runs, one setting.',

      'Record each objective as you go. The point of this step is the pattern across them rather than any '
      + 'one number, and reading the pattern off four rows in History is much more convincing than being '
      + 'told about it.',

      'Then look at what 6-hourly did to the dispatch. The evening peak is gone — averaged into a block '
      + 'with the hours either side — so the model never needs the capacity that peak requires and never '
      + 'prices it.',

      'Set the resolution back to 1h before moving on. The rest of the module and module 7 both assume '
      + 'the hourly axis.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Simulation window',
        note: 'Resolution lives here rather than on the snapshots sheet, because it is a property of the '
          + 'RUN rather than of the model — the same 24-row axis solved at four different resolutions.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'It reports what it used',
        runDialog: 'open',
        note: 'The line you have checked before every run since module 1 now earns its place: it names the '
          + 'resolution the run actually used, which is the only reliable way to know which of your four '
          + 'runs is which.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Four runs, side by side',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'All four are in History. Reading the error pattern off a comparison is the point of the '
          + 'step — the individual objectives matter far less than the fact that the error changes sign.',
      },
    ],
    entries: [
      {
        field: 'Settings → Simulation window → Resolution (2h)',
        label: '12 snapshots',
        value: '2h',
        why: 'Objective 53,172.05, +0.96% against hourly. Half the solve for a percent of error — which is '
          + 'why coarsening is so tempting, and why it is usually the right first move.',
      },
      {
        field: 'Settings → Simulation window → Resolution (4h)',
        label: '6 snapshots',
        value: '4h',
        why: 'Objective 50,958.74, −3.24%. Note the sign: the model now UNDERSTATES cost, because the '
          + 'evening peak is being averaged down. A conservative-looking model that is not conservative.',
      },
      {
        field: 'Settings → Simulation window → Resolution (6h)',
        label: '4 snapshots',
        value: '6h',
        why: 'Objective 65,797.36, +24.94%. A quarter out, from a setting that looks like a minor '
          + 'refinement of the 4h one. There is no warning and no diagnostic — the model simply solves a '
          + 'different problem.',
      },
      {
        field: 'Settings → Simulation window → Resolution (12h)',
        label: '2 snapshots',
        value: '12h',
        why: 'Objective 31,968.00, −39.30%. Two snapshots cannot represent a day at all: the peak, the '
          + 'trough, the ramps and the wind swing all average into two numbers, and the answer is '
          + 'confidently wrong by a factor approaching two.',
      },
      {
        field: 'Settings → Simulation window → Resolution (restore)',
        label: 'back to hourly',
        value: '1h',
        why: 'The reference the rest of the module and module 7 assume. Leaving it coarse would silently '
          + 'change every figure from here on.',
      },
    ],
    verify: [
      'You have four objectives recorded: 53,172.05, 50,958.74, 65,797.36 and 31,968.00',
      'You can say which of them understate cost and which overstate it',
      'You can explain the 6-hourly result in terms of what happens to the 18:00 peak',
      'You can say why "coarser is less accurate" is too kind a description',
      'The resolution is back to 1h',
    ],
    pitfalls: [
      'Assuming error scales with the coarsening factor. It does not, and it changes sign — so a '
      + 'convergence check needs actual runs rather than a rule of thumb.',
      'Choosing a resolution because it solved fast enough. The only defensible way to pick one is to '
      + 'refine until the answer stops moving, which is exactly the exercise you have just done.',
    ],
  },

  {
    id: 'm6t-sampled-blocks',
    section: SECTION,
    title: 'Representative periods — and what they break',
    tab: 'Analytics',
    where: 'Settings → Simulation window → Sampled blocks',
    concept: [
      'A year is 8,760 hours and a capacity-expansion model over 8,760 hours with storage and a network '
      + 'can take hours to solve. The standard answer is representative periods: solve a handful of '
      + 'carefully chosen days and weight them to stand for the whole year.',

      'Ragnarok implements this as Sampled blocks, with three shapes — N equal blocks, block-and-gap, and '
      + 'an averaged profile — and it scales totals up so energy, cost, emissions and constraint budgets '
      + 'represent the full window rather than the sampled part.',

      'It also tells you exactly what it costs, in the note under the control: totals are scaled to '
      + 'represent the full window, but storage and ramping stitch across block boundaries, so it is a '
      + 'fast preview and not a basis for storage sizing or peak adequacy.',

      'Read that against module 4. Storage is the component whose whole value comes from linking one hour '
      + 'to the next; sampling severs those links at every block boundary. So the technique that makes a '
      + 'year tractable is precisely the technique that breaks the asset a year was needed to value — '
      + 'which is not a reason to avoid it, but is a reason to know which questions you may still ask.',
    ],
    explain: [
      'Settings → Simulation window, switch Sampling from "Contiguous window" to "Sampled blocks". You '
      + 'get a choice of shape, a block size and a block count, and a live summary reporting how many '
      + 'steps will be solved and the weight applied.',

      'Try 2 blocks of 4 snapshots on the 24-hour day: 8 of 24 steps solved, weight ×3. Run it and '
      + 'compare against the hourly reference.',

      'Then read the app\'s own caveat under the control, because it is the most honest sentence in the '
      + 'settings and it is doing real work: this is a preview, not a storage or adequacy study.',

      'Set Sampling back to "Contiguous window" before you finish. Like resolution, it is a run setting '
      + 'rather than a model change, so it will silently apply to everything you do next.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Sampled blocks',
        note: 'On the same Simulation window section as resolution, because both answer the same question '
          + '— how much of the axis does the solver actually see — by different means.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'What the run really solved',
        runDialog: 'open',
        note: 'With sampling on, the summary reports the sampled step count and the weight. A sampled run '
          + 'that you later mistake for a full one is the sort of error this line exists to prevent.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Where it breaks',
        tab: 'Analytics',
        note: 'Compare the sampled state of charge against the contiguous one. The cycle is chopped at the '
          + 'block boundaries, which is exactly what the app\'s caveat warns about — storage cannot carry '
          + 'energy across a gap that the model did not solve.',
      },
    ],
    verify: [
      'A sampled run reports fewer steps solved and a weight above 1 in the planning summary',
      'You can say why totals are scaled and dispatch shapes are not',
      'You can say which of module 4\'s conclusions a sampled run could not have produced',
      'Sampling is back to "Contiguous window"',
    ],
    pitfalls: [
      'Sizing storage from a sampled run. The app says not to, and module 4 explains why: the value of '
      + 'storage IS the coupling that sampling severs.',
      'Reporting a sampled result without saying it was sampled. The totals look like full-window totals '
      + 'because they have been scaled to be, and nothing in a chart marks the difference.',
    ],
  },

  {
    id: 'm6t-rolling-horizon',
    section: SECTION,
    title: 'Rolling horizon — solving a year in pieces',
    tab: 'Analytics',
    where: 'Settings → Rolling horizon',
    concept: [
      'The other way to make a long horizon tractable is to keep every snapshot and stop solving them all '
      + 'at once. Rolling horizon cuts the window into overlapping chunks, solves each in order, and '
      + 'carries the end state of one into the start of the next.',

      'Two numbers describe it. The horizon is how many snapshots each solve covers; the overlap is how '
      + 'many of those are shared with the next chunk. The chunk advances by horizon minus overlap, so '
      + 'overlap is pure redundancy that you pay for in solve time and buy foresight with.',

      'What carries across is the state: storage levels above all. What does NOT carry is foresight. A '
      + 'chunk that ends at 14:00 cannot see the 18:00 peak, so it will not save energy for it — which '
      + 'means a rolling solve systematically under-uses storage compared with solving the whole window '
      + 'at once, and the shorter the horizon the worse it gets.',

      'That is a feature as much as a limitation. Real operators do not have perfect foresight either, so '
      + 'a rolling solve with a realistic horizon is often a BETTER model of how a system is actually '
      + 'run — while a full-window solve is the right model of what was theoretically achievable. They '
      + 'answer different questions and both are legitimate.',
    ],
    explain: [
      'Settings → Rolling horizon. The section reports the window it will chunk and lets you set the '
      + 'horizon and overlap, or express it as a number of chunks — it converts between the two so you '
      + 'can think in whichever is natural.',

      'On a 24-hour window try a 12-snapshot horizon with 4 of overlap: chunks advance 8 hours at a time. '
      + 'Run it and compare the objective and the storage trace against the full-window run.',

      'Expect the rolling answer to be slightly worse — a higher cost — and expect the storage to be less '
      + 'well used. That is the foresight you gave up, and seeing it as a number is the point.',

      'Turn rolling horizon off before you finish. Module 7 assumes a full-window solve, and a rolling '
      + 'setting left on would quietly change every capacity it chooses.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Rolling horizon',
        note: 'Its own section rather than part of the simulation window, because it does not change which '
          + 'snapshots are solved — only how many are solved together.',
      },
      {
        selector: '[data-card="chart"][data-card-metric="storage_soc_by_carrier"]',
        title: 'Foresight, or the lack of it',
        tab: 'Analytics',
        note: 'The rolling trace stores less ahead of the evening peak than the full-window one, because '
          + 'the chunk that could have charged for it could not see it coming. That gap is what foresight '
          + 'is worth, drawn.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Rolling against full-window',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both runs are in History. The difference between them is not an error to be minimised — it '
          + 'is the value of perfect foresight, which is a quantity worth knowing in its own right.',
      },
    ],
    verify: [
      'A rolling run completes and reports a higher objective than the full-window solve',
      'The storage trace shows less pre-charging ahead of the evening peak',
      'You can say what carries between chunks and what does not',
      'You can say why a rolling solve is sometimes the MORE realistic model',
      'Rolling horizon is off again',
    ],
    pitfalls: [
      'Reading the rolling result as an error. It is a different question — operation without foresight '
      + 'rather than operation with it — and for an operational study it is the better one.',
      'Setting the overlap to zero. Chunks then share nothing, every boundary is a hard cut, and storage '
      + 'behaves worse than any real operator would.',
    ],
  },

  {
    id: 'm6t-what-changed',
    section: SECTION,
    title: 'What module 6 settled, and how to choose',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Four things are now yours.',

      'The horizon decides which questions a model can answer. Three hours could not value a daily '
      + 'storage cycle, so it valued the pumped-hydro scheme at 45 when a day says 1,026. The model was '
      + 'not imprecise; it was answering a different question, confidently, with nothing in the output to '
      + 'say so.',

      'Replacing an axis does not replace the profiles on it, and a stale profile does not error — it '
      + 'falls back to a static value and solves. The row count in the time-series panel is the check, '
      + 'and it costs a second.',

      'Coarsening is not a precision dial. The error is non-monotonic, changes sign, and jumps from '
      + 'negligible to 25% between two adjacent settings. The only defensible way to choose a resolution '
      + 'is to refine until the answer stops moving.',

      'And the two techniques for a long horizon break different things. Sampling severs the hour-to-hour '
      + 'coupling, so it cannot size storage or test adequacy. Rolling horizon keeps the coupling and '
      + 'removes foresight, so it under-uses storage — and is the better model of real operation for '
      + 'exactly that reason.',
    ],
    explain: [
      'How to actually choose, in the order the choice is usually made.',

      'Start from the question. Sizing storage or testing adequacy needs chronology and extremes, so a '
      + 'contiguous horizon covering the hardest periods. Estimating annual energy or emissions tolerates '
      + 'sampling well. An operational study wants rolling horizon, because foresight is the thing being '
      + 'modelled.',

      'Then refine until it stops moving. Run at two resolutions; if the answer changes materially, you '
      + 'are not converged, and coarsening further is not a saving but a fiction.',

      'Then say what you did. A result from a 6-hourly sampled run is a legitimate result and a '
      + 'misleading one if presented as a full-year hourly answer. Module 9 has more to say about this, '
      + 'but the habit starts here.',

      'Two limits to name before module 7. This is still one day, chosen to be readable rather than '
      + 'representative — a real study needs a year, or a set of days picked to cover the hard cases '
      + 'including the still cold evening this day does not contain. And a day cannot show seasonal '
      + 'storage or the seasonal variability of run-of-river at all.',

      'Export the project. Module 7 finally asks what to build, on an axis that can support the question.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'A day, properly',
        tab: 'Analytics',
        note: '52,663.98 over 24 hours, with a real demand shape, real storage cycles and no peaker. The '
          + 'first model in this course that could support an investment decision — which is what module 7 '
          + 'goes on to make.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. This is the axis module 7 builds on, and the first one in the '
          + 'course worth keeping for reasons other than convenience.',
      },
    ],
    verify: [
      'You can say what module 5 got wrong about pumped hydro and why',
      'You can name the check that catches a stale profile after an axis change',
      'You can describe the resolution error pattern without looking it up',
      'You can say which technique to reach for given a question about storage, about annual energy, and about operation',
      'The model reads 52,663.98 at hourly resolution, contiguous, rolling off — and you have exported it',
    ],
    pitfalls: [
      'Treating this day as representative. It was built to be readable: a mild day with a manageable '
      + 'peak and no still, cold evening. Any real study picks its periods to include the hard cases, and '
      + 'this one deliberately does not.',
      'Assuming a longer horizon is always better. It is always more expensive, and past the point where '
      + 'the answer stops moving it buys nothing — which is the same lesson as line capacity in module 3 '
      + 'and battery duration in module 4.',
    ],
  },
];
