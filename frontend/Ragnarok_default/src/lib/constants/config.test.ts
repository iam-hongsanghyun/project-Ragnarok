import { describe, it, expect, afterEach } from '@jest/globals';
import { API_BASE, RUN_WINDOW, applySimulationDefaults, apiBaseFromAddress, resolveApiBase } from './config';

const shipped = { end: RUN_WINDOW.defaultSnapshotEnd, weight: RUN_WINDOW.defaultSnapshotWeight };
afterEach(() => {
  RUN_WINDOW.defaultSnapshotEnd = shipped.end;
  RUN_WINDOW.defaultSnapshotWeight = shipped.weight;
});

describe('applySimulationDefaults', () => {
  it('lets the server defaults win over the shipped run window', () => {
    applySimulationDefaults({ defaultSnapshotCount: 48, defaultSnapshotWeight: 2 });
    expect(RUN_WINDOW.defaultSnapshotEnd).toBe(48);
    expect(RUN_WINDOW.defaultSnapshotWeight).toBe(2);
  });

  it('ignores missing or non-positive values', () => {
    applySimulationDefaults(undefined);
    applySimulationDefaults({ defaultSnapshotCount: 0, defaultSnapshotWeight: Number.NaN });
    expect(RUN_WINDOW.defaultSnapshotEnd).toBe(shipped.end);
    expect(RUN_WINDOW.defaultSnapshotWeight).toBe(shipped.weight);
  });
});

describe('API base', () => {
  it('is the page origin (empty) on localhost, which jsdom serves from — not port 8000', () => {
    expect(window.location.hostname).toBe('localhost');
    expect(API_BASE).toBe('');
  });

  it('is empty whatever hostname the app was opened on, unless a base is configured', () => {
    // resolveApiBase takes no hostname at all: localhost, 127.0.0.1, [::1] and a LAN name all resolve alike.
    expect(resolveApiBase()).toBe('');
    expect(resolveApiBase(undefined, '')).toBe('');
    expect(resolveApiBase(null, '   ')).toBe('');
  });

  it('honours an explicit base, the first non-empty one wins, trailing slashes are dropped', () => {
    expect(resolveApiBase('http://api.example.org:9000/')).toBe('http://api.example.org:9000');
    expect(resolveApiBase('', 'http://10.0.0.5:8000')).toBe('http://10.0.0.5:8000');
    expect(resolveApiBase('http://a', 'http://b')).toBe('http://a');
  });
});

describe('backend named in the address (?api=)', () => {
  it('takes a loopback http(s) origin and drops any path', () => {
    expect(apiBaseFromAddress('?api=http://127.0.0.1:52185')).toBe('http://127.0.0.1:52185');
    expect(apiBaseFromAddress('?session=x&api=http%3A%2F%2Flocalhost%3A8000%2Fapi')).toBe('http://localhost:8000');
    expect(apiBaseFromAddress('?api=http://[::1]:9000')).toBe('http://[::1]:9000');
  });

  it('ignores a missing, malformed or non-loopback base', () => {
    expect(apiBaseFromAddress('')).toBe('');
    expect(apiBaseFromAddress('?api=not a url')).toBe('');
    expect(apiBaseFromAddress('?api=http://evil.example.org:8000')).toBe('');
    expect(apiBaseFromAddress('?api=file:///etc/passwd')).toBe('');
  });
});

