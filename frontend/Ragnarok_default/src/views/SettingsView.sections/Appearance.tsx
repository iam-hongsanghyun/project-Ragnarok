/**
 * Appearance section — carrier colors + ordering.
 */
import React from 'react';
import { WorkbookModel } from '../../shared/types';
import { resolvedColor, stringValue } from '../../shared/utils/helpers';

export interface AppearanceSectionProps {
  model: WorkbookModel;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierMove: (rowIndex: number, direction: -1 | 1) => void;
}

export function AppearanceSection({ model, onCarrierColorChange, onCarrierMove }: AppearanceSectionProps) {
  const carrierRows = model.carriers
    .map((row, index) => ({ row, index, name: stringValue(row.name) }))
    .filter((item) => item.name);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carrier colors</h3>
        <p>Default colors for each carrier across maps, legends, and charts.</p>
      </header>
      <div className="sg-color-list">
        {carrierRows.map(({ row, index, name }) => (
          <div key={`carrier-${name}-${index}`} className="sg-color-item">
            <span className="sg-color-name" title={name}>{name}</span>
            <div className="sg-color-actions">
              <button
                className="tb-btn tb-btn--muted sg-order-btn"
                disabled={index === 0}
                onClick={() => onCarrierMove(index, -1)}
                title="Move up"
              >
                ^
              </button>
              <button
                className="tb-btn tb-btn--muted sg-order-btn"
                disabled={index === carrierRows.length - 1}
                onClick={() => onCarrierMove(index, 1)}
                title="Move down"
              >
                v
              </button>
            </div>
            <input
              type="color"
              className="sg-color-input"
              value={resolvedColor(row.color, row.name)}
              onChange={(e) => onCarrierColorChange(index, e.target.value)}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
