/**
 * Module 12 — Adequacy and uncertainty (10 steps).
 *
 * The last thing the course owes a learner. Every module before this one
 * answered a conditional question — what is cheapest GIVEN this demand, this
 * weather, this fleet all working. Module 9 said a decision has to survive the
 * assumptions being wrong and then assembled its range by hand from runs that
 * already existed. This module does it properly: it asks what happens when
 * plant breaks, which is the one uncertainty every power system actually plans
 * for, and it uses the two checkpoints the course already ships rather than
 * inventing a new model.
 *
 * The arc is the point. `training_m7_year` is the system module 7 STARTED from;
 * `training_m7` is what its least-cost expansion built. Neither run ever
 * mentioned reliability, and the comparison shows what the optimum did to it by
 * accident. Every figure is pinned in
 * ``backend/tests/test_training_checkpoints.py`` at the panel's own defaults —
 * 200 Monte-Carlo samples, seed 42, forced outage rate 5%, MTTR 48 h:
 *
 *   brownfield year   LOLE P50 46.50 h/yr · P95 160.55 · mean 64.06 · EUE P50 1,045.7 MWh/yr
 *   after expansion   LOLE P50  1.00 h/yr · P95  19.10 · mean  4.73 · EUE P50     4.7 MWh/yr
 *   ELCC (expanded)   wind 75.37 of 150.15 MW = 50.2% · hydro 52.3% · solar 4.92 of 24.12 = 20.4%
 *                     battery 2.21 of 20 = 11.0% (energy-limited)
 *   convergence       EUE 1,554.30 MWh/yr, CI [1,457.16, 1,651.44], NOT converged in 1,000
 *                     at the 2% tolerance this module uses
 *
 * The yardstick throughout is LOLE ≈ 2.4 h/yr, the "one day in ten years"
 * standard. The brownfield system misses it by about twenty-seven times on the
 * mean; the expanded one improves thirteen-fold without ever being asked to and
 * still misses it, about twice over on the mean and far more at P95 — a more
 * useful lesson than either "cost-optimal is adequate" or "cost-optimal is not".
 *
 * All three reliability studies (outage Monte Carlo, ELCC, convergence) dispatch
 * storage with one shared kernel that respects its power rating, energy capacity
 * and efficiency, and recharges it only from surplus. Counting storage as firm at
 * its power rating — as these studies once did — credits the 20 MW battery at
 * 98% and understates every LOLE here several-fold.
 */
import { TutorialStep } from '../types';

const SECTION = '12 · Adequacy and uncertainty';

export const MODULE_12_ADEQUACY: TutorialStep[] = [
  {
    id: 'm12-one-year-is-one-sample',
    section: SECTION,
    title: 'One year is one sample',
    tab: 'Analytics',
    where: 'Analytics → Result, with module 7\'s starting year loaded',
    startOptions: {
      prebuiltExampleId: 'training_m7_year',
      completeExampleId: 'training_m7',
      note:
        'Prebuilt is the system module 7 STARTED from; complete is what its expansion built. This '
        + 'module runs the same study on both and compares, so you will want the first one now and the '
        + 'second at step 6.',
    },
    concept: [
      'Every answer in this course has been conditional on things that were entered as certainties. One '
      + 'demand profile. One weather year. And, silently, an assumption nobody ever wrote down: that '
      + 'every generator is available whenever the optimiser wants it.',

      'Real plant breaks. A large thermal unit is typically unavailable on unplanned outage something '
      + 'like 5% of the time, and when it fails it is gone for days rather than minutes. That is not a '
      + 'small correction to a dispatch — it is a different question. The optimiser asks what is '
      + 'cheapest when everything works; adequacy asks how often the system fails to serve its load, '
      + 'and how badly.',

      'The two metrics regulators use are worth learning by name. Loss-of-load expectation (LOLE) is the '
      + 'number of hours per year in which supply cannot meet demand. Expected unserved energy (EUE) is '
      + 'the megawatt-hours that go unserved. LOLE counts occasions; EUE measures depth. A system can '
      + 'score well on one and badly on the other, which is why both are quoted.',

      'And neither can be read off a single optimisation. Whether the system copes depends on which '
      + 'units happen to be broken at the moment demand peaks, and that is a random variable. The answer '
      + 'is a distribution, and getting one means sampling.',
    ],
    explain: [
      'Load module 7\'s starting year from the selector — a full 8,760 hours, the brownfield system '
      + 'before any expansion decision was made.',

      'Run it once, normally, and look at the result you get. It solves, it costs about 30 million, no '
      + 'load is shed and nothing anywhere on the dashboard suggests a reliability problem. That is the '
      + 'baseline this module exists to contradict.',

      'Notice what the run assumed to produce that clean answer: coal, oil, the gas supply and run-of-'
      + 'river all available in all 8,760 hours. No forced outages, because nothing in the workbook '
      + 'describes any. The model was never asked.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'A clean answer',
        tab: 'Analytics',
        note: 'No load shed, no scarcity, nothing to worry about — on the assumption that every unit '
          + 'runs whenever asked. The rest of this module is about that assumption.',
      },
    ],
    verify: [
      'The year loads with 8,760 snapshots and solves',
      'Load shedding reports zero',
      'You can say what LOLE and EUE each measure, and how they differ',
      'You can name the assumption in this run that nobody entered',
    ],
    pitfalls: [
      'Reading "no load shed" as "reliable". It means the deterministic model met demand with every '
      + 'unit working, which is the easiest possible test and not the one a system planner applies.',
    ],
  },

  {
    id: 'm12-for-and-mttr',
    section: SECTION,
    title: 'Forced outages: two numbers describe a broken plant',
    tab: 'Settings',
    where: 'Settings → Solve → Outage Monte Carlo',
    concept: [
      'A thermal unit\'s unplanned unavailability is conventionally described by two parameters. The '
      + 'forced-outage rate (FOR) is the long-run fraction of time it is broken — 5% is a reasonable '
      + 'default for a large thermal unit. Mean time to repair (MTTR) is how long an outage lasts once '
      + 'it starts, typically days rather than hours; 48 hours is the default here.',

      'Both are needed, and the second matters more than people expect. A unit that fails for one hour '
      + 'at a time, 5% of hours, is a nuisance. A unit that fails for two days at a time, adding up to '
      + 'the same 5%, can be absent for the entire cold spell that mattered. Same availability, very '
      + 'different reliability consequence.',

      'Ragnarok models each unit as a two-state Markov chain: up or down, with a per-step probability of '
      + 'failing and of being repaired, chosen so the long-run down-fraction equals the FOR exactly and '
      + 'the average outage lasts the MTTR. The chain starts from the stationary distribution, so the '
      + 'ensemble is already warmed up at hour zero rather than starting with everything working.',

      'Sampling that chain many times gives many possible years. Each is internally consistent — outages '
      + 'persist, they overlap, they land where they land — and across the set you can count how often '
      + 'the system came up short.',
    ],
    explain: [
      'Go to Settings → Solve → Outage Monte Carlo and read the four fields before changing anything: '
      + 'Monte-Carlo samples, random seed, forced outage rate and mean time to repair. Leave them at '
      + 'their defaults — 200, 42, 5% and 48 h — because every figure this module quotes is at those '
      + 'settings. Note the panel takes the outage rate as a PERCENTAGE: 5 here means the 0.05 the '
      + 'method documentation calls a forced-outage rate.',

      'The seed is what makes this reproducible. A Monte Carlo without a recorded seed is not a result '
      + 'anyone else can check, and the same seed with the same member count gives the same answer every '
      + 'time. Module 9\'s provenance argument applies here more than anywhere.',

      'Two things to understand about the study before you run it. It is a post-process, not a re-solve: '
      + 'it takes the solved network, samples availability, and asks whether available capacity covers '
      + 'load in each hour of each member. It does not re-dispatch. And it samples outages for thermal '
      + 'units only — wind and solar unavailability is intermittency, which the profile already '
      + 'describes, not a mechanical failure.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="outageMc"]',
        title: 'Outage Monte Carlo',
        tab: 'Settings',
        note: 'Under Solve. Unlike power flow and N-1 in module 10, this one does NOT replace the '
          + 'optimisation — it runs alongside it and adds a card.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → Outage Monte Carlo → Monte-Carlo samples',
        label: 'how many synthetic years to sample',
        value: '200',
        why: 'Each member is one complete possible year of outages. More members means a tighter '
          + 'estimate and a longer post-process; step 8 measures how many is actually enough, and the '
          + 'answer is uncomfortable.',
      },
      {
        field: 'Settings → Solve → Outage Monte Carlo → Random seed',
        label: 'random seed',
        value: '42',
        why: 'Makes the draw reproducible. Quote it with any result — a Monte Carlo number without its '
          + 'seed and member count cannot be reproduced, and an unreproducible number is not evidence.',
      },
      {
        field: 'Settings → Solve → Outage Monte Carlo → Forced outage rate (%)',
        label: 'long-run probability of being broken',
        value: '5',
        unit: 'per cent',
        why: 'Five per cent of the time, per thermal unit. Plausible for a large thermal plant; a '
          + 'well-maintained CCGT does better and an ageing unit far worse, and this is the single '
          + 'number the whole result is most sensitive to.',
      },
      {
        field: 'Settings → Solve → Outage Monte Carlo → Mean time to repair (h)',
        label: 'mean time to repair',
        value: '48',
        unit: 'hours',
        why: 'Sets how outages CLUSTER rather than how many there are. Doubling it while halving the '
          + 'FOR keeps availability the same and makes the system materially less reliable, because '
          + 'long outages are the ones that overlap a peak.',
      },
    ],
    verify: [
      'The four fields read 200, 42, 5 and 48',
      'You can explain why FOR alone does not describe an outage regime',
      'You can say why wind and solar are not given a forced-outage rate here',
      'You can say what "post-process, not a re-solve" rules out',
    ],
    pitfalls: [
      'Treating the FOR as a property of the study rather than of the plant. It is an input about the '
      + 'fleet, and a default is a placeholder for data you do not have.',
    ],
  },

  {
    id: 'm12-run-the-monte-carlo',
    section: SECTION,
    title: 'Run it: the clean answer had a reliability problem',
    tab: 'Analytics',
    where: 'Analytics → Result → outage Monte Carlo card',
    concept: [
      'The same year, the same dispatch, the same 30 million. The only thing added is the possibility '
      + 'that plant breaks — and the system that shed nothing at all now expects to fall short.',

      'The headline figures on the brownfield year are a P50 LOLE of 46.5 hours a year and a P95 of '
      + '160.55, with expected unserved energy of 1,045.7 MWh at P50 and 5,608.3 at P95. Read that as: in a '
      + 'typical year this system fails to serve its load for about two days in total, and in a bad year '
      + 'for the better part of a week.',

      'Nothing about the optimisation was wrong. It answered the question it was asked, which did not '
      + 'include this one.',
    ],
    explain: [
      'Turn Outage Monte Carlo on and run. The optimisation still happens exactly as before — the '
      + 'objective, prices and dispatch are unchanged — and the sampling runs afterwards on the solved '
      + 'network, so the extra time is seconds rather than another solve.',

      'Open the result and find the outage Monte Carlo card. Read the four summary figures: LOLE P50 '
      + '46.5 h/yr, LOLE P95 160.55 h/yr, EUE P50 1,045.7 MWh/yr, EUE P95 5,608.3 MWh/yr, over four thermal '
      + 'units sampled.',

      'Then compare against the run you did in step 1. Same cost. Same prices. Same everything the '
      + 'objective could see. The difference is entirely in a question the objective was never given.',

      'This is the most important habit in the module: a result that looks clean is not evidence of '
      + 'reliability, because a deterministic optimisation cannot produce that evidence at all.',
    ],
    spotlights: [
      {
        selector: '[data-card="outage-mc"]',
        title: 'The outage Monte Carlo card',
        tab: 'Analytics',
        note: 'LOLE and EUE, each at P50 and P95, plus how many thermal units were sampled. The card '
          + 'only appears when the study is on.',
      },
    ],
    run: {
      label: 'Run → Run model (outage Monte Carlo on)',
      detail: [
        'The optimisation is unchanged — about a minute for the year. The sampling is a post-process '
        + 'over 200 members and adds seconds, not minutes.',
      ],
      expect: 'The same objective as step 1, plus a card reporting LOLE P50 46.5 h/yr and P95 160.55.',
    },
    verify: [
      'The objective is identical to the step-1 run',
      'The card reports LOLE P50 46.5 h/yr and LOLE P95 160.55 h/yr',
      'EUE reads 1,045.7 MWh/yr at P50 and 5,608.3 at P95',
      'Four thermal units were sampled',
    ],
    pitfalls: [
      'Expecting the objective to change. It cannot — the study runs after the solve and never feeds '
      + 'back into it. Making the optimiser account for outages is a different technique entirely '
      + '(stochastic or security-constrained optimisation).',
    ],
  },

  {
    id: 'm12-a-distribution-not-a-number',
    section: SECTION,
    title: 'The answer is a distribution, and the mean is the least useful part',
    tab: 'Analytics',
    where: 'Analytics → Result → outage Monte Carlo card',
    concept: [
      'Look at the whole set rather than the headline: across the 200 members the LOLE runs from a P50 '
      + 'of 46.5 hours to a P90 of 135.0, a P95 of 160.55 and a worst member of 289.0, with a mean of '
      + '64.06. Those describe the same system.',

      'The spread is not noise to be averaged away. It is the answer. Half of all years are better than '
      + 'forty-six and a half hours and one in twenty is worse than one hundred and sixty, and a system planner cares far more '
      + 'about the second number than the first — the whole point of a reliability standard is to bound '
      + 'the bad case, not the typical one.',

      'Note also that the mean, 64.06, sits above the P50 of 46.5. That is the signature of a skewed '
      + 'distribution with a long right tail: most years are fine and a few are dreadful, and the mean '
      + 'is dragged up by the disasters. Quoting the mean of a skewed reliability metric describes no '
      + 'year that will ever happen.',

      'This is module 9\'s argument, arrived at from the other direction. There it was a range assembled '
      + 'by hand from sensitivity runs; here the model produces the distribution itself, and the '
      + 'temptation to collapse it back into one number is exactly as strong.',
    ],
    explain: [
      'Read all five statistics off the card and write them down: P50 46.5, P90 135.0, P95 160.55, mean '
      + '64.06, max 289.0 hours per year.',

      'Then do the same for EUE — P50 1,045.7, P95 5,608.3 MWh/yr — and notice that the EUE spread is much '
      + 'wider proportionally than the LOLE spread. Bad years are not just more frequent in their '
      + 'shortfalls; the shortfalls are deeper. That is what happens when two large units are out '
      + 'together instead of one.',

      'And decide which number you would put in a report. There is a defensible answer — the P95, with '
      + 'the P50 beside it and the member count and seed in a footnote — and an indefensible one, which '
      + 'is any single figure with no indication that the others exist.',
    ],
    verify: [
      'You have all five LOLE statistics written down',
      'You can say why the mean exceeds the median here, and what that implies',
      'You can say which statistic belongs in a report and why',
      'You can say why the EUE spread is proportionally wider than the LOLE spread',
    ],
    pitfalls: [
      'Averaging a skewed metric and reporting the result as "the" LOLE. It is a summary of a shape, '
      + 'and this shape is not symmetric.',
    ],
  },

  {
    id: 'm12-the-yardstick',
    section: SECTION,
    title: 'One day in ten years',
    tab: 'Analytics',
    where: 'Analytics → Result, and a piece of arithmetic',
    concept: [
      'A reliability number means nothing without a standard to read it against. The one most systems '
      + 'use is "one day in ten years" — a loss-of-load expectation of about 2.4 hours per year. It is '
      + 'a convention rather than a physical constant, and different jurisdictions set it differently, '
      + 'but it is the yardstick almost every capacity market and adequacy assessment is built on.',

      'Against it, this system is not close. A P50 of 46.5 hours a year is nearly twenty times the '
      + 'standard; the mean of 64.06 is nearly twenty-seven times it; the P95 of 160.55 is sixty-seven times. '
      + 'Whatever else module 7\'s starting system was, it was not adequate.',

      'The deeper point is what produced that gap. Nobody chose it. The fleet in this workbook is what '
      + 'the earlier modules happened to build — a coal unit here, an oil peaker there, a gas link — '
      + 'each added to illustrate a mechanism, none sized against a reliability target. That is exactly '
      + 'how real models drift, and the only defence is measuring rather than assuming.',
    ],
    explain: [
      'Do the comparison explicitly. Divide each of your five LOLE statistics by 2.4 and write the '
      + 'ratios down: 19 at P50, 56 at P90, 67 at P95, 27 on the mean, 120 at worst.',

      'Then ask what would fix it, and notice you cannot answer from this study. It tells you the '
      + 'system falls short; it does not tell you what to build. That is a capacity-expansion question '
      + '— module 7\'s question — and the two studies do not talk to each other unless you make them.',

      'The next step is the interesting version of that: module 7 already ran an expansion on this '
      + 'system, for reasons that had nothing to do with reliability. Find out what it did to the '
      + 'adequacy of the answer.',
    ],
    verify: [
      'You can state the "one day in ten years" standard in hours per year',
      'You have the five ratios against 2.4 written down',
      'You can say why this system\'s inadequacy was nobody\'s decision',
      'You can say why an adequacy study cannot tell you what to build',
    ],
    pitfalls: [
      'Treating 2.4 h/yr as a law of nature. It is a policy choice about how much unserved energy is '
      + 'worth avoiding, and it varies by jurisdiction — the discipline is comparing against a stated '
      + 'standard, not against that particular one.',
    ],
  },

  {
    id: 'm12-did-the-expansion-fix-it',
    section: SECTION,
    title: 'Did module 7\'s expansion fix it? Not on purpose',
    tab: 'Analytics',
    where: 'Load the complete model, then run the same study',
    concept: [
      'Module 7 offered wind, solar, the transmission line and the battery to the optimiser at their '
      + 'capital costs and asked what was worth building. It built 150 MW of wind, 24 of solar and '
      + 'uprated the line, and saved about twelve million a year. Reliability was not in the objective, '
      + 'not in a constraint, and not mentioned anywhere in the run.',

      'Run the same Monte Carlo on the result and the LOLE reads P50 1.00 hours a year, P95 19.1, mean '
      + '4.73 — against 46.5, 160.55 and 64.06 before. Expected unserved energy falls from 1,045.7 MWh at '
      + 'P50 to 4.7. The system went from twenty-seven times the standard to about twice it on the mean.',

      'Two conclusions, and the second matters more. The first is that capacity built for economic '
      + 'reasons often improves adequacy, because both respond to the same thing — not enough firm '
      + 'capacity at the peak. The second is that it was not designed to, and nothing guaranteed it '
      + 'would. Change the capital costs and the same optimiser would happily build a portfolio that '
      + 'saves as much money and fixes nothing.',

      'And it is not clean even here. The mean of 4.73 is still about twice 2.4, and the P95 of 19.1 is '
      + 'eight times it — one year in twenty is far outside the standard. A study that reported only the '
      + 'improvement would have called this done.',
    ],
    explain: [
      'Load the complete model from this module\'s start selector — module 7\'s expanded system — and '
      + 'run it with the Monte Carlo still on and the same four settings.',

      'Read the card: LOLE P50 1.00, P90 16.0, P95 19.1, mean 4.73, max 63.0 h/yr. EUE P50 4.7, P95 366.5 '
      + 'MWh/yr.',

      'Put the two sets side by side and work out the ratios: LOLE mean down thirteen-fold, EUE at '
      + 'P95 down fifteen-fold. That is a very large reliability improvement from an investment '
      + 'decision that never mentioned reliability.',

      'Then state the caveat as carefully as the finding. The improvement is real and it is a '
      + 'by-product. If you want a system that meets a standard, you constrain the expansion to meet it '
      + '— a reliability constraint, or a capacity requirement — rather than running an adequacy check '
      + 'afterwards and hoping.',
    ],
    run: {
      label: 'Run → Run model (on the expanded system)',
      detail: [
        'The expansion year is a bigger solve — allow a minute or two — and the sampling is seconds.',
      ],
      expect: 'LOLE P50 1.00 h/yr and P95 19.1, against 46.5 and 160.55 on the system it was built from.',
    },
    verify: [
      'The expanded system reports LOLE P50 1.00 h/yr and P95 19.1 h/yr',
      'EUE reads 4.7 MWh/yr at P50 and 366.5 at P95',
      'You can say by how much the mean LOLE improved, and that nothing asked it to',
      'You can say by how much the mean and the P95 still breach the 2.4 h/yr standard',
    ],
    pitfalls: [
      'Concluding that least-cost expansion delivers adequacy. It improved adequacy thirteen-fold here, on '
      + 'these costs, and still missed the standard. The general claim is false, and the way to be sure '
      + 'is to constrain it rather than to check afterwards.',
    ],
  },

  {
    id: 'm12-capacity-credit',
    section: SECTION,
    title: 'Capacity credit: what a megawatt of wind is worth as firm capacity',
    tab: 'Settings',
    where: 'Settings → Solve → ELCC / capacity credit',
    concept: [
      'Nameplate capacity is the wrong unit for comparing generators on reliability. A 150 MW wind farm '
      + 'and a 150 MW gas unit do not contribute the same amount of firmness, because the wind farm may '
      + 'be becalmed exactly when the system is short.',

      'The measure that fixes this is effective load-carrying capability — ELCC. It asks: how many '
      + 'megawatts of perfectly firm capacity would give the same reliability as this generator? '
      + 'Operationally the tool removes the asset, finds the block of firm capacity that restores the '
      + 'original LOLE, and reports that block.',

      'On the expanded system, 150.15 MW of wind has an ELCC of 75.37 MW — a capacity credit of 50%. '
      + 'Solar does much worse: 24.12 MW nameplate for 4.92 MW of firm equivalent, 20%, because this '
      + 'system\'s tight hours are winter evenings when solar output is nearly zero. The hydro carries 52% '
      + 'and the battery only 11%, because it runs out of energy.',

      'Those percentages are how capacity markets accredit resources, and they explain a great deal '
      + 'about how systems get paid. Two assets with the same nameplate can differ several-fold in what '
      + 'they contribute to keeping the lights on.',
    ],
    explain: [
      'Turn the Monte Carlo off and turn on Settings → Solve → ELCC / capacity credit, with the same '
      + 'member count, seed, FOR and MTTR. Leave the carrier list empty to get every carrier.',

      'Run it on the expanded system and read the card: wind 75.37 MW of 150.15 (50.2%), hydro 23.52 of '
      + '45 (52.3%), the battery 2.21 of 20 (11.0%), solar 4.92 of 24.12 (20.4%).',

      'Check the baseline LOLE the card reports — 4.73 h/yr, exactly the mean the Monte Carlo gave you '
      + 'in the previous step. That agreement is not automatic and it is worth confirming: the two '
      + 'studies have to be measuring the same system for their numbers to be comparable.',

      'Then reason about solar\'s 20%. It is not a statement about solar. It is a statement about when '
      + 'THIS system is short — and a system whose tight hours were summer afternoons would credit '
      + 'solar far higher and wind lower. Capacity credit is a property of the pairing, not of the '
      + 'technology.',

      'One number in that list deserves a second look, and step 9 is about it: the battery at 11%.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="elcc"]',
        title: 'ELCC / capacity credit',
        tab: 'Settings',
        note: 'Two below the Monte Carlo, under Solve. Same sampler underneath — the FOR, MTTR, member '
          + 'count and seed all mean the same thing here.',
      },
      {
        selector: '[data-card="elcc"]',
        title: 'The capacity-credit card',
        tab: 'Analytics',
        note: 'Nameplate, ELCC in MW and as a percentage, per carrier — plus the baseline LOLE it '
          + 'measured everything against. Check that baseline against the Monte Carlo\'s mean.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → ELCC → Carriers',
        label: 'which carriers to evaluate',
        value: '(leave empty)',
        why: 'Empty means every carrier present. Naming one is faster on a large model, since each '
          + 'carrier costs a bisection search over repeated LOLE evaluations.',
      },
    ],
    run: {
      label: 'Run → Run model (ELCC on, Monte Carlo off)',
      detail: ['The bisection runs several LOLE evaluations per carrier — still seconds on this model.'],
      expect: 'Wind at about 50% of nameplate, solar about 20%, the battery about 11%, and a baseline LOLE of 4.73 h/yr.',
    },
    verify: [
      'Wind reports an ELCC near 75 MW of 150.15 nameplate — about 50%',
      'Solar reports about 4.9 MW of 24.12 — about 20%',
      'The card\'s baseline LOLE matches the Monte Carlo\'s mean of 4.73 h/yr',
      'You can explain why solar scores low here without saying anything against solar',
    ],
    pitfalls: [
      'Quoting a capacity credit as a technology constant. It is specific to this system, this load '
      + 'shape and this weather year, and a different tight hour would reorder the whole table.',
    ],
  },

  {
    id: 'm12-how-many-members',
    section: SECTION,
    title: 'How many samples is enough?',
    tab: 'Settings',
    where: 'Settings → Solve → Convergence sampling',
    concept: [
      'Two hundred members produced a confident-looking table. Whether 200 was enough is a separate '
      + 'question, and it has a real answer: keep drawing until the estimate stops moving, and measure '
      + '"stops moving" by the standard error of the mean rather than by eye.',

      'The convergence study does exactly that. It draws in batches, recomputes the running estimate '
      + 'and its standard error after each, and stops when the relative standard error falls below a '
      + 'tolerance — or when it runs out of budget.',

      'On the brownfield year, targeting EUE at a 2% tolerance in batches of 50, it does not converge. '
      + 'It draws the full 1,000 members and reports an estimate of 1,554.30 MWh/yr with a 95% confidence '
      + 'interval of 1,457.16 to 1,651.44 — an interval of about ±6%, three times the tolerance asked for.',

      'That is the honest state of a heavy-tailed estimate, and it is why reliability studies quote member '
      + 'counts in the thousands. Unserved energy is dominated by a few deep shortfalls — the worst '
      + 'member in step 3 was 13,087 MWh against a median of 1,046 — so the variance comes from a handful '
      + 'of bad draws however many members you add.',
    ],
    explain: [
      'Turn ELCC off and turn on Settings → Solve → Convergence sampling on the brownfield year. Target '
      + 'metric EUE, tolerance 2%, batch size 50, max members lowered from its default of 2,000 to '
      + '1,000, and the same seed and outage '
      + 'parameters.',

      'Run it, then read the trace rather than the headline: 50 members gives 1,461.39 with a standard '
      + 'error of 207.08; 100 gives 1,441.58 ± 142.22; 150 gives 1,408.91 ± 117.24; by 450 it is '
      + '1,437.61 ± 65.45. The estimate stays within about 8% of its final value from very early on. The standard error '
      + 'is what refuses to come down, and it falls like the square root of the member count — four '
      + 'times the members for half the error.',

      'Read the verdict too: "stopped at maxMembers=1000 before converging". A study that says it did '
      + 'not converge is far more useful than one that quietly reports a number, and it is telling you '
      + 'to raise the budget or accept a wider interval.',

      'Then reconcile this against step 3. The Monte Carlo\'s 200-member EUE mean was 1,929.3 MWh/yr and '
      + 'this says 1,554.30 with an interval that does not contain it. Both are the same system with the '
      + 'same parameters, drawn differently. That gap IS the sampling error, made visible — and it is '
      + 'the reason the previous steps quoted P50 and P95 rather than the mean.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="convergence"]',
        title: 'Convergence sampling',
        tab: 'Settings',
        note: 'Under Solve. It answers the question the fixed-member Monte Carlo cannot: was 200 '
          + 'enough?',
      },
      {
        selector: '[data-card="convergence"]',
        title: 'The trace',
        tab: 'Analytics',
        note: 'Estimate and standard error after each batch. The estimate settles quickly; the error '
          + 'does not, and the difference between those two facts is the whole lesson.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → Convergence sampling → Target metric',
        value: 'EUE',
        why: 'The metric whose precision is being controlled. EUE is the harder of the two — it is a '
          + 'magnitude rather than a count, so a single deep shortfall moves it a long way.',
      },
      {
        field: 'Settings → Solve → Convergence sampling → Tolerance (%)',
        value: '2',
        why: 'Stop when the standard error is under 2% of the estimate. Achievable on a mild system and '
          + 'not on this one, which is the finding rather than a misconfiguration.',
      },
      {
        field: 'Settings → Solve → Convergence sampling → Max members',
        value: '1000',
        why: 'The budget, lowered from the default 2,000 so the study finishes quickly and the '
          + 'non-convergence is visible. Reaching it without converging is a legitimate outcome and is '
          + 'reported as one; four times the members would halve the interval.',
      },
    ],
    run: {
      label: 'Run → Run model (convergence sampling on)',
      detail: ['Up to 1,000 members drawn in batches of 50. Tens of seconds on this model.'],
      expect: 'An EUE estimate near 1,554 MWh/yr with a 95% CI of about [1,457, 1,651], reported as NOT '
        + 'converged at the 2% tolerance.',
    },
    verify: [
      'The study reports it stopped at 1,000 members without converging',
      'The estimate is about 1,554 MWh/yr with a CI of roughly 1,457 to 1,651',
      'The trace shows the estimate settling long before the standard error does',
      'You can say how many more members would halve the confidence interval',
    ],
    pitfalls: [
      'Reading a stable-looking estimate as a converged one. The trace is stable from 50 members and '
      + 'the interval is still ±6% at 1,000 — those are different claims about the same numbers.',
    ],
  },

  {
    id: 'm12-what-it-cannot-see',
    section: SECTION,
    title: 'What this study cannot see',
    tab: 'Analytics',
    where: 'Analytics → Result, reading critically',
    concept: [
      'Start with the battery in the ELCC table: 2.21 MW of firm equivalent from 20 MW of nameplate, '
      + '11%. A 20 MW battery with an hour of storage cannot cover a four-hour evening shortfall, and '
      + 'no capacity market would accredit it as though it could. The study does not either: it '
      + 'dispatches storage within its power rating, its energy capacity and its round-trip '
      + 'efficiency, and recharges it only from surplus, so a battery empties during a long shortfall '
      + 'and is credited for what it actually delivers. The pumped hydro, which is also energy-limited, '
      + 'sits at 52% for the same reason.',

      'That treatment is still a simplification, and worth reading rather than inferring. The storage '
      + 'rule has no foresight — it will not pre-charge from thermal plant ahead of a shortfall — and '
      + 'it is a post-process on the solved fleet, not a re-optimisation. Storage is credited '
      + 'conservatively; most of what follows flatters the system instead.',

      'The other limits follow from the same fact. The study never re-dispatches, so it cannot tell you '
      + 'whether the remaining plant could actually have been brought to the right output in time — '
      + 'module 11\'s ramp rates and minimum down times are invisible here. It compares total available '
      + 'capacity against total load with no network, so module 10\'s congestion cannot cause a '
      + 'shortfall in this arithmetic even though it plainly can in reality. And it samples outages '
      + 'against ONE weather year and ONE demand profile: the correlation between a cold still evening '
      + 'and a high load, which is what actually causes adequacy events, is present only to the extent '
      + 'that this particular year happens to contain it.',

      'None of that makes the study useless. Ramping and the network can only make real shortfalls '
      + 'worse than this arithmetic says, which is exactly how a planner would use it — if a system '
      + 'fails the test as stated, it fails.',
    ],
    explain: [
      'Go back to the ELCC table and identify which entries depend on how long the resource can keep '
      + 'going. The battery at 11% and the pumped hydro at 52% are energy-limited, so their credit '
      + 'falls as the shortfalls get longer. The wind and solar figures are profile-limited instead: '
      + 'they depend on when the output arrives, not on how much energy is stored.',

      'Then write down, in one line each, the four things this module\'s numbers do not account for: '
      + 'storage strategy (foresight and pre-charging), unit commitment and ramping, the network, and '
      + 'the correlation between weather and demand across years.',

      'That list is the deliverable. Module 9 argued that an honest result carries a statement of what '
      + 'the model could not see; this is that statement for the adequacy numbers you have just '
      + 'produced, and every item on it is a known property of the method rather than a doubt.',
    ],
    verify: [
      'You can say why the battery\'s capacity credit is 11% rather than near 100%',
      'You have the four limitations written down in your own words',
      'You can say why an optimistic adequacy test is still worth running',
      'You can name which module each of the first three limitations comes from',
    ],
    pitfalls: [
      'Discarding the study because it is approximate. Every model in this course is approximate; the '
      + 'distinction that matters is whether you know which direction the approximation errs in, and '
      + 'here you do.',
    ],
  },

  {
    id: 'm12-what-changes',
    section: SECTION,
    title: 'What uncertainty changes about the eleven modules before it',
    tab: 'Analytics',
    where: 'Everything you have built',
    concept: [
      'Every objective value in this course was a point estimate of a random variable, and until this '
      + 'module none of them said so. 12,000 in module 1 was exact because the model was a toy. '
      + '18,079,255 in module 7 was exact to the solver and had no more claim to being the cost of that '
      + 'system than 46.5 hours has to being its LOLE.',

      'What changes is not that the earlier answers were wrong. It is what a complete answer looks like. '
      + 'A cost, a reliability metric with its distribution, the standard being compared against, the '
      + 'sampling parameters that produced it, and the list of what the method could not see.',

      'And the ordering matters. Adequacy is a constraint, not a result. Checking it afterwards — which '
      + 'is what this module did, twice — tells you whether you got away with it. Building it in means '
      + 'putting a reliability requirement into the expansion problem, so the optimiser is choosing '
      + 'among portfolios that all meet the standard rather than among portfolios that all minimise cost.',
    ],
    explain: [
      'Take stock of the whole course, because this is the end of it.',

      'You can build a network from an empty sheet and check its answer by hand. You can read a merit '
      + 'order, a congestion price and a storage arbitrage. You can give a fuel its own bus, choose a '
      + 'time resolution you can defend, turn a dispatch model into an investment model, and apply a '
      + 'carbon price or a cap knowing they are the same instrument. You know why power divides between '
      + 'parallel paths, why a plant that cannot switch off spills free wind, and now what any of it is '
      + 'worth when plant breaks.',

      'The thread through all of it has been the same discipline, and it is the only thing here that '
      + 'will still be true in ten years: work out what the answer should be before you look, then find '
      + 'out which of you is wrong. Every module has done it, and in several of them the model was the '
      + 'one that turned out to be right for the wrong reason.',

      'Go back to your own model with the four questions this course keeps asking. What is the objective '
      + 'actually minimising? What is the axis, and what does it hide? Which constraints are binding, '
      + 'and what would it cost to relax them? And what is the range around the answer, with the '
      + 'conditions attached?',

      'If you can answer those four about a model you built, you can defend it. That was the point.',
    ],
    verify: [
      'You can say what a complete answer contains, beyond a number',
      'You can explain the difference between checking adequacy and constraining it',
      'You can state the four questions to ask of any model',
      'You can name, for your own model, the assumption you are least comfortable with',
    ],
    pitfalls: [
      'Finishing the course and reporting point estimates anyway. The habit is the deliverable, and it '
      + 'is easier to lose than to acquire.',
    ],
  },
];
