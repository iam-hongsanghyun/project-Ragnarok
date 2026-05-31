/**
 * Appearance section — carrier colors + ordering.
 *
 * A single vertical list (one carrier per row). Reorder by dragging a row;
 * the order is the carrier dispatch/legend order used across the app. Uses
 * the full panel height rather than a fixed scroll box.
 */
import React, { useState } from 'react';
import { WorkbookModel } from 'lib/types';
import { resolvedColor, stringValue } from 'lib/utils/helpers';

export interface AppearanceSectionProps {
  model: WorkbookModel;
  onCarrierColorChange: (rowIndex: number, color: string) => void;
  onCarrierReorder: (fromIndex: number, toIndex: number) => void;
}

export function AppearanceSection({ model, onCarrierColorChange, onCarrierReorder }: AppearanceSectionProps) {
  const carrierRows = model.carriers
    .map((row, index) => ({ row, index, name: stringValue(row.name) }))
    .filter((item) => item.name);

  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  const handleDrop = (toIndex: number) => {
    if (dragIndex !== null && dragIndex !== toIndex) onCarrierReorder(dragIndex, toIndex);
    setDragIndex(null);
    setOverIndex(null);
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carrier colors</h3>
        <p>Default colors for each carrier across maps, legends, and charts. Drag a row to reorder.</p>
      </header>
      <div className="sg-color-list">
        {carrierRows.map(({ row, index, name }) => (
          <div
            key={`carrier-${name}-${index}`}
            className={`sg-color-item${overIndex === index && dragIndex !== null ? ' sg-color-item--over' : ''}${dragIndex === index ? ' sg-color-item--dragging' : ''}`}
            draggable
            onDragStart={() => setDragIndex(index)}
            onDragOver={(e) => { e.preventDefault(); if (overIndex !== index) setOverIndex(index); }}
            onDrop={(e) => { e.preventDefault(); handleDrop(index); }}
            onDragEnd={() => { setDragIndex(null); setOverIndex(null); }}
          >
            <span className="sg-color-grip" aria-hidden="true">⋮⋮</span>
            <input
              type="color"
              className="sg-color-input"
              value={resolvedColor(row.color, row.name)}
              onChange={(e) => onCarrierColorChange(index, e.target.value)}
            />
            <span className="sg-color-name" title={name}>{name}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
