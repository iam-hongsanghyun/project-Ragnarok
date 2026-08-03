/**
 * Module 14 — The other side of the market (10 steps).
 *
 * Thirteen modules have been the planner's: minimise the cost of serving
 * everybody. This one belongs to somebody who owns four megawatts of the answer
 * and wants to know what they are worth. Same solved year, same prices, a
 * completely different question — and the answers disagree with the planner's
 * in ways that explain most of how power markets actually behave.
 *
 * Everything runs on `training_m7`, the expanded year, with an `owner` column
 * the learner adds. Two owners, chosen so the contrast is the lesson:
 *
 *   Nordwind   the wind and solar module 7 BUILT (extendable, carrying capex)
 *   Altkraft   the coal and oil that were already there (sunk, no capital charge)
 *
 * Verified figures, pinned in ``backend/tests/test_training_checkpoints.py``:
 *
 *   price at Nordwind's buses  mean 23.92 (system-wide 24.28)
 *   wind_1                603,645 MWh · capture 21.18 · revenue = capex · profit 0
 *   solar_1                34,794 MWh · capture 24.59 · revenue = capex · profit 0
 *   coal_1 (merchant)     109,400 MWh · capture 28.25 · profit 902,548
 *   oil_1                 never runs · earns nothing
 *   PPA @ 25              638,440 MWh · avg spot 21.36 · seller +2,320,908
 *   coal bid +50%         profit 902,548 → 4,269,487 · system price 24.28 → 30.71
 *
 * Three findings carry it. Capture price is not the average price and differs
 * per technology. An asset the planner chose to build earns exactly its capital
 * cost and no more — the long-run equilibrium, and the "missing money" argument
 * in one number. And the peaker the adequacy study in module 12 said the system
 * needs earns nothing at all from energy.
 *
 * Written after fixing the study these figures come from: the merchant and
 * bid-strategy counterfactuals were re-optimising capacity as well as dispatch,
 * so profit came out zero by construction on any expanded fleet.
 */
import { TutorialStep } from '../types';

const SECTION = '14 · The other side of the market';

export const MODULE_14_PARTICIPANT: TutorialStep[] = [
  {
    id: 'm14-whose-question-is-it',
    section: SECTION,
    title: 'Whose question is the model answering?',
    tab: 'Build',
    where: 'Build → Generators',
    startOptions: {
      prebuiltExampleId: 'training_m7',
      completeExampleId: 'training_m7',
      note:
        'Both options load module 7\'s expanded year. This module adds one column to it and then only '
        + 'reads — nothing here changes the system, because the participant does not get to.',
    },
    concept: [
      'Every objective in this course has been the same one: minimise the cost of serving demand, '
      + 'across the whole system, as though one organisation owned everything and wanted the cheapest '
      + 'outcome. That is the planner\'s question, and it is the right question for a regulator, a '
      + 'system operator or a ministry.',

      'Nobody who owns a power station has that question. They have a different one: given the prices '
      + 'this system produces, what do MY assets earn, and what should I do about it? The system\'s cost '
      + 'is not their concern and their profit is not the system\'s.',

      'The two are related but they are not the same, and the places they diverge are where most of the '
      + 'interesting behaviour in a power market lives — why a plant the system needs may not be worth '
      + 'owning, why a wind farm earns less per megawatt-hour than the average price, why anyone signs a '
      + 'long-term contract, and why a generator might bid above its own cost.',

      'The tools for this sit under Post-analysis, and they share one property worth knowing up front: '
      + 'none of them re-solves the system. The prices are the ones the planner\'s run produced. The '
      + 'participant is a price-taker looking at somebody else\'s answer.',
    ],
    explain: [
      'Load module 7\'s expanded year — 150 MW of wind, 24 of solar, the coal and oil that were there '
      + 'before, and a year of hourly prices.',

      'The one thing you have to add is ownership, because nothing in a PyPSA model knows who owns '
      + 'what. Open Build → Generators and add an `owner` column, then fill it in: `Nordwind` on wind_1 '
      + 'and solar_1, `Altkraft` on coal_1 and oil_1.',

      'That split is deliberate. Nordwind owns the two assets module 7 chose to BUILD, so they carry a '
      + 'capital charge. Altkraft owns the two that were already standing, whose capital is sunk and '
      + 'therefore costs nothing to keep. Same market, same prices, and — as you are about to find — '
      + 'opposite conclusions about whether generating is a good business.',

      'Leave the rest of the fleet unowned. An asset with no owner tag simply does not appear in these '
      + 'studies, which is a convenient way to scope them.',
    ],
    spotlights: [
      {
        selector: '[data-build-step="generators"]',
        buildStep: 'generators',
        title: 'The owner column',
        tab: 'Build',
        note: 'Add it with the column control — it is a plain text column and any name will do. PyPSA '
          + 'ignores it; these studies read it from the workbook.',
      },
    ],
    entries: [
      {
        field: 'generators.owner (wind_1, solar_1)',
        label: 'who owns this asset',
        value: 'Nordwind',
        why: 'The two assets module 7 built. They carry an annualised capital cost, which is what makes '
          + 'their profit an interesting number rather than an obvious one.',
      },
      {
        field: 'generators.owner (coal_1, oil_1)',
        label: 'who owns this asset',
        value: 'Altkraft',
        why: 'The incumbent thermal fleet. Already built, so no capital charge — the same market looks '
          + 'entirely different from behind these two rows.',
      },
    ],
    verify: [
      'The `generators` sheet has an `owner` column with two distinct values',
      'wind_1 and solar_1 read Nordwind; coal_1 and oil_1 read Altkraft',
      'You can say why these studies need a column PyPSA itself ignores',
      'You can state the participant\'s question in one sentence, and how it differs from the planner\'s',
    ],
    pitfalls: [
      'Spelling an owner differently on two rows. The tag is matched exactly, and a typo silently '
      + 'removes an asset from the analysis rather than erroring.',
    ],
  },

  {
    id: 'm14-capture-price',
    section: SECTION,
    title: 'Capture price: what your megawatt-hours actually sold for',
    tab: 'PostAnalysis',
    where: 'Post-analysis → Merchant (price-taker)',
    concept: [
      'Prices at Nordwind\'s two buses average 23.92 across the year, and the system as a whole averages '
      + '24.28. Either number describes the market. Neither describes what anybody earned, because '
      + 'nobody sells a flat megawatt across all 8,760 hours.',

      'What an asset earns per megawatt-hour is its capture price: revenue divided by energy, or '
      + 'equivalently the volume-weighted average of the price in the hours it actually ran. For a '
      + 'generator whose output correlates with high prices it is above the average; for one whose '
      + 'output arrives when prices are low it is below.',

      'Run the merchant study on Nordwind and the two renewables come out either side of the market. '
      + 'Wind captures 21.18 — 11% below the average — and solar captures 24.59, slightly above. Run it '
      + 'on Altkraft and coal captures 28.25, 18% above.',

      'The wind number has a name: cannibalisation. There is 150 MW of wind in a system whose peak '
      + 'demand is 175, so when the wind blows it is a large fraction of supply and it pushes the price '
      + 'down — in exactly the hours it is selling. It is competing with itself. Solar escapes this here '
      + 'only because there is 24 MW of it rather than 150.',
    ],
    explain: [
      'Go to Post-analysis → Merchant (price-taker). Its Mode row reads Optimise only until you switch it '
      + 'to Merchant analysis; do that, set Owner to Nordwind, leave Price signal on System price (LMP), '
      + 'and run the model.',

      'Read the three numbers that matter per asset: energy, revenue and capture price. Then compare '
      + 'each capture price against the 23.92 the same card reports — and note exactly what that figure '
      + 'is: the average price at THIS OWNER\'s buses, not the system\'s 24.28. The ratios are 0.885 '
      + 'for wind and 1.028 for solar.',

      'That ratio is the number a renewable developer lives on. It is the difference between a project '
      + 'that clears its cost of capital and one that does not, and it gets worse as more of the same '
      + 'technology is built — which is the mechanism, not a market failure.',

      'Then change the owner to Altkraft and run again. Coal captures 28.25, well above the average, '
      + 'because a mid-merit thermal unit runs precisely in the hours when something expensive is '
      + 'setting the price. Dispatchability is worth a premium, and this is what it looks like as a '
      + 'number.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="merchant"]',
        title: 'Merchant (price-taker)',
        tab: 'PostAnalysis',
        note: 'Under Post-analysis, not Settings — these studies read a solved run rather than change '
          + 'one. Its Mode row says Optimise only until you switch it to Merchant analysis.',
      },
    ],
    entries: [
      {
        field: 'Post-analysis → Merchant → Owner',
        value: 'Nordwind',
        why: 'Which owner tag to analyse. The study reports nothing at all for an owner with no '
          + 'matching assets, which is the usual cause of an empty card.',
      },
      {
        field: 'Post-analysis → Merchant → Price signal',
        value: 'System price (LMP)',
        why: 'Use the locational marginal prices the system solve produced — the standard merchant model. '
          + 'The alternative feeds in an exogenous price, for testing a project against somebody '
          + 'else\'s forward curve rather than your own model\'s.',
      },
    ],
    run: {
      label: 'Post-analysis → Merchant → Merchant analysis, then Run (once per owner)',
      detail: ['A small LP over the owner\'s assets only. Seconds, not minutes.'],
      expect: 'Nordwind: wind capture 21.18, solar 24.59. Altkraft: coal 28.25. System mean 23.92.',
    },
    verify: [
      'The card reports a mean price of 23.92 at Nordwind\'s buses, ranging 15.14 to 50.00',
      'wind_1 captures 21.18 and solar_1 captures 24.59',
      'coal_1 captures 28.25 under the Altkraft owner',
      'You can explain why the wind number is below the average and the coal number above it',
    ],
    pitfalls: [
      'Comparing capture prices between technologies as though they measured quality. They measure '
      + 'correlation with price, which is a property of the technology AND of how much of it there is.',
    ],
  },

  {
    id: 'm14-zero-profit',
    section: SECTION,
    title: 'The assets the planner built earn exactly their capital cost',
    tab: 'PostAnalysis',
    where: 'Post-analysis → Merchant, Nordwind',
    concept: [
      'Look at Nordwind\'s bottom line. Wind: revenue 12,784,479, capital charge 12,784,479, profit '
      + 'zero. Solar: revenue 855,604, capital charge 855,604, profit zero. Not approximately — exactly, '
      + 'to the last unit.',

      'That is not a coincidence and it is not a bug. It is the long-run equilibrium condition of a '
      + 'capacity-expansion model, and it falls out of the mathematics: at the optimum, the last '
      + 'megawatt of a technology the optimiser chose to build must be worth exactly what it cost, or it '
      + 'would have built more or less of it. The marginal prices that clear the energy balance are '
      + 'precisely the prices that make that true.',

      'Which produces the most-argued-about result in power economics. A market that pays generators '
      + 'the marginal price, in a system built to least cost, pays each asset exactly its costs and '
      + 'nothing above them — no return on capital, no risk premium, nothing to pay a board. The '
      + '"missing money" is not missing because the model is wrong; it is missing because that is what '
      + 'this market design pays.',

      'Real markets are not at a long-run optimum, which is why real generators sometimes make money. '
      + 'But a model that IS at the optimum will always show this, and reading it as a finding about '
      + 'your project rather than about the method is a mistake worth not making.',
    ],
    explain: [
      'Confirm the equality yourself on both assets rather than taking it on trust — revenue minus '
      + 'operating cost minus capital charge, to the unit.',

      'Then notice what it depends on. The capital charge is `capital_cost × p_nom_opt`, pro-rated to '
      + 'the modelled window, which is exactly the term module 7 put in the objective. The revenue is '
      + 'the capture price times the energy. The equality between them is the envelope theorem, and it '
      + 'holds only because the optimiser was free to choose the capacity.',

      'So ask the diagnostic question: what would break it? Fix the capacity instead of expanding it, '
      + 'and the equality goes. Add a constraint the optimum would not have chosen — a build limit, a '
      + 'policy target — and it goes. Change the discount rate after solving, and it goes. Every one of '
      + 'those is a real situation, and each is a reason a real asset earns more or less than its cost.',
    ],
    verify: [
      'wind_1 shows revenue and capital charge equal, and a profit of zero',
      'solar_1 shows the same',
      'You can explain why that is the expected result rather than a surprise',
      'You can name two things that would make an asset earn more than its cost',
    ],
    pitfalls: [
      'Reporting "renewables do not cover their costs in this market" from a zero. Zero profit means '
      + 'they cover them exactly — the number to worry about would be a negative one.',
    ],
  },

  {
    id: 'm14-sunk-capital',
    section: SECTION,
    title: 'The same market, from behind the incumbent\'s desk',
    tab: 'PostAnalysis',
    where: 'Post-analysis → Merchant, Altkraft',
    concept: [
      'Switch the owner to Altkraft and the market looks like a good business. Coal earns 3,090,548 of '
      + 'revenue against 2,188,000 of fuel, for a profit of 902,548 — and no capital charge at all, '
      + 'because that plant was already standing when the model started and its capital does not appear '
      + 'in the objective.',

      'Nothing about the market changed between these two views. What changed is which costs are on the '
      + 'books. Nordwind is paying for capital it committed; Altkraft\'s is sunk, which in economics '
      + 'means it is not a cost of anything any more — only the fuel is.',

      'This is why incumbents and entrants disagree so persistently about whether a market is working. '
      + 'Both are reading their own accounts correctly. A market can simultaneously be profitable for '
      + 'everything already built and incapable of financing anything new, and this pair of runs is that '
      + 'situation in about two hundred lines of workbook.',
    ],
    explain: [
      'Run the merchant study again with the owner set to Altkraft, and read the whole row for coal: '
      + '109,400 MWh, revenue 3,090,548, operating cost 2,188,000, capital charge zero, profit 902,548.',

      'One number there deserves a second look. Module 7\'s dispatch had coal generating 316,353 MWh, '
      + 'and the merchant view says 109,400. Both are right, and the difference is the whole point of a '
      + 'price-taker model: the system runs coal whenever coal is the cheapest way to serve load, '
      + 'including hours when the clearing price only just covers its fuel. An owner choosing for '
      + 'themselves sells only when the price beats their marginal cost, so two thirds of that '
      + 'generation earned nothing worth having.',

      'The profit is identical either way — 902,548 — because the hours the merchant view drops '
      + 'contributed nothing. What it changes is the story: "we generated 316 GWh" and "109 GWh of our '
      + 'output was profitable" describe the same plant.',
    ],
    verify: [
      'Altkraft\'s coal reports a profit of 902,548 with no capital charge',
      'The merchant energy of 109,400 MWh is below the 316,353 MWh the system dispatched',
      'You can explain why both energy figures are correct',
      'You can say why sunk capital does not appear in either number',
    ],
    pitfalls: [
      'Concluding that coal is more profitable than wind. It is more profitable ON THESE BOOKS, because '
      + 'one owner is paying for capital and the other is not.',
    ],
  },

  {
    id: 'm14-the-peaker-earns-nothing',
    section: SECTION,
    title: 'The plant the system needs and the market does not pay',
    tab: 'PostAnalysis',
    where: 'Post-analysis → Merchant, Altkraft',
    concept: [
      'Altkraft\'s other asset is the oil peaker: 40 MW, and in this year it never runs. Zero energy, '
      + 'zero revenue, zero profit. From the energy market it earns nothing whatsoever.',

      'Now put that beside module 12. The adequacy study on this same system found a loss-of-load '
      + 'expectation the system only just meets — and it counted the oil unit as available capacity when '
      + 'it did so. The plant contributes to reliability precisely by being there for the hours that did '
      + 'not happen this year.',

      'So the energy market pays for energy, and reliability is not energy. A unit that runs in the '
      + 'worst 20 hours of a bad decade earns nothing in the 8,760 hours of a normal one, and no amount '
      + 'of it being genuinely necessary changes what the price times the volume comes to.',

      'That gap is the entire reason capacity markets, strategic reserves and scarcity pricing exist. '
      + 'They are all ways of paying for the thing module 12 measured, which this module has just shown '
      + 'the energy market does not.',
    ],
    explain: [
      'Find oil_1 in the Altkraft results and confirm it: no energy, no revenue, no capture price at '
      + 'all — the card reports a blank rather than a zero, because dividing revenue by zero energy has '
      + 'no answer.',

      'Then do the thought experiment the module is built for. As Altkraft, would you keep it? It earns '
      + 'nothing and costs something to maintain, so the commercial answer is to close it. As the system '
      + 'operator who read module 12, would you want it closed? Its 40 MW is part of why the adequacy '
      + 'numbers are as good as they are.',

      'Both parties are being rational and they want opposite things. Every capacity mechanism ever '
      + 'designed is an attempt to make those two answers agree, and you now have both halves of the '
      + 'argument as numbers from one model.',
    ],
    verify: [
      'oil_1 reports zero energy and zero revenue, with no capture price',
      'You can say what module 12 credited that same unit with',
      'You can state the commercial case for closing it and the system case for keeping it',
      'You can name one mechanism designed to reconcile them',
    ],
    pitfalls: [
      'Reading "never runs" as "not needed". It ran in none of the 8,760 hours of THIS weather year, '
      + 'against this demand, with everything else available — which is exactly the case module 12 '
      + 'showed is the easy one.',
    ],
  },

  {
    id: 'm14-a-ppa-is-a-hedge',
    section: SECTION,
    title: 'A PPA: selling the price risk rather than the power',
    tab: 'PostAnalysis',
    where: 'Post-analysis → PPA contract',
    concept: [
      'A power purchase agreement fixes a price for a volume over a term. It does not move any '
      + 'electricity — the plant still sells into the market and the buyer still buys from it. What '
      + 'changes hands is the difference between the strike price and the spot price, so a PPA is a '
      + 'financial hedge wearing a physical name.',

      'Run one for Nordwind at a strike of 25 and the numbers say: 638,440 MWh under contract, an '
      + 'average spot price of 21.36 across those volumes, and a settlement of 2,320,908 to the seller. '
      + 'The buyer pays exactly that: it is zero-sum by construction, which the card reports as equal '
      + 'and opposite nets.',

      'The number to look at twice is the 21.36. It is not the system average of 24.28 — it is '
      + 'Nordwind\'s capture price across its portfolio, because a generation-volume PPA settles on what '
      + 'the generator actually produced, hour by hour. A wind PPA is priced against wind\'s capture '
      + 'price, and quoting the market average when negotiating one is how developers lose money '
      + 'politely.',

      'Which is also why a strike of 25 is above the spot average and the seller still gains. The buyer '
      + 'is not being generous; they are buying certainty, and 3.64 per MWh is what this contract '
      + 'charges for it in this year.',
    ],
    explain: [
      'Open Post-analysis → PPA contract, set Mode to Value PPA, Volume to Owner generation, Owner to '
      + 'Nordwind and Strike price to 25, then run.',

      'Read the settlement from both sides. Contract value 15,960,990, spot value 13,640,082, seller '
      + 'net +2,320,908, buyer net −2,320,908. Check the identity yourself: energy × (strike − average '
      + 'spot) = 638,440 × (25 − 21.36), which recovers the settlement to rounding.',

      'Then reason about the strike. At 21.36 the contract is worth nothing to either party in this '
      + 'year. Below it, the buyer gains and the seller pays. That single break-even number is what a '
      + 'PPA negotiation is actually about, and it moves with every assumption in the model that '
      + 'produced the price — which is the connection back to module 9 and module 13.',

      'And note what the contract does NOT do. It does not change dispatch, the system cost, the price '
      + 'or anybody else\'s revenue. Try it: the system results either side of a PPA are identical. '
      + 'Hedges move money between two parties and nothing else.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="ppa"]',
        title: 'PPA contract',
        tab: 'PostAnalysis',
        note: 'Two below the merchant study. Volume type decides what is under contract — the '
          + 'generator\'s own output, or a flat block regardless of what it produced.',
      },
    ],
    entries: [
      {
        field: 'Post-analysis → PPA contract → Volume',
        value: 'Owner generation',
        why: 'Owner generation settles on what the plant actually produced, so the contract inherits its shape '
          + 'and its capture price. A flat block instead settles on a constant MW and leaves the '
          + 'generator carrying the shape risk itself — a materially different contract.',
      },
      {
        field: 'Post-analysis → PPA contract → Strike price (/MWh)',
        value: '25',
        why: 'The fixed price. Set it to the capture price of 21.36 and the settlement is zero; every '
          + 'unit above that is what the buyer pays for certainty.',
      },
    ],
    run: {
      label: 'Post-analysis → PPA contract → Value PPA, then Run',
      detail: ['Pure post-processing on the solved run. Instant.'],
      expect: '638,440 MWh at an average spot of 21.36, with a seller net of +2,320,908.',
    },
    verify: [
      'The seller net is +2,320,908 and the buyer net is exactly its negative',
      'The average spot price is 21.36 — Nordwind\'s capture, not the system\'s 23.92',
      'energy × (strike − avg spot) recovers the settlement',
      'You can say what strike would make this contract worth nothing this year',
    ],
    pitfalls: [
      'Pricing a PPA off the system average. A generation PPA settles on the generator\'s own hours, '
      + 'and for wind that is systematically below the average.',
      'Expecting the system results to change. They do not, and a run where they did would mean the '
      + 'contract had been modelled as something other than a hedge.',
    ],
  },

  {
    id: 'm14-market-power',
    section: SECTION,
    title: 'Bidding above cost, and what it does to everybody else',
    tab: 'PostAnalysis',
    where: 'Post-analysis → Bid strategy (market power)',
    concept: [
      'Every module so far has assumed generators offer at their marginal cost. That is what makes the '
      + 'least-cost dispatch and the competitive price. It is also an assumption, and the one that a '
      + 'participant with any market power will not honour.',

      'The bid-strategy study asks what happens if they do not. Give Altkraft a 50% markup on coal — it '
      + 'offers at 30 instead of 20 — and re-clear the market. Altkraft\'s profit goes from 902,548 to '
      + '4,269,487, a gain of 3,366,939, and its capture price rises from 22.85 to 33.50.',

      'The striking part is the volume: 316,353 MWh both times, unchanged to the last megawatt-hour. '
      + 'Coal did not sell less by bidding higher. It is infra-marginal and pivotal — the system cannot '
      + 'serve its load without it, so raising the offer does not lose the business, it just raises the '
      + 'price everyone pays.',

      'And everyone does pay: the system average price goes from 24.28 to 30.71, a 26% increase, on a '
      + 'system where nothing physical changed. That transfer, from consumers to one generator, with no '
      + 'change in what was produced or what it cost, is what market power means and why market monitors '
      + 'exist.',
    ],
    explain: [
      'Open Post-analysis → Bid strategy (market power), set Mode to Simulate markup, Owner to '
      + 'Altkraft, Markup type to Percent and Markup (%) to 50, then run. The study clears the market '
      + 'twice — once at true costs, once at the marked-up offer — and reports both.',

      'Read the four numbers side by side: baseline profit 902,548 against strategic 4,269,487, and '
      + 'baseline system price 24.28 against strategic 30.71. Then read the energy, which does not move.',

      'Then check the profit is measured honestly. The strategic profit is computed at Altkraft\'s TRUE '
      + 'costs against the new clearing price — a generator does not actually burn more expensive coal '
      + 'because it offered a higher number. That distinction is what makes the comparison meaningful '
      + 'rather than circular.',

      'Finally, try a markup where the unit is not pivotal — a smaller owner, or a much larger one that '
      + 'prices itself out of merit — and watch the gain disappear or reverse. Market power is not a '
      + 'property of wanting more money; it is a property of the system needing you.',
    ],
    spotlights: [
      {
        selector: '[data-settings-section="bidding"]',
        title: 'Bid strategy (market power)',
        tab: 'PostAnalysis',
        note: 'The only study in this module that re-clears the market. It changes what the owner '
          + 'OFFERS, never what the fleet is or what it costs.',
      },
    ],
    entries: [
      {
        field: 'Post-analysis → Bid strategy → Owner',
        value: 'Altkraft',
        why: 'The incumbent, whose coal unit is mid-merit and pivotal. Running it for Nordwind instead '
          + 'is instructive: a zero-marginal-cost price-taker has almost nothing to mark up.',
      },
      {
        field: 'Post-analysis → Bid strategy → Markup (%)',
        value: '50',
        unit: 'per cent above true cost',
        why: 'Fifty per cent above true cost — 20 offered as 30. Large enough to move the clearing price and small '
          + 'enough that the unit stays in merit, which is the interesting regime.',
      },
    ],
    run: {
      label: 'Post-analysis → Bid strategy → Simulate markup, then Run',
      detail: ['One extra market clearing over the full year. About a minute.'],
      expect: 'Profit 902,548 → 4,269,487, system average price 24.28 → 30.71, energy unchanged.',
    },
    verify: [
      'Altkraft\'s profit rises to 4,269,487 — a gain of 3,366,939',
      'The system average price rises from 24.28 to 30.71',
      'Coal\'s energy is unchanged at 316,353 MWh',
      'You can explain why bidding higher did not cost it any volume',
    ],
    pitfalls: [
      'Treating this as a recommendation. It is a diagnostic — it measures how exposed a market is to '
      + 'one participant, which is what a monitor or a regulator wants to know.',
      'Assuming a bigger markup is always better for the owner. Past the point where the unit leaves '
      + 'merit the volume collapses, and the study will show it.',
    ],
  },

  {
    id: 'm14-two-books-one-system',
    section: SECTION,
    title: 'Reconciling the two views',
    tab: 'PostAnalysis',
    where: 'The numbers you now have',
    concept: [
      'Lay the two accounts side by side. The planner ran a system costing about 25.6 million a year '
      + 'and pronounced it optimal. The participants read the same year and reported: Nordwind exactly '
      + 'breaking even on 13.6 million of revenue, Altkraft making 902,548, and a 40 MW peaker earning '
      + 'nothing at all.',

      'None of those contradicts the planner\'s answer. They are the same solution described in a '
      + 'different accounting frame — and the frame determines which questions you can even ask. The '
      + 'planner cannot ask whether anybody will finance the wind farm. The participant cannot ask '
      + 'whether the system is adequate.',

      'The practical consequence is that a modelling study has to declare whose books it is keeping. '
      + '"Is this the least-cost system?" and "will this get built?" are different questions with '
      + 'different answers, and a study that slides between them without saying so is the commonest '
      + 'failure in this field.',
    ],
    explain: [
      'Write out the reconciliation as a table: for each of the four owned assets, its energy, capture '
      + 'price, revenue, costs and profit, and next to that what the planner\'s run said about it.',

      'Then find the three places the two views disagree, because each is a real phenomenon rather than '
      + 'an inconsistency. Coal\'s energy differs, because the planner dispatches on system cost and the '
      + 'owner on their own margin. Wind\'s profit is zero, because the planner sized it. And the '
      + 'peaker\'s value is entirely outside the energy market.',

      'Finally, decide what you would tell each party. Nordwind needs to know that its returns depend on '
      + 'capture price rather than average price, and that capture price falls as more wind is built. '
      + 'Altkraft needs to know that its profit is sunk-capital accounting and would vanish for a new '
      + 'build. The system operator needs to know that the plant keeping the lights on in the bad year '
      + 'has no commercial reason to exist.',
    ],
    verify: [
      'You have the four-asset table written out',
      'You can name the three places the two views disagree and why each is real',
      'You can say what question each frame cannot answer',
      'You can state what you would tell each of the three parties',
    ],
    pitfalls: [
      'Using participant profitability to judge a system plan, or system cost to judge a project. Each '
      + 'is the wrong instrument for the other question.',
    ],
  },

  {
    id: 'm14-what-this-view-cannot-see',
    section: SECTION,
    title: 'What the participant view cannot see',
    tab: 'PostAnalysis',
    where: 'Reading critically',
    concept: [
      'These studies are post-processing on one solved year, and every limitation follows from that.',

      'They price at the model\'s marginal prices, which are a competitive-equilibrium construct. Real '
      + 'markets have bid-ask spreads, balancing costs, imbalance exposure and contracts for '
      + 'differences, none of which appear here. A capture price from a model is a first-order estimate, '
      + 'not a revenue forecast.',

      'They see one weather year, so every capture price and every settlement is conditional on that '
      + 'year\'s wind and demand. Module 12 measured what a single year hides for reliability; the same '
      + 'applies to revenue, and more sharply, because revenue is concentrated in the extreme hours '
      + 'that vary most between years.',

      'They assume the participant is a price-taker — except in the bid-strategy study, which assumes '
      + 'the opposite and nothing in between. Real strategic behaviour is a repeated game with '
      + 'competitors who also respond, and a single markup against a fixed counterfactual is the '
      + 'simplest possible model of it.',

      'And they are static. Nothing here models entry, exit, retirement, or the fact that Nordwind\'s '
      + 'zero profit would in reality stop the next wind farm being built and thereby raise everybody '
      + 'else\'s capture price. The feedback that makes markets work is exactly what a single solved '
      + 'year cannot contain.',
    ],
    explain: [
      'Write down the four limits — market realism, one weather year, the price-taker assumption, and '
      + 'no entry or exit — with one line each on what it would change.',

      'Then re-read the module\'s headline numbers through them. The 21.18 capture price is this year\'s. '
      + 'The 2,320,908 PPA settlement is this year\'s. The 26% price increase from a markup assumes '
      + 'nobody responds. All three are correct answers to precisely stated questions and none is a '
      + 'forecast.',

      'That is not a reason to distrust them. It is the reason to state the question exactly, which is '
      + 'the same discipline module 9 asked for and the only one that survives contact with somebody '
      + 'who disagrees with your result.',
    ],
    verify: [
      'You have the four limitations written down',
      'You can say which of the module\'s numbers is most sensitive to the weather year and why',
      'You can say what would happen to capture prices if Nordwind\'s zero profit stopped further build',
      'You can distinguish a modelled capture price from a revenue forecast',
    ],
    pitfalls: [
      'Quoting a capture price as a business case. It is one year, one price model, no balancing costs '
      + 'and no contracts — the direction is robust, the level is not.',
    ],
  },

  {
    id: 'm14-both-sides',
    section: SECTION,
    title: 'Both sides of every question',
    tab: 'Analytics',
    where: 'Everything you have built',
    concept: [
      'Fourteen modules, one model, and an idea that only arrives this late: almost every question '
      + 'in this field has two correct answers, and which one you get depends on whose books you keep.',

      'A congested line is a constraint to a planner and a revenue stream to whoever owns the cheap side '
      + 'of it. A carbon price is a policy instrument and a cost line. Storage is a flexibility resource '
      + 'and an arbitrage business. A peaker is a reliability asset and a stranded one. Curtailed wind is '
      + 'a system inefficiency and somebody\'s lost invoice.',

      'The models in this course can answer either version. What they cannot do is tell you which one '
      + 'you were asked — and getting that wrong is a bigger error than any of the modelling mistakes '
      + 'the previous modules taught you to avoid.',
    ],
    explain: [
      'Take the five questions from module 13 and add the sixth this module contributed.',

      'What is the objective actually minimising? What is the time axis, and what does it hide? Which '
      + 'constraints are binding, and what would relaxing them cost? What is the range around the '
      + 'answer, with its conditions? Where did the demand come from? And — whose question is this, and '
      + 'whose books does the answer belong to?',

      'Take a model you did not write and answer all six about it. Where you cannot, you have found '
      + 'either something to go and read or something the study never established — and telling those '
      + 'two apart is most of what expertise in this field consists of.',

      'One question is still missing, and module 15 is about it: every price in this module assumed a '
      + 'particular market design, and changing it changes every number you just read.',
    ],
    verify: [
      'You can state all six questions without looking them up',
      'You can give two correct and opposite readings of one result from an earlier module',
      'You can answer all six about a model somebody else built',
    ],
    pitfalls: [
      'Answering the question you find most interesting rather than the one you were asked. It is the '
      + 'easiest mistake in the field and the hardest to notice from inside.',
    ],
  },
];
