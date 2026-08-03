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
    startOptions: {
      // Nothing precedes module 1, so there is no prebuilt start — only the
      // empty sheet the course assumes, or the model it ends with.
      completeExampleId: 'training_m1',
      note:
        'Module 1 builds a model from nothing, so Empty is the choice that teaches it — watching the '
        + 'first model appear one sheet at a time is most of the lesson. Complete data loads the finished '
        + 'module-1 model instead, for reading and running rather than building.',
    },
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

      'The step layout changes with the sheet, and the change is informative. Steps whose components '
      + 'have coordinates — buses, lines, links — show the network map. Steps whose sheets have no '
      + 'geography — network, snapshots, carriers, processes — show no map at all: the table sits on the '
      + 'left and a panel on the right. If you are looking for a map and there is none, that is the '
      + 'application telling you this sheet has nothing to place.',
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
        buildStep: 'carriers',
        title: 'Carriers — first of the five nouns',
        tab: 'Build',
        note: 'The table on the left scopes to the `carriers` sheet — and note there is no map: '
          + 'a carrier is a kind of energy, not a place. Carriers come before buses because buses point at '
          + 'them by name.',
      },
      {
        selector: '[data-build-step="buses"]',
        buildStep: 'buses',
        title: 'Buses — the nodes',
        tab: 'Build',
        note: 'The map appears here, because a bus is the one component with a position. Everything '
          + 'else inherits its location from the bus it attaches to. Compare with the Carriers step you just '
          + 'left, which had none.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Generators — injection',
        tab: 'Build',
        note: 'Look at the columns: `bus` (which node it injects at), `p_nom` (installed capacity, MW), '
          + '`marginal_cost` (cost per extra MWh), `carrier` (fuel), `efficiency`. The `bus` value must match '
          + 'a bus name exactly — reference by name, and the commonest source of a broken model.',
      },
      {
        selector: '[data-build-step="loads"]',
        buildStep: 'loads',
        title: 'Loads — withdrawal',
        tab: 'Build',
        note: 'Same shape as a generator, opposite sign: a load withdraws instead of injecting. `p_set` is '
          + 'the demand in MW that must be served at its bus in every snapshot.',
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
      'You can predict, for any step, whether it will show a map',
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
        buildStep: 'snapshots',
        title: 'The Snapshots step',
        tab: 'Build',
        note: 'Second in the strip, ahead of every component — that ordering is the lesson. Note there is '
          + 'no map here, and no per-row form: a time axis has no geography, and you never author snapshots '
          + 'one at a time.',
      },
      {
        selector: '.snapshot-builder',
        buildStep: 'snapshots',
        title: 'The snapshot builder',
        tab: 'Build',
        note: 'The axis is specified here, not typed into the table on the left.',
      },
      {
        selector: '[data-tour="snap-start"]',
        buildStep: 'snapshots',
        title: 'Start',
        tab: 'Build',
        note: 'The first snapshot. A date alone gives you midnight; add a time to start elsewhere.',
      },
      {
        selector: '[data-tour="snap-resolution"]',
        buildStep: 'snapshots',
        title: 'Resolution',
        tab: 'Build',
        note: 'The spacing between snapshots — this decides how many rows you get. Try switching it and '
          + 'watch the count in the summary line change.',
      },
      {
        selector: '[data-tour="snap-horizon"]',
        buildStep: 'snapshots',
        title: 'Horizon',
        tab: 'Build',
        note: 'How much time to cover. Pick "1 year" and read the summary: 8760 snapshots, with a warning '
          + 'about solve time. Then set it back — you want 3 snapshots in the next step.',
      },
      {
        selector: '[data-tour="snap-weight"]',
        buildStep: 'snapshots',
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
      'Press "Start from scratch" on the Welcome page. Ragnarok resets the session to an empty workbook — '
      + 'named `untitled_` and a timestamp, so two scratch projects never collide — and opens Build. If something is already loaded, use Clear in the top '
      + 'bar first — it drops the model and unsaved edits but keeps settings, history and plugins.',

      'Go to the Network step. It shows no map — `network` has no coordinates — so the table sits on the '
      + 'left and the attribute form on the right.',

      'The sheet is empty, so add a row with "+ Add Networks", then type the name into the `name` cell. '
      + 'Adding a row and filling it are two separate actions, and that pattern holds for every sheet in '
      + 'the course. You can type into the table cell or into the attribute form on the right — they are '
      + 'two views of the same row.',
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
        buildStep: 'network',
        title: 'The Network step',
        tab: 'Build',
        note: 'First in the strip, opened for you. No map — `network` has no coordinates — so the table is '
          + 'on the left and the attribute form on the right.',
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
        note: 'Should now start with "untitled_" followed by a timestamp. If it still shows an old project '
          + 'name, the reset did not happen — press Clear in the top bar and start again.',
      },
    ],
    entries: [
      {
        field: 'network.name',
        label: 'project name',
        value: 'my-first-model',
        why: 'Names the project wherever it is referred to later — exported filenames, report headers, run '
          + 'history entries. It has no effect on the solve, but three runs in, an unnamed project is '
          + 'indistinguishable from the other two.',
      },
    ],
    verify: [
      'The top-bar filename starts with "untitled_" and carries today\'s timestamp',
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
        selector: '[data-build-step="snapshots"]',
        buildStep: 'snapshots',
        title: 'Start here — the Snapshots step',
        tab: 'Build',
        note: 'Opened for you. The axis comes first because every profile in the model is indexed by it.',
      },
      {
        selector: '[data-tour="snap-horizon"]',
        buildStep: 'snapshots',
        title: 'Generate 3 snapshots',
        tab: 'Build',
        note: 'Set Horizon to "Custom count" and enter 3, with Start 2030-01-01 00:00 and Resolution '
          + '1 hour. Check the summary reads 3 snapshots, then press Generate. Do not type rows into the '
          + 'table.',
      },
      {
        selector: '[data-build-step="carriers"]',
        buildStep: 'carriers',
        title: 'Then carriers',
        tab: 'Build',
        note: 'Two rows. `name` is the text other sheets point at; `co2_emissions` is tonnes of CO2 per MWh '
          + 'of FUEL burnt, not per MWh of electricity. Row 1: AC, 0 — electricity carries no emissions '
          + 'itself. Row 2: gas, 0.2 — the fuel does.',
      },
      {
        selector: '[data-build-step="buses"]',
        buildStep: 'buses',
        title: 'Then the bus',
        tab: 'Build',
        note: 'One row: `name` = bus_1 (the text the generator and load will both point at), `v_nom` = 380 '
          + 'kV (nominal voltage — unused by this solve, but a blank warns), `carrier` = AC. Clicking the '
          + 'map drops a bus and fills x/y for you; you still type the other three.',
      },
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'Then the generator',
        tab: 'Build',
        note: 'The row that carries the economics. `p_nom` is installed capacity in MW — the most it can '
          + 'produce at any instant (100). `marginal_cost` is the cost of one more MWh (50) and is what the '
          + 'optimiser sorts on. `efficiency` is MWh electricity per MWh fuel (0.5). And `bus` must match '
          + 'bus_1 exactly — a typo there silently detaches the unit.',
      },
      {
        selector: '[data-build-step="loads"]',
        buildStep: 'loads',
        title: 'Then the load',
        tab: 'Build',
        note: '`p_set` is demand in MW that MUST be met in every snapshot — a constraint, not a target. '
          + '80 MW against the generator\'s 100 MW leaves 20 MW of headroom, so the model is feasible in '
          + 'every hour. Push it above 100 and the solve returns INFEASIBLE instead of a number.',
      },
      {
        selector: '.build-step-strip',
        title: 'Check the ticks',
        tab: 'Build',
        note: 'Network, Snapshots, Carriers, Buses, Generators and Loads should each show a tick — the strip '
          + 'ticks a step once its sheet has enough rows to be usable. Storage, Lines, Links, Processes and '
          + 'Constraints stay blank, and that is correct: they are optional, and an empty optional sheet is '
          + 'not an error.',
      },
    ],
    entries: [
      {
        field: 'Snapshots → builder → Start',
        label: 'first snapshot',
        value: '2030-01-01 00:00',
        why: 'The instant the model begins. Everything temporal is indexed from here, so a profile you '
          + 'import later must line up with this. The year is arbitrary for this exercise — 2030 is a '
          + 'convention for "a future planning year".',
      },
      {
        field: 'Snapshots → builder → Resolution',
        label: 'spacing between snapshots',
        value: '1 hour',
        why: 'How finely time is cut. One hour means each snapshot represents one hour, which makes the '
          + 'cost arithmetic in step 6 trivial to check. Coarser resolution means fewer rows and a faster '
          + 'solve, at the cost of hiding within-hour variation.',
      },
      {
        field: 'Snapshots → builder → Horizon',
        label: 'total time covered',
        value: 'Custom count',
        why: 'None of the presets is 3 snapshots — they start at one full day (24). Custom lets you state '
          + 'the row count directly.',
      },
      {
        field: 'Snapshots → builder → Count',
        label: 'number of snapshots',
        value: '3',
        why: 'Three hours. Enough that the model is a time series rather than a single instant, small '
          + 'enough that you can multiply the answer out on paper. Real studies use 8760.',
      },
      {
        field: 'Snapshots → builder → run resolution checkbox',
        label: 'snapshot weight = resolution',
        value: 'ticked',
        why: 'Sets the weight to 1 hour per snapshot. Weight is how many real hours each snapshot stands '
          + 'for, and every energy and cost total is multiplied by it. Leave it unticked and the objective '
          + 'in step 6 will not be 12,000 even though nothing else changed.',
      },

      {
        field: 'carriers.name (row 1)',
        label: 'carrier name',
        value: 'AC',
        why: 'A carrier is the KIND of energy a component deals in. `AC` is alternating-current '
          + 'electricity. The bus will point at this exact text, so the spelling is load-bearing.',
      },
      {
        field: 'carriers.co2_emissions (row 1)',
        label: 'emission factor',
        value: '0',
        unit: 'tCO2 per MWh of fuel',
        why: 'Electricity carries no emissions itself — emissions are attributed to the fuel that made it, '
          + 'so double-counting is avoided. Leave it 0.',
      },
      {
        field: 'carriers.name (row 2)',
        label: 'carrier name',
        value: 'gas',
        why: 'The fuel the generator burns. Separating fuel from electricity is what lets one emission '
          + 'factor serve every gas plant in the model.',
      },
      {
        field: 'carriers.co2_emissions (row 2)',
        label: 'emission factor',
        value: '0.2',
        unit: 'tCO2 per MWh of fuel burnt',
        why: 'Per MWh of FUEL, not per MWh of electricity. The generator\'s efficiency converts between '
          + 'them: at 50% efficient, 0.2 per MWh of gas becomes 0.4 per MWh of electricity. Unused until '
          + 'module 8, but set it now so the model is complete.',
      },

      {
        field: 'buses.name',
        label: 'bus name',
        value: 'bus_1',
        why: 'A bus is a place where power balances. This text is the key every other component uses to '
          + 'say "I am here", so it must be typed identically in the generator and load rows.',
      },
      {
        field: 'buses.v_nom',
        label: 'nominal voltage',
        value: '380',
        unit: 'kV',
        why: 'The voltage level this node operates at. It does not affect THIS solve — a linear dispatch '
          + 'ignores voltage — but power-flow calculations and per-unit conversions need it, and a blank '
          + 'raises validation warnings. 380 kV is a typical transmission level.',
      },
      {
        field: 'buses.carrier',
        label: 'carrier',
        value: 'AC',
        why: 'Which kind of energy balances at this node. Must match a `carriers.name` exactly.',
      },

      {
        field: 'generators.name',
        label: 'generator name',
        value: 'gas_1',
        why: 'Identifies the unit in results — per-asset dispatch, revenue and emissions are all reported '
          + 'under this name.',
      },
      {
        field: 'generators.bus',
        label: 'which bus it connects to',
        value: 'bus_1',
        why: 'Must match `buses.name` exactly. This is the single commonest way to break a model: a typo '
          + 'here does not error, it silently detaches the generator, and the solve then reports INFEASIBLE '
          + 'because nothing is left to serve the load.',
      },
      {
        field: 'generators.carrier',
        label: 'fuel / technology',
        value: 'gas',
        why: 'Links the unit to its emission factor and groups it in per-carrier results. Must match a '
          + '`carriers.name`.',
      },
      {
        field: 'generators.p_nom',
        label: 'installed capacity',
        value: '100',
        unit: 'MW',
        why: 'The maximum power this unit can produce at any instant — its nameplate rating. The solver '
          + 'may dispatch anywhere from 0 to 100 MW in each hour. It must exceed the 80 MW load or the '
          + 'model has no feasible answer; the 20 MW of headroom is deliberate slack.',
      },
      {
        field: 'generators.marginal_cost',
        label: 'cost per extra MWh',
        value: '50',
        unit: 'currency per MWh',
        why: 'What it costs to produce one more MWh — fuel plus variable O&M. This is what the optimiser '
          + 'sorts on: with several generators, cheapest runs first (the merit order, module 2). With only '
          + 'one it changes nothing about WHAT runs, but it sets the objective value and the market price '
          + 'you will check in step 6.',
      },
      {
        field: 'generators.efficiency',
        label: 'fuel-to-electricity conversion',
        value: '0.5',
        why: 'MWh of electricity out per MWh of fuel in. 0.5 is typical of an older gas plant. Combined '
          + 'with the carrier factor it gives 0.4 tCO2 per MWh generated. It also means the unit burns 2 '
          + 'MWh of gas for every 1 MWh it sells.',
      },

      {
        field: 'loads.name',
        label: 'load name',
        value: 'load_1',
        why: 'Identifies this demand in results. With one load it hardly matters; in a national model you '
          + 'read served energy and unserved energy per load, so the name is how you find a region.',
      },
      {
        field: 'loads.bus',
        label: 'which bus it draws from',
        value: 'bus_1',
        why: 'Must match `buses.name` exactly. Demand must balance at the node it is attached to.',
      },
      {
        field: 'loads.carrier',
        label: 'carrier',
        value: 'AC',
        why: 'The kind of energy demanded — electricity here. It matters once a model couples sectors, '
          + 'where a load might draw hydrogen or heat instead. Must match a `carriers.name`.',
      },
      {
        field: 'loads.p_set',
        label: 'demand',
        value: '80',
        unit: 'MW',
        why: 'How much power must be delivered in EVERY snapshot — this is a constraint, not a target: the '
          + 'model must serve it or fail. Constant here; the `loads-p_set` sheet takes an hour-by-hour '
          + 'profile instead, which is what you would use for real demand.',
      },
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
      + 'period. Here you can derive it yourself. The load is 80 MW in each of 3 snapshots, and the '
      + 'builder set the snapshot weight to 1 h, so each snapshot really is one hour and 240 MWh must be '
      + 'served. Only gas_1 can serve it, at 50 per MWh. Total cost = 240 × 50 = 12,000.',

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

      'Then press Run with Dry run off and Run model. The run does not block the screen — it is queued on '
      + 'the server, and the status line says so. Three snapshots solve in about a second.',

      'A finished run does not open itself. Go to History → History, tick the run at the top of the list, '
      + 'and press View result — that is what loads it into Analytics. This is the loop for every run in '
      + 'the rest of the course: run, then open it from History. Then read the objective in Analytics → '
      + 'Result and reconcile it against 12,000.',

      'If your number differs, the likeliest cause is the snapshot weight — each snapshot standing for '
      + 'more or fewer than one hour rescales the whole objective. The Run dialog\'s summary reports the '
      + 'resolution it used; it should say 1h. If it does not, the weight checkbox in the snapshot builder '
      + 'was unticked, and Settings → Simulation window is where to put it right.',
    ],
    spotlights: [
      {
        selector: '.run-button',
        title: 'The Run button',
        runDialog: 'closed',
        note: 'Everything you solve starts here. It opens the Run dialog — the next stop opens it for you '
          + 'so you can see inside.',
      },
      {
        selector: '.sg-scenario-summary',
        title: 'The planning summary',
        runDialog: 'open',
        note: 'Read it before every run: scenario, solve mode, snapshot window, resolution, active '
          + 'constraints. This is the cheapest check in the whole application, and most surprising results '
          + 'are a run that used a different window than you assumed.',
      },
      {
        selector: '[data-tour="dry-run"]',
        title: 'Dry run',
        runDialog: 'open',
        note: 'Turn it on yourself. Watch the action button on the right relabel to Validate — that is the '
          + 'model going to the validation endpoint instead of the solver.',
      },
      {
        selector: '.modal-actions .run-button',
        title: 'Validate, then run',
        runDialog: 'open',
        note: 'Press it to validate. Then reopen the dialog, turn Dry run off, and press it again to solve '
          + 'for real. Both presses are yours — the walkthrough never submits a run.',
      },
      {
        selector: '[data-subtab="Validation"]',
        title: 'Validation results',
        tab: 'Analytics',
        runDialog: 'closed',
        note: 'Where structural problems land. Warnings are worth reading even when the model is valid — '
          + 'they usually name a component contributing nothing.',
      },
      {
        selector: '.history-list',
        title: 'The finished run',
        tab: 'History',
        runDialog: 'closed',
        note: 'Runs are queued on the server and land here, newest first — yours reads "Base case", a few '
          + 'seconds ago, 1h res, 80 MWh demand. Tick its checkbox.',
      },
      {
        selector: '[data-tour="view-result"]',
        title: 'View result',
        tab: 'History',
        runDialog: 'closed',
        note: 'This is the step people miss. Nothing appears in Analytics until you press it — a solved '
          + 'run sitting in History is not a loaded run. With two or more ticked it relabels to Compare '
          + 'results, which is module 9\'s tool.',
      },
      {
        selector: '[data-subtab="Result"]',
        title: 'The objective value',
        tab: 'Analytics',
        runDialog: 'closed',
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
      expect: 'A finished run in History which, once ticked and opened with View result, shows an '
        + 'objective value of 12,000 in Analytics → Result.',
    },
    verify: [
      'Analytics → Validation reports the model valid, with no errors',
      'History → History lists the run, and View result loads it into Analytics',
      'Analytics → Result shows a total cost of 12,000 — and you can say where that number comes from',
      'Dispatch reads 240 MWh, average price 50, min · max 50 · 50, snapshots 3 × 1h',
    ],
    pitfalls: [
      'INFEASIBLE means no answer satisfies the constraints — here, almost certainly a mistyped `bus` '
      + 'reference detaching the generator, or a load above 100 MW.',
      'An objective that is a clean multiple or fraction of 12,000 is a snapshot-weighting difference, '
      + 'not a modelling error. Check the resolution in the Run dialog summary.',
    ],
  },
];
