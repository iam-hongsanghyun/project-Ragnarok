/**
 * Module 9 — From result to decision (10 steps).
 *
 * The capstone, and the only module that adds no modelling capability at all.
 * Everything it uses has already been built: the scenario table, the comparison
 * view, History, and — more importantly — the sensitivities this course has
 * already run and then walked away from.
 *
 * That is the design. Every module since the second has ended by naming what it
 * could not say, and those endings were not throat-clearing: they are the
 * material. Module 6 found that a horizon choice moved the value of pumped hydro
 * by a factor of twenty-three. Module 7 found that two points on the discount
 * rate moved 30 MW between technologies. Module 8 found that the same 45% target
 * costs 3.46 or 66.67 per tonne depending on whether the model may build. None
 * of those is a caveat. Each is a finding, and a study that reports the central
 * case without them is not a shorter version of the truth — it is a different
 * claim.
 *
 * No new figures are introduced here and no new solves are needed. Every number
 * the module uses was verified in the module that produced it, which is itself
 * the point: a decision is assembled from runs you already have.
 */
import { TutorialStep } from '../types';

const SECTION = '9 · From result to decision';

export const MODULE_9_DECISION: TutorialStep[] = [
  {
    id: 'm9-not-a-decision',
    section: SECTION,
    title: 'A result is not a decision',
    tab: 'Analytics',
    where: 'Analytics → Result',
    startOptions: {
      prebuiltExampleId: 'training_m7',
      completeExampleId: 'training_m7',
      note:
        'Module 9 adds nothing to the model. It works with module 7\'s year and the runs already in your '
        + 'History from modules 6, 7 and 8 — so if you have been running as you go, you already have '
        + 'everything this module needs.',
    },
    concept: [
      'Module 7 produced a clean answer: build 90 MW of wind, 24 of solar and 81 of transmission, and '
      + 'save 11.9 million a year. It is correct, reproducible, and not a recommendation.',

      'A model answers a conditional question — what is cheapest GIVEN these assumptions. A decision '
      + 'has to survive the assumptions being wrong, and nothing in a single optimisation tells you '
      + 'whether it does. The optimum is the beginning of the analysis, not the end of it.',

      'This course has already shown how much room there is. The same system was worth building '
      + 'differently at 5% and at 7%. The same storage asset was worth 45 on one horizon and 1,026 on '
      + 'another. The same emissions target implied a carbon price of 3.46 or 66.67 depending on whether '
      + 'the model could invest. Every one of those is inside the range of choices a competent modeller '
      + 'might make without comment.',

      'So the deliverable is not the optimum. It is the optimum, the range around it, the assumptions '
      + 'that range is most sensitive to, and a clear statement of what the model could not see. That is '
      + 'more work than producing the number, and it is the part that makes the number usable.',
    ],
    explain: [
      'Nothing to run. Look at what you already have.',

      'Open History. If you have worked through modules 6 to 8 you should have a dozen or more runs: '
      + 'resolutions, discount rates, brownfield and greenfield, carbon prices and caps. Each was an '
      + 'experiment answering a question, and together they are the evidence base for a decision.',

      'That is the habit this module is really about. Runs are cheap and memory is not — every '
      + 'sensitivity you have run in this course is still there, with its settings, and can be compared '
      + 'against any other. A study assembled from stored runs is reproducible; one assembled from '
      + 'remembered numbers is not.',

      'If your History is thin because you have been reading rather than running, that is fine — the '
      + 'figures are all in the course text and the steps below work either way.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="History"]',
        title: 'Everything you have run',
        note: 'Every solve since module 1, with its configuration. This is the evidence base — and the '
          + 'reason to run experiments deliberately rather than overwriting one configuration repeatedly.',
      },
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The answer that is not a recommendation',
        tab: 'Analytics',
        note: '+90 MW wind, +24 solar, +81 line. Correct, reproducible, conditional on a dozen '
          + 'assumptions, and not yet something anyone should act on.',
      },
    ],
    verify: [
      'You can state the difference between a conditional answer and a decision',
      'You can name three findings from earlier modules that would change the module-7 answer',
      'Your History holds the runs from modules 6 to 8, or you know where the figures are',
      'You can say why stored runs beat remembered numbers',
    ],
    pitfalls: [
      'Treating the optimum as the finding. It is the input to the finding.',
      'Running experiments by editing one configuration repeatedly. The comparison is the analysis, and '
      + 'it needs the runs to still exist.',
    ],
  },

  {
    id: 'm9-scenarios',
    section: SECTION,
    title: 'Scenarios — running the experiment set deliberately',
    tab: 'Settings',
    where: 'Settings → Scenarios',
    concept: [
      'So far every sensitivity in this course has been run by hand: change a setting, run, note the '
      + 'number, change it back. That works for one or two and falls apart at a dozen — you lose track '
      + 'of what was set when, and a study nobody can reproduce is a study nobody should believe.',

      'A scenario is a saved run configuration: the carbon price, the discount rate, the window, the '
      + 'sampling, the constraints. Naming one records what you meant; the difference table then shows '
      + 'only the settings that actually differ between them, which is the fastest way to see whether '
      + 'the experiment you ran is the experiment you designed.',

      'And they can be run as a batch, in order, without supervision — which matters when each solve '
      + 'takes a minute and you have eight of them.',

      'The discipline worth taking from this: define the scenario set BEFORE running it. A set assembled '
      + 'afterwards from whichever runs happened to look interesting is not a sensitivity analysis, it '
      + 'is a selection effect.',
    ],
    explain: [
      'Settings → Scenarios. Whatever settings the app currently holds can be saved as a named scenario '
      + 'with "Add as Scenario" — from here or from the Run console.',

      'Build a small set that covers what this course has found to matter: a central case, a low and a '
      + 'high discount rate, and a carbon-price case. Four scenarios is enough to demonstrate the '
      + 'mechanism and enough to be a real sensitivity analysis on this model.',

      'Name them for what they ASSUME, not for what you expect them to show. "Central", "Discount 7%", '
      + '"Carbon 100" are good names; "High renewables" is a conclusion wearing a scenario\'s clothes, '
      + 'and it will bias how everyone reads the table.',

      'Then run them. The batch runner takes them in order; on this model expect roughly a minute each, '
      + 'so it is worth starting and doing something else.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'Scenarios',
        note: 'The scenario difference table and the batch runner. The table shows only the settings that '
          + 'differ between scenarios, which is how you check that an experiment varies what you intended '
          + 'and nothing else.',
      },
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Where they land',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Scenario runs go to History like any other and compare the same way. The value of naming '
          + 'them is that six months later you can still tell what each one assumed.',
      },
    ],
    verify: [
      'You have at least three named scenarios and can see the difference table',
      'Every scenario name describes an assumption rather than an expected outcome',
      'You can say why the scenario set should be defined before it is run',
      'You can find the batch runner',
    ],
    pitfalls: [
      'Naming scenarios for their conclusions. It frames every reader before they see a number.',
      'Assembling the set after the fact from runs that looked interesting. That is selection, not '
      + 'sensitivity.',
    ],
  },

  {
    id: 'm9-which-assumptions',
    section: SECTION,
    title: 'Which assumptions actually move the answer',
    tab: 'Analytics',
    where: 'Analytics → Comparison',
    concept: [
      'Not all assumptions matter equally, and the ones that matter are rarely the ones that get '
      + 'argued about. This course has measured several, and the ranking is worth collecting in one '
      + 'place.',

      'The discount rate moved 30 MW of wind into 17 MW of solar between 5% and 7% — a change of mix, '
      + 'not just of scale, from a number that describes financing rather than physics.',

      'The time horizon moved the value of the pumped-hydro scheme from 45 to 1,026 — a factor of '
      + 'twenty-three, from a choice that looks like a technical convenience.',

      'The resolution moved the objective by +25% at 6-hourly and −39% at 12-hourly, non-monotonically '
      + 'and with a sign change, from a setting most people treat as a speed dial.',

      'Whether the model may build moved the implied carbon price of a 45% cut from about 66.67 to 3.46 '
      + '— a factor of nineteen, from a modelling scope decision that is usually invisible in the '
      + 'write-up.',

      'Against those, the things people argue about — a fuel price a few per cent either way, a capital '
      + 'cost from one database rather than another — barely register. The largest uncertainties in an '
      + 'energy model are usually structural rather than parametric, and they are the hardest to see '
      + 'because they do not look like numbers.',
    ],
    explain: [
      'Nothing to run. Collect what you already have into a single table: assumption, range tested, '
      + 'effect on the answer.',

      'Rank it by effect. That ranking IS the sensitivity analysis, and it is the part a decision-maker '
      + 'needs most — it tells them which arguments are worth having.',

      'Then notice what is missing from your table. You have varied the discount rate, the horizon, the '
      + 'resolution and the policy. You have not varied the demand profile, the weather year, the fuel '
      + 'price, the capital costs, the siting limits or the technology efficiencies — and every one of '
      + 'those is uncertain too.',

      'A complete sensitivity analysis is not achievable and is not the goal. Knowing which of your '
      + 'untested assumptions could plausibly matter, and saying so, is.',
    ],
    spotlights: [
      {
        selector: '[data-subtab="Comparison"]',
        title: 'Reading effects side by side',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'The comparison view is where a ranking gets built. Two runs differing in one setting is '
          + 'the unit of evidence; the whole table is a set of those.',
      },
    ],
    verify: [
      'You can rank four assumptions this course tested by how much they moved the answer',
      'You can name four uncertain inputs the course never varied',
      'You can say why structural assumptions usually dominate parametric ones',
      'You can say what a sensitivity ranking is for',
    ],
    pitfalls: [
      'Testing only the assumptions that are easy to vary. Resolution and horizon are one keystroke; '
      + 'model scope is not, and it usually matters more.',
      'Presenting a sensitivity table as complete. It covers what you tested, and saying which untested '
      + 'assumptions could matter is part of the result.',
    ],
  },

  {
    id: 'm9-ranges',
    section: SECTION,
    title: 'Report a range, and say what it is a range over',
    tab: 'Analytics',
    where: 'Analytics → Comparison',
    concept: [
      'Once several scenarios exist, the honest headline is a range rather than a number. Module 7\'s '
      + 'wind build is not "90 MW" — it is "60 to 90 MW of new wind across the discount rates tested, '
      + 'rising to 143 MW under a 100 per tonne carbon price".',

      'That is longer, less quotable, and much more useful, because it tells a reader what would have to '
      + 'be true for each end to hold.',

      'A range needs its basis stated or it is worse than a point estimate. "60 to 143 MW" without the '
      + 'conditions attached invites the reader to treat it as a confidence interval, which it is not. '
      + 'It is not a probability distribution — nothing here has probabilities. It is the span of answers '
      + 'across a set of assumptions someone chose, and the choice of set is itself a judgement.',

      'The distinction matters because the two get conflated constantly. A statistical interval says '
      + '"the truth is probably in here". A scenario range says "if the world looks like one of these, '
      + 'the answer is one of these". The second makes no claim about likelihood at all.',
    ],
    explain: [
      'Write the headline for your scenario set. It should have three parts: the central answer, the '
      + 'range, and the conditions the range is over.',

      'Something like: "Across discount rates of 5 to 7% with no carbon price, the least-cost plan adds '
      + '60 to 90 MW of wind, 24 to 42 MW of solar and about 130 to 141 MW of transmission. A carbon '
      + 'price of 100 per tonne raises this to 143 MW of wind and 133 MW of solar and adds 62 MW of '
      + 'storage." Every figure in that sentence is one you have run.',

      'Then say what it is NOT. It is not a probability range, it assumes one weather year and one '
      + 'demand year, and it holds fuel prices, capital costs and siting limits fixed at single values.',

      'That paragraph — range, conditions, exclusions — is the deliverable. The optimum was one input to '
      + 'it.',
    ],
    spotlights: [
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'One end of the range',
        tab: 'Analytics',
        note: 'Whichever run is loaded shows one scenario\'s capacities. The range is the span across the '
          + 'set — no single view shows it, which is why the headline has to be written rather than read.',
      },
    ],
    verify: [
      'You have written a headline with a central case, a range and its conditions',
      'You can say why a scenario range is not a confidence interval',
      'You can name three things your range holds fixed',
      'Every figure in your headline comes from a run you can point to',
    ],
    pitfalls: [
      'Quoting a range without its basis. Readers will assume it is probabilistic, and it is not.',
      'Widening the range to seem cautious. A range is the span of the scenarios you ran; padding it is '
      + 'as misleading as narrowing it.',
    ],
  },

  {
    id: 'm9-provenance',
    section: SECTION,
    title: 'Every number back to a source',
    tab: 'Data',
    where: 'Data view, and the model sheets',
    concept: [
      'A result is only as defensible as the inputs behind it, and the first question a serious reviewer '
      + 'asks is where a number came from.',

      'Be uncomfortable about this model for a moment. The demand, wind, solar and run-of-river profiles '
      + 'are SYNTHETIC — shaped by hand to be structurally realistic and corresponding to no real place. '
      + 'The capital costs are plausible round figures rather than quotations. The fuel price is a round '
      + 'number. The siting limits were chosen to leave headroom rather than from any land study.',

      'None of that makes the course wrong: every mechanism it demonstrates is real, and the arithmetic '
      + 'is exact. But not one figure from this model should appear in a document about a real system, '
      + 'and the reason is provenance rather than accuracy.',

      'For a real study the standard is that every number traces to a source or to a numbered '
      + 'assumption. Ragnarok\'s Data view exists for the first half of that: importers for demand, '
      + 'weather, prices and networks, each recording where the data came from. The second half — '
      + 'writing down the assumptions that have no source — is yours.',
    ],
    explain: [
      'Open the Data view. It has gone unused for the entire course, and it is where a real version of '
      + 'this model would begin: hourly demand from ENTSO-E or EIA, weather-derived renewable profiles, '
      + 'fuel and carbon prices, network topology.',

      'Then go back through the model you have built and try to source each number. `p_nom` 50 for coal '
      + '— from where? The 0.34 emission factor — which database, which year, and is it per MWh of fuel '
      + 'on a gross or net basis? The 200 km line length?',

      'You will not be able to source most of them, because they were teaching values. Make the list '
      + 'anyway: the exercise of trying is what shows you how much of a model is assumption rather than '
      + 'data, and it is usually far more than people expect.',

      'The practical standard for a real study: a data register with one row per input — value, source, '
      + 'date, licence — and a numbered assumption list for everything else. Every figure in the report '
      + 'then points at a row or an assumption number.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Data"]',
        title: 'The view this course never used',
        note: 'Importers for demand, weather, prices and networks, each recording provenance. A real '
          + 'version of this model starts here rather than with hand-typed values — which is exactly why '
          + 'the course avoided it while teaching mechanisms.',
      },
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'Try to source these',
        tab: 'Build',
        note: 'Four emission factors typed in module 1. Which database, which year, gross or net '
          + 'calorific value? Most models carry numbers whose origin nobody can reconstruct.',
      },
    ],
    verify: [
      'You can name four inputs in this model that have no source',
      'You can say why synthetic profiles make the course valid and its figures unusable',
      'You can describe what a data register contains',
      'You have looked at the Data view and can name two things it imports',
    ],
    pitfalls: [
      'Assuming that because a model solves, its inputs are sound. The solver checks consistency, never '
      + 'provenance.',
      'Reporting a modelled figure without its assumption list. The figure will be quoted; the '
      + 'assumptions will not follow it unless they are attached.',
    ],
  },

  {
    id: 'm9-what-cannot-be-seen',
    section: SECTION,
    title: 'Collect what the model cannot see',
    tab: 'Analytics',
    where: 'Analytics',
    concept: [
      'Every module in this course ended by naming its own limits. Collected, they are a substantial '
      + 'document — and they belong in the deliverable rather than in a modeller\'s memory.',

      'No demand response. Every tonne abated in module 8 came from changing supply; nobody used less '
      + 'electricity, because no price elasticity exists anywhere in the model. Real carbon prices '
      + 'reduce demand.',

      'One weather year and one demand year, with perfect foresight. Module 6 showed how much a horizon '
      + 'choice can move an answer; a plan that looks robust against this year may fail in a still, cold '
      + 'one that this year does not contain.',

      'One sector. A carbon price applies economy-wide, and industry, heat and transport are all outside '
      + 'these three buses. Module 5 showed how a second sector is added; the boundary is always a '
      + 'choice, and it is always worth stating.',

      'One investment period, no lead times, no supply chains and no politics. The model builds 133 MW '
      + 'of solar instantly at a known price. Whether that can happen is not a question it is equipped '
      + 'to ask.',

      'And no reliability standard. Nothing in this course tested whether the system survives an outage, '
      + 'a still week, or a demand year 10% higher — and a plan that is cheapest on average can be the '
      + 'one that fails first.',
    ],
    explain: [
      'Write the list. Six or seven lines, each naming something the model cannot represent and what it '
      + 'would take to represent it.',

      'Then sort it into two groups: limits that could be removed with more modelling — demand response, '
      + 'more weather years, a reliability study, another sector — and limits that cannot, like politics, '
      + 'consenting risk and supply chains.',

      'The first group is a work plan. The second is a permanent caveat and belongs beside the headline '
      + 'rather than in an appendix.',

      'This is the least glamorous part of a study and the part most often skipped. It is also what '
      + 'distinguishes analysis from advocacy: an advocate reports what the model said, an analyst '
      + 'reports what it said and what it could not.',
    ],
    spotlights: [
      {
        selector: '.activity-bar',
        title: 'What the course never used',
        note: 'Physical Risk, Siting, Post-analysis and most of Data have gone untouched for nine '
          + 'modules. Each is a class of question this model has not asked — which is a useful, concrete '
          + 'way to see the boundary of what you have built.',
      },
    ],
    verify: [
      'You have a written list of at least six things this model cannot see',
      'You have sorted them into removable and permanent limits',
      'You can say which of them would change the module-7 answer most',
      'You can say why the removable list is a work plan',
    ],
    pitfalls: [
      'Burying the limits in an appendix. The permanent ones belong with the headline, because they '
      + 'qualify it.',
      'Treating the list as an admission of failure. Every model has one; the ones that do not publish '
      + 'it have one too.',
    ],
  },

  {
    id: 'm9-presenting',
    section: SECTION,
    title: 'Presenting to someone who did not build it',
    tab: 'Analytics',
    where: 'Analytics → Result',
    concept: [
      'The audience for a model result has not read the model, will not read it, and is right not to. '
      + 'They need to know what to do, how confident to be, and what would change the answer.',

      'Three things make a model result usable by someone who did not build it. First, the recommendation '
      + 'and its range up front, with conditions attached. Second, the two or three assumptions that '
      + 'drive the range, named in plain language — "how expensive capital is" beats "the discount rate". '
      + 'Third, what the model could not see.',

      'What does NOT help: the objective value, the solver, the number of snapshots, or the structure of '
      + 'the optimisation. Those establish credibility with other modellers and are noise to everyone '
      + 'else. They belong in an annex, and they should exist — but not first.',

      'One discipline in particular. Do not present a single number with a decimal point unless you '
      + 'would defend the decimal. Module 7\'s answer is "about 90 MW of wind", not "90.15 MW". Spurious '
      + 'precision is the fastest way to lose a technical audience and the fastest way to mislead a '
      + 'non-technical one.',
    ],
    explain: [
      'Write the summary. Half a page, in this order: what to do, the range, what would change it, what '
      + 'the model could not see.',

      'Test it by removing every piece of modelling vocabulary. If the summary still says something, it '
      + 'is a summary; if it collapses, it was a description of a model rather than a finding.',

      'Then prepare the annex — the objective, the settings, the scenario table, the data register, the '
      + 'assumption list. The purpose of the annex is that someone could reproduce you, and that is not '
      + 'the same audience or the same document.',

      'Ragnarok\'s Post-analysis view is worth knowing about here: it holds workflows that turn a solved '
      + 'model into financial questions — NPV, payback, ownership, PPA valuation — which is the language '
      + 'most decisions are actually made in. This course has not used it, and for a study that ends in '
      + 'an investment decision it is where the last mile happens.',
    ],
    spotlights: [
      {
        selector: '.activity-bar-btn[aria-label="Post-analysis"]',
        title: 'The last mile',
        note: 'Decisions framed as money questions — NPV, payback, ownership, PPA valuation — computed '
          + 'from a solved model without re-solving. Unused by this course, and where a study aimed at an '
          + 'investment committee would finish.',
      },
      {
        selector: '[data-card="kpi-strip"]',
        title: 'What not to lead with',
        tab: 'Analytics',
        note: 'The objective is the number a modeller checks first and the one an audience needs least. '
          + 'It belongs in the annex — present the decision, not the optimisation.',
      },
    ],
    verify: [
      'You have a half-page summary that survives having the jargon removed',
      'It leads with a recommendation and a range rather than an objective value',
      'You can name the two assumptions that drive your range in plain language',
      'You have a separate annex that would let someone reproduce the work',
    ],
    pitfalls: [
      'Leading with the model. The audience needs the decision; the model is how you got there.',
      'Quoting 90.15 MW. Present the precision you would defend, which on this model is "about 90".',
    ],
  },

  {
    id: 'm9-reproducible',
    section: SECTION,
    title: 'Could someone else get your number?',
    tab: 'Model',
    where: 'Model → Export project',
    concept: [
      'The test of a study is not whether it is right — nobody can check that — but whether someone else '
      + 'starting from your inputs would get your answer. Everything else rests on that.',

      'For this model, reproducibility needs four things: the workbook, the run settings, the software '
      + 'version, and the assumption list. Three of them the app can give you.',

      'The workbook exports as a file that round-trips exactly. The run settings live in scenarios, '
      + 'which are saved with the project. The version is in the app. The assumption list is the one that '
      + 'has to be written, and it is the one that goes missing.',

      'A study that cannot be reproduced is not a weaker study — it is a claim rather than an analysis. '
      + 'That distinction is worth being strict about, because the failure is silent: nobody discovers a '
      + 'result is irreproducible until they try, which is usually after it has been acted on.',
    ],
    explain: [
      'Export the project — Model → Export project — and put it somewhere that will still exist when '
      + 'someone asks. Alongside it: the scenario definitions, the assumption list, and a note of the '
      + 'app version.',

      'Then apply the real test. Could someone take that bundle and get your numbers without asking you '
      + 'a single question? Where the answer is no, that gap is what your documentation is missing.',

      'Two gaps are almost always the same ones. First, settings that live outside the workbook — the '
      + 'discount rate is in Project defaults and the carbon price in Market & Policy, and neither is in '
      + 'the exported model. Second, the sequence: which runs were done in which order and which one the '
      + 'headline came from.',

      'Both are solved by writing them down. Neither is solved by remembering.',
    ],
    spotlights: [
      {
        selector: '.topbar-file',
        title: 'Export the model',
        note: 'Model → Export project writes the whole workbook to a file that round-trips exactly. It is '
          + 'the reproducible core — but not the whole of it, because several settings live outside the '
          + 'workbook.',
      },
      {
        selector: '.activity-bar-btn[aria-label="Settings"]',
        title: 'The settings that travel separately',
        note: 'The discount rate is in Project defaults; the carbon price and constraints are in Market & '
          + 'Policy. None of them is in the exported workbook, which is the commonest reproducibility gap '
          + 'in this tool.',
      },
    ],
    verify: [
      'You have exported the project and know where the file is',
      'You can name two settings that are NOT in the exported workbook',
      'You have written down which run the headline figure came from',
      'You can say why irreproducibility is a silent failure',
    ],
    pitfalls: [
      'Exporting the model and assuming that is the study. The settings outside it change every number.',
      'Relying on History for the record. It is a session artefact, not a deliverable.',
    ],
  },

  {
    id: 'm9-the-decision',
    section: SECTION,
    title: 'Making the call',
    tab: 'Analytics',
    where: 'Analytics',
    concept: [
      'At some point the analysis stops and a decision gets made, and the model does not make it. Three '
      + 'things it cannot supply are usually what the decision turns on.',

      'Risk appetite. The least-cost plan is not the least-risky plan. Module 7 built 90 MW of wind '
      + 'behind a constraint and 81 MW of wire to reach it; a decision-maker who doubts the wire will get '
      + 'consented may prefer the more expensive plan that does not depend on it. The model has no view '
      + 'on that and cannot be given one.',

      'Distribution. Module 8 showed a carbon price moving far more money in transfers than in resource '
      + 'costs. Who pays and who gains is usually what an argument is actually about, and it is outside '
      + 'the objective function by construction.',

      'Reversibility. A model treats a 25-year wind farm and a 15-year battery as comparable annuities. '
      + 'A decision-maker facing genuine uncertainty may rationally prefer the shorter-lived, more '
      + 'expensive option because it can be changed — and least-cost optimisation cannot express that '
      + 'preference at all.',

      'The right posture is neither deference nor dismissal. The model tells you what is physically '
      + 'consistent and what things cost in resources, which is a great deal and is not everything. '
      + 'Someone still has to decide.',
    ],
    explain: [
      'Nothing to run. Take your headline and ask the three questions.',

      'What in this plan is hard to reverse, and what would it cost to be wrong about it? On this model, '
      + 'the transmission is the least reversible thing in the answer and the largest single commitment.',

      'Who pays for it and who benefits? The model says the system saves 11.9 million a year. It has no '
      + 'opinion about whether that reaches consumers, generators or a network owner.',

      'And what would have to be true for this to be the wrong plan? If you cannot answer that, you have '
      + 'not stress-tested the recommendation — you have described the optimum in more words.',

      'That last question is the most useful one in this course. A recommendation you can argue against '
      + 'is one you understand.',
    ],
    spotlights: [
      {
        selector: '[data-card="capacity-expansion"]',
        title: 'The commitment',
        tab: 'Analytics',
        note: '81 MW of new transmission is the least reversible thing in this plan and among the '
          + 'longest-lived. Least-cost optimisation weighs it as an annuity; a decision-maker weighs it as '
          + 'a commitment, and those are different judgements.',
      },
    ],
    verify: [
      'You can name the least reversible element of your plan',
      'You can say who bears the cost and who receives the benefit, or that the model cannot say',
      'You can state what would have to be true for your recommendation to be wrong',
      'You can say what a model is authoritative about and what it is not',
    ],
    pitfalls: [
      'Deferring to the model because it is quantitative. It optimises what it was given and is silent '
      + 'on everything else.',
      'Dismissing it because it is simplified. It is the only thing in the room that checks physical and '
      + 'economic consistency, and that is not a small contribution.',
    ],
  },

  {
    id: 'm9-what-changed',
    section: SECTION,
    title: 'What you can do now',
    tab: 'Analytics',
    where: 'Analytics, then wherever your own work is',
    concept: [
      'Nine modules from an empty sheet. What you can do now, and it is worth naming precisely:',

      'Build a power-system model from nothing — carriers, buses, generators, loads, a time axis, a '
      + 'network, storage, a second energy carrier — and know what every attribute on every component '
      + 'means and what it changes.',

      'Read an answer properly: dispatch, prices, congestion, curtailment, state of charge, shadow '
      + 'prices, and the difference between a price and an average cost.',

      'Choose a time representation and defend it, having seen a horizon move a valuation by twenty-'
      + 'three times and a resolution move an objective by a quarter.',

      'Turn a dispatch model into an investment model on a defensible cost basis, and know why levelised '
      + 'cost is a screening tool rather than a decision rule.',

      'Apply carbon policy as either a price or a limit, knowing they are duals, and read a shadow price '
      + 'as the implied price of a target.',

      'And produce a range with its conditions, a sensitivity ranking, a provenance trail and a '
      + 'statement of limits — which is the difference between a model output and a piece of analysis.',
    ],
    explain: [
      'Where to go next, in the order that usually works.',

      'Build something real. Take a system you know — a country, a region, a company\'s portfolio — and '
      + 'model it badly, then improve it. The Data view\'s importers exist for exactly this, and the '
      + 'first version being wrong is not a problem: every module of this course was a wrong model made '
      + 'less wrong.',

      'Then the parts this course did not reach. Multi-period pathways, where capacity is built over '
      + 'decades rather than at once. Unit commitment, where plants have start-up costs and minimum run '
      + 'times. Stochastic runs across weather years. Security-constrained dispatch and N-1. Every one is '
      + 'a settings section you have walked past, and every one is a proper study on its own.',

      'And one habit above the rest. Whenever a model gives you an answer, ask what assumption it is '
      + 'most sensitive to and go and test that. It is the fastest way to learn a system, and it is what '
      + 'separates people who run models from people who understand them.',
    ],
    spotlights: [
      {
        selector: '.activity-bar',
        title: 'What is left',
        note: 'Physical Risk, Siting, Post-analysis, and most of Settings\' study modes. Nine modules in, '
          + 'each of those is now a section you could read and use rather than a mystery.',
      },
      {
        selector: '.activity-bar-btn[aria-label="Data"]',
        title: 'Where a real model starts',
        note: 'Importers for demand, weather, networks and prices. This course typed everything by hand '
          + 'to teach what the numbers mean; your next model should not.',
      },
    ],
    verify: [
      'You can list what you are now able to do without looking at this page',
      'You have chosen a real system to model next',
      'You can name three capabilities this course did not cover',
      'You can state the habit worth keeping from all nine modules',
    ],
    pitfalls: [
      'Waiting until you can build it properly. Every model in this course was wrong and useful; the '
      + 'first version of yours will be too.',
      'Treating the course model as a template. It was built to teach mechanisms one at a time, and a '
      + 'real study starts from data rather than from this.',
    ],
  },
];
