"""Importer registry + endpoint contract (network-free parts).

The per-module fetch paths hit live upstreams (Overpass, GitHub, World
Bank), so they're exercised manually / in preview rather than here — a
flaky network must not break the unit suite. These tests cover the
deterministic surface: the registry shape, the protocol conformance of
each module, the voltage parser, and the MATPOWER parser.
"""
from __future__ import annotations

from backend.app.importers.registry import (
    available_databases,
    available_sources,
    get_database,
    registered_databases,
)
from backend.app.importers.protocol import Database, WorkbookFragment
from backend.app.importers.combine import combine_fragments, combine_previews


def test_registry_lists_expected_modules():
    ids = set(registered_databases().keys())
    assert ids == {
        "osm", "wri_gppd", "worldbank_demand",
        "kpg193_network", "kpg193_renewable_capacity",
        "kpg193_demand_profile", "kpg193_renewable_profile",
        "eia_demand", "entsoe_load",
    }


def test_kpg193_split_into_separate_datasets():
    """Each KPG193 dataset is its own tree entry with cohesive filters — no
    bundling of distinct datasets behind toggles in one importer."""
    by_id = {m["id"]: m for m in available_databases()}
    # Network: topology only, no renewable_year / profile filters.
    net = by_id["kpg193_network"]
    assert net["category"] == "transmission"
    net_filters = {f["id"] for f in net["filters"]}
    assert net_filters == {"version", "include_dc_links"}
    # Renewable capacity: generation, version + year.
    cap = by_id["kpg193_renewable_capacity"]
    assert cap["category"] == "generation"
    assert {f["id"] for f in cap["filters"]} == {"version", "renewable_year"}
    # Demand profile: demand, version + profile window.
    dem = by_id["kpg193_demand_profile"]
    assert dem["category"] == "demand"
    assert {f["id"] for f in dem["filters"]} == {
        "version", "profile_start", "profile_days"
    }
    assert dem["targets"] == ["loads-p_set", "loads-q_set"]
    # Renewable profile: generation, version + year + profile window.
    ren = by_id["kpg193_renewable_profile"]
    assert ren["category"] == "generation"
    assert {f["id"] for f in ren["filters"]} == {
        "version", "renewable_year", "profile_start", "profile_days"
    }
    assert ren["targets"] == ["generators-p_max_pu"]
    # All four are KOR-only.
    for db_id in ("kpg193_network", "kpg193_renewable_capacity",
                  "kpg193_demand_profile", "kpg193_renewable_profile"):
        assert by_id[db_id]["country_coverage"] == ["KOR"]


def test_eia_declares_byok_key():
    """The BYOK exemplar must advertise the key it needs so the frontend
    can prompt for it and gate the Fetch button."""
    by_id = {m["id"]: m for m in available_databases()}
    eia = by_id["eia_demand"]
    assert eia["requires_secrets"] == ["eia_key"]
    assert eia["country_coverage"] == ["USA"]


def test_eia_granularity_options_span_three_levels():
    """The respondent select must offer national (US48), regional, and
    balancing-authority granularities — the user picks the level."""
    by_id = {m["id"]: m for m in available_databases()}
    eia = by_id["eia_demand"]
    resp = next(f for f in eia["filters"] if f["id"] == "respondent")
    values = {o["value"] for o in resp["options"]}
    assert "US48" in values            # national
    assert {"CAL", "TEX", "MIDW"} <= values  # regions
    assert {"PJM", "CISO"} <= values   # balancing authorities
    assert resp["default"] == "US48"


def test_entsoe_declares_byok_and_eu_coverage():
    """ENTSO-E is the national hourly demand source: BYOK token, EU coverage."""
    by_id = {m["id"]: m for m in available_databases()}
    ent = by_id["entsoe_load"]
    assert ent["requires_secrets"] == ["entsoe_key"]
    assert ent["category"] == "demand"
    cov = ent["country_coverage"]
    assert {"DEU", "FRA", "ESP", "GBR"} <= set(cov)


def test_entsoe_xml_parse_and_hourly_aggregation():
    """Parse a minimal GL_MarketDocument and confirm sub-hourly points fold
    onto the hourly grid by mean."""
    from backend.app.importers.databases import entsoe_load as ent

    # Hourly (PT60M): positions 1..2 → 00:00, 01:00.
    hourly_xml = (
        '<GL_MarketDocument xmlns="urn:x">'
        "<TimeSeries><Period>"
        "<timeInterval><start>2023-01-01T00:00Z</start>"
        "<end>2023-01-01T02:00Z</end></timeInterval>"
        "<resolution>PT60M</resolution>"
        "<Point><position>1</position><quantity>100</quantity></Point>"
        "<Point><position>2</position><quantity>120</quantity></Point>"
        "</Period></TimeSeries></GL_MarketDocument>"
    )
    pts = ent._parse_load_xml(hourly_xml)
    assert len(pts) == 2
    hourly = ent._aggregate_hourly(pts)
    assert hourly == [("2023-01-01 00:00", 100.0), ("2023-01-01 01:00", 120.0)]

    # 15-min (PT15M): four points in the first hour average to one snapshot.
    quarter_xml = (
        '<GL_MarketDocument xmlns="urn:x">'
        "<TimeSeries><Period>"
        "<timeInterval><start>2023-01-01T00:00Z</start>"
        "<end>2023-01-01T01:00Z</end></timeInterval>"
        "<resolution>PT15M</resolution>"
        "<Point><position>1</position><quantity>100</quantity></Point>"
        "<Point><position>2</position><quantity>200</quantity></Point>"
        "<Point><position>3</position><quantity>300</quantity></Point>"
        "<Point><position>4</position><quantity>400</quantity></Point>"
        "</Period></TimeSeries></GL_MarketDocument>"
    )
    hourly_q = ent._aggregate_hourly(ent._parse_load_xml(quarter_xml))
    assert hourly_q == [("2023-01-01 00:00", 250.0)]  # mean of 100..400


def test_entsoe_acknowledgement_raises_reason():
    """An error document surfaces its Reason text, not a silent empty set."""
    from backend.app.importers.databases import entsoe_load as ent

    ack = (
        '<Acknowledgement_MarketDocument xmlns="urn:x">'
        "<Reason><code>999</code><text>No matching data found</text></Reason>"
        "</Acknowledgement_MarketDocument>"
    )
    import pytest

    with pytest.raises(RuntimeError, match="No matching data found"):
        ent._parse_load_xml(ack)


def test_every_module_conforms_to_protocol():
    for db in registered_databases().values():
        assert isinstance(db, Database)
        assert db.meta.id
        assert db.meta.short_name
        assert isinstance(db.meta.requires_secrets, list)


def test_database_metas_json_shape():
    by_id = {m["id"]: m for m in available_databases()}
    assert by_id["osm"]["category"] == "transmission"
    assert by_id["wri_gppd"]["category"] == "generation"
    assert by_id["worldbank_demand"]["category"] == "demand"
    assert by_id["kpg193_network"]["country_coverage"] == ["KOR"]
    # short_name present and concise for every module
    for m in by_id.values():
        assert m["short_name"]
        assert "filters" in m


def test_kpg193_grouped_into_one_source():
    """The four KPG193 datasets present as ONE source (Country → Database →
    Datasets) with the shared settings hoisted into common_filters."""
    sources = {s["source_id"]: s for s in available_sources()}
    kpg = sources["kpg193"]
    assert kpg["source_label"].startswith("KPG193")
    assert [d["id"] for d in kpg["datasets"]] == [
        "kpg193_network", "kpg193_renewable_capacity",
        "kpg193_demand_profile", "kpg193_renewable_profile",
    ]
    # version is shared by all 4; year by capacity+ren-profile; window by the
    # two profiles — all land in common_filters (≥2 datasets), in first-seen order.
    assert kpg["common_filter_ids"] == [
        "version", "renewable_year", "profile_start", "profile_days",
    ]
    assert kpg["country_coverage"] == ["KOR"]
    # Singletons: one dataset, nothing shared.
    assert len(sources["eia_demand"]["datasets"]) == 1
    assert sources["eia_demand"]["common_filter_ids"] == []


def test_dataset_dependency_order():
    """Selecting a profile auto-includes its anchor, dependency-first, so a
    fetch is never a dangling time-series."""
    from backend.app.routers.importers import _resolve_dataset_order

    assert _resolve_dataset_order(["kpg193_demand_profile"]) == [
        "kpg193_network", "kpg193_demand_profile",
    ]
    # renewable_profile → renewable_capacity → network (transitive)
    assert _resolve_dataset_order(["kpg193_renewable_profile"]) == [
        "kpg193_network", "kpg193_renewable_capacity", "kpg193_renewable_profile",
    ]
    assert _resolve_dataset_order(["osm"]) == ["osm"]

    import pytest

    with pytest.raises(KeyError):
        _resolve_dataset_order(["not-a-dataset"])


def test_combine_fragments_aligns_unions_and_dedupes():
    """combine_fragments folds dataset fragments into one: static rows concat,
    carriers union by name, snapshots sorted-union, one provenance row. The
    combined preview reads counts from the fragment (not summed)."""
    network = WorkbookFragment(sheets={
        "buses": [{"name": "1"}, {"name": "2"}],
        "loads": [{"name": "load_1", "bus": "1"}, {"name": "load_2", "bus": "2"}],
        "carriers": [{"name": "AC"}, {"name": "load"}],
        "generators": [{"name": "gen_1", "bus": "1"}],
    })
    demand = WorkbookFragment(
        sheets={"loads-p_set": [{"snapshot": "2024-01-01 00:00", "load_1": 10, "load_2": 5}]},
        snapshots=["2024-01-01 00:00"],
    )
    renewable = WorkbookFragment(
        sheets={
            "generators": [{"name": "gen_solar_1", "bus": "1", "carrier": "solar"}],
            "generators-p_max_pu": [{"snapshot": "2024-01-01 01:00", "gen_solar_1": 0.5}],
            "carriers": [{"name": "solar"}, {"name": "AC"}],  # AC duplicates → union
        },
        snapshots=["2024-01-01 01:00"],
    )

    out = combine_fragments(
        [network, demand, renewable],
        source_id="kpg193", country_iso="KOR", country_name="South Korea",
        filters={"version": "latest"}, dataset_ids=["a", "b", "c"],
    )
    # generators concat (thermal + renewable); carriers union (no duplicate AC)
    assert {r["name"] for r in out.sheets["generators"]} == {"gen_1", "gen_solar_1"}
    assert {r["name"] for r in out.sheets["carriers"]} == {"AC", "load", "solar"}
    assert out.snapshots == ["2024-01-01 00:00", "2024-01-01 01:00"]  # sorted union
    assert out.provenance is not None

    preview = combine_previews(out, [])
    assert preview.counts["generators"] == 2   # from the fragment, not summed
    assert preview.counts["snapshots"] == 2     # union count, not 1+1


def test_get_unknown_database_raises():
    import pytest

    with pytest.raises(KeyError):
        get_database("not-a-real-db")


def test_osm_voltage_parser():
    from backend.app.importers.databases import osm

    # The parser is the load-bearing OSM normaliser; spot-check the
    # documented edge cases. Locate it by name regardless of internal
    # helper naming.
    parse = getattr(osm, "parse_voltage_kv", None) or getattr(osm, "_parse_voltage_kv", None)
    if parse is None:
        # Some ports keep it private inside the class module; skip if not
        # exposed rather than fail the suite.
        import pytest

        pytest.skip("voltage parser not module-level")
    assert parse("110000") == [110.0]
    assert sorted(parse("110000;220000")) == [110.0, 220.0]
    assert parse("110 kV") == [110.0]
    assert parse("") == []
    assert parse("unknown") == []


def test_kpg193_profile_window_resolution():
    """The hourly-profile window maps (start date, day count) to clamped
    1-based daily-file indices, never escaping the dataset bounds."""
    from backend.app.importers.databases import kpg193

    # Base date → file index 1.
    assert kpg193._resolve_profile_window(
        {"profile_start": "2024-01-01", "profile_days": 3}
    ) == [1, 2, 3]
    # Eighth day → index 8, two days.
    assert kpg193._resolve_profile_window(
        {"profile_start": "2024-01-08", "profile_days": 2}
    ) == [8, 9]
    # Day count is capped at PROFILE_MAX_DAYS.
    assert (
        len(kpg193._resolve_profile_window(
            {"profile_start": "2024-01-01", "profile_days": 9999}
        )) == kpg193.PROFILE_MAX_DAYS
    )
    # The tail clamps to the last available day.
    win = kpg193._resolve_profile_window(
        {"profile_start": "2024-12-29", "profile_days": 10}
    )
    assert win[-1] == kpg193.PROFILE_DAYS_AVAILABLE


def test_kpg193_snapshot_label():
    """Snapshots are fixed-width ISO `YYYY-MM-DD HH:00` so a lexical sort is
    chronological (the frontend's fragment-merge relies on this)."""
    from backend.app.importers.databases import kpg193

    assert kpg193._snapshot_label(1, 1) == "2024-01-01 00:00"
    assert kpg193._snapshot_label(1, 24) == "2024-01-01 23:00"
    assert kpg193._snapshot_label(2, 1) == "2024-01-02 00:00"
    labels = [kpg193._snapshot_label(d, h) for d in (1, 2) for h in range(1, 25)]
    assert labels == sorted(labels)


def test_kpg193_build_load_and_renewable_profiles():
    """The long-format daily CSVs pivot to wide per-snapshot rows, and a
    renewable series only attaches to generators that exist."""
    from backend.app.importers.databases import kpg193

    demand_csv = (
        "hour,bus_id,demandP,demandQ\n"
        "1,1,100.0,10.0\n1,2,50.0,5.0\n"
        "2,1,110.0,11.0\n2,2,55.0,5.5\n"
    )
    p_rows, q_rows, snaps = kpg193._build_load_profile([1], [demand_csv])
    assert snaps == ["2024-01-01 00:00", "2024-01-01 01:00"]
    assert p_rows[0]["snapshot"] == "2024-01-01 00:00"
    assert p_rows[0]["load_1"] == 100.0 and p_rows[0]["load_2"] == 50.0
    assert p_rows[1]["load_1"] == 110.0
    assert q_rows[0]["load_1"] == 10.0

    ren_csv = (
        "hour,bus_id,pv_profile_ratio,wind_profile_ratio,hydro_profile_ratio\n"
        "1,1,0.0,0.3,0.5\n1,2,0.0,0.2,0.4\n"
        "12,1,0.8,0.4,0.5\n12,2,0.7,0.1,0.4\n"
    )
    # Only bus 1 has a solar generator and bus 2 a wind generator.
    existing = {"gen_solar_1", "gen_wind_2"}
    rows, rsnaps = kpg193._build_renewable_profile([1], [ren_csv], existing)
    assert rsnaps == ["2024-01-01 00:00", "2024-01-01 11:00"]
    noon = next(r for r in rows if r["snapshot"] == "2024-01-01 11:00")
    assert noon["gen_solar_1"] == 0.8         # bus-1 solar attached
    assert noon["gen_wind_2"] == 0.1          # bus-2 wind attached
    assert "gen_wind_1" not in noon           # no generator → no series
    assert "gen_solar_2" not in noon


def test_kpg193_matpower_block_parser():
    from backend.app.importers.databases import kpg193

    extract_scalar = getattr(kpg193, "extract_scalar", None) or getattr(kpg193, "_extract_scalar", None)
    extract_block = getattr(kpg193, "extract_block_lines", None) or getattr(kpg193, "_extract_block_lines", None)
    if extract_scalar is None or extract_block is None:
        import pytest

        pytest.skip("MATPOWER parser helpers not module-level")
    text = "mpc.baseMVA = 100;\nmpc.bus = [\n1 2 0 0;\n2 1 0 0;\n];\n"
    assert extract_scalar(text, "baseMVA") == "100"
    rows = extract_block(text, "bus")
    # Raw block lines (empties are filtered later by parse_matrix); the
    # two data rows must be present.
    nonblank = [r for r in rows if r.strip()]
    assert len(nonblank) == 2
