# `src/lib/` — pure-logic layer

Everything under this directory must be **independent of React, the DOM,
and any UI library**. Goals:

- Same logic can run in a Web Worker, a Node CLI, or a different frontend.
- Pure functions are easy to test in isolation (no need to mount React).
- Clean import boundary makes the codebase easier to reason about as it
  grows.

## Rule

Code under `src/lib/` may **not** import from:

- `react`, `react-dom`, `react-leaflet`, `react-calendar`,
  `react-responsive-carousel`
- `features/*`, `views/*`, `layout/*`
- `shared/components/*`, `shared/hooks/*`

Type-only imports from `leaflet` (e.g. `import type { LatLngBoundsExpression }`)
are allowed for geometry type names — they get stripped at compile time.

The rule is enforced by ESLint
(`no-restricted-imports`, see `package.json`'s `eslintConfig.overrides`).

If you find yourself wanting to import a UI module from lib, extract the
TYPE into a lib file and have the UI module re-export it. Two existing
examples:

- `lib/validation/issue.ts` defines `ModelIssue`; the hook
  `features/validation/useModelIssues.ts` re-exports it.
- `lib/settings/types.ts` defines `DateFormat` / `SolverType` /
  `AppSettings`; `features/settings/useSettings.ts` re-exports them.

## Subdirectories

| dir | contents |
|---|---|
| `api/` | upstream-fetch wrappers (e.g. `databases.ts`) |
| `build/` | Build-view step computations |
| `constants/` | static catalogues (PyPSA schema, standard line/transformer types, currencies, capabilities) |
| `constraints/` | constraint DSL parser + helpers |
| `dashboard/` | Analytics dashboard presets + types |
| `data/` | data-import session store |
| `export/` | chart & results exporters |
| `importers/` | per-database external-data importers (osm, wri_gppd, worldbank_demand) + registry |
| `input/` | TSV / range parsers |
| `plugins/` | plugin runtime + manifest types |
| `results/` | derive run results, asset details, scenarios, pathway, rolling |
| `settings/` | settings type definitions (DateFormat, AppSettings, …) |
| `types/` | top-level shared types (WorkbookModel, GridRow, …) |
| `utils/` | small helpers + formatters |
| `validation/` | ModelIssue shape |
| `workbook/` | workbook construction, merging, CSV-folder I/O |

## Where UI code lives

| dir | contents |
|---|---|
| `views/` | top-level tab views |
| `features/` | feature-grouped React components (Build view, Data view UI, Analytics cards, …) |
| `layout/` | resizable panels, activity bar |
| `shared/components/` | reusable components (SearchableSelect, primitives) |
| `shared/hooks/` | reusable React hooks (`usePersistedState`) |
| `App.tsx`, `index.tsx`, `*.css` | entry + global styles |
