# Ragnarok TODO

Last updated: 2026-05-24

This list is derived from the current support matrix in [README.md](/Users/sanghyun/github/pypsa_gui/README.md).

## Priority scale

- `Critical`: blocks trustworthy project exchange or core modeling correctness
- `High`: major product gap or frequent user pain
- `Medium`: meaningful support expansion or UX improvement
- `Low`: polish or secondary capability

## Cost scale

`Estimated token cost` is a rough implementation budget for one focused coding pass, including reading, patching, verification, and light documentation. It is not a calendar estimate.

## Top priorities

| Priority | Area | Gap | Why it matters | Estimated token cost |
|---|---|---|---|---:|
| `Critical` | Optimization capability | Add multi-investment / pathway planning support | This is one of the largest gaps between PyPSA and Ragnarok. It requires `investment_periods`, period weightings, multi-index snapshots, pathway-specific run options, and new analytics. | 35,000 |
| `Critical` | Project export/import | Retain the solved backend `pypsa.Network` or solved workbook artifact after a run | Current project export is frontend-reconstructed from `results.outputs`, not from the authoritative solved network. This is the main trust and reliability gap in project exchange. | 18,000 |
| `Critical` | Project export/import | Add Ragnarok metadata sheets for settings, constraints, run window, run history, plugin analytics, and import provenance | Current project import restores only workbook inputs/outputs. Users do not get the full project back. | 20,000 |
| `High` | Optimization capability | Add rolling-horizon optimization workflow | PyPSA supports rolling-horizon style operation, but Ragnarok only supports a single static solve window today. | 18,000 |
| `High` | Optimization capability | Add stochastic optimization support | PyPSA supports two-stage stochastic planning; Ragnarok has no scenario or uncertainty model. | 30,000 |
| `High` | Optimization capability | Add security-constrained optimization / SCLOPF workflow | Important missing transmission-planning capability for serious network studies. | 24,000 |
| `High` | Import fidelity | Restore plugin analytics and non-derivable solve metadata on project import | Imported projects currently lose plugin analytics and CO2 shadow information. | 10,000 |
| `High` | Backend correctness | Apply the `network` sheet explicitly in backend network construction | The sheet is editable and preserved, but currently not used as a true runtime input. | 8,000 |
| `High` | Validation | Expand validation from common electricity checks to schema-aware coverage | The input schema is broad, but validation still focuses on buses, loads, generators, lines, and links. | 12,000 |

## Secondary priorities

| Priority | Area | Gap | Why it matters | Estimated token cost |
|---|---|---|---|---:|
| `High` | Data platform | Add location-based wind and solar profile generation/import | Users should be able to choose a location and populate renewable profiles without preparing time series manually. This needs source selection, caching/database design, and workbook write-back into PyPSA time-series sheets. | 22,000 |
| `High` | Data platform | Add a renewable/weather profile database layer | Location-based profiles should not be one-off fetches only. Ragnarok needs persistent storage or cache/indexing for reusable wind/solar resources by location, year, and source. | 18,000 |
| `High` | Data platform | Add national-level starter model imports | Users should be able to import a prebuilt country-scale baseline model instead of constructing one workbook from scratch. | 24,000 |
| `High` | Data platform | Add a source registry for national models and profile datasets | National model import and profile generation need a managed catalogue of sources, versions, coverage, and provenance. | 16,000 |
| `High` | Optimization UX | Add scenario and multi-period run configuration UX | Multi-year and stochastic support are not useful without a first-class configuration surface. | 18,000 |
| `High` | Analytics | Add multi-period and scenario-aware result analytics | Pathway/stochastic support requires different result views, comparisons, and summaries. | 20,000 |
| `High` | Analytics | Add workbook-import restoration for more solve-derived metrics beyond current derivation set | Imported project analytics should match a fresh solve more closely. | 12,000 |
| `High` | Workbook model | Decide and enforce policy for `shapes` and `sub_networks` | They are exposed/preserved today, but their runtime meaning is unclear. | 6,000 |
| `Medium` | Components | Add dedicated result UX for `processes` | Backend and workbook support exist, but there is no analytics surface. | 12,000 |
| `Medium` | Components | Add dedicated result UX for `shunt_impedances` where useful | Currently workbook/backend only. | 8,000 |
| `Medium` | Types and standard types | Clarify and test `line_types` / `transformer_types` behavior end-to-end | These are currently mostly implicit/pass-through capabilities. | 7,000 |
| `Medium` | Constraints | Expand the custom constraint panel or better expose native `global_constraints` behavior | Constraint authoring is stronger in the workbook/backend than in the UI. | 9,000 |
| `Medium` | Testing | Add round-trip tests for `Save`, `Export Project`, `Import Project`, and `Export Result` | Current support is powerful enough that regression risk is now high. | 14,000 |

## Lower priorities

| Priority | Area | Gap | Why it matters | Estimated token cost |
|---|---|---|---|---:|
| `Medium` | Data platform | Add data-source health checks and provenance reporting | Imported profiles and national baseline models should expose where they came from, which version was used, and whether the source is still reachable. | 12,000 |
| `Medium` | Data platform | Add user-facing data import presets by country/region | A curated “import baseline model for country X” flow reduces setup effort and keeps national models consistent. | 14,000 |
| `Medium` | File formats | Support PyPSA CSV folder import/export in the UI | Useful for advanced users and larger cases. | 15,000 |
| `Medium` | File formats | Support netCDF/HDF5 workflows in the UI | Better aligned with PyPSA’s broader I/O model than Excel-only workflows. | 18,000 |
| `Low` | Analytics | Add a dedicated carrier-level analytics view | Carrier data exists indirectly today. | 6,000 |
| `Low` | Analytics | Add load drill-down analytics | Loads drive system metrics but do not have a first-class detail view. | 8,000 |
| `Low` | Documentation | Auto-generate the support matrix from schema + capability declarations | Reduces drift between code and docs. | 9,000 |

## Suggested execution order

1. Retain solved backend network/workbook artifacts.
2. Add metadata-backed full project export/import.
3. Implement multi-investment / pathway planning support.
4. Add location-based renewable profile import and the supporting data registry/database layer.
5. Add national-level starter model imports.
6. Fix `network` sheet application and broaden validation.
7. Add round-trip tests for project workflows.
8. Add rolling-horizon, stochastic, and security-constrained workflows.
9. Expand analytics/component coverage after the project exchange path, data layer, and core optimization modes are trustworthy.
