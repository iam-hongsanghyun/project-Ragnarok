"""Self-hosted historical hourly demand database (TODO D2).

* :mod:`.catalogue` - what each series measures, licences, area naming
* :mod:`.parsers`   - upstream file -> hourly MW frames (pure)
* :mod:`.store`     - parquet slices, manifest, validation, atomic writes
* :mod:`.refresh`   - the refresh CLI (``python -m backend.app.importers.demand_db.refresh``)

The Data-view importer lives in ``importers/databases/demand_db``; the REST routes in
``routers/demand_db.py``; the MCP tools in ``backend/mcp/tools_demand_db.py``.
"""
