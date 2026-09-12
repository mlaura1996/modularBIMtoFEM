# -*- coding: utf-8 -*-
"""Builds a thesis-ready Word document for the self-weight-only (bonded, no
Task A interfaces) analysis's eigenvalue/modal results
(docker/opensees/eigen_self_weight_full_aggregate_refined_joints.py, 0.6 m
global mesh with local refinement to 0.15 m at 4 flagged joints), plus the
clean-style self-weight and mode-shape figures produced by
docker/opensees/plot_eigen_and_selfweight_refined.py: a native Word table
of all computed modes (period, frequency, modal participation mass
ratios), descriptive text, and the embedded deformed-shape / mode-shape
figures.

Uses the REFINED-JOINTS mesh run, superseding both the original 1.0 m one
(eigen_self_weight_full_aggregate_clean.py) and the uniform-0.6 m one
(eigen_self_weight_full_aggregate_fine.py) - the 1.0 m mode shapes'
localized appearance ("sembra che si staccano due unita") prompted first a
0.6 m re-run, then (after the user pushed back a second time, on mode 3)
local refinement at the specific small joints those modes concentrate on,
to rule out the joint's own mesh resolution as the cause. See the "Mesh
sensitivity and localized modes" section below for what both checks found.

Run locally (not in Docker - only needs python-docx + the JSON/txt/PNG
files already written under output/castelnuovo/, all bind-mounted from the
same repo checkout the Docker runs used):

    pip install python-docx   # if not already available
    python scripts/build_eigen_results_docx.py

Writes output/castelnuovo/plots/Full_Aggregate_Eigen_Results.docx.
"""
import json
import os
import sys

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLOTS_DIR = os.path.join(REPO_ROOT, "output", "castelnuovo", "plots")
EIGEN_DIR = os.path.join(REPO_ROOT, "output", "castelnuovo",
                          "recorders_full_aggregate_clean_eigen_refined")
SUMMARY_PATH = os.path.join(EIGEN_DIR, "summary.json")
MODAL_PROPS_PATH = os.path.join(EIGEN_DIR, "modal_properties.txt")
EIGENVALUES_PATH = os.path.join(EIGEN_DIR, "eigenvalues.txt")
OUT_PATH = os.path.join(PLOTS_DIR, "Full_Aggregate_Eigen_Results.docx")
IMG_PREFIX = "full_aggregate_refined"
IMG_SUFFIX = "REFINED"

VIEW_SUFFIXES = ["view1", "view2"]

# --- load numbers ---------------------------------------------------------
for p in (SUMMARY_PATH, MODAL_PROPS_PATH, EIGENVALUES_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p} - run docker/opensees/"
                  f"eigen_self_weight_full_aggregate_clean.py first.")

with open(SUMMARY_PATH) as f:
    s = json.load(f)

with open(EIGENVALUES_PATH) as f:
    eigenvalues = [float(x) for x in f.read().split()]

with open(MODAL_PROPS_PATH) as f:
    modal_txt = f.read()

# Per-mode (period, freq) from section "2. EIGENVALUE ANALYSIS"
import math
periods = {}
freqs = {}
for i, lam in enumerate(eigenvalues, start=1):
    T = 2 * math.pi / math.sqrt(lam)
    periods[i] = T
    freqs[i] = 1.0 / T

# Per-mode, non-cumulative participation mass ratios (%) - section 9
section9 = modal_txt.split("9. MODAL PARTICIPATION MASS RATIOS")[1].split("* 10.")[0]
ratios = {}  # mode -> (mx, my, mz, rmx, rmy, rmz)
for line in section9.splitlines():
    parts = line.split()
    if len(parts) == 7 and parts[0].isdigit():
        mode = int(parts[0])
        ratios[mode] = tuple(float(x) for x in parts[1:])

# Cumulative ratios (%) - section 10, for the closing "how much mass is
# captured by the 10 computed modes" statement.
section10 = modal_txt.split("* 10. MODAL PARTICIPATION MASS RATIOS")[1]
cum_rows = []
for line in section10.splitlines():
    parts = line.split()
    if len(parts) == 7 and parts[0].isdigit():
        cum_rows.append((int(parts[0]), tuple(float(x) for x in parts[1:])))
cum_final = cum_rows[-1][1] if cum_rows else None  # (mx,my,mz,rmx,rmy,rmz) after mode 10

# Rank by translational (MX+MY) significance, same criterion used to choose
# which modes get plotted (docker/opensees/plot_eigen_and_selfweight_clean.py)
ranked = sorted(ratios.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
top_modes = [m for m, _ in ranked[:3]]

# --- document setup --------------------------------------------------------
doc = Document()

section = doc.sections[0]
section.page_width = Cm(21.0)
section.page_height = Cm(29.7)
section.left_margin = Cm(2.5)
section.right_margin = Cm(2.5)
section.top_margin = Cm(2.5)
section.bottom_margin = Cm(2.5)

normal = doc.styles["Normal"]
normal.font.name = "Times New Roman"
normal.font.size = Pt(12)
normal.paragraph_format.line_spacing = 1.15
normal.paragraph_format.space_after = Pt(10)


def heading(text, level=2):
    h = doc.add_heading(level=level)
    run = h.add_run(text)
    run.font.name = "Times New Roman"
    return h


def para(text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    return p


def shade_cell(cell, hex_color):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def add_summary_table(rows, headers=("Quantity", "Value")):
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.font.bold = True
                r.font.name = "Times New Roman"
        shade_cell(hdr[i], "D9D9D9")
    for k, v in rows:
        row = tbl.add_row().cells
        row[0].text = k
        row[1].text = v
        for cell in row:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(11)
    tbl.columns[0].width = Cm(9.0)
    tbl.columns[1].width = Cm(6.0)
    doc.add_paragraph()
    return tbl


def add_modes_table():
    headers = ["Mode", "T (s)", "f (Hz)", "MX (%)", "MY (%)", "MZ (%)"]
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for p in hdr[i].paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.font.bold = True
                r.font.name = "Times New Roman"
                r.font.size = Pt(10.5)
        shade_cell(hdr[i], "D9D9D9")

    col_widths = [Cm(1.6), Cm(2.2), Cm(2.2), Cm(2.4), Cm(2.4), Cm(2.4)]

    for mode in sorted(ratios):
        mx, my, mz, rmx, rmy, rmz = ratios[mode]
        values = [
            str(mode),
            f"{periods[mode]:.3f}",
            f"{freqs[mode]:.3f}",
            f"{mx:.2f}",
            f"{my:.2f}",
            f"{mz:.4f}",
        ]
        row = tbl.add_row().cells
        for i, v in enumerate(values):
            row[i].text = v
            for p in row[i].paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in p.runs:
                    r.font.name = "Times New Roman"
                    r.font.size = Pt(10.5)
                    if mode in top_modes:
                        r.font.bold = True
        if mode in top_modes:
            for cell in row:
                shade_cell(cell, "E2EFDA")

    for i, w in enumerate(col_widths):
        tbl.columns[i].width = w
    doc.add_paragraph()
    return tbl


def add_figure_row(paths, caption):
    """Two (or however many) images side by side, one caption underneath."""
    any_found = False
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    width = Cm(8.0) if len(paths) <= 2 else Cm(6.0)
    for path in paths:
        if not os.path.isfile(path):
            continue
        any_found = True
        run = p.add_run()
        run.add_picture(path, width=width)
        p.add_run("  ")
    if not any_found:
        wp = doc.add_paragraph()
        wr = wp.add_run(f"[figures not found: {paths}]")
        wr.italic = True
        wr.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
        return
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    crun = c.add_run(caption)
    crun.italic = True
    crun.font.size = Pt(10.5)
    crun.font.name = "Times New Roman"
    c.paragraph_format.space_after = Pt(14)


# ==========================================================================
heading("Self-Weight and Modal (Eigenvalue) Analysis - Bonded Model "
        "(No Task A Interfaces)", level=2)

para(
    "This section reports the self-weight static check and the modal "
    "(eigenvalue) analysis of the full Castelnuovo di Porto aggregate "
    "(cleaned geometry), modelled with fully bonded contacts between "
    "adjacent solids - i.e. without the Task A wall-to-wall contact "
    "interfaces described elsewhere in this chapter. The bonded "
    "assumption is used here deliberately: it removes the contact "
    "nonlinearity from the eigenproblem, giving a linear-elastic reference "
    "against which the effect of the contact interfaces can later be "
    "assessed. The mesh "
    f"({s['mesh_nodes']:,} nodes, {s['mesh_elements']:,} elements at "
    f"{s.get('global_mesh_size_m', 0.6):g} m global size, matching the "
    "static-only interface checks elsewhere in this chapter, with local "
    f"refinement to {s.get('local_size_min_m', 0.15):g} m at 4 specific "
    "joints - see \"Mesh sensitivity and localized modes\" below) is not "
    "domain-decomposed (a single MPI rank): this was necessary to make the "
    "eigenvalue solve (ARPACK, via OpenSees' built-in eigen command) "
    "converge at all - it stalled indefinitely under MPI domain "
    "partitioning regardless of mesh size or number of requested modes, "
    "a limitation also encountered with the serial STKO-based pipeline "
    "used in an earlier chapter."
)

heading("Self-weight check", level=3)
para(
    "As with the interfaces model, the total vertical reaction at the "
    "base is compared against the independently calculated self-weight, "
    "ρ·g·V, as a basic correctness check on the boundary conditions and "
    "mass before trusting the eigenvalue results built on the same model."
)
rows = [
    ("Mesh nodes", f"{s['mesh_nodes']:,}"),
    ("Mesh elements", f"{s['mesh_elements']:,}"),
    ("MPI ranks / partitions", "1 (no domain decomposition)"),
    ("Total volume", f"{s['total_volume_m3']:.2f} m³"),
    ("Self-weight, calculated (ρ·g·V)", f"{s['self_weight_calculated_N']:,.1f} N"),
    ("Total base reaction, analysis", f"{s['total_base_reaction_N']:,.1f} N"),
    ("Weight / reaction difference", f"{s['weight_reaction_diff_pct']:.3f} %"),
]
add_summary_table(rows)

para(
    f"The base reaction matches the calculated self-weight to within "
    f"{abs(s['weight_reaction_diff_pct']):.3f}%, confirming the bonded "
    "model's mass and boundary conditions before proceeding to the modal "
    "analysis."
)

add_figure_row(
    [os.path.join(PLOTS_DIR, f"{IMG_PREFIX}_selfweight_{IMG_SUFFIX}_{v}.png")
     for v in VIEW_SUFFIXES],
    "Figure 1 - Deformed shape under self-weight (bonded model), "
    "×200 magnification.",
)

heading("Modal analysis", level=3)
para(
    f"{s['n_modes']} modes were computed. Table 1 lists, for every mode: "
    "the natural period T and frequency f, and the modal participation "
    "mass ratios in the two horizontal directions (MX, MY) and the "
    "vertical direction (MZ), each expressed as a percentage of the "
    "structure's total free mass in that direction - the standard measure "
    "of how much a given mode actually contributes to the structure's "
    "response, as opposed to its position in the eigenvalue ordering."
)

heading("Table 1 - Modal analysis results (all modes)", level=3)
add_modes_table()

if cum_final is not None:
    cmx, cmy, cmz, _, _, _ = cum_final
    para(
        f"Cumulatively, the {s['n_modes']} computed modes capture "
        f"{cmx:.1f}% of the total mass in X and {cmy:.1f}% in Y "
        "(vertical participation, MZ, remains negligible throughout, as "
        "expected for a self-weight-dominated masonry aggregate with no "
        "vertical excitation mechanism)."
    )

para(
    "The three most significant modes by translational participation "
    f"(MX + MY) are modes {', '.join(str(m) for m in top_modes)} "
    "(highlighted in Table 1), rather than the first three by eigenvalue "
    "order - mode 2, for instance, has a lower period than mode 3 but "
    "contributes comparatively little translational mass. Their deformed "
    "shapes are shown below, each normalised to a common maximum visual "
    "displacement (the eigenvectors themselves carry no physical "
    "amplitude) and coloured by relative modal displacement magnitude, "
    "with the underlying solid geometry's edges overlaid (drawn from the "
    "CAD curves the mesh was generated from, not the finite-element mesh "
    "itself) so individual blocks and openings stay identifiable."
)

heading("Mesh sensitivity and localized modes", level=3)
para(
    "The mode shapes first computed at a coarser (1.0 m) mesh showed a "
    "small region moving with much larger relative amplitude than the "
    "rest of the structure in several modes, visually reading as two "
    "units separating - in a location with no Task A interface nearby, "
    "which is what prompted this closer look rather than accepting the "
    "images at face value. A dedicated check "
    "(docker/opensees/diagnose_mode_localization.py) attributed each "
    "localized region to specific volumes by cross-referencing high-"
    "displacement nodes with the same touching-surface detector "
    "(InterfaceDetection.find_touching_surface_pairs()) used to build the "
    "Task A interface candidate list, confirming first that fragment() "
    "had genuinely fused every touching pair (no unfused gap anywhere) - "
    "so any softness found is a property of the joint's geometry, not a "
    "modelling defect."
)
para(
    "Two distinct causes were found, with two different implications:"
)
para(
    "Modes 1 and 3 both isolate almost entirely on one volume: a large, "
    "thin, flat solid (bounding box roughly 2.9 × 7.5 × 1.0 m) tied to its "
    "neighbours through only a 0.185 m² vertical face and a 3.857 m² "
    "horizontal bearing face - a slab-like element resting on, and only "
    "narrowly keyed into, the surrounding walls. Re-running the same "
    "check at the finer 0.6 m mesh (used for the results in this section) "
    "reproduces the identical localization on the identical volume, "
    "confirming this is a genuine structural weak point of the aggregate "
    "as modelled - a flexible slab/floor element with a comparatively "
    "small tie-in area - rather than a meshing artefact."
)
para(
    "Mode 8, by contrast, isolated at 1.0 m on three small, slender "
    "volumes (roughly 0.2-1.4 m across) each meshed with only 16-18 "
    "nodes, connected to their neighbour through two 0.1 m² faces - too "
    "coarse to resolve those small contact areas with more than one or "
    "two elements. At the finer 0.6 m mesh, mode 8 no longer isolates on "
    "any single volume: the displacement spreads over a broad region of "
    "the façade instead (Figure showing Mode 8 below). This mode's "
    "earlier localized appearance was therefore a coarse-mesh artefact, "
    "not a real, isolated structural feature - the finer mesh used here "
    "was adopted for exactly this reason, confirmed by the fact that the "
    "eigenvalue solver's earlier stalling turned out to depend on MPI "
    "domain partitioning, not on mesh density, so refining the mesh "
    "without partitioning was always available as a check."
)
para(
    "A second, independent check addressed the mode-1/3 slab's plotted "
    "shape directly: at the visual displacement scale first used "
    "(normalised so the single most-displaced node reaches 2 m), the free "
    "edges of a large, mostly free-standing slab rotating about a narrow "
    "bearing line swing far enough to look like a gap opening up, even "
    "though the joint itself does not move. "
    "docker/opensees/render_volume118_check.py confirms numerically - not "
    "just visually - that this is not the case: 41 mesh node ids are "
    "literally shared (identical row in the stiffness matrix) between "
    "volume 118 and its bearing neighbour, and 4 between volume 118 and "
    "its tied neighbour, with no node-splitting applied anywhere in this "
    "bonded model. The mode-shape figures below use a smaller, more "
    "proportionate 0.5 m visual scale and overlay the undeformed geometry "
    "in light grey for direct comparison, so the joints read as continuous "
    "without needing the underlying node count alongside them."
)
para(
    "A third check went further still, after the same sharp colour "
    "transition was flagged again on mode 3's plot even at the smaller "
    "visual scale: local mesh refinement (0.6 m down to 0.15 m within 1 m "
    "of the 4 joints modes 1/3 concentrate on) increases the number of "
    "literally shared mesh nodes at those joints by 5-9× (e.g. 4 → 22 at "
    "volume 118's tied edge, 41 → 269 at its bearing face) without "
    "changing the mechanism at all - the same two volumes (118, 106) "
    "still dominate the same modes, and the sharp colour transition at "
    "their joints is unchanged in character. This rules out coarse joint "
    "resolution as the cause: it is a real, continuous, but geometrically "
    "narrow connection producing a genuinely steep displacement gradient, "
    "which a flat-shaded (one colour per mesh triangle) plot renders as a "
    "hard edge rather than a gradient. A related check "
    "(docker/opensees/diagnose_joint_gaps.py) also ruled out a second "
    "hypothesis - that the small joint areas are an artefact of "
    "fragment() only catching a thin sliver of a much larger near-miss in "
    "the source geometry: no larger nearby (within 1.5 m), roughly-"
    "parallel, un-fused face pair exists for any of the 4 joints, so the "
    "small area is the full, real extent of contact in the source "
    "geometry, not a tolerance artefact. The mode-shape figures below use "
    "this refined-joints mesh and colour the surface by Laplacian-"
    "smoothed (neighbour-averaged) nodal values rather than the raw "
    "per-node field, which reads as a smoother gradient without changing "
    "the underlying result."
)
para(
    "Refining the joints did shift which modes rank as most significant "
    "by translational participation - mode 9's share rose from about 10% "
    "to 21% (overtaking mode 1, which fell from 11% to 10%), while modes "
    "3 and 8 stayed the top two in both meshes - a genuine mesh-"
    "sensitivity finding worth noting in the methodology, distinct from "
    "the joint-continuity question above: the modes selected as \"most "
    "significant\" in Table 1 and shown individually below are computed "
    "on this refined-joints mesh."
)

heading("Deformed shapes - all modes", level=3)
para(
    "All 10 computed modes are shown below (user request: images for all "
    "10 modes, not just the 3 most significant). The 3 most significant "
    "by translational participation are marked accordingly."
)

for mode in sorted(ratios):
    mx, my, mz, rmx, rmy, rmz = ratios[mode]
    sig_tag = " (most significant)" if mode in top_modes else ""
    heading(f"Mode {mode}{sig_tag} (T = {periods[mode]:.3f} s, "
            f"f = {freqs[mode]:.3f} Hz)", level=4)
    para(
        f"Modal participation mass ratios: MX = {mx:.2f}%, MY = {my:.2f}%, "
        f"MZ = {mz:.4f}%."
    )
    add_figure_row(
        [os.path.join(PLOTS_DIR, f"{IMG_PREFIX}_mode{mode}_{IMG_SUFFIX}_{v}.png")
         for v in VIEW_SUFFIXES],
        f"Mode {mode} deformed shape (two views), coloured by relative "
        "modal displacement magnitude.",
    )

doc.save(OUT_PATH)
print(f"Wrote {OUT_PATH}")
