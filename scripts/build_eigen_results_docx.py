# -*- coding: utf-8 -*-
"""Builds the thesis-ready Word document for the Castelnuovo modal results.

Targets the TIED run by default (docker/opensees/eigen_castelnuovo_tied.py,
80 modes): the model whose wall-to-wall continuity has been restored with
equalDOF constraints, built on the native framework (plain gmsh +
external/gmsh2opensees + ModelBuilder + openseespy) with the calibrated
masonry rather than the generic placeholder.

    python scripts/build_eigen_results_docx.py [recorders_dir] [out.docx]

Note on what this supersedes: an earlier version of this script documented
the apeGmsh refined-joints run and carried a long "mesh sensitivity and
localized modes" narrative. That narrative was written before the real
cause was found. The localized modes were NOT a meshing artefact and not a
genuine slab weak point - ~21 wall junctions are drawn 1.5-47 mm apart in
the source STEP, so those walls were structurally independent. Refining the
mesh could never have changed that, which is exactly why refining it did
not. The section below says so instead.

Figures: embedded only when images matching THIS run are present. Figures
from a different run are never substituted - they would show a different
model beside these numbers.

Needs python-docx, which in this environment lives only in
C:\\Users\\mlaur\\AppData\\Local\\Programs\\Python\\Python310\\python.exe.
"""
import json
import math
import os
import sys

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLOTS_DIR = os.path.join(REPO_ROOT, "output", "castelnuovo", "plots")
EIGEN_DIR = (sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    REPO_ROOT, "output", "castelnuovo", "recorders_castelnuovo_tied_80modes"))
OUT_PATH = (sys.argv[2] if len(sys.argv) > 2
            else os.path.join(PLOTS_DIR, "Castelnuovo_Modal_Results.docx"))

SUMMARY_PATH = os.path.join(EIGEN_DIR, "summary.json")
MODAL_PROPS_PATH = os.path.join(EIGEN_DIR, "modal_properties.txt")
EIGENVALUES_PATH = os.path.join(EIGEN_DIR, "eigenvalues.txt")

# Images are looked up per run; absent is reported, never silently replaced.
IMG_PREFIX = "full_aggregate_tied"
IMG_SUFFIX = "TIED"
VIEW_SUFFIXES = ["view1", "view2"]

TARGET_MASS = 85.0  # % - NTC2018 7.3.3.1 / EC8

# --- load numbers ---------------------------------------------------------
for p in (SUMMARY_PATH, MODAL_PROPS_PATH, EIGENVALUES_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p} - run docker/opensees/eigen_castelnuovo_tied.py "
                 f"--n-modes 80 first.")

with open(SUMMARY_PATH) as f:
    s = json.load(f)
with open(EIGENVALUES_PATH) as f:
    eigenvalues = [float(x) for x in f.read().split()]
with open(MODAL_PROPS_PATH) as f:
    modal_txt = f.read()

periods = {i: 2 * math.pi / math.sqrt(lam) for i, lam in enumerate(eigenvalues, 1)}
freqs = {i: 1.0 / T for i, T in periods.items()}


def parse_section(heading):
    body = modal_txt.split(heading)[1].split("\n*")[0]
    out = {}
    for line in body.splitlines():
        p = line.split()
        if len(p) == 7 and p[0].isdigit():
            out[int(p[0])] = tuple(float(x) for x in p[1:])
    return out


ratios = parse_section("9. MODAL PARTICIPATION MASS RATIOS")
cumulative = parse_section("* 10. MODAL PARTICIPATION MASS RATIOS")

assert len(ratios) == len(cumulative) == len(eigenvalues), (
    f"{len(ratios)} PRM rows, {len(cumulative)} cumulative rows, "
    f"{len(eigenvalues)} eigenvalues - the result files disagree about how "
    f"many modes this run has"
)
n_modes = len(eigenvalues)
cum_final = cumulative[max(cumulative)]


def first_mode_reaching(col, target=TARGET_MASS):
    """Lowest mode whose cumulative participation in `col` reaches target,
    or None - the number that justifies where the modal sum is truncated."""
    for m in sorted(cumulative):
        if cumulative[m][col] >= target:
            return m
    return None


cross_x = first_mode_reaching(0)
cross_y = first_mode_reaching(1)

# Rank by translational (MX+MY) significance - which modes actually drive
# the response, as opposed to where they sit in the eigenvalue ordering.
ranked = sorted(ratios.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
top_modes = [m for m, _ in ranked[:3]]

# --- document setup --------------------------------------------------------
doc = Document()
section = doc.sections[0]
section.page_width, section.page_height = Cm(21.0), Cm(29.7)
for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
    setattr(section, attr, Cm(2.5))

normal = doc.styles["Normal"]
normal.font.name = "Times New Roman"
normal.font.size = Pt(12)
normal.paragraph_format.line_spacing = 1.15
normal.paragraph_format.space_after = Pt(10)


def heading(text, level=2):
    h = doc.add_heading(level=level)
    h.add_run(text).font.name = "Times New Roman"
    return h


def para(text, italic=False):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run.italic = italic
    return p


def shade_cell(cell, hex_color):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def style_cell(cell, size=Pt(11), bold=False, center=False):
    for p in cell.paragraphs:
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p.runs:
            r.font.name = "Times New Roman"
            r.font.size = size
            r.font.bold = bold


def add_summary_table(rows, headers=("Quantity", "Value")):
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = "Table Grid"
    for i, h in enumerate(headers):
        tbl.rows[0].cells[i].text = h
        style_cell(tbl.rows[0].cells[i], bold=True)
        shade_cell(tbl.rows[0].cells[i], "D9D9D9")
    for k, v in rows:
        cells = tbl.add_row().cells
        cells[0].text, cells[1].text = k, v
        for c in cells:
            style_cell(c)
    tbl.columns[0].width = Cm(9.0)
    tbl.columns[1].width = Cm(6.0)
    doc.add_paragraph()
    return tbl


def add_modes_table():
    """Every computed mode, with the cumulative columns alongside the
    per-mode ones: on this structure the per-mode values are individually
    small and only the running total shows where the modal sum can be
    truncated."""
    headers = ["Mode", "T (s)", "f (Hz)", "MX (%)", "MY (%)", "MZ (%)",
               "\u03a3MX (%)", "\u03a3MY (%)"]
    widths = [Cm(1.3), Cm(1.8), Cm(1.8), Cm(1.8), Cm(1.8), Cm(1.8),
              Cm(2.0), Cm(2.0)]
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = "Table Grid"
    for i, h in enumerate(headers):
        tbl.rows[0].cells[i].text = h
        style_cell(tbl.rows[0].cells[i], size=Pt(9.5), bold=True, center=True)
        shade_cell(tbl.rows[0].cells[i], "D9D9D9")

    for mode in sorted(ratios):
        mx, my, mz = ratios[mode][:3]
        cx, cy = cumulative[mode][0], cumulative[mode][1]
        values = [str(mode), f"{periods[mode]:.4f}", f"{freqs[mode]:.3f}",
                  f"{mx:.2f}", f"{my:.2f}", f"{mz:.3f}",
                  f"{cx:.2f}", f"{cy:.2f}"]
        cells = tbl.add_row().cells
        for i, v in enumerate(values):
            cells[i].text = v
            style_cell(cells[i], size=Pt(9.5), bold=mode in top_modes,
                       center=True)
        if mode in top_modes:
            for c in cells:
                shade_cell(c, "E2EFDA")          # green: drives the response
        elif mode in (cross_x, cross_y):
            for c in cells:
                shade_cell(c, "FFF2CC")          # amber: 85% is reached here
    for i, w in enumerate(widths):
        tbl.columns[i].width = w
    doc.add_paragraph()
    return tbl


def add_figure_row(paths, caption):
    present = [p for p in paths if os.path.isfile(p)]
    if not present:
        p = doc.add_paragraph()
        r = p.add_run(f"[No figure available for this run yet: "
                      f"{', '.join(os.path.basename(x) for x in paths)}. "
                      f"Figures from other runs are deliberately not "
                      f"substituted here - they would show a different "
                      f"model.]")
        r.italic = True
        r.font.size = Pt(10.5)
        r.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)
        return False
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for path in present:
        p.add_run().add_picture(path, width=Cm(8.0) if len(present) <= 2 else Cm(6.0))
        p.add_run("  ")
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr = c.add_run(caption)
    cr.italic = True
    cr.font.size = Pt(10.5)
    cr.font.name = "Times New Roman"
    c.paragraph_format.space_after = Pt(14)
    return True


# ==========================================================================
heading("Self-Weight and Modal Analysis of the Castelnuovo di Porto "
        "Aggregate", level=2)

para(
    "This section reports the self-weight static check and the modal "
    "(eigenvalue) analysis of the full Castelnuovo di Porto masonry "
    "aggregate. The model is linear elastic and fully bonded - the Task A "
    "wall-to-wall contact interfaces described elsewhere in this chapter "
    "are deliberately omitted, so that the contact nonlinearity is removed "
    "from the eigenproblem and the result serves as the linear reference "
    "against which the effect of those interfaces can later be assessed."
)
para(
    "The analysis is built directly on the framework used throughout this "
    "work (gmsh for meshing, gmsh2opensees for the mesh-to-model transfer, "
    "and OpenSeesPy for the solution), run sequentially on a single "
    "process. Sequential execution is a requirement rather than a "
    "preference: the eigenvalue solve (ARPACK, through the OpenSees eigen "
    "command) stalls indefinitely under MPI domain partitioning regardless "
    "of mesh size or number of requested modes, so no domain decomposition "
    "is applied."
)

heading("Material", level=3)
para(
    "The masonry is modelled as a homogeneous linear-elastic continuum "
    f"with E = {s['young_modulus_MPa']:.2f} MPa, \u03bd = {s['poisson_ratio']:g} "
    f"and \u03c1 = {s['density_kg_m3']:.0f} kg/m\u00b3. The Young's modulus is "
    "the mean of the four masonry types calibrated for this aggregate "
    "through the HMO/MQI procedure (1526.6, 1198.7, 987.8 and 1198.7 MPa). "
    "The four types are weighted equally because assigning them per facade "
    "would require a volume-to-facade mapping that the current geometry "
    "does not carry; this is recorded as an open point of the methodology. "
    "This supersedes the generic placeholder values (700 MPa, \u03bd = 0.25, "
    "2000 kg/m\u00b3) used in the preliminary runs of this chapter."
)

heading("Restoration of wall-to-wall continuity", level=3)
para(
    "A structural defect inherited from the source geometry had to be "
    "corrected before the modal results could be interpreted. In the "
    "cleaned STEP model, 21 wall-to-wall junctions have their two solids "
    "drawn between 1.5 and 47 mm apart rather than in contact. The boolean "
    "fragment operation correctly declines to fuse solids that do not "
    "touch, so at each of those junctions the two walls shared no mesh "
    "node and therefore no stiffness: a wall could be attached to the block "
    "along one edge and completely free where it should have abutted its "
    "orthogonal walls. The consequence was directly visible in the first "
    "computed mode shapes, where individual walls swung out of plane while "
    "the walls that should have braced them stood still."
)
para(
    "Correcting this in the geometry was attempted first and did not "
    "succeed. Raising the import tolerance and removing duplicate entities "
    "recovered none of the 21 junctions; raising the boolean tolerance "
    "recovered 10 of 21 while renumbering the volumes; face sewing "
    "destroyed the model outright; and three variants of a purpose-built "
    "bridging-solid healing each made the topology worse rather than "
    "better, the count of open junctions rising from 21 to 145 and then to "
    "479 as each added bridge introduced more near-coincident faces than it "
    "closed."
)
para(
    "Continuity was therefore restored at the finite-element level, by "
    f"means of {s['equaldof_constraints']} multi-point constraints "
    "(equalDOF) tying the facing nodes across the gaps - the standard "
    "treatment for coupling non-matching meshes, and the exact converse of "
    "the node-splitting used elsewhere in this chapter to decouple a Task A "
    "contact interface. Two implementation points govern the result. "
    "First, the analysis must use the Transformation constraint handler: "
    "the default Plain handler ignores multi-point constraints silently, so "
    "the ties would be declared and have no effect. Second, the mesh is "
    "locally refined to 0.10 m within 0.40 m of the facing surfaces only. "
    "At the 0.60 m global size the facing nodes lie roughly 0.6 m apart "
    "while the gaps themselves are millimetres, so almost no node pair is "
    "close enough to tie; refining locally produces many short ties instead "
    "of a few long ones, a long tie being a rigid link that would stiffen "
    "the junction far beyond anything the masonry does."
)
para(
    "Six of the 21 junctions receive no tie of their own. These lie in a "
    "cluster where six volumes meet at a single corner with gaps of about "
    "1.2 mm, and since each node may be used only once, the available ties "
    "are taken by the three principal pairs. Verification at cluster level "
    "confirms that all six pairs are nevertheless connected through a third "
    "volume at the same corner, so no wall is left unbraced. It should be "
    "noted that the aggregate forms a single connected component both with "
    "and without the ties: the open junctions were a local bracing defect, "
    "not a global disconnection, and the evidence that the ties corrected "
    "it is the modal behaviour reported below rather than any connectivity "
    "count."
)
para(
    "The effect on the modal results is substantial and, importantly, "
    "selective. The three modes carrying the most translational mass move "
    "from modes 8, 3 and 9 - high-order, locally confined wall mechanisms - "
    "to modes 1, 7 and 2. The first two periods shorten by 14.8% and 20.4% "
    "respectively, while modes 3 to 10 change by only 0.7% to 6.6%. A "
    "uniform shortening across all periods would have indicated that the "
    "constraints were simply adding stiffness everywhere; the fact that the "
    "change is concentrated in the modes governed by the previously "
    "unbraced walls is what indicates that the ties act where continuity "
    "was missing and essentially nowhere else."
)

heading("Self-weight check", level=3)
para(
    "The total vertical reaction at the base is compared against the "
    "independently calculated self-weight \u03c1\u00b7g\u00b7V, as a basic "
    "check on mass and boundary conditions before the eigenvalue results "
    "built on the same model are relied upon."
)
add_summary_table([
    ("Mesh nodes", f"{s['mesh_nodes']:,}"),
    ("Mesh elements", f"{s.get('mesh_elements', 0):,}"),
    ("Global mesh size", f"{s.get('global_mesh_size_m', 0.6):g} m"),
    ("Local refinement at junctions", "0.10 m within 0.40 m"),
    ("equalDOF constraints", f"{s['equaldof_constraints']}"),
    ("MPI ranks / partitions", "1 (no domain decomposition)"),
    ("Total volume", f"{s['total_volume_m3']:.2f} m\u00b3"),
    ("Self-weight, calculated (\u03c1\u00b7g\u00b7V)",
     f"{s['self_weight_calculated_N']:,.1f} N"),
    ("Total base reaction, analysis", f"{s['total_base_reaction_N']:,.1f} N"),
    ("Weight / reaction difference", f"{s['weight_reaction_diff_pct']:.3f} %"),
])
para(
    f"The base reaction matches the calculated self-weight to within "
    f"{abs(s['weight_reaction_diff_pct']):.3f}%."
)
add_figure_row(
    [os.path.join(PLOTS_DIR, f"{IMG_PREFIX}_selfweight_{IMG_SUFFIX}_{v}.png")
     for v in VIEW_SUFFIXES],
    "Figure 1 - Deformed shape under self-weight, \u00d7200 magnification.",
)

heading("Modal analysis", level=3)
para(
    f"{n_modes} modes were computed. Table 1 lists, for each mode, the "
    "natural period T, the frequency f, the modal participation mass "
    "ratios in the two horizontal directions (MX, MY) and in the vertical "
    "direction (MZ), and the running totals \u03a3MX and \u03a3MY. Each "
    "ratio is expressed as a percentage of the structure's total free mass "
    "in that direction, which measures how much a mode actually "
    "contributes to the response rather than merely where it falls in the "
    "eigenvalue ordering."
)
para(
    f"The three most significant modes by translational participation are "
    f"modes {', '.join(str(m) for m in top_modes)}, highlighted in green. "
    f"Mode {top_modes[0]} alone carries "
    f"{ratios[top_modes[0]][0]:.1f}% of the mass in X, and mode "
    f"{ranked[1][0]} carries {ratios[ranked[1][0]][1]:.1f}% in Y, so the "
    "two principal horizontal directions are governed by distinct modes."
)

if cross_x and cross_y:
    para(
        f"The cumulative participating mass reaches the {TARGET_MASS:g}% "
        "required by NTC2018 \u00a77.3.3.1 and EC8 at mode "
        f"{cross_y} in Y (f = {freqs[cross_y]:.2f} Hz) and mode {cross_x} "
        f"in X (f = {freqs[cross_x]:.2f} Hz), highlighted in amber. Over "
        f"all {n_modes} computed modes the totals are "
        f"\u03a3MX = {cum_final[0]:.2f}% and \u03a3MY = {cum_final[1]:.2f}%, "
        f"so the requirement is satisfied in both horizontal directions."
    )
else:
    para(
        f"Over the {n_modes} computed modes the cumulative participating "
        f"mass reaches \u03a3MX = {cum_final[0]:.2f}% and "
        f"\u03a3MY = {cum_final[1]:.2f}%. This does NOT meet the "
        f"{TARGET_MASS:g}% required by NTC2018 \u00a77.3.3.1 and EC8, and a "
        "larger number of modes is required before a response-spectrum "
        "verification on these results would be admissible."
    )

para(
    "Three qualifications belong with these figures. The vertical "
    f"participation reaches only {cum_final[2]:.1f}% and does not attain "
    f"{TARGET_MASS:g}%; the requirement is satisfied in the horizontal "
    "directions, which are the directions of interest here, and the "
    "statement should not be generalised to the vertical one. The number "
    "of modes needed is itself a result: no single mode dominates this "
    "structure, and beyond the first ten no mode carries more than a few "
    "percent, so the final increments of participating mass accumulate "
    "from many small, locally confined wall mechanisms. Consequently the "
    f"{TARGET_MASS:g}% threshold is only attained at frequencies around "
    f"{freqs[max(filter(None, [cross_x, cross_y]))]:.0f} Hz "
    "if it is attained at all - far above the energetic content of a "
    "realistic seismic input, so those high modes satisfy the code "
    "criterion while contributing little to the actual response."
)

heading("Table 1 - Modal analysis results (all computed modes)", level=3)
add_modes_table()

heading("Mode shapes", level=3)
para(
    "The mode shapes are normalised to a common maximum visual "
    "displacement, the eigenvectors carrying no physical amplitude of "
    "their own, and are coloured by relative modal displacement magnitude "
    "with the underlying CAD edges overlaid so that individual blocks and "
    "openings remain identifiable."
)

n_missing = 0
for mode in sorted(ratios):
    if mode not in top_modes and mode > 10:
        continue    # beyond the tenth, only the significant modes are shown
    mx, my, mz = ratios[mode][:3]
    tag = " (most significant)" if mode in top_modes else ""
    heading(f"Mode {mode}{tag} (T = {periods[mode]:.4f} s, "
            f"f = {freqs[mode]:.3f} Hz)", level=4)
    para(f"Modal participation mass ratios: MX = {mx:.2f}%, "
         f"MY = {my:.2f}%, MZ = {mz:.4f}%.")
    ok = add_figure_row(
        [os.path.join(PLOTS_DIR,
                      f"{IMG_PREFIX}_mode{mode}_{IMG_SUFFIX}_{v}.png")
         for v in VIEW_SUFFIXES],
        f"Mode {mode} deformed shape (two views), coloured by relative "
        "modal displacement magnitude.",
    )
    if not ok:
        n_missing += 1

doc.save(OUT_PATH)
print(f"Wrote {OUT_PATH}")
print(f"{n_modes} modes, sigma MX = {cum_final[0]:.2f}%, "
      f"sigma MY = {cum_final[1]:.2f}%, sigma MZ = {cum_final[2]:.2f}%")
print(f"85% reached at mode {cross_x} (X) / {cross_y} (Y)"
      if cross_x and cross_y else "85% NOT reached")
if n_missing:
    print(f"WARNING: {n_missing} mode section(s) have no figure for this run "
          f"- run the plotting script for {os.path.basename(EIGEN_DIR)} and "
          f"rebuild, or the document ships with placeholders.")
