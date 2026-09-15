"""Renders the damage and principal-strain pattern on the real geometry,
with real gmsh screenshots (true OpenGL z-buffer, correct hidden-surface
removal - see render_eigen_gmsh.py's docstring for why matplotlib was
abandoned for this).

Reads:
  - mesh.msh              the EXACT mesh the time-history analysis used
                          (copied from the desktop's recorders_timehistory/,
                          not re-meshed - re-meshing would not reproduce the
                          same element tags)
  - sampled_elements.txt   element_index -> element_tag, from the same run
  - damage_map.csv, principal_strains.csv  scripts/postprocess_timehistory.py's
                          output, keyed by element_index

Colours EVERY sampled element (85,311 of 119,953 - the rest were never
recorded, see timehistory_castelnuovo.py's SOLID_SAMPLE) using gmsh's own
ElementData view, which renders directly on each element's own faces - no
manual triangle-to-tetrahedron ownership lookup needed, unlike the earlier
matplotlib-based renders.

STRAIN IS CLIPPED, DELIBERATELY, NOT SILENTLY. A handful of elements
(~0.5%, spatially clustered - see chat log) carry principal strains up to
69% from a known, still-open numerical artifact (ASDConcrete3D + Task A
contact interfaces don't converge cleanly - docs/source/developer_guide/
known_issues.md). Left unclipped, that handful would saturate the colour
scale and make the other 99.5% of the structure read as a single flat
colour. The scale is clipped to the 99th percentile of the SAMPLED
elements' own peak values (computed fresh each run, not a hard-coded
number) and every run prints how many elements were clipped and their
range, so the clipping is visible and auditable rather than a number
quietly chosen to make the picture look better.

    conda activate castelnuovo_viewer
    python scripts/render_damage_strain_gmsh.py [run_dir] [out_dir]
"""
import csv
import os
import sys

import numpy as np
import gmsh

RUN_DIR = sys.argv[1] if len(sys.argv) > 1 else "."
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "output/castelnuovo/plots"
MESH_PATH = os.path.join(RUN_DIR, "mesh.msh")
SAMPLED_PATH = os.path.join(RUN_DIR, "sampled_elements.txt")
DAMAGE_PATH = os.path.join(RUN_DIR, "damage_map.csv")
STRAIN_PATH = os.path.join(RUN_DIR, "principal_strains.csv")

VIEWS = [("view1", 18, -65), ("view2", 25, -20)]
STRAIN_CLIP_PERCENTILE = 99.0

for p in (MESH_PATH, SAMPLED_PATH, DAMAGE_PATH, STRAIN_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p}")

# --- element_index -> element_tag -----------------------------------------
idx_to_tag = {}
with open(SAMPLED_PATH) as fh:
    for line in fh:
        if line.startswith("#"):
            continue
        i, tag = line.strip().split(",")
        idx_to_tag[int(i)] = int(tag)
print(f"{len(idx_to_tag)} sampled elements mapped")

# --- damage: tension component (governs the crack pattern in masonry) ----
damage_tags, damage_vals = [], []
with open(DAMAGE_PATH) as fh:
    for row in csv.DictReader(fh):
        i = int(row["element_index"])
        if i not in idx_to_tag:
            continue
        damage_tags.append(idx_to_tag[i])
        damage_vals.append(float(row.get("damage_tension", row.get("final_component_0", 0.0))))
damage_vals = np.array(damage_vals)
print(f"damage: {len(damage_tags)} elements, range "
      f"[{damage_vals.min():.4f}, {damage_vals.max():.4f}]")

# --- principal strain: tension, clipped -----------------------------------
strain_tags, strain_vals = [], []
with open(STRAIN_PATH) as fh:
    for row in csv.DictReader(fh):
        i = int(row["element_index"])
        if i not in idx_to_tag:
            continue
        strain_tags.append(idx_to_tag[i])
        strain_vals.append(float(row["max_tensile_principal_strain"]))
strain_vals = np.array(strain_vals)
clip_at = float(np.percentile(strain_vals, STRAIN_CLIP_PERCENTILE))
n_clipped = int((strain_vals > clip_at).sum())
print(f"strain: {len(strain_tags)} elements, raw range "
      f"[{strain_vals.min():.4e}, {strain_vals.max():.4e}]")
print(f"  clipped at the {STRAIN_CLIP_PERCENTILE:g}th percentile = "
      f"{clip_at:.4e} - {n_clipped} element(s) above it, "
      f"max among them {strain_vals.max():.4e} "
      f"({100*strain_vals.max():.1f}% strain, the known numerical hot-spot)")
strain_vals_clipped = np.minimum(strain_vals, clip_at)

# --- gmsh: headless off-screen render, same recipe as render_eigen_gmsh.py
gmsh.initialize()
gmsh.option.setNumber("General.GraphicsPositionX", -32000)
gmsh.option.setNumber("General.GraphicsPositionY", -32000)
gmsh.option.setNumber("General.GraphicsWidth", 50)
gmsh.option.setNumber("General.GraphicsHeight", 50)
gmsh.option.setNumber("General.Terminal", 1)
gmsh.option.setNumber("General.Trackball", 0)
gmsh.option.setNumber("General.Axes", 0)
gmsh.option.setNumber("General.SmallAxes", 0)
gmsh.fltk.initialize()

gmsh.open(MESH_PATH)
model_name = gmsh.model.getCurrent()
print(f"Loaded {MESH_PATH}, model {model_name!r}")

# A sparse ElementData view on 3D elements shows every rendered
# tetrahedron's own four faces with no hidden-surface awareness of its
# (uncoloured) neighbours - with 29% of elements never sampled, that
# renders as a "confetti" cloud with no recognisable building shape
# (confirmed by looking at a first attempt without this). Fixed by
# drawing the FULL mesh's own exterior surface first, in a flat neutral
# grey, using every one of the 119,953 elements - giving a solid, closed
# building silhouette - and letting the damage/strain View sit on top of
# it, visible only where it actually says something.
gmsh.option.setNumber("Geometry.Points", 0)
gmsh.option.setNumber("Geometry.Curves", 0)
gmsh.option.setNumber("Geometry.Surfaces", 0)
gmsh.option.setNumber("Geometry.Volumes", 0)
gmsh.option.setNumber("Mesh.Points", 0)
gmsh.option.setNumber("Mesh.Lines", 0)
gmsh.option.setNumber("Mesh.SurfaceEdges", 1)   # context lines, not fill
gmsh.option.setNumber("Mesh.SurfaceFaces", 0)
gmsh.option.setNumber("Mesh.VolumeEdges", 0)
gmsh.option.setNumber("Mesh.VolumeFaces", 0)
gmsh.option.setNumber("Mesh.LineWidth", 0.6)
# Two things were tried and abandoned before this:
# 1. Opaque Mesh.SurfaceFaces=1 as a solid grey shell: gives a recognisable
#    building, but the damaged elements are often INSIDE the wall
#    thickness (a tied junction, a contact interface), not on the exterior
#    face, so an opaque shell hides every one of them.
# 2. The same shell made semi-transparent (gmsh.model.setColor(..., alpha)):
#    the damage View disappeared entirely - an OpenGL blending/draw-order
#    issue between a transparent face pass and a separate View pass, not
#    resolved in the time available.
# Exterior EDGES (thin lines, not filled faces) give context without
# either problem - lines do not participate in face-transparency ordering
# the same way, and they let the confetti-style ElementData View underneath
# (each rendered element's own faces, see the module docstring) show
# through everywhere, including elements behind the wall's visible face.
vol_entities = gmsh.model.getEntities(3)
gmsh.model.setColor(vol_entities, 60, 60, 60, 255, recursive=True)

os.makedirs(OUT_DIR, exist_ok=True)


def render(name, tags, vals, clim, cbar_label):
    view_tag = gmsh.view.add(name)
    data = [[float(v)] for v in vals]
    gmsh.view.addModelData(view_tag, 0, model_name, "ElementData",
                           list(tags), data, numComponents=1)
    gmsh.view.option.setNumber(view_tag, "RangeType", 2)  # custom
    gmsh.view.option.setNumber(view_tag, "CustomMin", clim[0])
    gmsh.view.option.setNumber(view_tag, "CustomMax", clim[1])
    gmsh.view.option.setNumber(view_tag, "ShowScale", 1)
    gmsh.view.option.setNumber(view_tag, "IntervalsType", 3)  # continuous
    gmsh.view.option.setString(view_tag, "Name", cbar_label)

    for view_name, elev, azim in VIEWS:
        presets = {(18, -65): (-25, 0, -25), (25, -20): (-35, 0, -60)}
        rx, ry, rz = presets.get((elev, azim), (-25, 0, -25))
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("Print.Width", 2000)
        gmsh.option.setNumber("Print.Height", 1700)
        gmsh.option.setNumber("General.RotationX", rx)
        gmsh.option.setNumber("General.RotationY", ry)
        gmsh.option.setNumber("General.RotationZ", rz)
        path = f"{OUT_DIR}/castelnuovo_timehistory_{name}_{view_name}.png"
        gmsh.write(path)
        print(f"  Wrote {path}")
    gmsh.view.remove(view_tag)


render("damage_tension", damage_tags, damage_vals, (0.0, 1.0),
      "Tension damage d+")
render("strain_tension_clipped", strain_tags, strain_vals_clipped,
      (0.0, clip_at), f"Max tensile principal strain (clipped at {clip_at:.2e})")

gmsh.fltk.finalize()
print("Done.")
