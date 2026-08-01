/**
 * External tab-module store — package parsing and validation.
 *
 * The contract: a directory / multi-file / .zip selection containing a
 * tabmodule.json manifest + a CommonJS entry. Ids must never collide with a
 * built-in tab, and paths re-base to wherever the manifest sits.
 */
import { describe, expect, it } from '@jest/globals';
import { MANIFEST_NAME, parseModuleFiles } from './store';

function file(name: string, content: string, relPath?: string): File {
  const f = new File([content], name, { type: 'text/plain' });
  if (relPath) {
    Object.defineProperty(f, 'webkitRelativePath', { value: relPath });
  }
  return f;
}

const MANIFEST = JSON.stringify({
  id: 'hello-tab', label: 'Hello', hint: 'hi', description: 'an example', order: 130,
});
const ENTRY = 'module.exports = { mount(el, ctx) { el.textContent = "hi"; } };';

describe('parseModuleFiles', () => {
  it('accepts a flat multi-file selection', async () => {
    const mod = await parseModuleFiles([file(MANIFEST_NAME, MANIFEST), file('index.js', ENTRY)]);
    expect(mod.manifest.id).toBe('hello-tab');
    expect(mod.manifest.entry).toBe('index.js');
    expect(mod.enabled).toBe(true);
    expect(mod.files['index.js']).toBe(ENTRY);
  });

  it('re-bases a directory selection to the manifest directory', async () => {
    const mod = await parseModuleFiles([
      file(MANIFEST_NAME, MANIFEST, `hello/${MANIFEST_NAME}`),
      file('index.js', ENTRY, 'hello/index.js'),
      file('README.md', 'docs', 'hello/README.md'),
    ]);
    expect(Object.keys(mod.files).sort()).toEqual(['README.md', 'index.js', MANIFEST_NAME].sort());
  });

  it('rejects a package without a manifest', async () => {
    await expect(parseModuleFiles([file('index.js', ENTRY)])).rejects.toThrow(MANIFEST_NAME);
  });

  it('rejects a manifest whose entry file is missing', async () => {
    await expect(parseModuleFiles([file(MANIFEST_NAME, MANIFEST)])).rejects.toThrow('index.js');
  });

  it('rejects ids that collide with built-in tabs', async () => {
    for (const id of ['Forge', 'Settings', 'Plugins']) {
      const manifest = JSON.stringify({ id, label: id });
      await expect(
        parseModuleFiles([file(MANIFEST_NAME, manifest), file('index.js', ENTRY)]),
      ).rejects.toThrow('collides');
    }
  });

  it('rejects unusable ids', async () => {
    const manifest = JSON.stringify({ id: 'has spaces!', label: 'x' });
    await expect(
      parseModuleFiles([file(MANIFEST_NAME, manifest), file('index.js', ENTRY)]),
    ).rejects.toThrow('alphanumeric');
  });
});
