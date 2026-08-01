/**
 * External tab-module host — mounts a module's entry into the workspace.
 *
 * The entry file is evaluated as CommonJS (same trusted-local-code stance as
 * `lib/plugins/runtime.ts`) and its `mount(el, ctx)` renders the tab. The
 * module owns everything inside `el`; Ragnarok owns everything outside it. A
 * throwing module renders an error card instead of taking the app down.
 */
import React, { useEffect, useRef, useState } from 'react';
import { API_BASE } from 'lib/constants';
import { DEFAULT_SESSION_ID } from 'lib/api/session';
import type { ExternalModuleExports, ExternalTabModule } from './types';

function evalEntry(mod: ExternalTabModule): ExternalModuleExports {
  const entry = mod.manifest.entry ?? 'index.js';
  const src = mod.files[entry];
  if (typeof src !== 'string') {
    throw new Error(`Entry file "${entry}" not found in the installed package.`);
  }
  const moduleObj: { exports: Record<string, unknown> } = { exports: {} };
  // Trusted local code (single-user app, user-installed) — same stance as the
  // plugin runtime. Only module/exports are injected.
  // eslint-disable-next-line no-new-func
  const factory = new Function('module', 'exports', src);
  factory(moduleObj, moduleObj.exports);
  return moduleObj.exports as ExternalModuleExports;
}

export function ExternalModuleHost({ module: mod }: { module: ExternalTabModule }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return undefined;
    el.innerHTML = '';
    setError(null);
    let cleanup: (() => void) | void;
    try {
      const exports = evalEntry(mod);
      if (typeof exports.mount !== 'function') {
        throw new Error('The module exports no mount(el, ctx) function.');
      }
      cleanup = exports.mount(el, { apiBase: API_BASE, sessionId: DEFAULT_SESSION_ID });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    return () => {
      try {
        if (typeof cleanup === 'function') cleanup();
      } catch {
        /* a failing unmount must not break tab switching */
      }
      el.innerHTML = '';
    };
  }, [mod]);

  return (
    <div className="external-module-view">
      {error && (
        <div className="external-module-error">
          <h3>Module “{mod.manifest.label}” failed</h3>
          <p>{error}</p>
          <p>Fix the module and re-add it from Settings → Modules (re-adding the same id updates it in place).</p>
        </div>
      )}
      <div ref={hostRef} className="external-module-mount" />
    </div>
  );
}
