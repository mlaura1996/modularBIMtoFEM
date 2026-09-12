"""
Opens the Castelnuovo self-weight + eigenmode results in a REAL interactive
gmsh window, so the screenshots come out of gmsh itself (real OpenGL
z-buffer, real hidden-surface removal) instead of matplotlib - per explicit
request: "non ci siamo, questo non e' gmsh... apri i risultati in gmsh che
io faccio gli screenshoot". Same idea as scripts/inspect_partition_gui.py,
which was used the same way for the partition maps.

Loads:
  - output/castelnuovo/recorders_castelnuovo_native/castelnuovo_native.msh
    (the EXACT mesh docker/opensees/eigen_castelnuovo_native_gmsh.py
    analysed, exported by docker/opensees/export_native_mesh.py - not
    re-meshed here, so node tags line up with the result files by
    construction)
  - selfweight_displacement.txt + mode<k>_eigenvector.txt from the same
    directory (node_id,ux,uy,uz per line)

Each result becomes one gmsh post-processing View with VectorType =
"displacement", i.e. gmsh warps the shape itself and colours it by
displacement magnitude - the native equivalent of the matplotlib deformed
plots, but rendered by gmsh.

Only ONE view is visible at a time (the self-weight one on open); switch
between them in the left-hand panel / the "View" menu, or press the
visibility checkbox. Mode-shape eigenvectors carry no physical amplitude,
so each is normalised to max|u| = 1 and then shown with a 0.5 m
displacement factor (the same visual scale the matplotlib figures used);
self-weight is real metres, shown at x200 like those figures.

Run locally (this OPENS A WINDOW and blocks until you close it):

    conda activate castelnuovo_viewer
    python scripts/view_results_gmsh.py                 # untied, as-imported geometry
    python scripts/view_results_gmsh.py tied            # with the equalDOF ties
    python scripts/view_results_gmsh.py tied80          # the documented 80-mode run
    python scripts/view_results_gmsh.py tied80 3        # PRM >= 3% instead of 5%
    python scripts/view_results_gmsh.py tied80 all      # every computed mode
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh

RUNS = {
    "native": ("output/castelnuovo/recorders_castelnuovo_native",
               "castelnuovo_native.msh",
               "docker/opensees/eigen_castelnuovo_native_gmsh.py and "
               "docker/opensees/export_native_mesh.py"),
    "tied": ("output/castelnuovo/recorders_castelnuovo_tied",
             "castelnuovo_tied.msh",
             "docker/opensees/eigen_castelnuovo_tied.py"),
    "tied80": ("output/castelnuovo/recorders_castelnuovo_tied_80modes",
               "castelnuovo_tied.msh",
               "docker/opensees/eigen_castelnuovo_tied.py --n-modes 80"),
}
RUN = sys.argv[1] if len(sys.argv) > 1 else "native"
if RUN not in RUNS:
    sys.exit(f"Unknown run {RUN!r} - choose one of: {', '.join(RUNS)}")
DATA_DIR, _MSH_NAME, _HOW_TO_MAKE = RUNS[RUN]
MSH_PATH = f"{DATA_DIR}/{_MSH_NAME}"
SELFWEIGHT_FACTOR = 200.0     # real metres -> same x200 as the matplotlib figures
MODE_FACTOR = 0.5             # m, applied to eigenvectors normalised to max|u| = 1

# Which modes to load. Loading all 80 would be useless for taking figure
# screenshots - most of them are tiny local mechanisms - so by default only
# the modes that actually drive the response are loaded, selected the same
# way the document ranks them: participating mass, not eigenvalue order.
# Pass a PRM threshold in % as the second argument, or "all" for every mode
# the run wrote. Each view's title carries f, T and PRMx/PRMy so a
# screenshot is self-labelling.
PRM_THRESHOLD = 5.0
_arg2 = sys.argv[2] if len(sys.argv) > 2 else None
if _arg2 == "all":
    PRM_THRESHOLD = None
elif _arg2:
    PRM_THRESHOLD = float(_arg2)


def parse_float(s):
    """The writer used repr() on numpy scalars; numpy>=2 renders those as
    'np.float64(1.23)'. Accept both that and a plain number."""
    s = s.strip()
    if s.startswith("np.float64(") and s.endswith(")"):
        s = s[len("np.float64("):-1]
    return float(s)


def load_vector_file(path):
    """node_id,ux,uy,uz per line -> (tags, flat_values)."""
    tags, flat = [], []
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 4:
                continue
            tags.append(int(parts[0]))
            flat.extend([parse_float(parts[1]), parse_float(parts[2]), parse_float(parts[3])])
    return tags, flat


def normalise(flat):
    """Scale so the largest nodal vector magnitude is 1 (eigenvectors have
    no physical amplitude of their own)."""
    max_mag = 0.0
    for i in range(0, len(flat), 3):
        mag = math.sqrt(flat[i] ** 2 + flat[i + 1] ** 2 + flat[i + 2] ** 2)
        max_mag = max(max_mag, mag)
    if max_mag == 0:
        return flat
    return [v / max_mag for v in flat]


for path in (MSH_PATH, f"{DATA_DIR}/selfweight_displacement.txt"):
    if not os.path.isfile(path):
        sys.exit(f"Missing {path} - run {_HOW_TO_MAKE} first.")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)
gmsh.open(MSH_PATH)
model_name = gmsh.model.getCurrent()
print(f"Run {RUN!r}: loaded mesh, model name: {model_name!r}")

with open(f"{DATA_DIR}/eigenvalues.txt") as f:
    eigenvalues = [float(x) for x in f.read().split()]

# Participating mass per mode, to label and to select.
with open(f"{DATA_DIR}/modal_properties.txt") as f:
    _modal = f.read()
_body = _modal.split("9. MODAL PARTICIPATION MASS RATIOS")[1].split("* 10.")[0]
prm = {}
for _line in _body.splitlines():
    _p = _line.split()
    if len(_p) == 7 and _p[0].isdigit():
        prm[int(_p[0])] = (float(_p[1]), float(_p[2]))

if PRM_THRESHOLD is None:
    modes_to_load = sorted(prm)
else:
    modes_to_load = sorted(m for m, (mx, my) in prm.items()
                           if max(mx, my) >= PRM_THRESHOLD)
    if not modes_to_load:      # never open an empty window
        modes_to_load = [m for m, _ in sorted(
            prm.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:3]]
        print(f"No mode reaches PRM {PRM_THRESHOLD:g}%; falling back to the "
              f"top 3 by MX+MY.")
print(f"Loading {len(modes_to_load)} mode(s): "
      f"{', '.join(str(m) for m in modes_to_load)}")

view_tags = []

# --- self-weight ----------------------------------------------------------
tags, flat = load_vector_file(f"{DATA_DIR}/selfweight_displacement.txt")
v = gmsh.view.add(f"[{RUN}] Self-weight (x{SELFWEIGHT_FACTOR:g})")
gmsh.view.addHomogeneousModelData(v, 0, model_name, "NodeData", tags, flat,
                                   numComponents=3)
gmsh.view.option.setNumber(v, "VectorType", 5)          # 5 = displacement (warps the shape)
gmsh.view.option.setNumber(v, "DisplacementFactor", SELFWEIGHT_FACTOR)
gmsh.view.option.setNumber(v, "IntervalsType", 3)       # continuous colour map
gmsh.view.option.setNumber(v, "NbIso", 20)
gmsh.view.option.setNumber(v, "ShowScale", 1)
view_tags.append(v)
print(f"View {v}: self-weight")

# --- modes ----------------------------------------------------------------
for mode in modes_to_load:
    path = f"{DATA_DIR}/mode{mode}_eigenvector.txt"
    if not os.path.isfile(path):
        print(f"  mode {mode}: no eigenvector file, skipped")
        continue
    tags, flat = load_vector_file(path)
    flat = normalise(flat)
    T = 2 * math.pi / math.sqrt(eigenvalues[mode - 1])
    mx, my = prm[mode]
    # Name the run AND the participating mass in the view title: the whole
    # point here is comparing runs and picking modes for a figure, and a
    # screenshot that does not say which mode of which run it shows is
    # worse than no screenshot.
    v = gmsh.view.add(f"[{RUN}] Mode {mode} - f={1.0 / T:.2f}Hz, T={T:.4f}s, "
                      f"PRMx={mx:.2f}%, PRMy={my:.2f}%")
    gmsh.view.addHomogeneousModelData(v, 0, model_name, "NodeData", tags, flat,
                                       numComponents=3)
    gmsh.view.option.setNumber(v, "VectorType", 5)
    gmsh.view.option.setNumber(v, "DisplacementFactor", MODE_FACTOR)
    gmsh.view.option.setNumber(v, "IntervalsType", 3)
    gmsh.view.option.setNumber(v, "NbIso", 20)
    gmsh.view.option.setNumber(v, "ShowScale", 1)
    view_tags.append(v)
    print(f"View {v}: mode {mode} (f={1.0 / T:.2f}Hz, "
          f"PRMx={mx:.2f}%, PRMy={my:.2f}%)")

# Show only the first view on open - with 11 warped shapes stacked on top of
# each other the window is unreadable otherwise. Toggle the rest from the
# left-hand panel (or View menu) as you go.
for i, v in enumerate(view_tags):
    gmsh.view.option.setNumber(v, "Visible", 1 if i == 0 else 0)

# Clean display: no CAD entities, no mesh wireframe over the coloured result.
# The 1-D curve elements (the geometry edges) stay available on Mesh.Lines if
# you want them - off by default here since gmsh draws them undeformed while
# the view itself is warped, which reads oddly on a mode shape.
gmsh.option.setNumber("Geometry.Points", 0)
gmsh.option.setNumber("Geometry.Curves", 0)
gmsh.option.setNumber("Geometry.Surfaces", 0)
gmsh.option.setNumber("Geometry.Volumes", 0)
gmsh.option.setNumber("Mesh.Points", 0)
gmsh.option.setNumber("Mesh.Lines", 0)
gmsh.option.setNumber("Mesh.SurfaceEdges", 0)
gmsh.option.setNumber("Mesh.SurfaceFaces", 0)
gmsh.option.setNumber("Mesh.VolumeEdges", 0)
gmsh.option.setNumber("Mesh.VolumeFaces", 0)
gmsh.option.setNumber("General.Axes", 0)
gmsh.option.setNumber("General.SmallAxes", 1)
gmsh.option.setNumber("General.Trackball", 0)
gmsh.option.setNumber("General.RotationX", -25)
gmsh.option.setNumber("General.RotationY", 0)
gmsh.option.setNumber("General.RotationZ", -25)

print(f"\n{len(view_tags)} views loaded. Opening gmsh - "
      f"toggle views in the left panel, screenshot with File > Export (or "
      f"Ctrl+P / the camera button).")
gmsh.fltk.run()
gmsh.finalize()
