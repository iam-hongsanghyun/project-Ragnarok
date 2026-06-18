import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * App-styled replacement for the browser's native `alert` / `confirm` /
 * `prompt`. Renders a single modal that slides in from the top, dims the page,
 * and sits above every other overlay (see `--z-dialog` in index.css). Imperative
 * API via {@link useDialog} so call sites read like the natives they replace:
 *
 *   const { confirm } = useDialog();
 *   if (await confirm('Delete this row?', { danger: true })) …
 */

type DialogKind = 'alert' | 'confirm' | 'prompt';

export interface DialogOptions {
  /** Bold heading above the message. */
  title?: string;
  /** Primary button label (default: "OK"). */
  confirmText?: string;
  /** Secondary button label (default: "Cancel"). */
  cancelText?: string;
  /** Style the primary button as destructive. */
  danger?: boolean;
  /** prompt only — initial input value. */
  defaultValue?: string;
  /** prompt only — input placeholder. */
  placeholder?: string;
}

type Resolve = (value: boolean | string | null | undefined) => void;

interface DialogState extends DialogOptions {
  kind: DialogKind;
  message: string;
  resolve: Resolve;
}

interface DialogContextValue {
  alert: (message: string, options?: DialogOptions) => Promise<void>;
  confirm: (message: string, options?: DialogOptions) => Promise<boolean>;
  prompt: (message: string, options?: DialogOptions) => Promise<string | null>;
}

const noopCtx: DialogContextValue = {
  alert: async () => {},
  confirm: async () => false,
  prompt: async () => null,
};

const DialogContext = createContext<DialogContextValue>(noopCtx);

export function useDialog(): DialogContextValue {
  return useContext(DialogContext);
}

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const [dialog, setDialog] = useState<DialogState | null>(null);

  const open = useCallback(
    (kind: DialogKind, message: string, options?: DialogOptions): Promise<boolean | string | null | undefined> =>
      new Promise((resolve) => setDialog({ kind, message, ...options, resolve })),
    [],
  );

  // Stable API identity so consumers don't re-render on each open.
  const api = useRef<DialogContextValue>({
    alert: (m, o) => open('alert', m, o).then(() => undefined),
    confirm: (m, o) => open('confirm', m, o).then((v) => v === true),
    prompt: (m, o) => open('prompt', m, o).then((v) => (typeof v === 'string' ? v : null)),
  });

  const close = useCallback((value: boolean | string | null | undefined) => {
    setDialog((cur) => {
      cur?.resolve(value);
      return null;
    });
  }, []);

  return (
    <DialogContext.Provider value={api.current}>
      {children}
      {dialog && createPortal(<DialogModal dialog={dialog} onClose={close} />, document.body)}
    </DialogContext.Provider>
  );
}

function DialogModal({ dialog, onClose }: { dialog: DialogState; onClose: (v: boolean | string | null | undefined) => void }) {
  const { kind, message, title, confirmText, cancelText, danger, defaultValue, placeholder } = dialog;
  const [value, setValue] = useState(defaultValue ?? '');
  const [visible, setVisible] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Cancel resolves to the "negative" value for each kind.
  const cancel = useCallback(() => onClose(kind === 'prompt' ? null : kind === 'confirm' ? false : undefined), [kind, onClose]);
  const accept = useCallback(() => onClose(kind === 'prompt' ? value : kind === 'confirm' ? true : undefined), [kind, value, onClose]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true));
    (kind === 'prompt' ? inputRef.current : confirmRef.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); cancel(); }
      else if (e.key === 'Enter' && kind !== 'prompt') { e.preventDefault(); accept(); }
    };
    window.addEventListener('keydown', onKey);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('keydown', onKey); };
  }, [kind, cancel, accept]);

  return (
    <div className="app-dialog-backdrop" onMouseDown={cancel} role="presentation">
      <div
        className={`app-dialog${visible ? ' app-dialog--visible' : ''}`}
        role={kind === 'alert' ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-label={title ?? message}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {title && <div className="app-dialog-title">{title}</div>}
        <div className="app-dialog-message">{message}</div>
        {kind === 'prompt' && (
          <input
            ref={inputRef}
            className="app-dialog-input"
            value={value}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); accept(); } }}
          />
        )}
        <div className="app-dialog-actions">
          {kind !== 'alert' && (
            <button className="tb-btn tb-btn--muted" onMouseDown={(e) => e.preventDefault()} onClick={cancel}>
              {cancelText ?? 'Cancel'}
            </button>
          )}
          <button
            ref={confirmRef}
            className={`tb-btn ${danger ? 'tb-btn--danger' : 'tb-btn--active'}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={accept}
          >
            {confirmText ?? 'OK'}
          </button>
        </div>
      </div>
    </div>
  );
}
