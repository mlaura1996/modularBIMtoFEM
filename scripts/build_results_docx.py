# -*- coding: utf-8 -*-
"""Builds a thesis-ready Word document for the full-aggregate + Task A
contact interfaces analysis (docker/opensees/full_aggregate_with_
interfaces_clean.py): a native Word results table (not a flat image) with
descriptive text, plus the gmsh partition/deformed-shape screenshots
(docker/opensees/full_aggregate_with_interfaces_clean.py's
render_gmsh_views(), three camera angles each) embedded with captions.

Run locally (not in Docker - only needs python-docx + the JSON/PNG files
docker/opensees/full_aggregate_with_interfaces_clean.py already wrote
under output/castelnuovo/plots/, both bind-mounted from the same repo
checkout the Docker run used):

    pip install python-docx   # if not already available
    python scripts/build_results_docx.py

Writes output/castelnuovo/plots/Full_Aggregate_Interfaces_Results.docx.
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
SUMMARY_PATH = os.path.join(PLOTS_DIR, "full_aggregate_interfaces_clean_summary.json")
OUT_PATH = os.path.join(PLOTS_DIR, "Full_Aggregate_Interfaces_Results.docx")

VIEW_NAMES = ["Vista 1", "Vista 2", "Vista 3"]


def view_path(prefix, view_name):
    return os.path.join(PLOTS_DIR, f"{prefix}_{view_name.replace(' ', '_')}.png")


# --- load the numbers written by the analysis script --------------------
if not os.path.isfile(SUMMARY_PATH):
    sys.exit(f"Missing {SUMMARY_PATH} - run docker/opensees/"
              f"full_aggregate_with_interfaces_clean.py first.")
with open(SUMMARY_PATH) as f:
    s = json.load(f)

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


def add_table(rows, headers=("Quantity", "Value")):
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


def add_figure_row(prefix, caption_prefix):
    """One row of the three VIEWS side by side (or as available), captioned."""
    any_found = False
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for view_name in VIEW_NAMES:
        path = view_path(prefix, view_name)
        if not os.path.isfile(path):
            continue
        any_found = True
        run = p.add_run()
        run.add_picture(path, width=Cm(6.0))
        p.add_run("  ")
    if not any_found:
        wp = doc.add_paragraph()
        wr = wp.add_run(f"[figures not found: {prefix}_<Vista 1|2|3>.png]")
        wr.italic = True
        wr.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
        return
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    crun = c.add_run(caption_prefix)
    crun.italic = True
    crun.font.size = Pt(10.5)
    crun.font.name = "Times New Roman"
    c.paragraph_format.space_after = Pt(14)


def add_single_figure(path, caption):
    """One standalone image (not the three-views layout) - the matplotlib
    deformed-shape plot, which is a single figure, not per-angle renders."""
    if not os.path.isfile(path):
        wp = doc.add_paragraph()
        wr = wp.add_run(f"[figure not found: {path}]")
        wr.italic = True
        wr.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(path, width=Cm(13.0))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    crun = c.add_run(caption)
    crun.italic = True
    crun.font.size = Pt(10.5)
    crun.font.name = "Times New Roman"
    c.paragraph_format.space_after = Pt(14)


# ==========================================================================
heading("Full-Aggregate Analysis with Task A Contact Interfaces", level=2)

para(
    "This section reports the results of a linear-elastic, self-weight-only "
    "static analysis of the full Castelnuovo di Porto aggregate (cleaned "
    "geometry, see § [geometry cleaning section]), including the "
    "wall-to-wall contact interfaces selected interactively with the tool "
    "described in § [interactive selection tool section]. The purpose of "
    "this run is twofold: to confirm that the analysis converges with a "
    "deliberately chosen, non-trivial set of contact interfaces (11, rather "
    "than an arbitrary small subset), and to verify the model's self-weight "
    "balance - the total base reaction should equal the independently "
    "calculated weight of the structure, ρ·g·V, to within numerical "
    "tolerance."
)

para(
    "The analysis is distributed across "
    f"{s['mpi_ranks']} MPI ranks (OpenSeesMP, MUMPS parallel direct solver) "
    "via domain decomposition of the finite-element mesh. "
    f"Table 1 summarises the geometry, mesh, and analysis outcome."
)

heading("Table 1 - Model and results summary", level=3)

rows = [
    ("Volumes (solids)", f"{s['volumes']}"),
    ("Candidate interfaces detected", f"{s['candidate_interfaces']}"),
    ("Interfaces selected", f"{s['selected_interfaces']}"),
    ("Duplicate nodes (split interfaces)", f"{s['duplicate_nodes']}"),
    ("Mesh nodes", f"{s['mesh_nodes']:,}"),
    ("Mesh elements", f"{s['mesh_elements']:,}"),
    ("MPI ranks / partitions", f"{s['mpi_ranks']}"),
    ("Ground-bearing volumes", f"{s['ground_bearing_volumes']}"),
    ("Base-fixed nodes", f"{s['base_fixed_nodes']}"),
    ("Converged on all ranks", "Yes" if s["converged_all_ranks"] else "NO"),
    ("Total volume", f"{s['total_volume_m3']:.2f} m³"),
    ("Self-weight, calculated (ρ·g·V)", f"{s['self_weight_calculated_N']:,.1f} N"),
    ("Total base reaction, analysis", f"{s['total_base_reaction_N']:,.1f} N"),
    ("Weight / reaction difference", f"{s['weight_reaction_diff_pct']:.3f} %"),
    ("Max. downward displacement", f"{s['max_downward_displacement_mm']:.3f} mm"),
]
add_table(rows)

para(
    "The base reaction sum matches the independently calculated self-weight "
    f"to within {abs(s['weight_reaction_diff_pct']):.3f}%, confirming that "
    "the base boundary conditions (per-volume ground-bearing detection, "
    "§ [base fixity section]) and the contact-interface node-splitting "
    "(§ [Task A implementation section]) are both correctly represented in "
    "the assembled model - an incorrect node substitution, in particular, "
    "would either disconnect part of the structure (singular stiffness "
    "matrix, analysis fails to converge) or double-count/omit mass, both of "
    "which would show up here as a large imbalance rather than a numerical "
    "rounding-level one."
)

heading("Domain decomposition", level=3)
para(
    f"Figure 1 shows the {s['mpi_ranks']}-way MPI partition of the mesh, "
    "coloured by owning rank (each solid coloured by whichever rank owns "
    "the majority of its elements)."
)
add_figure_row("full_aggregate_interfaces_clean_partitions_gmsh",
                "Figure 1 - Mesh partitioned across MPI ranks (Vista 1, 2, 3).")

heading("Deformed shape under self-weight", level=3)
para(
    f"Figure 2 shows the deformed shape under self-weight alone, magnified "
    f"×200 for visibility (max. actual downward displacement: "
    f"{s['max_downward_displacement_mm']:.3f} mm)."
)
add_single_figure(
    os.path.join(PLOTS_DIR, "full_aggregate_interfaces_clean_deformed_uz.png"),
    "Figure 2 - Deformed shape under self-weight, ×200 magnification "
    "(undeformed shape overlaid in grey for reference).")

heading("Implementation verification: two defects found and corrected", level=3)

para(
    "Reaching the converged result above required diagnosing and fixing two "
    "implementation defects, both specific to the parallel (TCL/OpenSeesMP) "
    "export path rather than the geometry, the contact-element formulation, "
    "or the interface selection itself. Both are reported here because they "
    "affected earlier convergence results obtained with a smaller, "
    "hand-picked interface subset, and because the diagnostic process - not "
    "just the fix - is part of what establishes confidence in the final "
    "model."
)

para(
    "First, the node-splitting step that decouples the two sides of a "
    "selected interface (so that a zeroLengthContactASDimplex element, "
    "rather than a rigidly shared node, connects them) was applying its "
    "substitution to every element in the model regardless of which volume "
    "that element actually belongs to. Since the boundary node in question "
    "is, by construction, shared with the neighbouring (non-split) volume "
    "as well, that volume's own elements were being silently rewritten too - "
    "leaving the original mesh node referenced by no solid element at all, "
    "connected to the rest of the model only through its own contact "
    "spring. This produces a numerically singular global stiffness matrix, "
    "and was traced by direct inspection of the exported model: counting, "
    "for a given interface, how many tetrahedral elements referenced its "
    "original node versus its duplicate confirmed the original was "
    "orphaned. The fix restricts the substitution to elements belonging to "
    "the interface's own split volume, determined before partitioning (see "
    "below) and passed explicitly into the element-export routine."
)

para(
    "Second, the natural fix for the first defect - querying which "
    "elements belong to a given volume from inside the same export "
    "routine - returned no elements at all, because it was being called "
    "after the mesh had already been partitioned across MPI ranks; "
    "partitioning mutates the same internal bookkeeping that the query "
    "depends on. This mirrors an issue already known from the interface-"
    "detection step itself, which must also run before partitioning for the "
    "same reason. The corrected implementation computes the volume-to-"
    "element mapping once, before partitioning, and threads it through "
    "explicitly rather than recomputing it later."
)

para(
    "A related, lower-severity issue was found while reconciling a "
    "selection made interactively (on one machine, one library version) "
    "with the analysis environment (a Docker image pinning a different, "
    "older version of the same meshing library): the two environments "
    "assign different internal numeric tags to the same solids, even from "
    "the identical input geometry, so a selection identified by volume tag "
    "failed to reload in the analysis environment. The candidate identity "
    "key was changed to use only each interface's geometric centroid - "
    "which matched to sub-millimetre precision across both environments - "
    "removing the dependency on any tool-internal numbering."
)

doc.save(OUT_PATH)
print(f"Wrote {OUT_PATH}")
