/**
 * Minimal DOM test harness (React 19 `act` + `createRoot` on jsdom) for components that fetch or react to clicks.
 * Static markup (`renderToStaticMarkup`) stays the tool for pure render tests; this is for effects and interaction.
 */
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export interface Mounted {
  container: HTMLElement;
  unmount: () => Promise<void>;
}

const roots: Root[] = [];

export async function mount(element: React.ReactElement): Promise<Mounted> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => { root.render(element); });
  return {
    container,
    unmount: async () => { await act(async () => { root.unmount(); }); container.remove(); },
  };
}

/** Let pending promises (mocked fetches) settle and the resulting state render. */
export async function settle(): Promise<void> {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

export async function click(node: Element | null): Promise<void> {
  if (!node) throw new Error('click: element not found');
  await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  await settle();
}

export function button(container: HTMLElement, label: string | RegExp): HTMLButtonElement | null {
  const match = (t: string) => (typeof label === 'string' ? t.trim() === label : label.test(t));
  return Array.from(container.querySelectorAll('button')).find((b) => match(b.textContent ?? '')) ?? null;
}
