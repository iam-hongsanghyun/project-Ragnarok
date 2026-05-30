# Ragnarok Documentation

Ragnarok is a local browser-based GUI for building and solving PyPSA power-system
models (React + TypeScript frontend, FastAPI + PyPSA + linopy backend, HiGHS solver).
This directory is the manual; the top-level [README.md](../README.md) stays at the
repository root.

## Read in this order

| Step | Document | For |
|---|---|---|
| 1 | [getting-started.md](./getting-started.md) | Install, launch with `run.command`, and a quick tour |
| 2 | [guides/USER_MANUAL.md](./guides/USER_MANUAL.md) | Day-to-day use: open, edit, run, analyse, export |
| 3 | [guides/PLUGIN_AUTHORING.md](./guides/PLUGIN_AUTHORING.md) | Build a plugin (manifest GUI, JS hooks, own server) |
| 4 | [architecture/ARCHITECTURE.md](./architecture/ARCHITECTURE.md) | System overview, tech stack, topology, data flow |
| — | [architecture/PROCESSES.md](./architecture/PROCESSES.md) | Step-by-step logic of each process (open, build, solve, export) |
| — | [architecture/DESIGN.md](./architecture/DESIGN.md) | UI design philosophy |
| — | [CAPABILITIES.md](./CAPABILITIES.md) | What Ragnarok can and cannot do (code-checked) |
| — | [SUPPORT_MATRIX.md](./SUPPORT_MATRIX.md) | Generated PyPSA feature support matrix |
| — | [reference/](./reference/) | Per-module function reference (backend + frontend) |
| — | [TODO.md](./TODO.md) | Living project task log and roadmap |
| — | [slides/](./slides/) | Architecture + plugin overview slide deck (PDF) |

## Directory layout

```
docs/
  README.md            this index
  getting-started.md   install, launch, first run, view tour
  CAPABILITIES.md      what Ragnarok can and cannot do (code-checked)
  SUPPORT_MATRIX.md    generated feature support matrix (npm run generate:support-matrix)
  TODO.md              living project task log and roadmap
  architecture/
    ARCHITECTURE.md    system overview, tech stack, topology, repo layout, data flow
    PROCESSES.md       step-by-step logic of each process
    DESIGN.md          UI design philosophy
  guides/
    USER_MANUAL.md     end-user manual for analysts
    PLUGIN_AUTHORING.md  how to build a plugin
  reference/           per-module function reference (backend + frontend)
  slides/              architecture + plugin overview deck (PDF)
```
