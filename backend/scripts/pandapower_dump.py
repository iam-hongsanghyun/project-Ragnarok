"""Isolated pandapower reader: pandapower JSON net on stdin -> table dump JSON on stdout.

Runs ONLY inside the pandapower venv (``.venv-pandapower``), never in the PyPSA
environment: pandapower pins pandas~=2.3, PyPSA 1.4 needs pandas 3. The parent
(``backend/pypsa/network/pypsa_io.py``) rebuilds a duck-typed net from this dump
and hands it to PyPSA's own ``import_from_pandapower_net``.
"""
from __future__ import annotations

import json
import sys

TABLES = ("bus", "gen", "ext_grid", "load", "sgen", "line", "trafo", "shunt", "switch")


def main() -> None:
    import pandapower as pp

    net = pp.from_json_string(sys.stdin.read())
    out: dict = {"f_hz": float(net.f_hz), "pandapower": pp.__version__, "tables": {}}
    for name in TABLES:
        df = getattr(net, name)
        # keep the integer pandapower index as an explicit column; index must survive for .loc lookups
        out["tables"][name] = json.loads(df.reset_index().to_json(orient="split", date_format="iso"))
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
