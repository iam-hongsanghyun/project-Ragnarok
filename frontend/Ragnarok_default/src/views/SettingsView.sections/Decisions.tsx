/**
 * Decisions launcher (DW1) — the financial-first home for the Market tab.
 *
 * Frames the tool around money questions ("profit of gas → solar?", "is a
 * battery viable?", …) instead of component editing. Each card enables the
 * matching workflow's config and jumps to its setup; after a run, that
 * workflow's card leads with the money (NPV / IRR / payback / Δprofit).
 */
import React from 'react';
import {
  AssetSwapConfig,
  BidStrategyConfig,
  EssConfig,
  MerchantConfig,
} from 'lib/types';

export interface DecisionsSectionProps {
  assetSwapConfig: AssetSwapConfig;
  onAssetSwapConfigChange: (config: AssetSwapConfig) => void;
  essConfig: EssConfig;
  onEssConfigChange: (config: EssConfig) => void;
  merchantConfig: MerchantConfig;
  onMerchantConfigChange: (config: MerchantConfig) => void;
  bidStrategyConfig: BidStrategyConfig;
  onBidStrategyConfigChange: (config: BidStrategyConfig) => void;
  onNavigate: (section: string) => void;
}

export function DecisionsSection(props: DecisionsSectionProps) {
  interface UseCase {
    question: string;
    detail: string;
    answer: string;
    setup: () => void;
  }
  const cases: UseCase[] = [
    {
      question: 'What’s the profit of switching gas → solar?',
      detail: 'Retire a carrier and replace it 1:1 with another; solve before vs after.',
      answer: 'ΔNPV · Δemissions · payback',
      setup: () => { props.onAssetSwapConfigChange({ ...props.assetSwapConfig, enabled: true }); props.onNavigate('assetSwap'); },
    },
    {
      question: 'Is a battery business viable here, and at what size?',
      detail: 'Sweep storage sizes; price each against the market as energy arbitrage.',
      answer: 'NPV / IRR / payback by size',
      setup: () => { props.onEssConfigChange({ ...props.essConfig, enabled: true }); props.onNavigate('ess'); },
    },
    {
      question: 'What’s the most profit for one owner?',
      detail: 'Optimise an owner’s assets against the market price (price-taker).',
      answer: 'owner revenue & profit',
      setup: () => { props.onMerchantConfigChange({ ...props.merchantConfig, enabled: true }); props.onNavigate('merchant'); },
    },
    {
      question: 'Does bidding above cost pay off?',
      detail: 'Raise an owner’s offers by a markup and re-clear the market.',
      answer: 'Δprofit vs price-taker',
      setup: () => { props.onBidStrategyConfigChange({ ...props.bidStrategyConfig, enabled: true, mode: 'fixed' }); props.onNavigate('bidding'); },
    },
    {
      question: 'What’s the profit-maximising bid?',
      detail: 'Sweep the markup and find the best-response bid against the fringe.',
      answer: 'optimal markup + curve',
      setup: () => { props.onBidStrategyConfigChange({ ...props.bidStrategyConfig, enabled: true, mode: 'optimal' }); props.onNavigate('bidding'); },
    },
  ];

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Decisions</h3>
        <p>
          Start from a money question. Each launches a workflow that answers it as
          a number after your next run — leading with NPV, IRR, payback or profit,
          not MW. Pick one to set it up, then hit Run.
        </p>
      </header>

      <div className="decision-grid">
        {cases.map((c) => (
          <div key={c.question} className="decision-card">
            <div className="decision-card-q">{c.question}</div>
            <div className="decision-card-detail">{c.detail}</div>
            <div className="decision-card-answer">→ {c.answer}</div>
            <button className="tb-btn tb-btn--active decision-card-btn" onClick={c.setup}>Set up →</button>
          </div>
        ))}
      </div>
    </section>
  );
}
