"""Opens the time-history's damage/strain results in a REAL interactive
gmsh window - same idea as scripts/view_results_gmsh.py (used the same way
for the eigenmode shapes), used here because getting an automated,
headless render of these two fields together with a legible building
shape hit a real, unsolved problem: a semi-transparent exterior shell
makes the coloured damage/strain View disappear entirely (an OpenGL
blending/draw-order issue between the transparent face pass and the
separate View pass - see scripts/render_damage_strain_gmsh.py's docstring
for the three things that were tried). Interactively, that stops being a
blocker: gmsh's own transparency slider (Tools > Options > Mesh >
Visibility tab) can be dragged live to find a setting that shows both the
building and the colour, which is not something worth automating blind.

Loads output/castelnuovo/results_timehistory/mesh.msh - the exact mesh
the time-history analysed (copied from the desktop's raw run directory,
not re-meshed - re-meshing would not reproduce the same element tags) -
plus sampled_elements.txt (element_index -> element_tag), damage_map.csv
and principal_strains.csv, all from the same directory.

Four views, ElementData (colours each element's own faces directly, no
node averaging): damage tension (d+), damage compression (d-), max
tensile principal strain (RAW, unclipped - reaches 69% at the known
numerical hot-spot, see chat log) and the same strain CLIPPED at its 99th
percentile so the other 99.5% of the structure is not flattened to one
colour by that handful of elements. Only damage_tension is visible on
open; toggle the others in the left-hand panel or the View menu.

Only 85,311 of 119,953 elements were ever recorded (see
timehistory_castelnuovo.py's SOLID_SAMPLE) - the rest carry no data and
will not appear in any of the four Views regardless of transparency.

Run locally (this OPENS A WINDOW and blocks until you close it):

    conda activate castelnuovo_viewer
    python scripts/view_timehistory_gmsh.py
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh

DATA_DIR = "output/castelnuovo/results_timehistory"
MESH_PATH = f"{DATA_DIR}/mesh.msh"
SAMPLED_PATH = f"{DATA_DIR}/sampled_elements.txt"
DAMAGE_PATH = f"{DATA_DIR}/damage_map.csv"
STRAIN_PATH = f"{DATA_DIR}/principal_strains.csv"
STRAIN_CLIP_PERCENTILE = 99.0

for p in (MESH_PATH, SAMPLED_PATH, DAMAGE_PATH, STRAIN_PATH):
    if not os.path.isfile(p):
        sys.exit(f"Missing {p} - copy it from the desktop's "
                 f"recorders_timehistory/ (see the chat log) first.")

idx_to_tag = {}
with open(SAMPLED_PATH) as fh:
    for line in fh:
        if line.startswith("#"):
            continue
        i, tag = line.strip().split(",")
        idx_to_tag[int(i)] = int(tag)
print(f"{len(idx_to_tag)} sampled elements mapped")

damage_tags = []
d_tension, d_compression = [], []
with open(DAMAGE_PATH) as fh:
    for row in csv.DictReader(fh):
        i = int(row["element_index"])
        if i not in idx_to_tag:
            continue
        damage_tags.append(idx_to_tag[i])
        d_tension.append(float(row.get("damage_tension", row.get("final_component_0", 0.0))))
        d_compression.append(float(row.get("damage_compression", row.get("final_component_1", 0.0))))

strain_tags, strain_vals = [], []
with open(STRAIN_PATH) as fh:
    for row in csv.DictReader(fh):
        i = int(row["element_index"])
        if i not in idx_to_tag:
            continue
        strain_tags.append(idx_to_tag[i])
        strain_vals.append(float(row["max_tensile_principal_strain"]))

import numpy as np
strain_vals = np.array(strain_vals)
clip_at = float(np.percentile(strain_vals, STRAIN_CLIP_PERCENTILE))
strain_clipped = np.minimum(strain_vals, clip_at)
n_clipped = int((strain_vals > clip_at).sum())
print(f"strain: raw range [{strain_vals.min():.4e}, {strain_vals.max():.4e}], "
      f"{n_clipped} element(s) above the {STRAIN_CLIP_PERCENTILE:g}th "
      f"percentile ({clip_at:.4e})")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.open(MESH_PATH)
model_name = gmsh.model.getCurrent()
print(f"Loaded mesh, model name: {model_name!r}")

view_tags = []


def add_view(name, tags, vals, clim):
    v = gmsh.view.add(name)
    data = [[float(x)] for x in vals]
    gmsh.view.addModelData(v, 0, model_name, "ElementData", list(tags), data,
                           numComponents=1)
    gmsh.view.option.setNumber(v, "RangeType", 2)   # custom
    gmsh.view.option.setNumber(v, "CustomMin", clim[0])
    gmsh.view.option.setNumber(v, "CustomMax", clim[1])
    gmsh.view.option.setNumber(v, "IntervalsType", 3)  # continuous
    gmsh.view.option.setNumber(v, "ShowScale", 1)
    view_tags.append(v)
    print(f"View {v}: {name}")
    return v


add_view("damage tension (d+)", damage_tags, d_tension, (0.0, 1.0))
add_view("damage compression (d-)", damage_tags, d_compression, (0.0, 1.0))
add_view(f"max tensile principal strain (RAW, up to {strain_vals.max():.3f})",
        strain_tags, strain_vals, (0.0, float(strain_vals.max())))
add_view(f"max tensile principal strain (clipped at {clip_at:.2e})",
        strain_tags, strain_clipped, (0.0, clip_at))

for i, v in enumerate(view_tags):
    gmsh.view.option.setNumber(v, "Visible", 1 if i == 0 else 0)

# Mesh left ON (unlike view_results_gmsh.py, which hides it) - this is
# exactly what lets the building be recognisable, and Tools > Options >
# Mesh > Visibility's transparency slider is what makes the colour show
# through it. Starts opaque; drag the slider to taste.
gmsh.option.setNumber("Geometry.Points", 0)
gmsh.option.setNumber("Geometry.Curves", 0)
gmsh.option.setNumber("Geometry.Surfaces", 0)
gmsh.option.setNumber("Geometry.Volumes", 0)
gmsh.option.setNumber("Mesh.SurfaceFaces", 1)
gmsh.option.setNumber("Mesh.SurfaceEdges", 1)
gmsh.option.setNumber("Mesh.LineWidth", 0.6)
# gmsh.option.setColor("Mesh.SurfaceFaces", ...) errors outright ("Could
# not set option") - colour goes on the ENTITIES instead
# (gmsh.model.setColor), the same API render_damage_strain_gmsh.py and
# plot_candidate_interfaces.py already use successfully.
gmsh.model.setColor(gmsh.model.getEntities(3), 190, 190, 195, 255, recursive=True)
gmsh.option.setNumber("General.Trackball", 0)
gmsh.option.setNumber("General.RotationX", -25)
gmsh.option.setNumber("General.RotationY", 0)
gmsh.option.setNumber("General.RotationZ", -25)

print(f"\n{len(view_tags)} views loaded. Opening gmsh -")
print("  - toggle views (damage/strain) in the left panel or the View menu")
print("  - Tools > Options > Mesh > Visibility tab has the transparency "
      "slider for the grey shell - drag it until the colour shows through")
print("  - screenshot with File > Export, Ctrl+P, or the camera button")
gmsh.fltk.run()
gmsh.finalize()
