"""Build the local hazard catalog (the physical-risk worker's CLIMADA-ready perils DB).

Vendored from climaterisk ``scripts/build_hazard.py`` (paths adjusted to the
Ragnarok layout). Runs in the CLIMADA conda env — NOT .venv-pypsa:

  # 1. Convert a standardized observation grid (from real ingestion) -> catalog HDF5
  ./.climada-env/bin/python scripts/physical_risk_build_hazard.py convert path/to/grid.json

  # 2. Cache a CLIMADA Data API hazard for offline / reproducible runs
  ./.climada-env/bin/python scripts/physical_risk_build_hazard.py cache \\
      --data-type tropical_cyclone --peril tropical_cyclone \\
      --scenario rcp45 --region JPN --year 2040 \\
      --props '{"country_iso3alpha":"JPN","climate_scenario":"rcp45","ref_year":"2040",\\
                "event_type":"synthetic","model_name":"random_walk","spatial_coverage":"country"}'

  ./.climada-env/bin/python scripts/physical_risk_build_hazard.py list

The catalog lives at ``$CLIMATERISK_HAZARD_DB`` (default ``<repo>/data/hazard_db``,
git-ignored) — the same location the backend injects into the worker on spawn.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from physical_risk_worker import catalog  # noqa: E402
from physical_risk_worker.hazard_convert import convert_grid_to_catalog  # noqa: E402


def cmd_convert(args: argparse.Namespace) -> None:
    grid = json.loads(Path(args.grid).read_text(encoding="utf-8"))
    entry = convert_grid_to_catalog(grid, catalog.catalog_dir())
    catalog.register(entry)
    print(
        f"registered {entry['file']}  ({entry['n_events']} events × {entry['n_centroids']} centroids)"
    )


def cmd_cache(args: argparse.Namespace) -> None:
    from climada.util.api_client import Client

    haz = Client().get_hazard(args.data_type, properties=json.loads(args.props))
    db = catalog.catalog_dir()
    peril_dir = db / args.peril
    peril_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{haz.haz_type}_{args.scenario}_{args.region}_{args.year}.hdf5"
    haz.write_hdf5(str(peril_dir / fname))
    entry = {
        "peril": args.peril,
        "haz_type": haz.haz_type,
        "climate_scenario": args.scenario,
        "region": args.region,
        "year": args.year,
        "units": haz.units,
        "file": f"{args.peril}/{fname}",
        "n_events": int(haz.size),
        "n_centroids": int(haz.centroids.size),
        "source": f"CLIMADA Data API ({args.data_type}, cached)",
        "license": "per CLIMADA Data API",
    }
    catalog.register(entry)
    print(
        f"cached {entry['file']}  ({entry['n_events']} events × {entry['n_centroids']} centroids)"
    )


def cmd_ingest(args: argparse.Namespace) -> None:
    """Run an ingest refiner from the CLI (same code path as the worker)."""
    from physical_risk_worker.ingest import run_ingest

    points = [[float(p) for p in pt.split(",")] for pt in args.point]
    request = {
        "source": args.source,
        "peril": args.peril,
        "scenario": args.scenario,
        "year": args.year,
        "points": points,
    }
    result = run_ingest(request)
    print(result.get("detail") or result.get("status"))


def cmd_list(_args: argparse.Namespace) -> None:
    entries = catalog.load_manifest()
    print(f"{len(entries)} catalog entries in {catalog.catalog_dir()}")
    for e in entries:
        print(
            f"  {e['peril']:18} {e['climate_scenario']:14} {e['region']:6} {e.get('year')}  "
            f"{e['n_events']}ev × {e['n_centroids']}ce  [{e['source']}]"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Build the local CLIMADA hazard catalog.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("convert", help="convert a standardized grid JSON into the catalog")
    pc.add_argument("grid")
    pc.set_defaults(func=cmd_convert)

    pk = sub.add_parser("cache", help="cache a Data API hazard into the catalog")
    for a in ("--data-type", "--peril", "--scenario", "--region", "--props"):
        pk.add_argument(a, required=True)
    pk.add_argument("--year", type=int, required=True)
    pk.set_defaults(func=cmd_cache)

    pi = sub.add_parser(
        "ingest", help="run an ingest refiner (dataapi / aqueduct) into the catalog"
    )
    pi.add_argument("--source", required=True, choices=("dataapi", "aqueduct"))
    pi.add_argument("--peril", default="river_flood")
    pi.add_argument("--scenario", required=True)
    pi.add_argument("--year", type=int, required=True)
    pi.add_argument("--point", action="append", required=True, help="lat,lon (repeatable)")
    pi.set_defaults(func=cmd_ingest)

    pl = sub.add_parser("list", help="list catalog entries")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
