/**
 * Module 7 — Investment and capacity expansion (13 steps).
 *
 * Every module so far has ended by admitting the model could not say whether
 * something was worth building. Capacity was given, so unused capacity was free,
 * so the answer was always "how should this fleet run" and never "what should
 * this fleet be".
 *
 * Built on a full year — 8,760 hourly snapshots — and that is not only realism.
 * Ragnarok annuitises a workbook `capital_cost` and the results layer pro-rates
 * that annual figure by modelled_hours/8760 for display. On any shorter window
 * the optimiser needs the cost pre-scaled and the display then scales it again,
 * so the pre-scaled cost is scaled twice and the displayed capital is nonsense.
 * At 8,760 the factor is 1, the overnight cost goes in exactly as a cost
 * database quotes it, and the capital reported is the capital charged. Module 6
 * is what makes this module honest.
 *
 * One difference survives, and step 9 teaches it rather than hiding it: the KPI
 * reports 25,611,302 (fuel plus the annuity on the WHOLE fleet) while the solver
 * minimised 18,115,684 (fuel plus the annuity on what it BUILDS). Sunk capital
 * cannot be changed by a decision, so it belongs in a tariff and not in a
 * comparison between decisions. Both numbers are right for different questions.
 *
 * Four assets compete. Every figure verified against a real HiGHS solve through
 * the app's own build path, at the default 5% discount rate:
 *
 *   fixed capacity          29,980,642   7.82 GWh of oil burnt
 *   expansion at 5%         18,115,684   wind 150.15, solar 24.12, line 141.04
 *                                        battery declined at its 20 MW floor
 *   expansion at 7%         20,419,029   wind 120.17, solar 41.67, line 130.85
 *   greenfield at 5%        18,045,470   battery falls to 4.00 MW
 *
 * Three results carry the module. Expansion saves 11.9m a year — 40% of system
 * cost — and removes the oil peaker entirely. The discount rate does not merely
 * build less, it builds DIFFERENTLY: two points less wind and nearly twice the
 * solar. And greenfield exposes what brownfield hides — a fresh build would put
 * in 4 MW of battery where 20 MW already stands, which is a stranded asset that
 * no brownfield run can show you.
 */
import { TutorialStep } from '../types';

const SECTION = '7 · Investment and capacity expansion';

export const MODULE_7_INVESTMENT: TutorialStep[] = [
  {
    id: 'm7-what-to-build',
    section: SECTION,
    title: 'From how hard to run, to what to build',
    tab: 'Build',
    where: 'Build → Generators step',
    startOptions: {
      prebuiltExampleId: 'training_m7_year',
      completeExampleId: 'training_m7',
      note:
        'Module 7 needs a full year, so the prebuilt option is the course\'s system on 8,760 hourly '
        + 'snapshots with demand, wind, run-of-river and solar profiles already in place — module 6 '
        + 'taught how to get there and typing 8,760 rows is not a lesson. Nothing is extendable yet; '
        + 'that is what this module adds.',
    },
    concept: [
      'Six modules have asked one question: given this equipment, how should it run? Capacity was a '
      + 'number you typed, so unused capacity cost nothing, so the model could never say whether a plant '
      + 'was worth having — only what it was worth running. Every module has ended by saying so.',

      'Capacity expansion makes capacity a decision variable. `p_nom` stops being an input and becomes '
      + 'something the optimiser chooses between a floor and a ceiling, with a cost attached to whatever '
      + 'it picks. The objective changes from "cheapest way to run this fleet" to "cheapest way to serve '
      + 'this demand, counting what the fleet costs to own".',

      'That needs a kind of number you have not used yet. Everything priced so far has been marginal — '
      + 'the cost of one more MWh. Capital cost is the cost of one more MW existing, whether or not it '
      + 'ever runs, and the two cannot be added until the capital cost is spread across time.',

      'The spreading is where expansion models go wrong, and the next three steps are about it before '
      + 'anything gets built. The arithmetic is simple. The units are not, and a capital cost in the '
      + 'wrong units gives a confident answer that is out by orders of magnitude.',
    ],
    explain: [
      'Load the prebuilt year. It is module 5\'s system — three buses, a CCGT, a gas store, wind, '
      + 'run-of-river, a battery, a pumped-hydro scheme — on 8,760 hourly snapshots, plus one addition: '
      + 'a solar site at bus_2, the demand end, with a capacity of zero.',

      'A zero-capacity generator with a profile is how you offer the model a site it has not built yet. '
      + 'It contributes nothing until step 7 makes it extendable, and then it is a real option.',

      'Run it as it stands, before changing anything. The objective is 29,980,642 and the oil peaker '
      + 'burns 7.82 GWh across the year. That is the fixed-capacity baseline everything else is measured '
      + 'against, and it is the last time in this course you will see the peaker run.',

      'A word on the year. The profiles are synthetic — a shaped day modulated seasonally, wind with '
      + 'winter maximum and realistic persistence, solar with a summer maximum and nothing at night. They '
      + 'are not measurements, and a real study would import them (Ragnarok\'s Data view does exactly '
      + 'that). They are structured enough for every lesson here to hold, and saying so is part of the '
      + 'lesson: a model is only as defensible as the provenance of its inputs.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Six generators now',
        tab: 'Build',
        note: 'coal, oil, wind, run-of-river, the gas import — and solar_1 at p_nom 0. Scroll right and '
          + 'you will find p_nom_extendable, p_nom_min, p_nom_max, capital_cost and lifetime, sitting '
          + 'unused since module 1. That is the whole of capacity expansion, already in the sheet.',
      },
      {
        selector: '[data-build-step="snapshots"]',
        buildStep: 'snapshots',
        title: '8,760 rows',
        tab: 'Build',
        note: 'A full year at hourly resolution, which module 6 warned would be 8,760 rows and would take '
          + 'real time to solve. Expect about a minute per run from here on — that is what an honest '
          + 'investment question costs.',
      },
    ],
    verify: [
      'The session holds 8,760 snapshots and the fixed-capacity run answers 29,980,642',
      'oil_1 burns about 7.82 GWh across the year',
      'solar_1 exists with p_nom 0 and a profile',
      'You can say why a dispatch model cannot value a plant, only its output',
    ],
    pitfalls: [
      'Expecting expansion to be a different kind of model. It is the same linear program with a few '
      + 'more variables and a few more objective terms — which is also why it is so much slower.',
      'Treating synthetic profiles as data. They are shaped to teach; every conclusion here is about the '
      + 'mechanism, not about any real system.',
    ],
  },

  {
    id: 'm7-a-year',
    section: SECTION,
    title: 'Why this module needs a whole year',
    tab: 'Settings',
    where: 'Settings → Simulation window',
    concept: [
      'Module 6 showed that a horizon decides which questions a model can answer. For investment there '
      + 'is a second, sharper reason, and it is about units rather than physics.',

      'An annuitised capital cost is a cost per YEAR. If the objective covers a year, the two match and '
      + 'nothing needs adjusting. If it covers three hours, the capital charge is 2,920 times too large '
      + 'against the fuel bill, the optimiser builds nothing, and the "no" looks considered rather than '
      + 'dimensionally wrong.',

      'You can compensate by scaling the overnight cost down by the fraction of the year modelled — and '
      + 'that works for the OPTIMISER. But Ragnarok also pro-rates capital by modelled_hours/8760 when it '
      + 'reports cost, so a pre-scaled cost gets scaled a second time and the reported total no longer '
      + 'equals the objective the solver minimised. There is no setting where both are right.',

      'At 8,760 hours the factor is 1 and the problem evaporates. The overnight cost goes into the sheet '
      + 'exactly as a cost database quotes it, the objective and the reported total agree, and nothing '
      + 'needs explaining in a footnote. That is why this module comes after module 6 rather than before.',
    ],
    explain: [
      'Nothing to change. Open Settings → Simulation window and confirm the window covers all 8,760 '
      + 'snapshots at 1h resolution, because everything from here depends on it.',

      'Resist the temptation to narrow it for speed. A shorter window is not a faster version of this '
      + 'study — it is a different study whose capital arithmetic no longer lines up, and the numbers it '
      + 'produces cannot be compared with the ones in this module.',

      'If you do want a faster preview, module 6 gave you the honest tools: coarsen the resolution or '
      + 'sample blocks, and report that you did. Both change the answer, and both change it less than '
      + 'silently mismatching your capital units.',

      'One practical consequence: every run in this module takes about a minute. That is the cost of '
      + 'asking a question that needs a year, and it is worth feeling once.',
    ],
    spotlights: [
      {
        selector: '.sg-scenario-summary',
        title: 'The window, checked one last time',
        runDialog: 'open',
        note: 'It should read 8,760 snapshots at 1h. The habit of checking this line before every run '
          + 'started in module 1 as good practice; here it is what keeps the capital costs meaningful.',
      },
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Leave the window alone',
        note: 'Simulation window and Sampling both change what the solver sees. Either would make this '
          + 'module\'s capital arithmetic wrong in a way nothing on screen would flag.',
      },
    ],
    verify: [
      'The simulation window covers all 8,760 snapshots at 1h',
      'You can say why an annualised capital cost and a three-hour objective cannot be compared',
      'You can say why pre-scaling the cost fixes the optimiser and breaks the reported total',
      'You can say why a full year makes both correct at once',
    ],
    pitfalls: [
      'Narrowing the window to save time and keeping the same capital costs. The optimiser then sees a '
      + 'year of capital against a fraction of a year of fuel and builds nothing.',
      'Assuming the app will warn you. It cannot: on a model with weighted representative periods a short '
      + 'window is entirely correct, so there is no rule it could apply.',
    ],
  },

  {
    id: 'm7-overnight-and-crf',
    section: SECTION,
    title: 'Overnight cost, annuity, and who does the arithmetic',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'A wind farm costs about 1,200,000 per MW to build. That is the OVERNIGHT cost — what it would '
      + 'cost if it appeared instantly with no financing — and it is the number cost databases publish '
      + 'and engineers quote.',

      'It cannot enter the objective as a lump sum, because the objective is a cost over a period of '
      + 'operation. Annuitisation converts it: the capital recovery factor gives the equal annual payment '
      + 'that repays the lump sum over the asset\'s life at a given discount rate.',

      'CRF = r(1+r)^n / ((1+r)^n − 1). At 5% over 25 years that is 0.0710, so 1,200,000 per MW becomes '
      + '85,150 per MW per year — the figure that belongs beside a fuel bill.',

      'Ragnarok does this for you, and knowing that is the point of this step. The `capital_cost` column '
      + 'holds the OVERNIGHT cost; the app multiplies by CRF using the row\'s `lifetime` and the discount '
      + 'rate from Settings. PyPSA used directly expects the annuitised figure instead, so a cost that is '
      + 'right in one is twelve times wrong in the other. Always establish which convention you are in '
      + 'before trusting a number.',
    ],
    explain: [
      'Nothing to enter yet — find the columns. On the Generators step, scroll right past `efficiency` '
      + 'and you reach `p_nom_extendable`, `p_nom_min`, `p_nom_max`, `capital_cost` and `lifetime`. Use '
      + 'the Columns button if scrolling is awkward.',

      '`lifetime` matters more than it looks. Left blank, PyPSA defaults it to infinity, which has no '
      + 'finite annuity — so Ragnarok substitutes 20 years rather than letting the cost annuitise to '
      + 'nothing. A blank lifetime is not neutral; it is a 20-year assumption you did not make.',

      'The four figures this module uses, all overnight and all plausible for 2030: wind 1,200,000 per MW '
      + 'over 25 years, solar 500,000 over 25, transmission 600,000 per MW over 40, and a two-hour '
      + 'battery 150,000 per MW over 15.',

      'Note the lifetimes as much as the costs. Transmission at 40 years carries a CRF of 0.058 against '
      + 'wind\'s 0.071 — the same capital costs 18% less per year — which is a real and underappreciated '
      + 'reason networks are often the cheapest fix.',
    ],
    spotlights: [
      {
        selector: '.tables-grid-wrap',
        buildStep: 'generators',
        title: 'The columns that have been waiting',
        tab: 'Build',
        note: 'p_nom_extendable, p_nom_min, p_nom_max, capital_cost, lifetime. Every model in this course '
          + 'has carried them empty — expansion adds attributes, not components.',
      },
    ],
    verify: [
      'You can state the CRF formula and say what each symbol means',
      'You can compute the annual cost of a 1,200,000/MW asset over 25 years at 5%',
      'You can say which convention Ragnarok uses for `capital_cost`, and why it matters',
      'You can say what happens when `lifetime` is left blank',
    ],
    pitfalls: [
      'Entering an already-annuitised cost. Ragnarok annuitises what you give it, so it gets annuitised '
      + 'twice and comes out about twelve times too small — which makes new capacity look nearly free.',
      'Leaving `lifetime` blank. It becomes 20 years, which is wrong for almost everything and moves the '
      + 'annual cost by a third.',
    ],
  },

  {
    id: 'm7-discount-rate',
    section: SECTION,
    title: 'The discount rate — the assumption you inherit',
    tab: 'Settings',
    where: 'Settings → Project defaults → Discount rate',
    concept: [
      'The discount rate decides how heavily a future cost counts today, and in an expansion model it '
      + 'decides how much capital is worth committing. A low rate favours capital-heavy, fuel-free '
      + 'technologies — wind, solar, nuclear, transmission. A high rate favours cheap-to-build, '
      + 'expensive-to-run plant, which means gas.',

      'The effect is large and it is not uniform. Step 13 moves the rate from 5% to 7% and the answer '
      + 'does not merely shrink: wind falls by 30 MW while solar nearly doubles. The rate changes the '
      + 'MIX, not just the total, which is why two studies can disagree about which technology to build '
      + 'while agreeing about everything physical.',

      'Ragnarok puts the number in front of you — Settings → Project defaults → Discount rate, with the '
      + 'app\'s own note explaining what it does — and ships it at 0.05. Treat that default as a hazard '
      + 'rather than a convenience: an assumption you inherit silently is more dangerous than one you are '
      + 'forced to supply, because nothing prompts you to defend it.',

      'The API is stricter. A run submitted without a rate, while extendable assets carry capital costs, '
      + 'is refused outright with a message naming them — so an agent or a script cannot author this '
      + 'assumption by omission. The GUI gives you 0.05 and expects you to look at it.',
    ],
    explain: [
      'Settings → Project defaults. Confirm Discount rate reads 0.05 and leave it — every figure in this '
      + 'module assumes it, so a learner who never opens Settings still matches the course.',

      'Read the app\'s note under the field: "used to annualise capital costs for extendable assets, 0.05 '
      + '= 5% WACC". That is the whole mechanism, and it explains why the setting did nothing for six '
      + 'modules — until something is extendable, there is no capital to annualise.',

      'Make a deliberate note that you have looked at this number and accepted it. In a real study that '
      + 'is the difference between an assumption and an accident, and it is the first thing a reviewer '
      + 'will ask about.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Project defaults',
        note: 'The rate lives with the project defaults because it is a scenario-level assumption rather '
          + 'than a component attribute — one number applied to every capital cost in the model.',
      },
    ],
    entries: [
      {
        field: 'Settings → Project defaults → Discount rate',
        value: '0.05',
        why: 'The app default, kept so every figure here matches what you see out of the box. Five per '
          + 'cent is a plausible weighted average cost of capital for a regulated utility. It sets the '
          + 'capital recovery factor for every extendable asset, so it decides not only how much capital '
          + 'the model commits but which technologies it commits it to — step 13 measures exactly that.',
      },
    ],
    verify: [
      'Settings → Project defaults → Discount rate reads 0.05',
      'You can say which technologies a low rate favours, and why',
      'You can say what the GUI does about a missing rate and what the API does instead',
      'You can say why the setting did nothing in modules 1 to 6',
    ],
    pitfalls: [
      'Accepting the default without deciding it is right. It is still your assumption once you publish '
      + 'the answer, and it is the one most likely to be challenged.',
      'Confusing it with inflation or a project IRR. Here it is the rate at which capital is annuitised, '
      + 'and it should reflect the cost of capital of whoever is doing the building.',
    ],
  },

  {
    id: 'm7-lcoe',
    section: SECTION,
    title: 'Comparing technologies honestly — capacity factor beats headline cost',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'Before offering the model anything, work out what each option costs per unit of ENERGY. Cost per '
      + 'MW is what gets quoted and it is not what matters: a MW that runs 46% of the time is worth far '
      + 'more than a MW that runs 16% of the time.',

      'The levelised cost is the annuitised capital divided by the energy that capacity actually '
      + 'delivers: overnight × CRF / (capacity factor × 8760).',

      'On this year, at 5%: wind has a capacity factor of 0.46, so 1,200,000 × 0.0710 / (0.46 × 8760) is '
      + 'about 21 per MWh. Solar has a capacity factor of 0.165, so 500,000 × 0.0710 / (0.165 × 8760) is '
      + 'about 25 per MWh. Solar is less than half the price per MW and dearer per MWh, because it runs '
      + 'less than half as often.',

      'That is the arithmetic that makes energy debates confusing when only one of the two numbers is '
      + 'quoted. And it is still not sufficient — a levelised cost ignores WHEN the energy arrives and '
      + 'WHERE, and this module is about to show both mattering more than the 4 per MWh between these '
      + 'two.',
    ],
    explain: [
      'Nothing to enter. Work the two numbers out yourself before running anything, because the point of '
      + 'the exercise is to have a prediction the model can contradict.',

      'On levelised cost alone, wind wins: 21 against 25 per MWh. A study that ranked options by LCOE and '
      + 'stopped there would build wind and no solar.',

      'Hold that prediction. Step 9 builds both, and step 11 explains why — the wind is behind a '
      + 'congested line and the solar is not, and that difference is worth more than the 4 per MWh gap '
      + 'between them.',

      'For the storage and the line there is no meaningful levelised cost at all, because neither '
      + 'produces energy. They are valued entirely by what they let the rest of the system avoid, which '
      + 'is precisely why they cannot be assessed outside a model.',
    ],
    spotlights: [
      {
        selector: '[data-card="statistics"]',
        title: 'Capacity factors from the baseline run',
        tab: 'Analytics',
        note: 'The per-carrier statistics table reports what each technology actually delivered against '
          + 'its capacity. Those are the capacity factors the levelised arithmetic needs — take them from '
          + 'the run rather than from a brochure.',
      },
    ],
    verify: [
      'You can write down the levelised cost formula from memory',
      'You can compute roughly 21 per MWh for wind and 25 for solar at 5%',
      'You can say why cost per MW is a misleading way to rank generation',
      'You can say why a levelised cost cannot value a battery or a line at all',
      'You have a written prediction of what the model will build',
    ],
    pitfalls: [
      'Ranking technologies by levelised cost and stopping. It ignores when the energy arrives, where it '
      + 'arrives, and what else has to be built to use it — all three of which this module shows mattering.',
      'Using a brochure capacity factor. Use the one your own profiles produce, or the arithmetic '
      + 'describes a different site.',
    ],
  },

  {
    id: 'm7-extendable',
    section: SECTION,
    title: 'Make wind and the line decisions',
    tab: 'Build',
    where: 'Build → Generators, then Build → Lines',
    concept: [
      'Four attributes turn a fixed component into an investment question, and they work identically on '
      + 'generators, lines, links and storage.',

      '`p_nom_extendable` says the optimiser may choose the capacity. `p_nom_min` and `p_nom_max` bound '
      + 'the choice. `capital_cost` prices it. On a line the names are `s_nom_*`, because a line is rated '
      + 'in apparent power, and nothing else differs.',

      '`p_nom_min` is where brownfield modelling lives, and it is the most consequential of the four. Set '
      + 'it to what already exists and the model may add but never remove — correct, because a standing '
      + 'asset is a sunk cost and demolishing it saves nothing. Set it to zero and you ask a greenfield '
      + 'question: what would you build if nothing were here?',

      'Those are different studies with different answers, and confusing them is common. Step 12 runs '
      + 'both and finds something the brownfield version cannot show.',
    ],
    explain: [
      'Build → Generators, on wind_1: tick `p_nom_extendable`, set `p_nom_min` to 60 — what already '
      + 'stands — `p_nom_max` to 300, `capital_cost` to 1200000 and `lifetime` to 25.',

      'Then Build → Lines, on line_1: tick `s_nom_extendable`, `s_nom_min` 60, `s_nom_max` 300, '
      + '`capital_cost` 600000, `lifetime` 40.',

      'The maxima are siting limits, not modelling conveniences. 300 MW of wind is what the site could '
      + 'physically host; 300 MW is what the transmission corridor could carry given its right of way. An '
      + 'unbounded model will build implausible quantities of whatever is cheapest, and a reviewer will '
      + 'ask where the limit came from.',

      'Do not run yet. Two more options to offer first, and the interesting result is what happens when '
      + 'all four compete at once rather than in sequence.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'wind_1 becomes a decision',
        tab: 'Build',
        note: 'Five cells on one row. Everything else in the fleet stays fixed, so whatever the model does '
          + 'with wind is attributable to this change alone.',
      },
      {
        selector: '[data-build-step="lines"]',
        buildStep: 'lines',
        title: 'And the line',
        tab: 'Build',
        note: 's_nom_extendable rather than p_nom_extendable — a line is rated in apparent power. The '
          + 'meaning of all five attributes is identical.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom_extendable (wind_1)',
        label: 'capacity is a decision',
        value: 'true',
        why: 'Turns p_nom from a number you typed into a variable the optimiser chooses. This single '
          + 'checkbox is the difference between a dispatch model and an expansion model.',
      },
      {
        field: 'generators.p_nom_min (wind_1)',
        label: 'what already stands',
        value: '60',
        unit: 'MW',
        why: 'The existing farm. A floor here makes this a brownfield study — build more if it pays, but '
          + 'never pretend you could unbuild what is there. Step 12 sets it to zero and the difference is '
          + 'the whole point of that step.',
      },
      {
        field: 'generators.p_nom_max (wind_1)',
        label: 'siting limit',
        value: '300',
        unit: 'MW',
        why: 'What the site could physically host — land, connection capacity, consent. Not a modelling '
          + 'convenience: an unbounded maximum invites the model to solve everything with one technology, '
          + 'and the limit is part of describing the world honestly.',
      },
      {
        field: 'generators.capital_cost (wind_1)',
        label: 'overnight cost',
        value: '1200000',
        unit: 'currency per MW',
        why: 'The overnight cost exactly as a database quotes it, with no scaling — which is only correct '
          + 'because the model covers a whole year. Ragnarok applies CRF(5%, 25 y) itself, giving about '
          + '85,150 per MW per year in the objective.',
      },
      {
        field: 'generators.lifetime (wind_1)',
        label: 'economic life',
        value: '25',
        unit: 'years',
        why: 'How long the capital is repaid over, which sets the annuity factor. Blank would mean 20 '
          + 'years and a 15% higher annual charge, applied without telling you.',
      },
      {
        field: 'lines.s_nom_extendable (line_1)',
        label: 'the wire is a decision too',
        value: 'true',
        why: 'The transmission business case module 3 sketched and module 6 could not price properly. '
          + 'Offering it alongside generation rather than separately is what lets the model see that they '
          + 'are complements.',
      },
      {
        field: 'lines.s_nom_min (line_1)',
        label: 'existing circuit',
        value: '60',
        unit: 'MW',
        why: 'The wire already strung. Brownfield for the same reason as the wind farm: taking a line down '
          + 'does not refund what it cost to build.',
      },
      {
        field: 'lines.s_nom_max (line_1)',
        label: 'corridor limit',
        value: '300',
        unit: 'MW',
        why: 'What the route could carry — right of way, tower design, consent. Without it the model will '
          + 'happily solve congestion with unlimited wire.',
      },
      {
        field: 'lines.capital_cost (line_1)',
        label: 'overnight cost',
        value: '600000',
        unit: 'currency per MW',
        why: 'Half the wind figure per MW, and cheaper still per year because it is repaid over 40 years '
          + 'rather than 25 — CRF 0.058 against 0.071. Long asset life is a real and underrated advantage '
          + 'of network investment.',
      },
      {
        field: 'lines.lifetime (line_1)',
        label: 'economic life',
        value: '40',
        unit: 'years',
        why: 'Transmission outlives generation by a wide margin. The 20-year default would overstate its '
          + 'annual cost by about a quarter and could flip the decision.',
      },
    ],
    verify: [
      'wind_1 has p_nom_extendable ticked, min 60, max 300, capital_cost 1200000, lifetime 25',
      'line_1 has s_nom_extendable ticked, min 60, max 300, capital_cost 600000, lifetime 40',
      'No capital cost has been scaled by anything',
      'You can say what p_nom_min would mean if it were 0',
    ],
    pitfalls: [
      'Scaling the capital costs. That was a workaround for a short horizon and it is wrong here — a full '
      + 'year needs the raw overnight figure.',
      'Leaving p_nom_min at 0 by accident. The model may then choose LESS wind than exists, which is not '
      + 'a decision anyone can act on.',
    ],
  },

  {
    id: 'm7-solar',
    section: SECTION,
    title: 'Offer solar — at the demand end',
    tab: 'Build',
    where: 'Build → Generators step',
    concept: [
      'The solar site is already in the sheet with a capacity of zero and a full-year profile. Making it '
      + 'extendable turns it from a placeholder into a real option.',

      'Two things make it interesting rather than a fifth variable. Its capacity factor is 0.165 against '
      + 'wind\'s 0.46, so on levelised cost it loses — 25 per MWh against 21. And it sits at bus_2, the '
      + 'demand end, so unlike the wind it is not behind the congested line.',

      'Its output shape is also completely different. Solar produces nothing at night and peaks at '
      + 'midday, with a strong summer maximum; the wind on this year is windiest in winter and at night. '
      + 'Two zero-carbon, zero-marginal-cost technologies whose output barely overlaps.',

      'That combination — worse on paper, better placed, differently shaped — is exactly the situation a '
      + 'model is for. No amount of comparing levelised costs will tell you what to do with it.',
    ],
    explain: [
      'Build → Generators, on solar_1. Tick `p_nom_extendable`, set `p_nom_min` to 0, `p_nom_max` to 400, '
      + '`capital_cost` to 500000 and `lifetime` to 25.',

      'The minimum is 0 rather than 60 because nothing is built yet — this is a greenfield option inside '
      + 'an otherwise brownfield study, which is the normal situation. Brownfield and greenfield are '
      + 'properties of each ASSET, not of the study.',

      'The maximum of 400 MW is deliberately generous. Solar needs a lot of land per MW, and giving it '
      + 'plenty of headroom means whatever the model chooses is an economic answer rather than a '
      + 'constraint you imposed.',

      'Still do not run. One more option.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'A zero-capacity site becomes an option',
        tab: 'Build',
        note: 'solar_1 has had a profile and no capacity since you loaded the year. Ticking extendable is '
          + 'what turns "a site we could develop" into something the optimiser can choose.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom_extendable (solar_1)',
        label: 'capacity is a decision',
        value: 'true',
        why: 'Offers the site to the optimiser. Until now it has contributed nothing at all, because a '
          + 'generator with p_nom 0 produces nothing however good its profile.',
      },
      {
        field: 'generators.p_nom_min (solar_1)',
        label: 'nothing built yet',
        value: '0',
        unit: 'MW',
        why: 'Zero, because there is no existing array — this option is greenfield even though the study '
          + 'as a whole is brownfield. That combination is the normal case, and it is why brownfield is a '
          + 'property of each asset rather than of the run.',
      },
      {
        field: 'generators.p_nom_max (solar_1)',
        label: 'siting limit',
        value: '400',
        unit: 'MW',
        why: 'Generous on purpose. Solar needs roughly five times the land per MW that wind does, so a '
          + 'real limit would come from a land study — leaving headroom here means the answer is economics '
          + 'rather than a ceiling you chose.',
      },
      {
        field: 'generators.capital_cost (solar_1)',
        label: 'overnight cost',
        value: '500000',
        unit: 'currency per MW',
        why: 'Under half the wind cost per MW and still dearer per MWh, because the capacity factor is '
          + 'about a third. This one pair of numbers is the clearest illustration in the course of why '
          + 'cost per MW is the wrong comparison.',
      },
      {
        field: 'generators.lifetime (solar_1)',
        label: 'economic life',
        value: '25',
        unit: 'years',
        why: 'Same as wind, so the two are compared on equal financing terms and any difference in the '
          + 'answer is about resource and location rather than about the annuity.',
      },
    ],
    verify: [
      'solar_1 is extendable with min 0, max 400, capital_cost 500000, lifetime 25',
      'You can say why its minimum is 0 while wind\'s is 60',
      'You can say how its output shape differs from wind on this year',
      'Your prediction from step 5 still says wind wins on levelised cost',
    ],
    pitfalls: [
      'Giving solar a p_nom_min above 0. It would force capacity the model may not want and quietly '
      + 'guarantee the answer you were hoping to test.',
      'Assuming the lower cost per MW makes it the cheaper option. It is dearer per MWh, and step 5 has '
      + 'the arithmetic.',
    ],
  },

  {
    id: 'm7-battery',
    section: SECTION,
    title: 'Offer more battery',
    tab: 'Build',
    where: 'Build → Storage step',
    concept: [
      'Storage expands exactly like everything else, and the attributes sit on the storage unit rather '
      + 'than needing a new component.',

      'One subtlety worth knowing: `capital_cost` on a StorageUnit is per MW of POWER, while its energy '
      + 'capacity comes from `max_hours`. So a 2-hour battery at 150,000 per MW is really 75,000 per MWh, '
      + 'and doubling `max_hours` without changing the capital cost gives you twice the energy for '
      + 'nothing. That is a modelling error, not a bargain — a real longer-duration battery costs more '
      + 'per MW, and if you want to expand power and energy independently you need a Store and two Links, '
      + 'exactly as module 4 said.',

      'The battery is at bus_2, the demand end, where module 4 showed storage is worth roughly three '
      + 'times what it is worth behind the constraint. So this is storage in the best place the model '
      + 'offers, given every chance to prove itself.',

      'Watch what happens to it anyway.',
    ],
    explain: [
      'Build → Storage, on batt_1 in the `storage_units` sheet. Tick `p_nom_extendable`, set `p_nom_min` '
      + 'to 20 — what exists — `p_nom_max` to 300, `capital_cost` to 150000 and `lifetime` to 15.',

      'Leave `max_hours` at 2 and both efficiencies where they are. You are asking whether to build more '
      + 'of the same battery, not a different one.',

      'Fifteen years is right for lithium-ion and shorter than everything else here, which raises its '
      + 'annual charge: CRF(5%, 15 y) is 0.0963 against wind\'s 0.0710. Short-lived assets carry their '
      + 'capital heavily, and that is part of why storage has to be genuinely useful to be worth building.',

      'Now run it. About a minute.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="storage"]',
        buildStep: 'storage',
        title: 'The same four attributes again',
        tab: 'Build',
        note: 'p_nom_extendable, min, max, capital_cost — identical in meaning to the generator and line '
          + 'versions. Expansion is one mechanism applied uniformly, which is worth noticing.',
      },
      {
        selector: '[data-tour="companion-sheets"]',
        buildStep: 'storage',
        title: 'storage_units, not stores',
        tab: 'Build',
        note: 'The battery is a StorageUnit; the gas tank on the other sheet is a Store. Module 4 drew the '
          + 'distinction and module 5 used it — here you want the first one.',
      },
    ],
    entries: [
      {
        field: 'storage_units.p_nom_extendable (batt_1)',
        label: 'capacity is a decision',
        value: 'true',
        why: 'Offers more battery at the demand end — the best location the model has, by module 4\'s own '
          + 'measurement. If storage cannot justify itself here it cannot justify itself anywhere in this '
          + 'system.',
      },
      {
        field: 'storage_units.p_nom_min (batt_1)',
        label: 'what already stands',
        value: '20',
        unit: 'MW',
        why: 'The existing 20 MW battery, which the model may add to but not remove. Step 12 relaxes this '
          + 'to zero and finds something uncomfortable.',
      },
      {
        field: 'storage_units.p_nom_max (batt_1)',
        label: 'upper bound',
        value: '300',
        unit: 'MW',
        why: 'Generous — batteries need little land and siting is rarely the binding limit. As with solar, '
          + 'plenty of headroom means the answer is economics rather than a ceiling.',
      },
      {
        field: 'storage_units.capital_cost (batt_1)',
        label: 'overnight cost, per MW of power',
        value: '150000',
        unit: 'currency per MW',
        why: 'Per MW of POWER, with energy following from max_hours — so at 2 hours this is 75,000 per '
          + 'MWh. Raising max_hours without raising this cost would give free energy capacity, which is a '
          + 'modelling error rather than a cheap battery.',
      },
      {
        field: 'storage_units.lifetime (batt_1)',
        label: 'economic life',
        value: '15',
        unit: 'years',
        why: 'Shorter than everything else here, which matters: CRF(5%, 15 y) is 0.0963 against wind\'s '
          + '0.0710, so the same capital costs 36% more per year. Short-lived assets have to earn faster.',
      },
    ],
    verify: [
      'batt_1 is extendable with min 20, max 300, capital_cost 150000, lifetime 15',
      'max_hours is still 2 and the efficiencies are unchanged',
      'All four options — wind, solar, line, battery — are now extendable',
      'You can say why a 2-hour battery at 150,000 per MW is 75,000 per MWh',
    ],
    pitfalls: [
      'Raising max_hours to make the battery look better. Energy capacity would become free and the '
      + 'result meaningless.',
      'Using a 25-year lifetime for lithium-ion. It would understate the annual cost by a third and is '
      + 'not what the technology does.',
    ],
  },

  {
    id: 'm7-run',
    section: SECTION,
    title: 'Run: three of four, and 11.9 million saved',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'The objective falls from 29,980,642 to 18,115,684 — a saving of 11,864,958 a year, NET of the '
      + 'capital because the capital sits in the objective alongside the fuel. Decomposed: the fuel bill '
      + 'drops from 29,980,642 to 6,750,551, a saving of 23.2 million, bought with 11.4 million a year of '
      + 'new capital charges.',

      'Two different totals appear on screen and it is worth knowing which is which. The objective is '
      + 'fuel plus the annuity on what you BUILD, because capital already spent cannot be changed by a '
      + 'decision and so does not belong in a comparison between decisions. The KPI strip reports '
      + '25,611,302 instead — fuel plus the annuity on the ENTIRE fleet, existing assets included. That '
      + 'is the total cost of owning and running the system: the right number for a tariff, the wrong one '
      + 'for choosing what to build next.',

      'What got built: wind from 60 to 150.15 MW, solar from 0 to 24.12 MW, the line from 60 to 141.04 '
      + 'MW. What did not: the battery, which sits at 20 MW — its floor. Three of four.',

      'And the oil peaker stops running entirely. It burned 7.82 GWh in the baseline year and burns '
      + 'nothing now. Nobody retired it and nothing forbade it; enough cheap capacity arrived, in the '
      + 'right places, that it was never the cheapest way to serve an hour.',

      'The result that should surprise you is solar. Your step-5 arithmetic said it loses to wind on '
      + 'levelised cost — 25 per MWh against 21 — and the model built it anyway. Step 11 is why.',
    ],
    explain: [
      'Validate, then run. It takes about a minute; the planning summary should confirm 8,760 snapshots '
      + 'at 1h before you commit to the wait.',

      'Read the cost breakdown rather than only the headline. Fuel 6,750,551 and capital 18,860,751 sum '
      + 'to the 25,611,302 the KPI shows. Subtract the annuity on capacity that already existed and you '
      + 'are back to the 18,115,684 the solver minimised. Both are correct; they answer different '
      + 'questions, and confusing them is how a cost saving gets reported that nobody can find in a budget.',

      'Then find the built capacities — the expansion card reports each asset\'s starting capacity, its '
      + 'optimal capacity and the delta, which is the most direct answer to "what should we build" this '
      + 'course has produced.',

      'Check the oil unit too. Zero generation across 8,760 hours is a strong statement about the fleet, '
      + 'and it is the kind of result that only appears once capacity can move.',

      'Do not read the battery result as "storage is uneconomic". Read it as "more storage, at these '
      + 'costs, in a system that is about to gain 90 MW of wind and 24 MW of solar and a much bigger '
      + 'wire, is not the next thing to build". Those are very different claims and step 12 shows why the '
      + 'distinction matters.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Result"]',
        title: 'Two totals, both correct',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The KPI reports 25,611,302 — fuel plus the annuity on the whole fleet. The solver '
          + 'minimised 18,115,684 — fuel plus the annuity on what it BUILDS, because sunk capital cannot '
          + 'be changed by a decision. Know which one you are quoting.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'What to build',
        tab: 'Analytics',
        note: 'Starting capacity, optimal capacity and the delta for every extendable asset. Wind +90, '
          + 'solar +24, line +81, battery +0 — the most direct answer to the question this whole course '
          + 'has been building towards.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'And no oil',
        tab: 'Analytics',
        note: '7.82 GWh in the baseline year, zero now. A peaking unit that never runs across 8,760 hours '
          + 'is worth noticing — module 8 will ask whether it should still be kept.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'The new fleet',
        tab: 'Analytics',
        note: 'Per-carrier capacities and generation after expansion. Compare the renewable share against '
          + 'the baseline: nothing was mandated, and it moved a long way on cost alone.',
      },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Four capacity variables and 8,760 snapshots of dispatch. About a minute — the cost of an honest investment question.',
        'If the run is refused for a missing discount rate, step 4 is where that is set.',
      ],
      expect: 'An objective of 18,115,684, with wind at 150.15 MW, solar at 24.12, the line at 141.04, and the battery unchanged at 20.',
    },
    verify: [
      'The cost breakdown reads fuel 6,750,551 and capital 18,860,751',
      'You can say which total the solver minimised and why it differs from the KPI',
      'wind_1 is about 150 MW, solar_1 about 24, line_1 about 141, and batt_1 unchanged at 20',
      'oil_1 generates nothing across the whole year',
      'You can say why the 11.9m saving is net rather than gross',
      'You noticed that solar was built despite losing on levelised cost',
    ],
    pitfalls: [
      'Reading the battery result as a verdict on storage. It is a verdict on MORE storage, at these '
      + 'costs, in this system, next — which is a much narrower claim.',
      'Quoting 11.9m without its assumptions. It depends on the discount rate, the synthetic profiles, '
      + 'the siting limits and the fuel price, and step 14 is about saying so.',
    ],
  },

  {
    id: 'm7-why-solar',
    section: SECTION,
    title: 'Why solar beat its own levelised cost',
    tab: 'Analytics',
    where: 'Analytics → Result',
    concept: [
      'Solar costs about 25 per MWh on this year and wind about 21. The model built 90 MW of wind and '
      + '24 MW of solar. Both facts are true and the second is not a contradiction of the first.',

      'The first reason is location. The wind is at bus_1, behind a line that has been the binding '
      + 'constraint since module 3. Every extra MW of wind needs wire to be useful, and the model is '
      + 'paying for 81 MW of new wire alongside 90 MW of new wind. The solar is at bus_2, in front of the '
      + 'constraint, so its cost is its whole cost.',

      'The second is timing. Wind on this year is windiest in winter and at night; solar peaks at midday '
      + 'in summer. Adding wind to a system that already has wind produces more energy in hours that are '
      + 'already cheap — and increasingly, hours where it is curtailed. The first MW of a technology you '
      + 'do not yet have is worth more than the hundredth MW of one you do. That is diminishing marginal '
      + 'value, and no levelised cost can express it because LCOE prices a technology in isolation.',

      'This is the single most important limitation of levelised cost, and it is why capacity-expansion '
      + 'models exist at all. LCOE answers "what does a MWh from this technology cost". A system model '
      + 'answers "what is a MWh from this technology, in this place, at these hours, given everything '
      + 'else, actually worth". Only the second is a basis for a decision.',
    ],
    explain: [
      'Nothing to run. Read the answer you have.',

      'Look at the dispatch by carrier across the year, and at the curtailment chart. Wind curtailment '
      + 'rises with wind capacity — the model built up to the point where the next MW would be spilled '
      + 'too often to pay for itself, and stopped there.',

      'Then look at when solar generates against when wind does not. The two barely overlap, which is '
      + 'exactly why a system wants some of each rather than more of the cheaper one. Complementarity is '
      + 'worth real money and it is invisible to any per-technology cost comparison.',

      'The practical lesson: never rank generation options by levelised cost and build the top of the '
      + 'list. The right question is always marginal — what is the next MW worth, given what is already '
      + 'there — and the answer changes as you build.',
    ],
    spotlights: [
      {
        selector: '[data-card="chart"][data-card-metric="curtailment"]',
        title: 'Where wind stopped being worth it',
        tab: 'Analytics',
        note: 'Curtailment rises as wind capacity does. The model built up to the point where the next MW '
          + 'would be spilled often enough not to pay, then stopped — which is what diminishing marginal '
          + 'value looks like in a result.',
      },
      {
        selector: '[data-card="statistics"]',
        title: 'Two resources, barely overlapping',
        tab: 'Analytics',
        note: 'Compare the capacity factors and the generation by carrier. Solar delivers a third as much '
          + 'per MW as wind and delivers it in hours wind does not — which is worth more than the 4 per '
          + 'MWh between their levelised costs.',
      },
    ],
    verify: [
      'You can give two reasons solar was built despite a higher levelised cost',
      'You can explain diminishing marginal value in terms of curtailment',
      'You can say what LCOE prices and what it cannot',
      'You can say why the first MW of a new technology is worth more than the hundredth of an existing one',
    ],
    pitfalls: [
      'Concluding solar is better than wind. The model built four times as much wind — it built SOME '
      + 'solar because a mix is worth more than either alone.',
      'Using levelised cost to rank options in a system study. It is a useful screening number and it '
      + 'cannot see location, timing or what is already built.',
    ],
  },

  {
    id: 'm7-greenfield',
    section: SECTION,
    title: 'Greenfield — what brownfield was hiding',
    tab: 'Analytics',
    where: 'Build → the three minima, then run again',
    concept: [
      'Every floor you set in steps 6 to 8 said "this already exists and cannot be unbuilt". That is the '
      + 'right assumption for a decision about what to do NEXT. It is the wrong one for asking whether '
      + 'the system you have is the system you would choose.',

      'Set every minimum to zero and re-run and the answer barely moves — 18,045,470 against 18,115,684, '
      + 'and wind, solar and the line land within a MW of where they were. The existing wind farm and the '
      + 'existing wire are things a fresh build would have chosen anyway.',

      'The battery is not. It falls from 20 MW to 4.00 MW. A greenfield system would put in a fifth of '
      + 'the storage that actually stands there.',

      'That is a stranded asset, and no brownfield run could have shown it. With the floor at 20, "build '
      + 'no more" and "this is the right amount" produce exactly the same output — the model cannot '
      + 'distinguish an asset that is correctly sized from one that is oversized, because it is not '
      + 'allowed to consider removing it.',
    ],
    explain: [
      'Set three cells to zero: `p_nom_min` on wind_1, `s_nom_min` on line_1 and `p_nom_min` on batt_1. '
      + 'Solar is already 0. Then run — about a minute and a half, since the model has more freedom.',

      'Read the four capacities against the brownfield run. Three barely move; the battery collapses.',

      'Then be careful about what that means. It is NOT a recommendation to remove 16 MW of battery — the '
      + 'capital is spent and removing it recovers nothing, so the brownfield answer of "build no more" '
      + 'remains the right decision. What the greenfield run tells you is that the money spent on the '
      + 'last 16 MW is not earning, which is a lesson for the NEXT procurement rather than this one.',

      'Set the three minima back before you finish. The module ends brownfield, and the checkpoint '
      + 'assumes it.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Brownfield against greenfield',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Both runs are in History. Three capacities agree within a MW and one does not — and the one '
          + 'that does not is the finding.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The battery at 4 MW',
        tab: 'Analytics',
        note: 'A fifth of what stands. The existing 20 MW is not wrong to keep — the capital is sunk — but '
          + 'it is not what anyone would build today, and only the greenfield run can say so.',
      },
    ],
    entries: [
      {
        field: 'generators.p_nom_min (wind_1, greenfield)',
        label: 'pretend nothing is built',
        value: '0',
        unit: 'MW',
        why: 'Lets the model choose less wind than exists. It does not — it lands within a tenth of a MW '
          + 'of the brownfield answer, which is a strong signal that the existing farm is correctly sized.',
      },
      {
        field: 'lines.s_nom_min (line_1, greenfield)',
        label: 'pretend the wire is not there',
        value: '0',
        unit: 'MW',
        why: 'Same test for transmission, and the same result: 141.89 against 141.04. The corridor is '
          + 'about the right size for the system that is being built around it.',
      },
      {
        field: 'storage_units.p_nom_min (batt_1, greenfield)',
        label: 'pretend the battery is not there',
        value: '0',
        unit: 'MW',
        why: 'The one that moves. The model chooses 4.00 MW where 20 stands — so 16 MW of installed '
          + 'storage is not earning its keep, which the brownfield run reported identically to a battery '
          + 'that was exactly right.',
      },
      {
        field: 'the three minima (restore)',
        label: 'back to brownfield',
        value: '60, 60 and 20',
        why: 'Returns the study to the question that can actually be acted on — what to build next, given '
          + 'what exists. The greenfield run is a diagnostic, not a plan.',
      },
    ],
    verify: [
      'The greenfield objective is 18,045,470',
      'Wind, solar and the line land within about a MW of the brownfield answer',
      'The battery falls to 4.00 MW',
      'You can say why this is not a recommendation to remove any battery',
      'The three minima are back to 60, 60 and 20',
    ],
    pitfalls: [
      'Reading greenfield as a plan. Sunk capital is sunk; the actionable question is always brownfield, '
      + 'and greenfield is how you find out what your brownfield answer cannot tell you.',
      'Running only brownfield and concluding the fleet is well sized. "Build no more" and "correctly '
      + 'sized" are indistinguishable in a brownfield result.',
    ],
  },

  {
    id: 'm7-discount-sensitivity',
    section: SECTION,
    title: 'Two points on the discount rate changes what you build',
    tab: 'Analytics',
    where: 'Settings → Project defaults, then run again',
    concept: [
      'Everything physical is now settled — the technologies, their costs, their lifetimes, the demand, '
      + 'the network. One number is not a fact about any of them, and this step moves it from 0.05 to '
      + '0.07.',

      'The objective rises from 18,115,684 to 20,419,029, which is expected: capital is dearer, so the '
      + 'system costs more. What is not obvious is the mix. Wind falls from 150.15 to 120.17 MW — and '
      + 'solar RISES from 24.12 to 41.67.',

      'Less wind and more solar, from a change that made all capital more expensive. The reason is that '
      + 'wind on this system comes bundled with transmission: every extra MW behind the constraint needs '
      + 'wire to be useful, so raising the cost of capital raises the cost of wind-plus-wire more than it '
      + 'raises the cost of solar, which needs no wire at all.',

      'So the discount rate does not simply scale ambition down. It reweights the whole portfolio, and it '
      + 'does so through second-order effects that no per-technology cost comparison could predict. Two '
      + 'studies disagreeing about the future generation mix are, very often, disagreeing about nothing '
      + 'except this number.',
    ],
    explain: [
      'Settings → Project defaults → Discount rate. Change 0.05 to 0.07 and run.',

      'Read the four capacities and compare against the 5% run in Analytics → Comparison. Both are in '
      + 'History; do not do this from memory, because the interesting part is a 30 MW fall alongside a '
      + '17 MW rise and that is exactly the sort of thing memory smooths over.',

      'Then think about reporting. "The model builds 150 MW of wind and 24 of solar" and "the model '
      + 'builds 120 of wind and 42 of solar" are both true statements about this system, and which one '
      + 'you publish depends on a number you could defend either way. A result that moves this much '
      + 'inside a plausible range is a sensitivity, and presenting it as an answer is misleading even if '
      + 'every figure is correct.',

      'Set the rate back to 0.05 before finishing.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Comparison"]',
        title: '5% against 7%',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Wind down 30 MW, solar up 17 MW, from one number that describes financing rather than '
          + 'physics. Comparing the two runs properly is the point — this is not a difference memory '
          + 'reconstructs accurately.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The mix, reweighted',
        tab: 'Analytics',
        note: 'Not a uniform scaling down. Wind falls and solar rises, because wind on this system comes '
          + 'bundled with the transmission it needs and solar does not.',
      },
    ],
    entries: [
      {
        field: 'Settings → Project defaults → Discount rate (the experiment)',
        value: '0.07',
        why: 'Two points higher, well inside the range reasonable people choose. It raises the annual cost '
          + 'of all capital — and because wind here needs wire to be useful while solar does not, it '
          + 'raises the effective cost of wind by more, shifting 30 MW of the answer from one technology '
          + 'to another.',
      },
      {
        field: 'Settings → Project defaults → Discount rate (restore)',
        value: '0.05',
        why: 'Back to the app default and the state the checkpoint assumes. The discount rate is not '
          + 'stored in the model — it lives in your settings — so leaving it at 0.07 would silently change '
          + 'every figure in module 8.',
      },
    ],
    verify: [
      'At 7% the objective is 20,419,029',
      'Wind is 120.17 MW and solar is 41.67 MW',
      'You can explain why solar rose when all capital got more expensive',
      'You can say why this belongs in a report as a sensitivity rather than an answer',
      'The discount rate is back to 0.05',
    ],
    pitfalls: [
      'Choosing the rate that gives the answer you wanted. It is the easiest number in the model to '
      + 'justify either way, which is why it must be chosen and stated before the runs.',
      'Assuming a higher rate just means less of everything. It reweights the mix, and the reweighting is '
      + 'often the more important result.',
    ],
  },

  {
    id: 'm7-what-changed',
    section: SECTION,
    title: 'What module 7 settled, and what it cannot answer',
    tab: 'Analytics',
    where: 'Analytics, then Model → Export project',
    concept: [
      'Five things are now yours.',

      'Capacity can be a decision. Four attributes — extendable, min, max, capital cost, plus a lifetime '
      + '— turn any component into an investment question, and the same mechanism works identically on '
      + 'generators, lines, links and storage.',

      'Capital costs must be annuitised and matched to the modelled window. Ragnarok annuitises the '
      + 'overnight cost using the lifetime and the discount rate; matching the window is why this module '
      + 'needs a year, and getting it wrong produces a confident "build nothing" that is a unit error.',

      'Levelised cost is a screening tool, not a decision rule. Solar lost on LCOE and got built, because '
      + 'LCOE cannot see location, timing, or what is already there. The right question is always what '
      + 'the NEXT MW is worth given everything else.',

      'Brownfield answers what to do next; greenfield tells you what your brownfield answer is hiding. '
      + 'Running only the first would have reported a correctly-sized battery and a 16 MW stranded asset '
      + 'identically.',

      'And the discount rate reweights the portfolio rather than scaling it. Two points moved 30 MW from '
      + 'one technology to another, through a mechanism no per-technology comparison could predict.',
    ],
    explain: [
      'Three limits, and they are the remaining course.',

      'There is one investment period. Everything is built at once, at one set of prices, with one '
      + 'demand year. A real plan builds over decades against falling technology costs and rising demand, '
      + 'and PyPSA supports multi-period pathways that Ragnarok exposes — but the ideas need the time '
      + 'foundation module 6 laid and the policy layer module 8 adds.',

      'There is no policy. The carbon numbers you typed in modules 1 and 2 have sat unused for seven '
      + 'modules; the gas carrier carries 0.2 tCO2 per MWh and it has never once changed an answer. A '
      + 'carbon price would change every decision here — it raises the cost of the gas that new wind and '
      + 'solar displace, so it makes both worth more. Module 8 turns them on, and this is the model it '
      + 'turns them on for.',

      'And there is one future. One demand year, one weather year, one fuel price, one set of capital '
      + 'costs — and a single optimal answer that is optimal only for that combination. The honest '
      + 'version of everything in this module is a range, and module 9 is about producing one.',

      'Export the project before you go.',
    ],
    spotlights: [
      {
        selector: '[data-card="kpi-strip"]',
        title: 'Seven modules on',
        tab: 'Analytics',
        note: 'The fuel bill fell from 30.0m to 6.75m, bought with 11.4m a year of new capital — a net '
          + '11.9m saving for the same demand, with no policy and no mandate. Pure cost minimisation, '
          + 'given a better description of the system and the freedom to change it.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The answer, such as it is',
        tab: 'Analytics',
        note: '+90 MW wind, +24 solar, +81 line, +0 battery. Defensible as a direction and not as a plan '
          + '— one weather year, one demand year, one discount rate, synthetic profiles.',
      },
      {
        selector: '.topbar-file',
        title: 'Export before you leave',
        note: 'Model → Export project. Module 8 applies policy to this model, and it is the first one in '
          + 'the course whose answer anyone might act on.',
      },
    ],
    verify: [
      'You can name the attributes that make a component extendable, and say which one encodes brownfield',
      'You can say what Ragnarok does with `capital_cost` and what it leaves to you',
      'You can explain why levelised cost got solar wrong',
      'You can say what a greenfield run tells you that a brownfield run cannot',
      'You can list three assumptions this answer depends on that were never tested',
      'The model reads 18,115,684 at 5%, brownfield, and you have exported it',
    ],
    pitfalls: [
      'Quoting a capacity from this module as a recommendation. It is one scenario on synthetic profiles '
      + 'with one discount rate — a direction of travel, not a plan.',
      'Assuming more modelling would remove the uncertainty. It would not: the range in module 9 is the '
      + 'honest output, and a single number was never available.',
    ],
  },
];
