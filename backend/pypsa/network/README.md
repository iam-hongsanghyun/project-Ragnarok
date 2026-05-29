# Backend Import Contract

This module turns the in-memory workbook model
(`{sheet_name: [row_dict, …]}` posted by the frontend) into a fully populated
`pypsa.Network`. The mapping is **schema-driven**: nothing per-sheet is
hardcoded except the two genuine special cases below.

## Three rules

### 1. `network` sheet — explicit runtime import allow-list

Only the fields whitelisted in
[`src/config/network_import_policy.json`](../../../src/config/network_import_policy.json)
with `enabled_for_runtime_import: true` are applied. Today that is **`name`,
`srid`, `crs`, `now`**. Every other column on the `network` sheet — including
PyPSA-defined ones like `investment_periods` and `snapshot_weightings` — is
ignored at runtime; those are sourced from dedicated sheets or run options.

New fields must be added to the policy file and given an explicit branch in
[`network_sheet._apply_network_sheet`](network_sheet.py) before they can leak
into the live network. **Do not** auto-apply unknown columns.

### 2. `snapshots` sheet — snapshot-index special case

The `snapshots` sheet does not produce a component; it produces the snapshot
index for the entire network. Handled by
[`snapshots._snapshots_index`](snapshots.py):

- **Single-period runs**: parses ISO timestamps into a flat `DatetimeIndex`,
  deduping if the workbook lists the same timestamp once per period.
- **Pathway runs** (`snapshot_mapping_mode == "explicit_period_column"`):
  builds a `pd.MultiIndex` with levels `["period", "timestep"]` from the
  `period` column on each row.

`_apply_pathway_config` then attaches investment-period weightings.

### 3. Every other schema-defined sheet — generic loop, no per-sheet branches

Buses, generators, loads, lines, links, stores, storage_units, transformers,
shunt_impedances, processes, line_types, transformer_types,
global_constraints, shapes, carriers — all flow through the same loop in
[`build_network`](__init__.py):

```
_ordered_component_sheets(network)
  → for each (sheet_name, cls):
      input_static_attributes(sheet_name)   # whitelist columns from schema
      _drop_broken_bus_refs(...)            # only for bus-referencing comps
      network.add(cls, names, **columns)
```

Time-series sheets follow the **`<list_name>-<attr>`** naming convention
(e.g. `generators-p_max_pu`, `loads-p_set`) and are routed through
[`_apply_ts_sheet`](components.py). Eligibility is determined entirely from
PyPSA's `components[list_name].defaults` — an attribute is time-varying iff
`defaults.at[attr, "varying"]` is true.

**Adding a new sheet must not require a new branch in `build_network`.** If
PyPSA adds a new component, dropping its sheet into the workbook should Just
Work; if the schema gains a new attribute, the generic column filter picks it
up. The only acceptable reasons to add a branch are the two listed above.

## Tests

See [`backend/tests/test_import_contract.py`](../../tests/test_import_contract.py)
— eight tests that pin every rule above. Run with:

```bash
.venv-pypsa/bin/python -m pytest backend/tests/ -v
```
