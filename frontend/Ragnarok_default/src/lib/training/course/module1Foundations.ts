/**
 * Module 1 — Foundations (steps 1–6).
 *
 * Starts from nothing: no power-systems background, no optimisation background,
 * no model loaded. Ends with an empty project open and one full
 * change → validate → run → read loop behind the learner.
 *
 * The only module with no checkpoint to load — it starts from an empty
 * workbook, because watching the first model appear one sheet at a time is most
 * of the lesson.
 */
import { TutorialStep } from '../types';

const SECTION = '1 · Foundations';

export const MODULE_1_FOUNDATIONS: TutorialStep[] = [
  {
    id: 'm1-what-is-a-model',
    section: SECTION,
    title: 'What a power-system model is',
    tab: 'Welcome',
    where: 'Welcome view',
    concept: [
      'The grid stores almost nothing. What is consumed now is generated now — across the whole '
      + 'network, at every instant. Miss the balance and frequency drifts, protection trips, and the '
      + 'failure can cascade. So someone must decide continuously which plants run and how hard.',

      'Many combinations balance the system. They differ hugely in cost and emissions. Choosing among '
      + 'them is an optimisation problem, and every optimisation problem has three parts: decision '
      + 'variables (what the model may choose — output per plant per hour, later capacity to build), '
      + 'an objective (the one number it minimises — total system cost), and constraints (what must '
      + 'hold — supply equals demand everywhere every hour, no plant over its capacity, no line over '
      + 'its rating).',

      'The answer is the cheapest way to satisfy every constraint. Not a forecast — a conditional '
      + 'answer, true if the world matches your assumptions. The rest of this course is making those '
      + 'assumptions explicit and testing how much the answer leans on them.',

      'One idea to carry throughout: constraints have prices. The extra cost of tightening a '
      + 'constraint by one unit is its shadow price. Electricity price is not an input here — it is '
      + 'the shadow price of the supply-equals-demand constraint, the cost of serving one more MWh at '
      + 'that place and time.',
    ],
    explain: [
      'Ragnarok is a browser front end for PyPSA. You edit the model as spreadsheet-like tables; the '
      + 'backend builds them into a PyPSA network, hands it to a solver, and returns the answer as '
      + 'charts and tables. No code, and nothing hidden — every number the solver sees is one you can '
      + 'see.',

      'Three fixed pieces of chrome. Top bar: the wordmark (click to return here), Run, Clear, Clear '
      + 'cache — and on the right, the filename and a status line. Watch that status line; most '
      + 'failures announce themselves there first.',

      'Far left is the activity bar — the only way to switch views. Hover an icon for its name and '
      + 'hint. The order is roughly the order of work: Data and Build make a model, Model and Forge '
      + 'refine it, Market & Policy and Settings decide how it solves, Analytics reads the result.',

      'Every one of the next 47 steps is the same loop: change the model, validate, run, read. The '
      + 'loop is the skill; the individual settings are details you look up.',
    ],
    spotlights: [
      {
        selector: '.topbar-brand',
        title: 'The wordmark',
        note: 'Click it from anywhere to come back to the Welcome page. Handy when you get lost.',
      },
      {
        selector: '.run-button',
        title: 'Run',
        note: 'Opens the Run dialog — where you validate or solve. Every run is queued and executes one '
          + 'at a time. Do not press it yet; there is nothing loaded to solve.',
      },
      {
        selector: '.topbar-file',
        title: 'Current filename',
        note: 'Which project is loaded. It says "untitled.xlsx" until you open or build something.',
      },
      {
        selector: '.topbar-status',
        title: 'Status line',
        note: 'The most useful thing on screen while you learn. It reports what the app just did, and '
          + 'almost every failure shows up here first. Get into the habit of glancing at it after every action.',
      },
      {
        selector: '.activity-bar',
        title: 'Activity bar',
        note: 'The only way to switch views. Hover any icon for its name and hint. Top to bottom it runs '
          + 'roughly in the order of work: make a model, refine it, decide how it solves, read the result.',
      },
      {
        selector: '.activity-bar-btn[aria-label="Build"]',
        title: 'Build — where you will start',
        note: 'Hover it now and read the tooltip. In step 4 you will open this view and author your first '
          + 'model here, one sheet at a time.',
      },
      {
        selector: '.activity-bar-btn[aria-label="Analytics"]',
        title: 'Analytics — where answers land',
        note: 'Every result you produce in this course appears here. Notice it can carry a badge: a ✓ when '
          + 'the model validates, or a count of errors and warnings when it does not.',
      },
    ],
    verify: [
      'You can name the three parts of an optimisation model without looking back',
      'You can say in one sentence why electricity must be balanced instant by instant',
      'You have run the walkthrough above and can point to the status line and the activity bar unprompted',
    ],
    pitfalls: [
      'A connection or backend error in the status line stops everything downstream — Ragnarok is a '
      + 'browser front end plus a Python backend, and the backend does the modelling. Check the '
      + 'terminal that launched it before going on.',
      'Treating the output as a forecast. It is least cost given your assumptions; two people with '
      + 'different assumptions get different answers and both can be right.',
    ],
  },

  {
    id: 'm1-object-model',
    section: SECTION,
    title: 'What a network is made of',
    tab: 'Build',
    where: 'Build → step strip',
    concept: [
      'A bus is a node — a point where power balances. Not a piece of equipment; a place. Everything '
      + 'else attaches to one.',

      'A generator injects power at its bus. A load withdraws power at its bus. A line carries power '
      + 'between two buses. A carrier is the kind of energy involved (electricity, gas, wind) and is '
      + 'where the emission factor lives.',

      'The whole model is those five nouns plus a time axis. Everything later in this course — '
      + 'storage, policy, investment — is an attribute on one of them or a constraint over them.',

      'Components refer to each other by name, as plain text. A generator says which bus it sits on '
      + 'by writing that bus\'s name. Get the name wrong and the generator is silently disconnected: '
      + 'the model may still solve, just without it. This is why things must be defined in dependency '
      + 'order — carriers and buses before the components that point at them.',
    ],
    explain: [
      'Ragnarok holds each component type as a sheet. Column headers are PyPSA attribute names '
      + '(`p_nom`, `marginal_cost`, `bus0`); the `name` column is the key other sheets point at.',

      'The Build view walks those sheets in dependency order — Network, Snapshots, Carriers, Buses, '
      + 'Generators, Loads, Storage, Lines, Links, Processes, Constraints, Review. Follow the strip '
      + 'left to right and a dangling reference is impossible by construction.',

      'Build and Model edit the same workbook — no draft copy. Build is the guided path; Model shows '
      + 'every sheet at once. Switch freely.',
    ],
    spotlights: [
      {
        selector: '.build-step-strip',
        title: 'The step strip',
        tab: 'Build',
        note: 'Twelve steps in dependency order. Each carries a tick when it has enough data, or a count '
          + 'when it has problems.',
      },
      {
        selector: '[data-build-step="carriers"]',
        title: 'Carriers — first of the five nouns',
        tab: 'Build',
        note: 'Click it. The panel below scopes to the `carriers` sheet. Carriers come before buses because '
          + 'buses point at them by name.',
      },
      {
        selector: '[data-build-step="buses"]',
        title: 'Buses — the nodes',
        tab: 'Build',
        note: 'Click it and look at the map in the middle. Buses are the only component with a position; '
          + 'everything else inherits its location from the bus it attaches to.',
      },
      {
        selector: '[data-build-step="generators"]',
        title: 'Generators — injection',
        tab: 'Build',
        note: 'Click it. Note the `bus` column in the table: that text must match a bus name exactly. This '
          + 'is the reference-by-name mechanic, and the single commonest source of a broken model.',
      },
      {
        selector: '[data-build-step="loads"]',
        title: 'Loads — withdrawal',
        tab: 'Build',
        note: 'Same shape as generators, opposite sign. `p_set` is the demand in MW.',
      },
      {
        selector: '.build-step-guide',
        title: 'The step guide',
        tab: 'Build',
        note: 'One line describing whatever step is selected. Cheap orientation whenever you lose the thread.',
      },
    ],
    verify: [
      'You can say what a bus is without using the word "bus"',
      'You can say how a generator declares which bus it sits on',
      'You can say why carriers come before buses in the strip',
    ],
    pitfalls: [
      'A reference typo does not raise an error — it silently detaches the component. Analytics → '
      + 'Validation and the Review step both catch it; nothing else will.',
    ],
  },

  {
    id: 'm1-snapshots',
    section: SECTION,
    title: 'Snapshots — the time axis',
    tab: 'Build',
    where: 'Build → Snapshots step',
    concept: [
      'The model does not solve continuous time. It solves a finite list of moments called snapshots, '
      + 'and inside each one everything is constant. Balance is enforced once per snapshot.',

      'Every time-varying quantity is indexed by that same list — a wind availability profile, a demand '
      + 'curve. One axis, shared by everything. That is why the axis must exist before any profile can '
      + 'be written.',

      'Two decisions sit here. Horizon: how much time you cover — a day, a week, a year. Resolution: '
      + 'how finely you cut it — hourly, or coarser. A full year at hourly resolution is 8760 snapshots, '
      + 'and snapshot count drives solve time far harder than component count does.',

      'Each snapshot can also carry a weight: how many real hours it stands for. Twelve snapshots '
      + 'weighted 730 hours each represent a year in monthly blocks. Weighting is how a small model can '
      + 'still produce annual totals — and getting it wrong silently rescales every cost in the answer.',
    ],
    explain: [
      'The `snapshots` sheet has one column, `snapshot`, and one row per time step. You do not type '
      + 'those rows. The Snapshots step has a builder on the right: give it a start, a resolution and a '
      + 'horizon, and it generates the axis. A year at hourly resolution is 8760 rows — this is the one '
      + 'sheet that is specified rather than authored.',

      'The builder shows a live summary before you commit: how many snapshots, the first and last label, '
      + 'and the total hours covered. Read it — it is the cheapest way to catch a resolution/horizon '
      + 'combination that is not what you meant.',

      'Generating REPLACES the axis, it does not append. That is deliberate: a half-replaced axis '
      + 'silently misaligns every profile indexed against it. If rows already exist the builder asks '
      + 'first and names how many it is about to discard.',

      'The checkbox underneath sets the run resolution to match. Keep it ticked unless you are '
      + 'deliberately building representative periods — the weight is what scales every energy and cost '
      + 'total in the answer.',

      'Settings → Setup → Simulation window narrows what actually gets solved without changing this '
      + 'sheet. Use it to make a first run fast, then widen it. Objective values from different windows '
      + 'are not comparable.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="snapshots"]',
        title: 'The Snapshots step',
        tab: 'Build',
        note: 'Click it. Second in the strip, ahead of every component — that ordering is the lesson. '
          + 'Note there is no map here: a time axis has no geography.',
      },
      {
        selector: '.snapshot-builder',
        title: 'The snapshot builder',
        tab: 'Build',
        note: 'The axis is specified here, not typed into the table on the left.',
      },
      {
        selector: '[data-tour="snap-start"]',
        title: 'Start',
        tab: 'Build',
        note: 'The first snapshot. A date alone gives you midnight; add a time to start elsewhere.',
      },
      {
        selector: '[data-tour="snap-resolution"]',
        title: 'Resolution',
        tab: 'Build',
        note: 'The spacing between snapshots — this decides how many rows you get. Try switching it and '
          + 'watch the count in the summary line change.',
      },
      {
        selector: '[data-tour="snap-horizon"]',
        title: 'Horizon',
        tab: 'Build',
        note: 'How much time to cover. Pick "1 year" and read the summary: 8760 snapshots, with a warning '
          + 'about solve time. Then set it back — you want 3 snapshots in the next step.',
      },
      {
        selector: '[data-tour="snap-weight"]',
        title: 'Run resolution',
        tab: 'Build',
        note: 'Weight is not the same as resolution. It is how many real hours each snapshot stands for, '
          + 'and it scales every energy and cost total. Leaving this ticked keeps the two consistent.',
      },
      {
        selector: '.tables-grid-wrap',
        title: 'The generated axis',
        tab: 'Build',
        note: 'The rows land here. Check the first row is the start you asked for — that is the one-second '
          + 'check that catches an off-by-one axis before it misaligns every profile you import later.',
      },
    ],
    verify: [
      'You can say why a profile cannot be written before snapshots exist',
      'You can say what drives solve time more — 10× the snapshots or 10× the generators',
      'You can explain the difference between resolution and weight',
      'You have watched the summary line change as you switch resolution and horizon',
    ],
    pitfalls: [
      'Generating replaces the axis. Any profile already indexed against the old one will not line up '
      + 'afterwards unless you re-import it — which is why the confirm names the row count it discards.',
      'Resolution and weight drifting apart is a silent error: the model solves, and every cost and '
      + 'energy total is scaled by the wrong factor. Keep the checkbox ticked unless you mean otherwise.',
    ],
  },

  {
    id: 'm1-empty-project',
    section: SECTION,
    title: 'Start an empty project',
    tab: 'Welcome',
    where: 'Welcome → Get started, then Build → Network step',
    concept: [
      'Every model needs an identity before it needs content. The network object carries project-level '
      + 'metadata — a name, a coordinate system, a base year — rather than any physical component.',

      'It matters more than it looks. Exports, reports and run history are all named from it, and three '
      + 'runs later a project called "untitled" is indistinguishable from the other two.',
    ],
    explain: [
      'Press "Start from scratch" on the Welcome page. Ragnarok resets the session to an empty workbook '
      + 'called `untitled.xlsx` and opens Build. If something is already loaded, use Clear in the top '
      + 'bar first — it drops the model and unsaved edits but keeps settings, history and plugins.',

      'Go to the Network step. The sheet is empty, so add a row with "+ Add Network", then type the name '
      + 'into the `name` cell. Adding a row and filling it are two separate actions — that pattern holds '
      + 'for every sheet in the course.',
    ],
    spotlights: [
      {
        selector: '[data-tour="start-scratch"]',
        title: 'Start from scratch',
        tab: 'Welcome',
        note: 'Press it. The session resets to an empty workbook and Build opens. Then come back here and '
          + 'press Next.',
      },
      {
        selector: '[data-build-step="network"]',
        title: 'The Network step',
        tab: 'Build',
        note: 'First in the strip. Click it if it is not already selected.',
      },
      {
        selector: '[data-tour="add-row"]',
        title: 'Add a row',
        tab: 'Build',
        note: 'The sheet starts empty. Press this to create the single `network` row, then type the name '
          + 'into the `name` cell in the table.',
      },
      {
        selector: '.topbar-file',
        title: 'Confirm the reset',
        note: 'Should now read "untitled.xlsx". If it still shows an old project, the reset did not happen — '
          + 'press Clear in the top bar and start again.',
      },
    ],
    entries: [
      {
        field: 'network.name',
        value: 'my-first-model',
        why: 'Names the project in exports, reports and run history. An unnamed project produces output files you cannot tell apart.',
      },
    ],
    verify: [
      'The top-bar filename reads "untitled.xlsx"',
      'The `network` sheet has exactly one row and its `name` cell reads my-first-model',
      'The Network step in the strip shows a tick',
    ],
    pitfalls: [
      'Typing into a cell without adding a row first does nothing — there is no row to type into. Add, then fill.',
    ],
  },

  {
    id: 'm1-smallest-model',
    section: SECTION,
    title: 'The smallest model that solves',
    tab: 'Build',
    where: 'Build → Snapshots, Carriers, Buses, Generators, Loads',
    concept: [
      'A model is solvable once it can satisfy its balance constraint. That needs four things: a time '
      + 'axis, somewhere for power to balance, something injecting, something withdrawing. One bus, one '
      + 'generator, one load, three snapshots.',

      'No network, because one bus has nowhere to send power to. No costs beyond a marginal cost, '
      + 'because with a single generator there is nothing to choose between. The optimiser has exactly '
      + 'one feasible answer: run the generator at the load.',

      'That is the point. When the answer is forced, you can compute it by hand — and a first result you '
      + 'can check by hand is worth more than a realistic one you cannot.',

      'Keep generator capacity above demand. If the only generator cannot cover the load, there is no '
      + 'feasible answer at all and the solver returns INFEASIBLE rather than a number.',
    ],
    explain: [
      'Work left to right along the step strip. Snapshots come from the builder on the right of that '
      + 'step; every other sheet is press "+ Add …" to create a row, then fill the cells listed below. '
      + 'Skip Storage, Lines, Links, Processes and Constraints — empty sheets are not errors.',

      'Three snapshots at one hour each. Two carriers: `AC` for the electrical side, `gas` for the fuel. '
      + 'One bus, one generator on it, one load on it.',

      'Watch the step strip as you go — each step picks up a tick once it has enough data. That is your '
      + 'progress indicator, and it costs nothing to glance at.',
    ],
    spotlights: [
      {
        selector: '[data-tour="snap-horizon"]',
        title: 'Start here — generate 3 snapshots',
        tab: 'Build',
        note: 'On the Snapshots step, set Horizon to "Custom count" and enter 3, with Start 2030-01-01 '
          + '00:00 and Resolution 1 hour. Press Generate. Do not type rows into the table.',
      },
      {
        selector: '[data-build-step="carriers"]',
        title: 'Then carriers',
        tab: 'Build',
        note: 'Two rows — AC and gas. The gas row carries the emission factor you will use in module 7.',
      },
      {
        selector: '[data-build-step="buses"]',
        title: 'Then the bus',
        tab: 'Build',
        note: 'One row. You can also click the map to drop it, which fills x and y for you — you still set '
          + 'name, v_nom and carrier.',
      },
      {
        selector: '[data-build-step="generators"]',
        title: 'Then the generator',
        tab: 'Build',
        note: 'One row. Check the `bus` cell matches your bus name exactly — this is the reference-by-name '
          + 'mechanic from step 2.',
      },
      {
        selector: '[data-build-step="loads"]',
        title: 'Then the load',
        tab: 'Build',
        note: 'One row, 80 MW against the generator\'s 100 MW. Deliberately under capacity, so the model is '
          + 'feasible in every hour.',
      },
      {
        selector: '.build-step-strip',
        title: 'Check the ticks',
        tab: 'Build',
        note: 'Network, Snapshots, Carriers, Buses, Generators and Loads should each show a tick. Storage, '
          + 'Lines and the rest stay blank — that is correct.',
      },
    ],
    entries: [
      { field: 'Snapshots → builder → Start', value: '2030-01-01 00:00', why: 'The first snapshot. Everything temporal is indexed from here.' },
      { field: 'Snapshots → builder → Resolution', value: '1 hour', why: 'Spacing between snapshots. One hour makes the arithmetic in the next step trivial.' },
      { field: 'Snapshots → builder → Horizon', value: 'Custom count', why: 'None of the presets is 3 snapshots — the custom option lets you say exactly how many.' },
      { field: 'Snapshots → builder → Count', value: '3', why: 'Three hours: enough for the model to be a time series, small enough to check the objective by hand.' },
      { field: 'Snapshots → builder → run resolution checkbox', value: 'ticked', why: 'Keeps the snapshot weight at 1 h, matching the resolution. The weight scales every energy and cost total.' },
      { field: 'carriers.name (row 1)', value: 'AC', why: 'The electrical carrier the bus uses.' },
      { field: 'carriers.co2_emissions (row 1)', value: '0', unit: 'tCO2/MWh', why: 'Electricity carries no emissions itself — they are attributed to the fuel.' },
      { field: 'carriers.name (row 2)', value: 'gas', why: 'The fuel carrier for the generator.' },
      { field: 'carriers.co2_emissions (row 2)', value: '0.2', unit: 'tCO2/MWh thermal', why: 'Per MWh of fuel burnt, not per MWh of electricity. Unused until module 7, but set it now.' },
      { field: 'buses.name', value: 'bus_1', why: 'The single node. Every other component points at this exact text.' },
      { field: 'buses.v_nom', value: '380', unit: 'kV', why: 'Nominal voltage. Not used by this solve, but a blank raises validation warnings.' },
      { field: 'buses.carrier', value: 'AC', why: 'Must match a name in `carriers`.' },
      { field: 'generators.name', value: 'gas_1', why: 'The single generator.' },
      { field: 'generators.bus', value: 'bus_1', why: 'Must match the bus name exactly. A typo here detaches the generator silently.' },
      { field: 'generators.carrier', value: 'gas', why: 'Must match a name in `carriers`.' },
      { field: 'generators.p_nom', value: '100', unit: 'MW', why: 'Installed capacity — above the 80 MW load, so the model is feasible in every hour.' },
      { field: 'generators.marginal_cost', value: '50', unit: 'currency/MWh', why: 'Cost of the next MWh. With one generator it does not change what runs, but it sets the objective value you will check by hand.' },
      { field: 'loads.name', value: 'load_1', why: 'The single demand.' },
      { field: 'loads.bus', value: 'bus_1', why: 'Must match the bus name exactly.' },
      { field: 'loads.carrier', value: 'AC', why: 'Electrical demand.' },
      { field: 'loads.p_set', value: '80', unit: 'MW', why: 'Constant demand in every snapshot. Under the generator\'s 100 MW on purpose.' },
    ],
    verify: [
      '`snapshots` has 3 rows, `carriers` 2, and `buses`, `generators`, `loads` 1 each',
      '`generators.bus` and `loads.bus` both read exactly bus_1',
      'The first six steps in the strip show ticks; the rest are blank',
    ],
    pitfalls: [
      'A generator or load whose `bus` does not match detaches silently. If the next step reports INFEASIBLE, check these two cells first — a detached generator means nothing is serving the load.',
      'Load above generator capacity makes the model infeasible. 80 against 100 is deliberate.',
    ],
  },

  {
    id: 'm1-validate-run-read',
    section: SECTION,
    title: 'Validate, run, and check the answer by hand',
    tab: 'Analytics',
    where: 'Run dialog, then Analytics → Result',
    concept: [
      'Validating and solving are different questions. Validation asks "can this be built into a network '
      + 'at all?" — dangling references, missing columns, empty sheets. It answers in seconds. Solving '
      + 'asks "what is the cheapest feasible operation?" and costs real time. Always validate first.',

      'The objective value is the number the optimiser minimised: total system cost over the modelled '
      + 'period. Here you can derive it yourself. The load is 80 MW in each of 3 hourly snapshots, so 240 '
      + 'MWh must be served. Only gas_1 can serve it, at 50 per MWh. Total cost = 240 × 50 = 12,000.',

      'Checking a solver against arithmetic is a habit worth forming now, while it is still possible. On '
      + 'a real model you cannot do this — which is exactly why you should know what the number is made '
      + 'of before the model gets big enough to hide it.',

      'And the marginal price should be 50 in every hour. That is the shadow price from step 1 made '
      + 'concrete: one more MWh of demand would be served by gas_1, costing 50. The price is not '
      + 'something you entered — it fell out of the constraint.',
    ],
    explain: [
      'Press Run in the top bar to open the Run dialog. Turn Dry run on — the action button relabels to '
      + 'Validate — and press it. Then open Analytics → Validation and clear any errors before going on.',

      'Read the planning summary at the top of the dialog before every run. It states what is actually '
      + 'about to be solved: scenario, single-period or pathway, snapshot range, resolution, active '
      + 'constraint count. Most surprising results are a run that used a different window than you '
      + 'assumed.',

      'Then press Run with Dry run off and Run model. Three snapshots solve instantly. Read the objective '
      + 'in Analytics → Result and reconcile it against 12,000.',

      'If your number differs, the likeliest cause is the snapshot weighting — each snapshot standing for '
      + 'more or fewer than one hour rescales the whole objective. The Run dialog\'s summary reports the '
      + 'resolution it used.',
    ],
    spotlights: [
      {
        selector: '.run-button',
        title: 'Open the Run dialog',
        note: 'Press it now — the walkthrough never clicks for you. The dialog opens over this callout; '
          + 'then press Next.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'The planning summary',
        note: 'Read it before every run: scenario, solve mode, snapshot window, resolution, active '
          + 'constraints. This is the cheapest check in the whole application.',
      },
      {
        selector: '[data-tour="dry-run"]',
        title: 'Dry run',
        note: 'Turn it on. The action button on the right relabels itself to Validate — it sends the model '
          + 'to the validation endpoint instead of the solver.',
      },
      {
        selector: '.modal-actions .run-button',
        title: 'Validate, then run',
        note: 'Press it to validate. Afterwards reopen the dialog, turn Dry run off, and press it again to '
          + 'solve for real.',
      },
      {
        selector: '[data-subtab="Validation"]',
        title: 'Validation results',
        tab: 'Analytics',
        note: 'Where structural problems land. Warnings are worth reading even when the model is valid — '
          + 'they usually name a component contributing nothing.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'The objective value',
        tab: 'Analytics',
        note: 'Your answer. Find the objective and reconcile it against 240 MWh × 50 = 12,000 before you go '
          + 'to module 2.',
      },
    ],
    entries: [
      { field: 'Run dialog → Dry run', value: 'on (first pass)', why: 'Sends the model for validation instead of solving — structural problems surface in seconds.' },
      { field: 'Run dialog → Dry run', value: 'off (second pass)', why: 'The real solve. Leaving it on would only re-validate.' },
      { field: 'Run dialog → Force LP', value: 'off', why: 'Default. Unit commitment is not in play with one always-available generator.' },
    ],
    run: {
      label: 'Run dialog → Validate, then Run model',
      detail: [
        'Validation builds the network and stops — a second or two, and no history entry.',
        'The solve optimises 3 snapshots. Effectively instant.',
      ],
      expect: 'A finished run in History, and an objective value of 12,000 in Analytics → Result.',
    },
    verify: [
      'Analytics → Validation reports the model valid, with no errors',
      'Analytics → Result shows an objective value of 12,000 — and you can say where that number comes from',
      'The marginal price is 50 in every snapshot',
      'History → History lists the run',
    ],
    pitfalls: [
      'INFEASIBLE means no answer satisfies the constraints — here, almost certainly a mistyped `bus` '
      + 'reference detaching the generator, or a load above 100 MW.',
      'An objective that is a clean multiple or fraction of 12,000 is a snapshot-weighting difference, '
      + 'not a modelling error. Check the resolution in the Run dialog summary.',
    ],
  },
];
