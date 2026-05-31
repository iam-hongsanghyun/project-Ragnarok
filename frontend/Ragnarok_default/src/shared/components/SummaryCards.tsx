import React from 'react';
import { SummaryItem } from 'lib/types';

export function SummaryCards({ items }: { items: SummaryItem[] }) {
  return (
    <div className="analytics-summary">
      {items.map((item) => (
        <div key={item.label} className="summary-card">
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          <p>{item.detail}</p>
        </div>
      ))}
    </div>
  );
}
