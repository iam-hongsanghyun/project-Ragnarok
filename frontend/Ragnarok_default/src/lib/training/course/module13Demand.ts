/**
 * Module 13 — Where the demand comes from (10 steps).
 *
 * Twelve modules have taken the demand profile as given. It arrived in a
 * checkpoint, nobody questioned it, and it is the single most consequential
 * input in the model — every capacity decision, every price and every
 * reliability metric in this course is downstream of it.
 *
 * The module uses the two checkpoints module 7 already ships and Ragnarok's own
 * demand transforms, which are local and deterministic, so every figure is
 * reproducible. Verified and pinned in
 * ``backend/tests/test_training_checkpoints.py``:
 *
 *   as shipped (2030)          peak 174.7 MW · 1,030.5 GWh
 *   CAGR 2%/yr to 2040         factor 1.219 · peak 212.9 MW · 1,256.2 GWh
 *   electrification, same GWh  peak 220.4 MW · 1,256.5 GWh  ← 3.5% more peak
 *
 *   brownfield fleet at 2040 demand      INFEASIBLE
 *   extendable fleet, CAGR 2040          31,848,292 · wind 202.8 MW · solar 50.0 MW
 *   extendable fleet, electrified 2040   31,679,393 · wind 208.3 MW · solar 20.2 MW
 *
 * The finding is the last pair. Identical annual energy, a 7.5 MW higher peak,
 * and the optimiser builds 5.5 MW more wind and 30 MW LESS solar — because
 * electrified heat and EV charging land in winter evenings, when solar is
 * useless and wind is good. The shape of demand growth changes which technology
 * you build more than it changes what it costs.
 */
import { TutorialStep } from '../types';

const SECTION = '13 · Where the demand comes from';

export const MODULE_13_DEMAND: TutorialStep[] = [
  {
    id: 'm13-the-input-nobody-questioned',
    section: SECTION,
    title: 'The input nobody questioned',
    tab: 'Model',
    where: 'Model → loads-p_set',
    startOptions: {
      prebuiltExampleId: 'training_m7_year',
      completeExampleId: 'training_m7',
      note:
        'Prebuilt is the brownfield year, which this module projects forward and then discovers it '
        + 'cannot serve. Complete is module 7\'s extendable fleet, which you will need from step 6 to '
        + 'let the optimiser respond.',
    },
    concept: [
      'Go back through this course and count what rested on the demand profile. The merit order in '
      + 'module 2 was cut where demand fell. Module 3\'s congestion happened because demand sat at the '
      + 'far end of a line. Module 4\'s battery arbitraged a peak that the profile defined. Module 7 '
      + 'built capacity for it, module 8 priced its emissions, module 12 measured whether it could be '
      + 'served. Every one of those answers is a function of a column that arrived in a spreadsheet.',

      'And in almost every real study that column is a projection — somebody\'s view of what demand will '
      + 'be in a future year. It is not measured, it is not certain, and the way it was produced changes '
      + 'the answer more than most of the modelling decisions you have spent twelve modules learning to '
      + 'make carefully.',

      'There are two families of method and the difference between them is the subject of this module. '
      + 'You can take today\'s profile and SCALE it — every hour grows by the same factor, so the shape '
      + 'is preserved exactly. Or you can build a new shape from what is driving the growth: more '
      + 'people, more economic activity, electrified heating, electric vehicles. The first is easy and '
      + 'the second is right, and the gap between them is a capacity decision.',
    ],
    explain: [
      'Load the brownfield year and open Model → loads-p_set. This is the column everything has rested '
      + 'on: 8,760 hourly values for one load, in 2030.',

      'Measure it before you change anything, because every comparison in this module is against these '
      + 'two numbers. The peak is 174.7 MW and the annual energy is 1,030.5 GWh. The Analytics load '
      + 'duration curve from module 3 is the fastest way to see both at once.',

      'Note also what the profile does NOT carry: any statement about where it came from, what year it '
      + 'represents beyond its timestamps, or how confident anyone is in it. A demand column is the '
      + 'least self-documenting object in a power-system model, and module 9\'s provenance argument '
      + 'applies to it more than to anything else.',
    ],
    spotlights: [
      {
        selector: '[data-card="duration-curve"][data-card-source="load"]',
        title: 'The load duration curve',
        tab: 'Analytics',
        note: 'Peak on the left, base load on the right. Read 174.7 MW off the top — this module is '
          + 'about what happens to that number.',
      },
    ],
    verify: [
      'The demand sheet has 8,760 rows, dated 2030',
      'You can read the peak as 174.7 MW and the annual energy as 1,030.5 GWh',
      'You can name four earlier modules whose answers depend on this column',
      'You can say what the profile does not tell you about itself',
    ],
    pitfalls: [
      'Treating a projected demand column as data. It is a model output from somebody else\'s model, '
      + 'and it deserves the same scrutiny as anything you produce.',
    ],
  },

  {
    id: 'm13-growth-is-not-a-forecast',
    section: SECTION,
    title: 'Scaling a profile is not forecasting it',
    tab: 'Forge',
    where: 'Forge → Temporal → Forecast to future year',
    concept: [
      'The simplest projection applies one growth rate to every hour. At a compound rate g over n '
      + 'years, every value is multiplied by (1+g)^n — 2% a year for ten years is a factor of 1.219. '
      + 'Ragnarok calls this CAGR; the linear option does the same thing with simple rather than '
      + 'compound growth.',

      'What that method assumes is worth stating out loud, because it is invisible in the result: it '
      + 'assumes the shape of demand in 2040 is identical to 2030. Same daily pattern, same seasonal '
      + 'pattern, same peak-to-average ratio, same hour of the year for the peak. Everything grows '
      + 'together.',

      'That is a strong assumption and it is almost always wrong in a decarbonising system, because the '
      + 'growth is coming from specific new uses — heat pumps, electric vehicles, data centres — each '
      + 'with its own daily and seasonal signature. But it is the right method when the growth really is '
      + 'diffuse, and it is the honest method when you know nothing about composition.',

      'The alternative within the same panel is to FIT the trend rather than assert it: Trend fit, '
      + 'ARIMA and Prophet estimate growth from the history in the series itself. They need history — at '
      + 'least three years of it — and this model has one year, so they are unavailable here. That is '
      + 'the usual situation, and it is why an asserted growth rate is what most studies actually use.',
    ],
    explain: [
      'Go to Forge — the tab between Model and Market & Policy — and open Temporal → Forecast to future '
      + 'year. Read the controls: a from-year and to-year pair, a row of method buttons (Compound '
      + '(CAGR), Linear, Trend fit, ARIMA, Prophet), and a Demand growth (%/yr) field that only appears '
      + 'for the first two. The action button names the year it will project to.',

      'Try Trend fit first, deliberately, and read the error: it needs at least three years '
      + 'of history in the demand series and found one. That message is doing you a favour — a fitted '
      + 'trend on a single year would be an extrapolation from nothing, and the tool refuses rather '
      + 'than obliging.',

      'Then note which sheets a forecast touches. Demand is grown; availability profiles like '
      + '`generators-p_max_pu` are re-dated to the target year but never scaled, because a capacity '
      + 'factor is a fraction and multiplying it by 1.219 would be meaningless. The snapshot axis moves '
      + 'with them, so everything stays aligned.',
    ],
    spotlights: [
      {
        selector: '[data-forge-op="forecast"]',
        title: 'Forecast to future year',
        tab: 'Forge',
        note: 'In the Forge rail, under Temporal. The three transforms this module uses are all in '
          + 'that group — retarget, forecast and the driver-based one.',
      },
    ],
    entries: [
      {
        field: 'Forge → Forecast to future year → From year',
        value: '2030',
        why: 'The year the current series represents. It comes from the snapshot timestamps rather than '
          + 'from anything you entered, and getting it wrong silently changes the number of compounding '
          + 'years.',
      },
      {
        field: 'Forge → Forecast to future year → To year',
        value: '2040',
        why: 'The target. Ten years of compounding at 2% is a factor of 1.219 — enough to matter and '
          + 'short enough to be a plausible planning horizon.',
      },
      {
        field: 'Forge → Forecast to future year → Demand growth (%/yr)',
        value: '2.0',
        unit: 'per cent per year',
        why: 'The whole projection, in one number. Mature systems have run at well under 1% for decades '
          + 'and electrifying ones project 2-4%; the honest treatment is a range rather than a point, '
          + 'which is module 9\'s argument applied to the most important input in the model.',
      },
      {
        field: 'Forge → Forecast to future year → Method',
        value: 'Compound (CAGR)',
        why: 'Compound growth on every hour. The fitted methods — Trend fit, ARIMA, Prophet — need three '
          + 'or more years of history and are the right choice when you have it.',
      },
    ],
    verify: [
      'Trend fit refuses, naming the three-year minimum',
      'You can say what a uniform growth factor assumes about 2040',
      'You can say why availability profiles are re-dated but not grown',
      'You can name a growth rate you would defend for a system you know',
    ],
    pitfalls: [
      'Reading a single growth rate as a forecast. It is a scenario, and it deserves the sensitivity '
      + 'treatment module 9 gave the discount rate.',
    ],
  },

  {
    id: 'm13-project-to-2040',
    section: SECTION,
    title: 'Project it, and check what moved',
    tab: 'Forge',
    where: 'Forge → Forecast to future year, then the load duration curve',
    concept: [
      'Applying 2% a year from 2030 to 2040 multiplies every hour by 1.219. Peak demand goes from 174.7 '
      + 'to 212.9 MW and annual energy from 1,030.5 to 1,256.2 GWh. Both grew by exactly the same '
      + 'factor, which is the method working as designed rather than a coincidence.',

      'The ratio between them — the load factor — is therefore unchanged, and so is every other shape '
      + 'statistic. The duration curve is the same picture with a different vertical scale. If you had '
      + 'been handed the 2040 profile with no explanation you could not tell it from the 2030 one.',
    ],
    explain: [
      'Set from 2030 to 2040, method Compound (CAGR), demand growth 2, and press Project to 2040. The '
      + 'panel defaults to 2025 → 2035, so both years need changing. The result '
      + 'reports the growth factor it '
      + 'applied — 1.219 — and which sheets it grew.',

      'Check the three things that should have changed and the one that should not. Peak 212.9 MW '
      + '(174.7 × 1.219). Energy 1,256.2 GWh. The snapshot axis now reads 2040. And the shape: pull up '
      + 'the load duration curve again and compare it against the one from step 1.',

      'Do the arithmetic yourself on at least one of them rather than accepting the number. 174.7 × '
      + '1.02^10 = 212.9. That habit is the whole course in one line, and it is worth keeping for a '
      + 'transform as consequential as this one.',
    ],
    run: {
      label: 'Forge → Forecast to future year → Project to 2040',
      detail: ['A local transform on the session — no solve, effectively instant.'],
      expect: 'A growth factor of 1.219, a peak of 212.9 MW and 1,256.2 GWh, all dated 2040.',
    },
    verify: [
      'The forecast reports a growth factor of 1.219',
      'Peak demand reads 212.9 MW and annual energy 1,256.2 GWh',
      'The snapshot axis and the availability profiles are dated 2040',
      'The load duration curve has the same shape as before, at a different scale',
    ],
    pitfalls: [
      'Forecasting twice by accident. The transform applies to whatever is currently in the session, so '
      + 'a second pass compounds on the first — reload the checkpoint if you are unsure where you are.',
    ],
  },

  {
    id: 'm13-the-model-cannot-serve-it',
    section: SECTION,
    title: 'Now run it: the model that worked does not',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Validation',
    concept: [
      'The brownfield fleet served 2030\'s 174.7 MW peak with room to spare and cost about 30 million. '
      + 'Against 212.9 MW it returns INFEASIBLE. There is no cheapest answer, because there is no answer '
      + 'at all — no combination of dispatch decisions meets that demand with that plant.',

      'This is the most important consequence of a demand projection and the one people are least '
      + 'prepared for. Growing demand is not a harmless rescale of an existing study. It can invalidate '
      + 'the model outright, and when it does, the honest reading is not "the model broke" but "this '
      + 'system cannot serve that demand".',

      'Count the capacity to see why. Coal 50 MW and oil 40 MW inject electricity directly; the gas '
      + 'supply reaches the electrical side through a Link, so what matters is the Link\'s rating and '
      + 'efficiency rather than the fuel unit\'s 150 MW. Add the firm contributions and the total is '
      + 'below the new peak. Wind and run-of-river help when they are there and cannot be relied on when '
      + 'they are not.',
    ],
    explain: [
      'Run the projected model. It fails, and the error names what it found: snapshots whose load cannot '
      + 'be covered by supply, with the window they fall in.',

      'Read that message properly rather than reaching for a fix. Ragnarok\'s infeasibility diagnostic '
      + 'tries to identify a structural cause and says so when it cannot — here it reports that capacity '
      + 'looks adequate on paper and points at transmission limits, commitment minimums or cyclic '
      + 'storage as the remaining candidates. On this model the answer is the Link between the gas bus '
      + 'and the electrical one, which is exactly the kind of thing a capacity count in a spreadsheet '
      + 'misses and module 5 taught you to look for.',

      'There are only two honest responses to an infeasible projection, and picking between them is a '
      + 'modelling decision rather than a technical one. Either the system gets more capacity — which is '
      + 'module 7\'s question, and the next step — or the demand projection is wrong and needs revising. '
      + 'What you must not do is enable load shedding to make the error go away and then report the '
      + 'result as a cost.',
    ],
    run: {
      label: 'Run → Run model',
      detail: ['The solve fails in seconds; an infeasible LP is usually faster than a feasible one.'],
      expect: 'INFEASIBLE, with a diagnostic naming uncovered load and the window it falls in.',
    },
    verify: [
      'The run returns INFEASIBLE rather than a cost',
      'You can find the diagnostic message and say what it identified',
      'You can explain why counting generator p_nom did not predict this',
      'You can state the two honest responses to an infeasible projection',
    ],
    pitfalls: [
      'Turning on load shedding to obtain a number. It converts an unbuildable system into an expensive '
      + 'one and hides the finding — the shedding cost is a made-up value of lost load, not a market '
      + 'price.',
      'Concluding the forecast was applied wrongly. Check the peak against your own arithmetic first; '
      + 'here 212.9 is exactly right and the fleet is exactly too small.',
    ],
  },

  {
    id: 'm13-let-the-optimiser-respond',
    section: SECTION,
    title: 'Give the question back to the optimiser',
    tab: 'Build',
    where: 'Load the complete model, forecast it, and run',
    concept: [
      'An infeasible dispatch model becomes a feasible investment model the moment capacity is a '
      + 'decision rather than a given. That is module 7\'s machinery, and applying it to a projected '
      + 'demand is the standard planning question: what has to be built to serve the load we expect?',

      'With wind, solar, the battery and the line all extendable at their capital costs, the projected '
      + 'year solves at 31,848,292 — about 6.6 million of fuel and 25.3 million of annuitised capital. '
      + 'To get there it builds wind from 60 to 202.8 MW and solar from nothing to 50.0 MW, and leaves '
      + 'the battery where it is.',

      'Hold on to those two capacity numbers. They are what a 2% uniform growth rate implies for the '
      + 'build programme, and the last part of this module changes nothing but the shape of that growth '
      + 'and watches them move.',
    ],
    explain: [
      'Load the complete model — module 7\'s extendable fleet — and apply the same forecast: 2030 to '
      + '2040, 2%, CAGR. The demand you get is identical to the one that was infeasible a moment ago; '
      + 'only the fleet is different.',

      'Run it. The solve takes a minute or so because expansion on 8,760 hours is a bigger problem than '
      + 'dispatch on the same axis.',

      'Read the objective and then the expansion results: wind 202.8 MW, solar 50.0 MW, battery '
      + 'unchanged at 20 MW. Compare that against what module 7 built for the 2030 demand — 150 MW of '
      + 'wind and 24 of solar — and you have the cost of ten years of 2% growth, expressed as plant.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'A feasible answer again',
        tab: 'Analytics',
        note: '31,848,292 — the same demand that had no answer at all, once capacity became a decision.',
      },
    ],
    run: {
      label: 'Run → Run model (extendable fleet, projected demand)',
      detail: ['Capacity expansion over 8,760 hours. Allow a minute or two.'],
      expect: 'An objective near 31,848,292, with wind built to 202.8 MW and solar to 50.0 MW.',
    },
    verify: [
      'The projected year now solves',
      'The objective is about 31,848,292',
      'Wind is built to 202.8 MW and solar to 50.0 MW',
      'You can say what changed between the infeasible run and this one',
    ],
    pitfalls: [
      'Forgetting to re-apply the forecast after loading the complete model. Its demand is the 2030 one '
      + 'until you project it, and a 2030 answer here would look plausible and be the wrong comparison.',
    ],
  },

  {
    id: 'm13-drivers-not-a-factor',
    section: SECTION,
    title: 'The other family: build the growth from what causes it',
    tab: 'Forge',
    where: 'Forge → Temporal → Driver-based demand forecast',
    concept: [
      'A driver-based forecast asks where the extra demand actually comes from and gives each source its '
      + 'own signature in time. Ragnarok splits it into two parts.',

      'The macro part scales the existing profile: population growth adds people using electricity the '
      + 'way today\'s people do, and economic growth adds consumption in proportion to GDP times an '
      + 'elasticity. Elasticity is the number that says how much electricity demand moves with economic '
      + 'output — well below one in a mature service economy, near or above one in an industrialising '
      + 'system. Those two together still preserve the shape, because they are scaling what is there.',

      'The electrification part does not. Electrified heat is added as energy with a winter, evening '
      + 'signature, because that is when buildings are cold. EV charging is added with its own daily '
      + 'pattern. Neither follows today\'s demand shape, and that is the whole point: they are new uses, '
      + 'not more of the old ones.',

      'So the same annual energy can arrive in two completely different arrangements, and the next step '
      + 'measures what that difference is worth.',
    ],
    explain: [
      'Reload the brownfield year, so the comparison is clean, and open Forge → Temporal → Driver-based '
      + 'demand forecast instead of the plain one.',

      'Set it up as pure electrification: population growth 0, GDP growth 0, and the added energy '
      + 'carried entirely by heat and EVs — 120 GWh of electrified heat and 106 GWh of EV charging. '
      + 'Those are chosen to land on the same annual total as the 2% CAGR run, so nothing but the shape '
      + 'differs.',

      'The action button reads Evolve demand to 2040, and the panel shows a macro factor of x1.000 '
      + 'while you set it up — confirmation that the macro half is doing nothing, so everything that '
      + 'changes afterwards came from the electrification half.',

      'That is a deliberately artificial split. A real study would carry macro growth AND electrification '
      + 'together; setting the macro terms to zero isolates the shape effect so you can see it, which is '
      + 'the same trick module 2 used when it added one generator at a time.',
    ],
    spotlights: [
      {
        selector: '[data-forge-op="driverForecast"]',
        title: 'Driver-based demand forecast',
        tab: 'Forge',
        note: 'One below the plain forecast. Read its description before you touch the inputs — it '
          + 'states exactly which parts scale the old shape and which add a new one.',
      },
    ],
    entries: [
      {
        field: 'Forge → Driver-based demand forecast → Population %/yr',
        value: '0',
        why: 'Zeroed deliberately. Macro growth scales the existing shape, and this step is isolating '
          + 'the part that does not.',
      },
      {
        field: 'Forge → Driver-based demand forecast → GDP %/yr',
        value: '0',
        why: 'Same reason. In a real projection this is where most of the growth in a mature system '
          + 'comes from.',
      },
      {
        field: 'Forge → Driver-based demand forecast → GDP elasticity',
        value: '0.5',
        why: 'How much electricity demand moves with economic output. Inactive here because GDP growth '
          + 'is zero, but it is the number that decides how much of a growth projection is macro — and '
          + 'a value most studies inherit without examining.',
      },
      {
        field: 'Forge → Driver-based demand forecast → Electrified heat (GWh/yr)',
        value: '120',
        why: 'Electrified heating, added on a winter-evening profile rather than proportionally. This '
          + 'is where the new peak comes from.',
      },
      {
        field: 'Forge → Driver-based demand forecast → EV charging (GWh/yr)',
        value: '106',
        why: 'Vehicle charging, on its own daily pattern. Chosen with the heat figure so the annual '
          + 'total matches the CAGR run to within a fraction of a per cent.',
      },
    ],
    verify: [
      'You have reloaded the brownfield year before applying this',
      'The driver forecast reports a macro factor of 1.0 and the two added energies',
      'You can say why macro growth preserves shape and electrification does not',
      'You can say why the macro terms were zeroed for this experiment',
    ],
    pitfalls: [
      'Applying the driver forecast on top of the CAGR one. They compound, and the comparison is then '
      + 'between two different energy totals rather than two shapes.',
    ],
  },

  {
    id: 'm13-same-energy-different-peak',
    section: SECTION,
    title: 'Same energy, a higher peak',
    tab: 'Analytics',
    where: 'The load duration curve, against step 3',
    concept: [
      'Annual energy is 1,256.5 GWh against the CAGR run\'s 1,256.2 — the same to within a fraction of '
      + 'a per cent, by construction. Peak demand is 220.4 MW against 212.9. Seven and a half megawatts, '
      + 'or 3.5%, of extra peak for the same amount of electricity consumed.',

      'That gap is the entire content of the phrase "demand growth changes shape". Every megawatt-hour '
      + 'is the same; where they land is not. Heat arrives on cold winter evenings and vehicles charge '
      + 'in patterns that overlap the existing evening peak, so the new energy piles onto hours that '
      + 'were already the busiest instead of spreading across the year.',

      'And peak is what capacity is sized for. A system pays for its peak in plant and its energy in '
      + 'fuel, so two projections with identical energy and different peaks are two different investment '
      + 'programmes — which the next step demonstrates rather than asserts.',
    ],
    explain: [
      'Measure the projected profile: peak 220.4 MW, energy 1,256.5 GWh. Write both down next to the '
      + 'CAGR run\'s 212.9 and 1,256.2.',

      'Then look at the two load duration curves together. The CAGR curve is the 2030 shape stretched '
      + 'vertically; this one is steeper at the left-hand end — more hours near the top — because the '
      + 'new load is concentrated rather than spread. The area under both curves is the same.',

      'This is also a warning about a common shortcut. If you were handed only the annual energy figure '
      + 'for 2040 and asked to build a profile by scaling today\'s, you would produce the CAGR curve and '
      + 'under-state the peak by 3.5% — on a projection whose composition you were never told.',
    ],
    spotlights: [
      {
        selector: '[data-card="duration-curve"][data-card-source="load"]',
        title: 'Steeper at the top',
        tab: 'Analytics',
        note: 'Same area, higher left-hand end. That is what electrified load does to a duration curve, '
          + 'and it is invisible in an annual energy total.',
      },
    ],
    verify: [
      'Peak reads 220.4 MW against the CAGR run\'s 212.9 MW',
      'Annual energy matches the CAGR run to within a fraction of a per cent',
      'The duration curve is steeper at its left-hand end',
      'You can say why the difference is invisible in an annual energy figure',
    ],
    pitfalls: [
      'Dismissing 3.5% as small. It is 3.5% on the number that sizes the fleet, on a deliberately mild '
      + 'electrification assumption — and it compounds with every other conservative choice in the same '
      + 'direction.',
    ],
  },

  {
    id: 'm13-what-the-shape-costs',
    section: SECTION,
    title: 'What the shape costs — and what it builds',
    tab: 'Analytics',
    where: 'The extendable fleet, projected both ways',
    concept: [
      'Run the electrified projection against module 7\'s extendable fleet and it solves at 31,679,393 '
      + '— about 169,000 LESS than the CAGR projection\'s 31,848,292, despite the higher peak. That is '
      + 'not the result most people predict, and it is worth understanding rather than explaining away.',

      'The build programme is where the difference really shows. The CAGR year builds wind to 202.8 MW '
      + 'and solar to 50.0 MW. The electrified year builds wind to 208.3 MW and solar to just 20.2 MW — '
      + 'five and a half megawatts more wind and thirty megawatts less solar, for the same energy.',

      'The reason is the same fact from both sides. Electrified heat and evening EV charging land in '
      + 'winter evenings, when solar produces nothing and wind produces well. So the load that a solar '
      + 'panel could have served did not grow much, and the load a wind turbine can serve grew a lot. '
      + 'The optimiser is not responding to the peak so much as to WHEN the new energy arrives.',

      'The lesson generalises beyond these numbers: the composition of demand growth determines which '
      + 'technologies are worth building, more strongly than it determines what the system costs. A '
      + 'study that projects demand by scaling and then reports a technology mix has answered a question '
      + 'about a system nobody is going to have.',
    ],
    explain: [
      'Load the complete model again, apply the driver-based demand forecast with the same five '
      + 'settings, and run.',

      'Read the objective — 31,679,393 — and put it beside the CAGR run\'s 31,848,292. Then read the '
      + 'expansion results and put those side by side too: wind 208.3 against 202.8, solar 20.2 against '
      + '50.0.',

      'Work out for yourself why the cheaper answer is the one with the higher peak, before reading the '
      + 'explanation again. The clue is in module 7: the value of an asset is not its capacity but the '
      + 'energy it displaces, and the hours the new load occupies are hours wind can serve.',

      'Then note the honest caveat. Both runs are one weather year, one elasticity, one split between '
      + 'heat and EVs, and one growth rate — and module 12 showed what a single weather year hides. The '
      + 'finding here is the DIRECTION and the mechanism, not the 169,000.',
    ],
    run: {
      label: 'Run → Run model (extendable fleet, driver-projected demand)',
      detail: ['Capacity expansion over 8,760 hours again. A minute or two.'],
      expect: 'An objective near 31,679,393, with wind at 208.3 MW and solar at 20.2 MW.',
    },
    verify: [
      'The electrified projection solves at about 31,679,393',
      'Wind is built to 208.3 MW and solar to 20.2 MW',
      'You can explain why the higher-peak year came out cheaper',
      'You can say what part of this finding you would quote and what part you would not',
    ],
    pitfalls: [
      'Reporting the 169,000 as the value of shape modelling. It is the difference between two runs on '
      + 'one weather year; the 30 MW of solar is the finding that would survive a sensitivity analysis.',
    ],
  },

  {
    id: 'm13-what-a-demand-projection-owes-you',
    section: SECTION,
    title: 'What a demand projection owes you',
    tab: 'Forge',
    where: 'Reading critically',
    concept: [
      'You now have two projections of the same system that agree on annual energy to within a fraction '
      + 'of a per cent and disagree by 30 MW on how much solar to build. Neither is wrong. They encode '
      + 'different assumptions about composition, and only one of those assumption sets was ever written '
      + 'down as a number you could argue with.',

      'That is what to demand of any demand forecast you are handed. Not just the growth rate, but what '
      + 'is growing: how much is macro, how much is electrification, what elasticity was assumed, what '
      + 'daily and seasonal signature the new load was given, and which weather year the base profile '
      + 'came from.',

      'And the reverse obligation when you produce one. Every number in the driver forecast you just '
      + 'ran — 120 GWh of heat, 106 of EVs, an elasticity of 0.5 — is an assumption that belongs in the '
      + 'write-up with a source or a reason, exactly as module 9 required of every other figure.',
    ],
    explain: [
      'Write down the five things to demand of any projection you are handed: what growth rate, what composition, what '
      + 'elasticity, what shape was assumed for new load, and which base year and weather year it '
      + 'started from.',

      'Then test them against this module. Two of the five differ between the runs you did, and the '
      + 'other three are identical — and yet the build programmes differ by 30 MW of solar. If someone '
      + 'hands you a 2040 profile with no answers to those questions, you cannot tell which of these two '
      + 'systems you are being asked to plan.',

      'One more practical point, because it is the commonest error in this area. A demand projection '
      + 'must be applied to the WHOLE model, not just the load column: the snapshot axis moves, and '
      + 'every other temporal sheet has to move with it. Ragnarok\'s forecast transforms do that for '
      + 'you, and a hand-edited spreadsheet will not — which produces a model where the demand is 2040 '
      + 'and the wind is 2030, silently, with no error anywhere.',
    ],
    verify: [
      'You have those five demands written down',
      'You can say which two differ between this module\'s two projections',
      'You can say what breaks if only the demand column is re-dated',
      'You can name the assumptions in your own projection that need a source',
    ],
    pitfalls: [
      'Accepting a demand column because it came from an official source. Official projections are '
      + 'models too, with all the same assumptions, and they are usually documented well enough that '
      + 'you can go and read them.',
    ],
  },

  {
    id: 'm13-five-questions',
    section: SECTION,
    title: 'Five questions, and what is still missing',
    tab: 'Analytics',
    where: 'Everything you have built',
    concept: [
      'Thirteen modules so far, one model, and the same move in every one of them: work out what the '
      + 'answer should be, then find out which of you is wrong.',

      'That habit found things. The merit order made 12,000 into 7,500. A line rating made one price '
      + 'into two. A battery was worth twenty-three times more on a day than on three hours. Two points '
      + 'on the discount rate moved 30 MW between technologies. A plant that could not switch off spilt '
      + 'free wind. A nodal price came out above every generator in the model. A system that shed no '
      + 'load turned out to be seven times outside its reliability standard. And a demand projection '
      + 'that changed nothing but shape moved 30 MW of solar out of the plan.',

      'None of those came from the solver being clever. Each came from asking a model a question it had '
      + 'not been asked before, and every one of them started as a number somebody could have accepted '
      + 'without checking.',
    ],
    explain: [
      'Nothing after this module adds to the model itself. What the last two add is perspective, and '
      + 'the running list of questions this course keeps arriving at grows by one in each of them. Four '
      + 'of them you can already ask of any model, including one you did not write.',

      'What is the objective actually minimising, and what is missing from it? What is the time axis, '
      + 'and what does its resolution and horizon hide? Which constraints are binding, and what would '
      + 'it cost to relax them? And what is the range around the answer, with the conditions that '
      + 'produced it?',

      'Add the fifth this module contributed: where did the demand come from, and what does it assume '
      + 'about what is growing?',

      'Take your own model and answer those five. Where you cannot, you have found the next thing to '
      + 'work on — which is the same method this course used to find every one of its own findings.',

      'Two questions are still missing, and neither is about the model. Module 14 asks whose books the '
      + 'answer belongs to, and module 15 asks what market design it assumes. Both change conclusions '
      + 'you have already drawn.',
    ],
    verify: [
      'You can state the five questions without looking them up',
      'You can answer all five about a model you built',
      'You can name the one you are least able to answer, and what it would take',
    ],
    pitfalls: [
      'Treating the course as finished. The habit is what was being taught; the modules were just the '
      + 'places to practise it.',
    ],
  },
];
