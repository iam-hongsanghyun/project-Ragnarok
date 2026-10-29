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

/** Set a text / number input or a select the way a user would, so React's onChange fires. */
export async function setValue(node: HTMLInputElement | HTMLSelectElement | null, value: string): Promise<void> {
  if (!node) throw new Error('setValue: element not found');
  const proto = node instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  await act(async () => {
    setter?.call(node, value);
    node.dispatchEvent(new Event(node instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  });
  await settle();
}

/** Put a file into a file input and fire change. */
export async function chooseFile(node: HTMLInputElement | null, file: File): Promise<void> {
  if (!node) throw new Error('chooseFile: element not found');
  Object.defineProperty(node, 'files', { value: [file], configurable: true });
  await act(async () => { node.dispatchEvent(new Event('change', { bubbles: true })); });
  await settle();
}

/** Replace `fetch` with a stub answering `reply(url, body)` as JSON; returns the recorded calls. */
export function stubFetch(
  reply: (url: string, body: Record<string, unknown>) => { status?: number; json: unknown },
): Array<{ url: string; body: Record<string, unknown> }> {
  const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
  (globalThis as { fetch: unknown }).fetch = async (input: unknown, init?: { body?: unknown }) => {
    const url = String(input);
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : {};
    calls.push({ url, body });
    const { status = 200, json } = reply(url, body);
    return { ok: status >= 200 && status < 300, status, json: async () => json } as Response;
  };
  return calls;
}
