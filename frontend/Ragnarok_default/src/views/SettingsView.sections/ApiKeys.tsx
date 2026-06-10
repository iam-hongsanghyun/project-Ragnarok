/**
 * API keys section (BYOK — bring your own key).
 *
 * Some data sources (ENTSO-E, EIA, …) gate their API behind a free
 * per-user token. The user types theirs here; it's stored in the
 * browser (localStorage, `ragnarok:secret:<name>`) and sent in the
 * request body of `/api/import/run` only for fetches that need it. The
 * backend uses it for that one request and never persists or logs it.
 *
 * Security model (see the discussion in the importer router): the key is
 * protected in transit by HTTPS — there is deliberately NO app-level
 * encryption, which over TLS would be theater (the encryption key would
 * itself ship in the bundle). Keep production behind HTTPS.
 *
 * The catalog below lists the providers Ragnarok knows how to use. A key
 * appears here whenever a registered importer declares it in
 * `requires_secrets`.
 */
import React, { useEffect, useState } from 'react';

import { getSecret, setUserSecret, clearSecret, putServerSecret, deleteServerSecret, listServerSecrets } from 'lib/api/secrets';

interface ApiKeyProvider {
  /** Matches the importer's `requires_secrets` entry + the storage slug. */
  name: string;
  label: string;
  help: string;
  signupUrl: string;
}

const PROVIDERS: ApiKeyProvider[] = [
  {
    name: 'eia_key',
    label: 'EIA (US Energy Information Administration)',
    help: 'Free key for US hourly demand / generation (Form-930). Public domain data.',
    signupUrl: 'https://www.eia.gov/opendata/register.php',
  },
  {
    name: 'entsoe_key',
    label: 'ENTSO-E Transparency Platform',
    help:
      'Free token for EU national hourly load. Register, email ' +
      'transparency@entsoe.eu for API access, then generate the token under ' +
      'My Account Settings.',
    signupUrl:
      'https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token',
  },
];

function ApiKeyRow({ provider }: { provider: ApiKeyProvider }) {
  const [value, setValue] = useState<string>(() => getSecret(provider.name) ?? '');
  const [saved, setSaved] = useState<boolean>(() => !!getSecret(provider.name));
  const [onServer, setOnServer] = useState(false);
  const [reveal, setReveal] = useState(false);

  // A key may already live on the SERVER (typed earlier, possibly from another
  // browser, or provided via the backend's env) — show that state.
  useEffect(() => {
    let cancelled = false;
    void listServerSecrets().then(({ stored, env }) => {
      if (!cancelled) setOnServer(stored.includes(provider.name) || env.includes(provider.name));
    });
    return () => { cancelled = true; };
  }, [provider.name]);

  const save = () => {
    setUserSecret(provider.name, value);
    setSaved(!!value.trim());
    // RECORD on the backend too: the key then works from any device and the
    // browser no longer needs to send it with each import.
    void putServerSecret(provider.name, value.trim()).then((ok) => { if (ok) setOnServer(!!value.trim()); });
  };
  const clear = () => {
    clearSecret(provider.name);
    setValue('');
    setSaved(false);
    void deleteServerSecret(provider.name).then((ok) => { if (ok) setOnServer(false); });
  };

  return (
    <div className="api-key-row">
      <div className="api-key-row__head">
        <span className="api-key-row__label">{provider.label}</span>
        <span className={`api-key-row__badge${saved || onServer ? ' is-set' : ''}`}>
          {onServer ? 'On server' : saved ? 'Key set' : 'Not set'}
        </span>
      </div>
      <p className="api-key-row__help">
        {provider.help}{' '}
        <a href={provider.signupUrl} target="_blank" rel="noreferrer">
          Get a key
        </a>
      </p>
      <div className="api-key-row__controls">
        <input
          type={reveal ? 'text' : 'password'}
          className="api-key-row__input"
          value={value}
          placeholder="Paste your API key…"
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="button" className="tb-btn tb-btn--muted" onClick={() => setReveal((r) => !r)}>
          {reveal ? 'Hide' : 'Show'}
        </button>
        <button type="button" className="tb-btn" onClick={save} disabled={!value.trim()}>
          Save
        </button>
        <button type="button" className="tb-btn tb-btn--muted" onClick={clear} disabled={!saved}>
          Remove
        </button>
      </div>
    </div>
  );
}

export function ApiKeysSection() {
  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>API keys</h3>
        <p>
          Keys for data sources that require one. Stored only in this
          browser and sent to the backend per-request over HTTPS — never
          saved on the server, never written to logs. Use the Remove
          button (or Clear cache) to delete a key from this browser.
        </p>
      </header>
      <div className="api-key-list">
        {PROVIDERS.map((p) => (
          <ApiKeyRow key={p.name} provider={p} />
        ))}
      </div>
    </section>
  );
}
