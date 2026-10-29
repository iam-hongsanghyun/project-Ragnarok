/**
 * Tab-module registry — enablement parsing and the core/module boundary.
 *
 * The classification is a product decision (2026-08-01): core = Welcome,
 * Build, Model, Market & Policy, Settings, Analytics, History, Plugins;
 * modules = Data, Forge, Physical Risk, Siting, Screening, Composites, Post-analysis, Reporting,
 * Training. These tests pin it so a tab can't silently change sides.
 */
import { describe, expect, it } from '@jest/globals';
import type { WorkspaceTab } from 'lib/types';
import {
  TAB_MODULES,
  defaultEnabledModulesCsv,
  isTabModule,
  parseEnabledModules,
  reconcileEnabledModules,
  serializeEnabledModules,
} from './registry';

const MODULE_TABS: WorkspaceTab[] = ['Data', 'Forge', 'PhysicalRisk', 'Siting', 'Screening', 'Composites', 'PostAnalysis', 'Reporting', 'Training'];
const CORE_TABS: WorkspaceTab[] = ['Welcome', 'Build', 'Model', 'Market', 'Settings', 'Analytics', 'History', 'Plugins'];

describe('the core/module split', () => {
  it('registers exactly the agreed module tabs', () => {
    expect(TAB_MODULES.map((m) => m.id).sort()).toEqual([...MODULE_TABS].sort());
  });

  it('never claims a core tab', () => {
    for (const tab of CORE_TABS) expect(isTabModule(tab)).toBe(false);
    for (const tab of MODULE_TABS) expect(isTabModule(tab)).toBe(true);
  });

  it('gives every module the manager-facing fields', () => {
    for (const m of TAB_MODULES) {
      expect(m.label.length).toBeGreaterThan(0);
      expect(m.hint.length).toBeGreaterThan(0);
      expect(m.description.length).toBeGreaterThan(20);
      expect(m.icon).toBeTruthy();
    }
  });
});

describe('enablement parsing', () => {
  it('an absent setting means every module (pre-modules behaviour)', () => {
    expect(parseEnabledModules(undefined).size).toBe(TAB_MODULES.length);
    expect(parseEnabledModules(null).size).toBe(TAB_MODULES.length);
  });

  it('an empty string is a deliberate none', () => {
    expect(parseEnabledModules('').size).toBe(0);
  });

  it('round-trips a partial set in registry order', () => {
    const set = parseEnabledModules('Training, Data');
    expect(serializeEnabledModules(set)).toBe('Data,Training');
  });

  it('drops unknown ids instead of keeping dead entries', () => {
    const set = parseEnabledModules('Data,NotAModule,Plugins,Build');
    expect(Array.from(set)).toEqual(['Data']);
  });

  it('defaults csv covers every module', () => {
    expect(parseEnabledModules(defaultEnabledModulesCsv()).size).toBe(TAB_MODULES.length);
  });
});

describe('reconcileEnabledModules', () => {
  const all = TAB_MODULES.map((m) => m.id);

  it('switches on a module added after the list was saved, once', () => {
    const saved = 'Data,Forge';
    const seen = 'Data,Forge,PhysicalRisk,Siting,PostAnalysis,Training';
    const first = reconcileEnabledModules(saved, seen);
    expect(first.enabledModules.split(',')).toEqual(expect.arrayContaining(['Data', 'Forge', 'Composites', 'Screening', 'Reporting']));
    expect(first.seenModules.split(',').sort()).toEqual([...all].sort());
  });

  it('keeps a module the user turned off once it has been seen', () => {
    const r = reconcileEnabledModules('Data', all.join(','));
    expect(r.enabledModules).toBe('Data');
    expect(reconcileEnabledModules(r.enabledModules, r.seenModules).enabledModules).toBe('Data');
  });

  it('a legacy list (no seen record) keeps the old deliberate offs and turns the newer modules on', () => {
    const r = reconcileEnabledModules('Data,Forge,Siting', undefined);
    const on = r.enabledModules.split(',');
    expect(on).toEqual(expect.arrayContaining(['Data', 'Forge', 'Siting', 'Composites', 'Screening', 'Reporting']));
    expect(on).not.toContain('PhysicalRisk');
    expect(on).not.toContain('Training');
  });

  it('the renamed P2X entry becomes Composites', () => {
    const r = reconcileEnabledModules('Data,P2X', 'Data,P2X');
    expect(r.enabledModules.split(',')).toContain('Composites');
    expect(r.enabledModules).not.toContain('P2X');
  });

  it('the shipped default list covers every registered module', () => {
    expect(defaultEnabledModulesCsv().split(',').sort()).toEqual([...all].sort());
  });
});
