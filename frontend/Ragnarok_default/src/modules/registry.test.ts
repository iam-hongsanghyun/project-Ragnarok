/**
 * Tab-module registry — enablement parsing and the core/module boundary.
 *
 * The classification is a product decision (2026-08-01): core = Welcome,
 * Build, Model, Market & Policy, Settings, Analytics, History, Plugins;
 * modules = Data, Forge, Physical Risk, Siting, Post-analysis, Training.
 * These tests pin it so a tab can't silently change sides.
 */
import { describe, expect, it } from '@jest/globals';
import type { WorkspaceTab } from 'lib/types';
import {
  TAB_MODULES,
  defaultEnabledModulesCsv,
  isTabModule,
  parseEnabledModules,
  serializeEnabledModules,
} from './registry';

const MODULE_TABS: WorkspaceTab[] = ['Data', 'Forge', 'PhysicalRisk', 'Siting', 'PostAnalysis', 'Training'];
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
