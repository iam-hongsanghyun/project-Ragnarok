# Ragnarok Documentation

Ragnarok is a local browser-based GUI for building and solving PyPSA power-system
models (React + TypeScript frontend, FastAPI + PyPSA + linopy backend, HiGHS solver).

The manual is five documents:

| # | Document | For |
|---|---|---|
| 1 | [user-manual.md](./user-manual.md) | Using the app: install, launch, every view and feature, import/export, capabilities |
| 2 | [architecture.md](./architecture.md) | How the system is built: tech stack, repo layout, topology, data flow, process logic, design |
| 3 | [backend.md](./backend.md) | Backend details: HTTP API, solve pipeline, network build, results, modes, constraints, utils |
| 4 | [frontend.md](./frontend.md) | Frontend details: App state, views, features, the plugin host, shared utils and types |
| 5 | [plugin.md](./plugin.md) | Building a plugin (frontend JS or backend Python): manifest, GUI schema, hooks, own local server, constraint flow, examples |

Supporting material:

- [SUPPORT_MATRIX.md](./SUPPORT_MATRIX.md) — generated PyPSA feature/attribute support matrix.
- [TODO.md](./TODO.md) — living project task log and roadmap.

New here? Start with [user-manual.md](./user-manual.md) (§1 launches the app in one command),
then [architecture.md](./architecture.md) for the big picture.
