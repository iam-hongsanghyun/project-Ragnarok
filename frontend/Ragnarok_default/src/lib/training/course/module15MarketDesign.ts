/**
 * Module 15 — Market design: how the price is set (10 steps).
 *
 * Fourteen modules used one market design without naming it: a single clearing
 * price equal to the marginal unit's cost, paid to everybody. That is a design
 * choice, not a law, and it is the one an LP happens to produce. This module
 * swaps the optimiser for explicit clearing RULES and changes them.
 *
 * It runs on `training_m7_year` — the brownfield year — and that choice is
 * deliberate rather than incidental. The market-simulation study never solves,
 * so it clears the capacity written in the workbook. On an expansion model that
 * is the PRE-expansion fleet, which would silently describe a system nobody has;
 * on the brownfield year the workbook capacity is the fleet. Step 8 teaches the
 * trap rather than falling into it.
 *
 * Verified figures, pinned in ``backend/tests/test_training_checkpoints.py``:
 *
 *   uniform      avg 24.50 · bill 25,394,711 · wind earns 5,905,943 · coal profits 1,972,000
 *   pay-as-bid   identical dispatch · bill 15,622,897 · every profit zero · wind earns 0
 *   gas is marginal in 7,888 of 8,760 hours; coal in 872; wind in none
 *   storage      nothing charged or discharged — no spread to trade
 *   scarcity (gas 40 MW)  470 unserved hours · 2,779.5 MWh · avg 209.94 · bill 214,758,788
 *     and in it: oil_1 finally runs — 63,065 MWh for a profit of 54,144,000,
 *     setting the price in 2,374 hours; both storage units wake up.
 *
 * The arc: pay-as-bid appears to cut the bill 38% and pays a truthful zero-cost
 * bidder nothing, which is why the saving is imaginary; and the peaker module 14
 * showed earning nothing earns 54 million in the 470 hours that matter, which is
 * how an energy-only market is supposed to pay for capacity.
 */
import { TutorialStep } from '../types';

const SECTION = '15 · Market design: how the price is set';

export const MODULE_15_MARKET_DESIGN: TutorialStep[] = [
  {
    id: 'm15-rules-not-an-optimum',
    section: SECTION,
    title: 'Rules instead of an optimum',
    tab: 'Settings',
    where: 'Settings → Solve → Market simulation',
    startOptions: {
      prebuiltExampleId: 'training_m7_year',
      completeExampleId: 'training_m7_year',
      note:
        'The brownfield year, not module 7\'s expanded one — and for a reason step 8 explains. This '
        + 'module changes how the market clears, never what is in it.',
    },
    concept: [
      'Every price in this course has come from the same place: the dual of the energy-balance '
      + 'constraint in a cost-minimising linear program. It is a good model of a competitive market '
      + 'clearing at marginal cost, and it has been silently making three assumptions the whole time — '
      + 'that every generator offers at its true cost, that everyone dispatched is paid the same '
      + 'clearing price, and that demand does not respond to price at all.',

      'All three are design choices. Real markets have made different ones and continue to argue about '
      + 'them, and a model that only ever produces the textbook answer cannot help with that argument.',

      'The market-simulation study replaces the optimiser with explicit rules. Each hour it sorts the '
      + 'available units by their offer, dispatches up the stack until demand is met, and lets the last '
      + 'unit in set the price. No objective function and no duals — a merit order executed as an '
      + 'algorithm, which is much closer to what an exchange actually does.',

      'Two consequences to hold on to. It is a copper-plate market — one zone, no network — so '
      + 'everything modules 3 and 10 taught about congestion is switched off. And storage follows a '
      + 'price-threshold rule rather than optimising, which is a fair description of a trader and a poor '
      + 'description of an LP.',
    ],
    explain: [
      'Load the brownfield year and go to Settings → Solve → Market simulation. Like power flow and N-1 '
      + 'in module 10, it is a study mode: it takes over the run rather than adding to it, so no '
      + 'objective value comes back.',

      'Read the rows before changing them. Settlement is what this module is about — Uniform price or '
      + 'Pay as bid. Value of lost load is what unserved energy is priced at when the stack cannot cover '
      + 'demand; 3,000 per MWh is a conventional figure and step 9 makes it matter. Leave Clearing model '
      + 'on Single-sided, and the storage rule\'s quantiles are its charge and discharge thresholds.',

      'Run it first with Settlement on Uniform price. That reproduces the market design every earlier '
      + 'module assumed, so it is the baseline everything else moves away from.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="marketsim"]',
        title: 'Market simulation',
        tab: 'Settings',
        note: 'Under Solve, between power flow and N-1 contingency. Another study mode — Mode reads '
          + '"Off (optimise)" until you turn it on, and turning it on replaces the optimisation.',
      },
    ],
    entries: [
      {
        field: 'Settings → Solve → Market simulation → Settlement',
        value: 'Uniform price',
        why: 'Everyone dispatched is paid the clearing price set by the marginal unit — the design every '
          + 'module before this one assumed without saying so. Step 4 changes it.',
      },
      {
        field: 'Settings → Solve → Market simulation → Value of lost load (per MWh)',
        value: '3000',
        unit: 'currency per MWh',
        why: 'What a megawatt-hour of unserved energy is priced at. An administrative parameter in most '
          + 'markets rather than a measured quantity, and the thing that makes scarcity pricing work — '
          + 'or, when it is capped, not.',
      },
    ],
    verify: [
      'The panel reads Mode On with Settlement on Uniform price',
      'You can name the three market-design assumptions every earlier module made',
      'You can say what a copper-plate market switches off',
      'You can say why this mode returns no objective value',
    ],
    pitfalls: [
      'Expecting it to reproduce the LP. It is a different model of the same system, and step 8 is '
      + 'about exactly how they differ.',
    ],
  },

  {
    id: 'm15-uniform-baseline',
    section: SECTION,
    title: 'Uniform pricing: the baseline every earlier module assumed',
    tab: 'Analytics',
    where: 'Analytics → Result → market simulation card',
    concept: [
      'The run clears every hour of the year and reports an average price of 24.50, a peak of 25.00, no '
      + 'unserved energy and no curtailment. The fleet meets its 1,030,509 MWh comfortably.',

      'The consumer bill is 25,394,711 — every dispatched megawatt-hour times the clearing price in its '
      + 'hour. That number is what the rest of this module changes.',

      'The dispatch is module 2 executed as a rule rather than solved: coal at a capacity factor of 0.99 '
      + 'because it is cheapest and almost always in merit, wind at 0.46 taking everything available, '
      + 'run-of-river at 0.59, and the gas supply swinging to fill the gap at 0.21. The oil peaker never '
      + 'runs at all.',
    ],
    explain: [
      'Run it and open the market-simulation card on the Result dashboard. Read the summary first, then '
      + 'the per-unit table.',

      'Coal earns 10,669,498 against fuel of 8,697,498, for a profit of 1,972,000. Wind earns 5,905,943 '
      + 'with no fuel cost, so all of it is profit, and run-of-river another 1,893,871 on the same '
      + 'basis. And the gas supply earns 6,925,399 against a fuel bill of exactly the same — profit '
      + 'zero.',

      'That last row is not a coincidence. The gas unit is the marginal unit almost all the time, and a '
      + 'marginal unit is paid its own cost by construction. Everything else earns the difference '
      + 'between its cost and the marginal unit\'s, which economists call inframarginal rent and '
      + 'generators call the business.',
    ],
    spotlights: [
      {
        selector: '[data-card="market-simulation"]',
        title: 'The market-simulation card',
        tab: 'Analytics',
        note: 'Summary, then a row per unit with its bid, energy, revenue, profit, capacity factor and '
          + 'how many hours it set the price. The last column is the one people overlook.',
      },
    ],
    run: {
      label: 'Run → Run model (market simulation on, Uniform price)',
      detail: ['A rule-based sweep through 8,760 hours. Faster than the LP it replaces.'],
      expect: 'Average price 24.50, consumer bill 25,394,711, no unserved energy.',
    },
    verify: [
      'The average price is 24.50 and the peak is 25.00',
      'Total consumer cost is 25,394,711 with zero unserved energy',
      'coal_1 profits 1,972,000 and wind_1 profits 5,905,943',
      'gas_supply\'s revenue equals its fuel cost exactly, and you can say why',
    ],
    pitfalls: [
      'Reading the marginal unit\'s zero profit as a problem. It is the definition of marginal, and it '
      + 'is why a fleet of identical units at identical costs would earn nothing at all.',
    ],
  },

  {
    id: 'm15-who-sets-the-price',
    section: SECTION,
    title: 'Who sets your price, and for how many hours',
    tab: 'Analytics',
    where: 'Analytics → Result → market simulation card',
    concept: [
      'The per-unit table answers a question no earlier module could: how many hours did each unit set '
      + 'the price? Gas sets it in 7,888 of 8,760 — ninety per cent of the year. Coal sets it in 872. '
      + 'Wind and run-of-river set it in none.',

      'That distribution is the most useful single summary of a power market, because the price is the '
      + 'marginal unit\'s cost and nothing else. It means this system\'s electricity price is, to a first '
      + 'approximation, the price of gas — and that every conclusion about revenue, about what is worth '
      + 'building, and about what a carbon price would do is really a conclusion about one fuel.',

      'It also explains why a zero-cost unit almost never sets the price. Wind is only marginal when '
      + 'supply exceeds demand and something must be curtailed, and in this year that never happens.',
    ],
    explain: [
      'Read the price-setting hours for every unit and check they sum to the horizon.',

      'Then reason about a gas price shock. If gas is marginal 90% of the time, a rise in its fuel cost '
      + 'passes almost directly into the electricity price — and lands on coal\'s and wind\'s profit as '
      + 'pure gain, because their costs did not change. Inframarginal generators are leveraged to the '
      + 'marginal fuel, which is why a gas crisis makes wind and nuclear operators rich.',

      'And ask module 8\'s question again with this column in front of you. A carbon price raises the '
      + 'marginal unit\'s cost, so it passes into the price the same way, and the inframarginal '
      + 'low-carbon plant collects the difference. The distributional consequence of carbon pricing is '
      + 'visible right here.',
    ],
    verify: [
      'gas_supply sets the price in 7,888 hours, coal_1 in 872, wind_1 in none',
      'The price-setting hours sum to the 8,760-hour horizon',
      'You can say what a gas price rise would do to coal\'s profit, and why',
      'You can explain why a zero-cost unit almost never sets the price',
    ],
    pitfalls: [
      'Confusing "runs the most" with "sets the price the most". Coal runs at a capacity factor of 0.99 '
      + 'and sets the price one hour in ten; the two columns measure different things.',
    ],
  },

  {
    id: 'm15-pay-as-bid',
    section: SECTION,
    title: 'Pay-as-bid: the same electricity, 38% off',
    tab: 'Settings',
    where: 'Settings → Solve → Market simulation → Settlement',
    concept: [
      'Change one row — Settlement from Uniform price to Pay as bid — and re-run. Now every dispatched '
      + 'unit is paid its own offer rather than the clearing price.',

      'The physical outcome does not move at all: identical dispatch, identical capacity factors, '
      + 'identical price-setting hours, the same 1,030,509 MWh served. The merit order does not care how '
      + 'settlement is done.',

      'The money moves enormously. The consumer bill falls from 25,394,711 to 15,622,897 — a saving of '
      + '9,771,814, or 38% — and every generator\'s profit goes to zero, because each is paid exactly '
      + 'what it said its costs were.',

      'That is the argument for pay-as-bid, and it is the one politicians reach for whenever wholesale '
      + 'prices spike: why should cheap plant be paid the price of the expensive one? The arithmetic is '
      + 'real. The conclusion drawn from it is wrong, for a reason the next step makes concrete.',
    ],
    explain: [
      'Switch Settlement to Pay as bid and run again. Compare the summaries: average price and dispatch '
      + 'unchanged, bill 25,394,711 against 15,622,897.',

      'Then compare the per-unit tables. Coal: revenue 10,669,498 becomes 8,697,498, exactly its fuel '
      + 'cost, profit zero. Gas: unchanged at 6,925,399, because as the marginal unit it was already '
      + 'being paid its own bid. Wind: 5,905,943 becomes zero. Run-of-river: 1,893,871 becomes zero.',

      'Sit with those last two rows. They bid zero because their marginal cost is zero and the rules '
      + 'said to bid your cost. Under pay-as-bid they are therefore paid nothing at all for 318,618 MWh '
      + 'of electricity. That is not an artefact — it is what this settlement rule does to a truthful '
      + 'zero-cost bidder.',
    ],
    entries: [
      {
        field: 'Settings → Solve → Market simulation → Settlement',
        value: 'Pay as bid',
        why: 'Each dispatched unit is paid its own offer instead of the clearing price. Nothing else in '
          + 'the model changes, which is what makes the comparison clean.',
      },
    ],
    run: {
      label: 'Run → Run model (Pay as bid)',
      detail: ['Same sweep, different settlement. Same runtime.'],
      expect: 'Identical dispatch, consumer bill 15,622,897, every generator at zero profit.',
    },
    verify: [
      'Dispatch and capacity factors are identical to the uniform run',
      'The consumer bill falls from 25,394,711 to 15,622,897',
      'wind_1 earns exactly zero for 241,212 MWh',
      'You can state the political argument for pay-as-bid in one sentence',
    ],
    pitfalls: [
      'Reporting the 38% saving as what pay-as-bid would achieve. It is what pay-as-bid achieves IF '
      + 'everyone keeps bidding their costs — the assumption the next step destroys.',
    ],
  },

  {
    id: 'm15-why-the-saving-is-imaginary',
    section: SECTION,
    title: 'Why nobody would bid that way twice',
    tab: 'Analytics',
    where: 'The two runs you now have, and module 14',
    concept: [
      'Under uniform pricing a generator has little reason to offer anything but its true cost. Bidding '
      + 'higher risks being dispatched out of merit and gains nothing when it is in merit, because '
      + 'somebody else sets the price. Truthful bidding is close to a dominant strategy, which is the '
      + 'design rationale.',

      'Under pay-as-bid that collapses. Your offer IS your revenue, so bidding your cost guarantees zero '
      + 'profit — the wind farm just demonstrated it. Every participant\'s incentive becomes to guess the '
      + 'clearing price and bid just underneath it.',

      'If everyone guesses well the offers converge on the clearing price and the bill converges back on '
      + 'the uniform one. What pay-as-bid actually changes is not the level of the bill but who can '
      + 'forecast: it rewards sophisticated traders over small generators, and it destroys the '
      + 'information content of the price, because an offer becomes a guess about other people rather '
      + 'than a statement about costs.',

      'This is the most-repeated debate in electricity market design, and you now have both halves as '
      + 'numbers: a real 38% saving in a world of truthful bidders, and a reason that world cannot '
      + 'exist.',
    ],
    explain: [
      'Test the argument rather than accepting it. Module 14\'s bid-strategy study measures exactly '
      + 'this — what one owner gains by offering above cost — and under uniform pricing it showed a gain '
      + 'that came entirely from moving the CLEARING price, which required being pivotal.',

      'Under pay-as-bid the gain no longer requires that. Any inframarginal unit that marks up to just '
      + 'below the clearing price collects the same rent uniform pricing handed it automatically. The '
      + 'rent does not disappear — it becomes something you have to be clever to collect.',

      'Then write down what you would tell a policymaker who asks for pay-as-bid to cut bills. Not "the '
      + 'model says 38%", and not "it makes no difference", but that the saving is conditional on '
      + 'bidding behaviour the design itself removes the incentive for, and that the distributional '
      + 'effect runs from small generators to sophisticated ones.',
    ],
    verify: [
      'You can say why truthful bidding is rational under uniform pricing and not under pay-as-bid',
      'You can say what happens to the bill if pay-as-bid bidders forecast well',
      'You can explain what pay-as-bid does to the information content of a price',
      'You can state the honest answer to "would pay-as-bid cut bills?"',
    ],
    pitfalls: [
      'Treating this as settled. It is genuinely argued by serious people, and the point of holding both '
      + 'numbers is to argue with evidence rather than intuition.',
    ],
  },

  {
    id: 'm15-storage-does-nothing',
    section: SECTION,
    title: 'The storage did nothing, and that is informative',
    tab: 'Analytics',
    where: 'Analytics → Result → market simulation card, storage section',
    concept: [
      'Both runs report the battery and the pumped hydro charging zero and discharging zero. Two storage '
      + 'assets, a full year, no arbitrage at all.',

      'The reason is in the price series. Prices run between roughly 24.50 and 25.00, because gas sets '
      + 'them nine hours in ten — there is barely a spread to trade. The storage rule charges below the '
      + '25th percentile and discharges above the 75th, and with those percentiles almost on top of each '
      + 'other a round trip loses more to efficiency than it gains on price.',

      'Compare module 4, where the same idea made money easily, because that model had prices of 20, 50 '
      + 'and 120. Storage arbitrage is a bet on price VARIANCE, not on price level, and a flat market has '
      + 'nothing to arbitrage. Step 9 makes the market anything but flat, and the storage wakes up.',
    ],
    explain: [
      'Find the storage section of the card and confirm the zeros for both units.',

      'Then work out what spread the battery would need. At about 90% efficiency each way a round trip '
      + 'keeps roughly 81% of the energy, so the discharge price has to beat the charge price by about a '
      + 'quarter before it breaks even. Nothing in a 24.50-to-25.00 price series is 25% above anything '
      + 'else.',

      'Notice what this says about the earlier modules. Module 7 built no more storage than it started '
      + 'with, and module 14 found the battery running a small loss. Three studies agreeing that storage '
      + 'is not worth much in THIS system — and all three would change together if the price series had '
      + 'more variance, which is precisely what step 9 produces.',
    ],
    verify: [
      'Both storage units report zero charged and zero discharged',
      'You can compute roughly what spread a 90%-each-way round trip needs',
      'You can say why module 4\'s battery made money and this one does not',
      'You can predict what will happen to storage in the scarcity run',
    ],
    pitfalls: [
      'Concluding that storage does not work. It concludes that arbitrage does not pay in a market whose '
      + 'price barely moves, which is a statement about the market rather than the technology.',
    ],
  },

  {
    id: 'm15-what-this-study-is-not',
    section: SECTION,
    title: 'What this study is not, and why the model matters',
    tab: 'Analytics',
    where: 'Reading critically',
    concept: [
      'This module runs on the brownfield year rather than module 7\'s expanded one, and the reason is a '
      + 'trap worth meeting deliberately.',

      'The market simulation never solves. It reads the capacity written in the workbook and clears a '
      + 'market for it. On a brownfield model that is exactly right — the workbook capacity IS the '
      + 'fleet. On an expansion model it is not: `p_nom` there is the PRE-expansion capacity, so the '
      + 'study would clear a market for 60 MW of wind in a system whose optimiser built 150, and a solar '
      + 'farm built from zero would not appear at all.',

      'Nothing warns you. The numbers are internally consistent and describe a system nobody has. Run '
      + 'this study on module 7\'s expanded checkpoint and you get a plausible, wrong answer — which is '
      + 'the most dangerous kind.',

      'The general rule is the one modules 10 and 12 kept arriving at from other directions: a study '
      + 'mode that replaces the solve cannot see anything the solve would have decided. Power flow '
      + 'cannot see the dispatch. N-1 cannot see the commitment. This cannot see the expansion.',
    ],
    explain: [
      'Confirm it for yourself if you want the lesson to stick: load module 7\'s expanded checkpoint, '
      + 'run the same study, and look at wind\'s energy. It reports the same 241,212 MWh as here, not '
      + 'the 603,645 that fleet actually generates.',

      'Then note the other differences from the LP, which are by design rather than traps. No network, '
      + 'so nothing modules 3 and 10 taught applies. No unit commitment or ramping, so module 11 is '
      + 'switched off. Rule-based storage rather than optimised. And it reports what consumers PAID '
      + 'rather than what production COST — module 14\'s distinction, and the two differ by exactly the '
      + 'inframarginal rent.',

      'So use each for its own question. For "what should this system do", the optimiser. For "what will '
      + 'this market design produce given a fleet", the rules — because a market is a set of rules being '
      + 'executed, not an optimisation being solved.',
    ],
    verify: [
      'You can say why this module uses the brownfield year',
      'You can say what the study reads for capacity, and when that is wrong',
      'You can name four things the rule-based model does not contain',
      'You can say why consumer bill and system cost are different quantities',
    ],
    pitfalls: [
      'Running any replace-the-solve study on an expansion model without checking which capacity it '
      + 'read. The result will look reasonable and describe a different system.',
    ],
  },

  {
    id: 'm15-scarcity',
    section: SECTION,
    title: 'Scarcity pricing: 0.27% of the energy, 8.5 times the bill',
    tab: 'Build',
    where: 'Build → Generators, then run again',
    concept: [
      'Everything so far has been a comfortable year. Make it uncomfortable: throttle the gas supply '
      + 'from 150 MW to 40 and re-run under uniform pricing.',

      'The stack can no longer cover demand in every hour. 2,779.5 MWh goes unserved across 470 hours — '
      + '0.27% of the year\'s energy — and in those hours the price is the value of lost load, 3,000 per '
      + 'MWh.',

      'The bill moves out of all proportion to the shortfall: average price 24.50 to 209.94, consumer '
      + 'cost 25,394,711 to 214,758,788. Eight and a half times, for a system that still served 99.73% '
      + 'of the same demand.',

      'And the oil peaker finally earns its keep. It ran for none of the 8,760 hours in the base case; '
      + 'here it produces 63,065 MWh, sets the price in 2,374 hours, and clears a profit of 54,144,000. '
      + 'That is the answer to module 14\'s puzzle — an energy-only market pays for capacity through '
      + 'scarcity rents, which means it pays almost nothing for years and then everything at once.',
    ],
    explain: [
      'Change `p_nom` on gas_supply from 150 to 40 in Build → Generators, leave Settlement on Uniform '
      + 'price, and run.',

      'Read the summary against the baseline, then find oil_1 in the per-unit table and read its four '
      + 'numbers: 63,065 MWh, revenue 61,711,804, profit 54,144,000, price-setting hours 2,374. Module '
      + '14 reported that same unit earning nothing whatsoever.',

      'Then check the storage. Both units are now trading — the battery charging 20,715 MWh and '
      + 'discharging 16,743, the pumped hydro 78,259 and 59,166. Nothing about the storage changed; the '
      + 'price variance did, exactly as step 7 predicted.',

      'Finally, work out where the money went. Unserved energy times VOLL is 2,779.5 × 3,000, about 8.3 '
      + 'million — nowhere near the 189 million the bill rose by. The rest is every other megawatt-hour '
      + 'in those 470 hours also clearing at 3,000. Scarcity pricing pays the scarcity price to '
      + 'everybody running, not only to the last unit.',

      'And ask whether you believe it. VOLL is an administrative parameter and this entire result is '
      + 'linear in it — halve it and the bill halves. Nothing here measures what consumers would '
      + 'actually pay to avoid an outage, and no real market measures it either, which is why price caps '
      + 'are a policy fight rather than a calculation.',
    ],
    run: {
      label: 'Run → Run model (gas throttled to 40 MW)',
      detail: ['Same sweep. The scarcity hours are what change.'],
      expect: '470 unserved hours, 2,779.5 MWh unserved, average price 209.94, bill 214,758,788.',
    },
    verify: [
      'The run reports 2,779.5 MWh unserved across 470 hours',
      'The average price rises to 209.94 and the peak reaches VOLL at 3,000',
      'oil_1 profits 54,144,000 having earned nothing in the base case',
      'Both storage units are now charging and discharging',
      'You can explain why the bill rose far more than unserved energy times VOLL',
    ],
    pitfalls: [
      'Reading 8.5 times as a forecast. It is linear in an administrative VOLL and assumes no price cap, '
      + 'no demand response and no intervention — three things every real market has.',
      'Forgetting to restore gas_supply to 150 MW before moving on.',
    ],
  },

  {
    id: 'm15-what-design-changes',
    section: SECTION,
    title: 'What market design changes about the fourteen modules before it',
    tab: 'Analytics',
    where: 'Everything you have built',
    concept: [
      'Every price in modules 1 to 14 assumed uniform pricing, truthful bidding and inelastic demand. '
      + 'That is not a criticism — it is the standard model and usually the right one — but it means '
      + 'every revenue, capture price and congestion rent in this course carried a market-design '
      + 'assumption that was never stated.',

      'What changes now is that you can sort the findings. The dispatch does not depend on it: the merit '
      + 'order cleared identically under both settlement rules. Neither does the system cost, the '
      + 'reliability metrics, or anything physical.',

      'But every conclusion about who earns what — module 14\'s entire subject — is as much about the '
      + 'settlement rule as about the assets. Under pay-as-bid, module 14\'s capture prices, its zero '
      + 'profit, its PPA settlement and its market-power gain are all different numbers, and the wind '
      + 'farm\'s capture price is zero.',

      'That division — physical findings that survive a design change, commercial findings that do not — '
      + 'is what separates a model of a power SYSTEM from a model of a power MARKET. Most studies '
      + 'contain both and say which is which about half the time.',
    ],
    explain: [
      'Go back through the course and mark each major finding as surviving a design change or not.',

      'Module 2\'s merit order, module 3\'s congestion, module 10\'s loop flows, module 11\'s commitment '
      + 'behaviour and module 12\'s reliability metrics are physical and survive. Module 7\'s least-cost '
      + 'expansion is a planning answer and survives.',

      'Module 14\'s capture prices, zero profit, PPA settlement and market-power gain do not — and '
      + 'neither does this module\'s own 54 million for the peaker, which exists only because the design '
      + 'has no price cap.',

      'Then state, for a study you might actually deliver, which market design it assumes and whether '
      + 'that is the design of the market being modelled. Uniform pricing is common and not universal, '
      + 'and the differences are the ones you just measured.',
    ],
    verify: [
      'You can sort the course\'s major findings into design-dependent and design-independent',
      'You can say which of module 14\'s numbers change under pay-as-bid',
      'You can state the three market-design assumptions every earlier module made',
      'You can say what an energy-only market pays capacity for, and when',
    ],
    pitfalls: [
      'Assuming the design in your model is the design in the market you are modelling. That assumption '
      + 'is usually inherited rather than chosen.',
    ],
  },

  {
    id: 'm15-the-end',
    section: SECTION,
    title: 'What you can do now',
    tab: 'Analytics',
    where: 'Everything you have built',
    concept: [
      'Fifteen modules, one model, and one habit: work out what the answer should be, then find out '
      + 'which of you is wrong.',

      'It found a merit order worth 4,500, a line rating worth two prices, a battery worth twenty-three '
      + 'times more on a day than on three hours, a discount rate worth 30 MW, a plant that spilt free '
      + 'wind to avoid a start-up charge, a nodal price above every generator in the model, a system '
      + 'seven times outside its reliability standard while shedding no load, a demand projection that '
      + 'moved 30 MW of solar without changing a kilowatt-hour, a wind farm earning exactly its capital '
      + 'cost and no more, and a settlement rule worth 38% of everybody\'s bill.',

      'None of those came from the solver being clever. Each came from asking a model a question it had '
      + 'not been asked, and every one began as a number somebody could have accepted without checking.',
    ],
    explain: [
      'Seven questions, to ask of any model — including one you did not write.',

      'What is the objective actually minimising, and what is missing from it? What is the time axis, '
      + 'and what does its resolution and horizon hide? Which constraints are binding, and what would '
      + 'relaxing them cost? What is the range around the answer, with the conditions that produced it? '
      + 'Where did the demand come from, and what does it assume is growing? Whose books does the answer '
      + 'belong to? And what market design is it assuming?',

      'Answer all seven about something you built. Where you cannot, you have found either something to '
      + 'go and read or something the study never established — and telling those two apart is most of '
      + 'what expertise in this field consists of.',

      'That is the end of the course. The models will change; the seven questions will not.',
    ],
    verify: [
      'You can state all seven questions without looking them up',
      'You can answer all seven about a model you built',
      'You can name the one you are least able to answer, and what it would take to answer it',
    ],
    pitfalls: [
      'Stopping here. The course was a place to practise the habit — the habit is what transfers.',
    ],
  },
];
