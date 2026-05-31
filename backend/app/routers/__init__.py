"""FastAPI sub-routers — each file mounts one isolated concern.

The pattern: a single router module per feature group (config, importers,
runs, …), mounted in ``main.py`` via ``app.include_router(...)``. Keeps
``main.py`` lean and lets each feature evolve without touching the entry
point — important as we add more datasets / endpoints.
"""
