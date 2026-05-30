"""Generate the Ragnarok architecture + plugin overview slide deck (PDF).

Pure-matplotlib, 16:9 landscape, one figure per slide -> a single PDF via
PdfPages. No external converters required.

    python docs/slides/build_deck.py            # writes ragnarok-architecture.pdf next to this file
    python docs/slides/build_deck.py out.pdf    # custom output path
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ── palette ────────────────────────────────────────────────────────────────
BRAND = "#0f766e"      # teal
INK = "#0f172a"        # slate-900
MUTED = "#475569"      # slate-600
LINE = "#94a3b8"       # slate-400
BG = "#ffffff"
PANEL = "#f1f5f9"      # slate-100
ACCENT = "#1d4ed8"     # blue-700
DANGER = "#b91c1c"     # red-700

W, H = 13.33, 7.5      # inches, 16:9


def _fig():
    fig = plt.figure(figsize=(W, H), dpi=150)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def _rule(ax, y=0.86):
    ax.plot([0.06, 0.94], [y, y], color=BRAND, lw=2.5, solid_capstyle="round")


def _footer(ax, text="Ragnarok"):
    ax.text(0.06, 0.045, text, color=MUTED, fontsize=10)
    ax.text(0.94, 0.045, "github: project-ragnarok", color=MUTED, fontsize=10, ha="right")


def slide_title(pdf):
    fig, ax = _fig()
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                fc=BRAND, ec="none", transform=ax.transAxes))
    ax.text(0.08, 0.62, "Ragnarok", color="white", fontsize=58, fontweight="bold")
    ax.text(0.08, 0.50, "Architecture & Plugins", color="#d1fae5", fontsize=30)
    ax.text(0.08, 0.40, "Build and solve PyPSA energy-system models in the browser.",
            color="#e2f5f2", fontsize=16)
    ax.text(0.08, 0.12, "React + TypeScript frontend   ·   FastAPI + PyPSA + linopy backend   ·   HiGHS solver",
            color="#a7f3d0", fontsize=12)
    pdf.savefig(fig)
    plt.close(fig)


def slide_bullets(pdf, title, bullets, kicker=None):
    fig, ax = _fig()
    if kicker:
        ax.text(0.06, 0.93, kicker.upper(), color=BRAND, fontsize=12, fontweight="bold")
    ax.text(0.06, 0.885, title, color=INK, fontsize=28, fontweight="bold")
    _rule(ax, 0.845)
    y = 0.76
    for b in bullets:
        sub = b.startswith("  ")
        text = b.strip()
        bx = 0.10 if sub else 0.07
        marker_x = 0.085 if sub else 0.065
        ax.add_patch(plt.Circle((marker_x, y + 0.012), 0.006 if not sub else 0.004,
                                color=BRAND if not sub else LINE, transform=ax.transAxes))
        ax.text(bx, y, text, color=INK if not sub else MUTED,
                fontsize=16 if not sub else 13, va="center")
        y -= 0.085 if not sub else 0.066
    _footer(ax)
    pdf.savefig(fig)
    plt.close(fig)


def _box(ax, x, y, w, h, title, lines, fc=PANEL, ec=LINE, tc=INK, title_color=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc=fc, ec=ec, lw=1.6, transform=ax.transAxes))
    ax.text(x + w / 2, y + h - 0.05, title, color=title_color or BRAND, fontsize=13,
            fontweight="bold", ha="center", va="top")
    ax.text(x + w / 2, y + h - 0.12, "\n".join(lines), color=tc, fontsize=10.5,
            ha="center", va="top")


def _arrow(ax, p0, p1, color=MUTED, style="-|>", lw=1.8, rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=16,
                                 color=color, lw=lw, shrinkA=4, shrinkB=4,
                                 connectionstyle=f"arc3,rad={rad}", transform=ax.transAxes))


def slide_architecture(pdf):
    fig, ax = _fig()
    ax.text(0.06, 0.885, "Architecture & communication topology", color=INK,
            fontsize=26, fontweight="bold")
    _rule(ax, 0.845)

    # Local machine container
    ax.add_patch(FancyBboxPatch((0.05, 0.18), 0.5, 0.58, boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc="#f8fafc", ec=LINE, lw=1.4, ls="--", transform=ax.transAxes))
    ax.text(0.07, 0.72, "YOUR MACHINE (local)", color=MUTED, fontsize=11, fontweight="bold")

    _box(ax, 0.08, 0.50, 0.44, 0.16, "Ragnarok frontend (browser)",
         ["React + TypeScript", "views, model editor, plugin host"])
    _box(ax, 0.08, 0.23, 0.44, 0.18, "Plugin's own local server  (optional)",
         ["e.g. PyPSA build server", "started via run.command", "reached over localhost"],
         fc="#ecfeff", ec=BRAND, title_color=BRAND)

    # Server side
    _box(ax, 0.66, 0.46, 0.29, 0.22, "Ragnarok backend",
         ["FastAPI + PyPSA + linopy", "HiGHS solver", "plugin-agnostic", "(moving server-side)"],
         fc="#eef2ff", ec=ACCENT, title_color=ACCENT)

    # arrows
    _arrow(ax, (0.52, 0.585), (0.66, 0.575), color=ACCENT)
    ax.text(0.585, 0.62, "HTTP /api/run", color=ACCENT, fontsize=10, ha="center")
    ax.text(0.585, 0.545, "model + constraintSpecs", color=MUTED, fontsize=9, ha="center")

    _arrow(ax, (0.30, 0.50), (0.30, 0.41), color=BRAND, style="<|-|>")
    ax.text(0.315, 0.455, "config -> build ;  model <-", color=BRAND, fontsize=9.5, ha="left")

    # forbidden link
    _arrow(ax, (0.52, 0.31), (0.665, 0.47), color=DANGER, style="-", lw=1.6, rad=-0.15)
    ax.text(0.60, 0.345, "NEVER", color=DANGER, fontsize=11, fontweight="bold", ha="center")
    ax.text(0.60, 0.315, "plugin never calls\nthe Ragnarok backend", color=DANGER, fontsize=8.5, ha="center", va="top")

    ax.text(0.06, 0.13, "Rule:  plugin <-> Ragnarok frontend  OK    ·    frontend <-> Ragnarok backend  OK    ·    plugin <-> Ragnarok backend  NEVER",
            color=INK, fontsize=11.5)
    _footer(ax)
    pdf.savefig(fig)
    plt.close(fig)


def slide_plugin_flow(pdf):
    fig, ax = _fig()
    ax.text(0.06, 0.885, "How a plugin flows into the model", color=INK,
            fontsize=26, fontweight="bold")
    _rule(ax, 0.845)

    steps = [
        ("1. Install", ".zip = manifest\n+ index.js"),
        ("2. GUI", "manifest ->\nconfig form"),
        ("3. Send", "transform ->\nlocal /build"),
        ("4. Receive", "model replaces\nthe workbook"),
        ("5. Constraints", "DSL rides in\nthe model"),
        ("6. Run", "-> specs ->\nsolved"),
    ]
    x = 0.06
    w = 0.135
    gap = 0.012
    y = 0.50
    h = 0.20
    for i, (t, d) in enumerate(steps):
        fc = "#ecfeff" if i in (2, 3) else PANEL
        ec = BRAND if i in (2, 3) else LINE
        _box(ax, x, y, w, h, t, [d], fc=fc, ec=ec, title_color=BRAND if i in (2, 3) else INK)
        if i < len(steps) - 1:
            _arrow(ax, (x + w, y + h / 2), (x + w + gap, y + h / 2), color=LINE)
        x += w + gap

    ax.text(0.06, 0.38, "Server registration", color=BRAND, fontsize=14, fontweight="bold")
    ax.text(0.06, 0.31,
            "The plugin's heavy server is registered once in the Ragnarok project's  plugins.env\n"
            "(<absolute server dir>|<run command>).  run.command launches every registered server on\n"
            "startup, auto-using the plugin's own .venv if present.  The plugin connects to it over localhost.",
            color=INK, fontsize=12.5, va="top")
    ax.text(0.06, 0.135,
            "Constraints from a plugin (capacity factors, custom limits) ride inside the built model as a\n"
            "RAGNAROK_CustomDSL sheet, show up editable in Advanced Constraints, and apply on the next Run.",
            color=MUTED, fontsize=12, va="top")
    _footer(ax)
    pdf.savefig(fig)
    plt.close(fig)


def build(out: Path):
    with PdfPages(out) as pdf:
        slide_title(pdf)

        slide_bullets(pdf, "What is Ragnarok?", [
            "A local, browser-based GUI for building and solving PyPSA power-system models.",
            "Frontend (React + TypeScript) runs on your machine; the backend solves with HiGHS.",
            "Models are spreadsheets: PyPSA component sheets + Ragnarok config sheets.",
            "Open / import an .xlsx workbook, edit, Run, analyse, and export -- full round-trip.",
            "Extensible through frontend-only plugins (no backend coupling).",
        ], kicker="Overview")

        slide_bullets(pdf, "What you can do", [
            "Build a network: buses, generators, loads, lines, links, storage, processes.",
            "Solve single-period dispatch, multi-year (pathway) planning, and rolling horizon.",
            "Apply policy: carbon price, native global constraints, and a custom-constraint DSL.",
            "Run stochastic and security-constrained (SCLOPF) studies.",
            "Explore results: KPI dashboards, time-series charts, maps, and cross-run comparison.",
            "Import / export the full input + output workbook entirely on the frontend.",
        ], kicker="Capabilities")

        slide_bullets(pdf, "The five views", [
            "Build (B) -- author the model step by step, on a grid or a map.",
            "Model (M) -- the raw component sheet tables.",
            "Settings (S) -- scenarios, window, planning, rolling, carbon, constraints, solver.",
            "  Standard Constraints = the global_constraints sheet (CO2 caps, expansion limits).",
            "  Advanced Constraints = a custom linear-constraint DSL.",
            "Analytics (A) -- validation, KPIs, dashboards, and run comparison.",
            "Plugins (P) -- install / uninstall plugins and drive their GUIs.",
        ], kicker="Workflow")

        slide_architecture(pdf)

        slide_bullets(pdf, "Constraints", [
            "Standard: rows in the global_constraints sheet -- handled natively by PyPSA.",
            "Advanced: a human-friendly DSL, one linear constraint per line. Examples:",
            "  gen(coal) <= 200000      cf(\"solar\") <= 0.5      emissions <= 0.4 * gen",
            "The frontend compiles the DSL to a constraintSpecs JSON and sends it on Run.",
            "Plugin-produced constraints arrive as a RAGNAROK_CustomDSL sheet, then flow the same way.",
            "Applied constraints (and shadow prices) are reported back after each solve.",
        ], kicker="Policy")

        slide_bullets(pdf, "Plugins: what they are", [
            "A plugin is a .zip: a module.json manifest + a JavaScript entry (index.js).",
            "Installed in the browser (Plugins tab). Install / Uninstall only -- no enable toggle.",
            "The host renders the plugin's GUI from the manifest config schema.",
            "JS hooks run in the browser: transform (replace model), contribute (merge + constraints),",
            "  analyze (read run output), plus named action hooks (e.g. connect).",
            "A plugin may run its own local server for heavy work -- never the Ragnarok backend.",
        ], kicker="Plugins")

        slide_plugin_flow(pdf)

        slide_bullets(pdf, "How to build a plugin", [
            "1. Write module.json: id, name, entry, a config schema (fields + tables + visibleWhen),",
            "   a panel layout, and -- if it has a server -- a server block (run / cwd / port / health).",
            "2. Write index.js (CommonJS): export transform / contribute / analyze and any action hooks.",
            "3. Optional: put heavy compute in your own backend server reached over localhost.",
            "4. Zip module.json + index.js and Install it in the Plugins tab.",
            "5. Register the server in plugins.env; run.command launches it. Click Connect, then Run.",
            "Full guide: docs/plugin.md",
        ], kicker="Authoring")

        slide_bullets(pdf, "Example: Dashboard Importer", [
            "A real plugin that turns a PyPSA dashboard workbook into a Ragnarok model.",
            "Rich manifest GUI: settings + reference tables (aggregation rules, CF limits, carbon).",
            "Heavy build (topology, aggregation, scaling) runs in the plugin's own FastAPI server.",
            "Send model -> POST config to localhost build server -> model returned to the frontend.",
            "CF limits (max_cf / min_cf) become cf(\"carrier\") <= / >= lines in Advanced Constraints.",
            "The Ragnarok backend is never contacted by the plugin.",
        ], kicker="Worked example")

        slide_bullets(pdf, "Where to read more", [
            "docs/user-manual.md -- install, launch, every view and feature, capabilities.",
            "docs/architecture.md -- tech stack, topology, data flow, process logic, design.",
            "docs/backend.md -- HTTP API, solve pipeline, network build, modes, constraints.",
            "docs/frontend.md -- App state, views, features, and the plugin host.",
            "docs/plugin.md -- the full plugin authoring guide.",
        ], kicker="Next")

    return out


if __name__ == "__main__":
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("ragnarok-architecture.pdf")
    build(out_path)
    print(f"wrote {out_path}")
