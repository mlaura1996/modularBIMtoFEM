"""
Static, headless visualization of Task A candidate wall-to-wall
interfaces - matplotlib only (the SAME robust, proven rendering path
already used for output/castelnuovo/plots/*.png), no Qt/VTK/OpenGL at
all. Built after apeGmsh's interactive MeshViewer turned out to be
unworkable on this machine (hours of Qt/GTK/conda-forge DLL conflicts -
see chat log). This sidesteps that whole stack entirely.

Run OUTSIDE Docker, on a local conda/micromamba environment with
ifcopenshell, pythonocc-core, gmsh, apeGmsh, numpy, matplotlib (NOT the
PySide2/pyvista/pyvistaqt pieces - those aren't needed here and were the
actual source of trouble):

    python scripts/plot_candidate_interfaces.py

Deliberately does NOT use core.ifc_processing.ifc_step_matching's real
IFC-type classification (point-in-solid tests, O(n_ifc_elements x
n_volumes) - a real bottleneck, minutes in some environments) - instead
uses a cheap volume-size threshold to drop small door/window frame
volumes (walls are far larger). Less precise than the real classifier,
fine for "roughly where are the candidates" visual triage - refine later
with scripts/inspect_interfaces.py's classifier-based filtering once a
selection is confirmed.

Produces one overview PNG under output/castelnuovo/plots/ - each
vertical_joint candidate's centroid shown as a numbered point (number
matches the row in core.mesh_generation.wall_interfaces.InterfaceSelection.
present_cli()'s table). No wireframe/volume context drawn (that loop was
the likely cause of a hang/crash on this machine with 279 volumes) - the
point cloud's own shape traces the building. Look at the image, note the
numbers you want, then run scripts/inspect_interfaces.py (gmsh-native,
non-Qt, proven working) and type them in when it asks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
OUT_DIR = "output/castelnuovo/plots"
PLOT_ORIENTATIONS = ("vertical_joint",)
MIN_VOLUME_M3 = 0.3  # cheap door/window-frame filter - walls are far bigger

os.makedirs(OUT_DIR, exist_ok=True)

with apeGmsh(model_name="plot_candidates") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.", flush=True)

    big_vol_tags = {t for _d, t in all_vols if gmsh.model.occ.getMass(3, t) >= MIN_VOLUME_M3}
    print(f"{len(big_vol_tags)}/{len(all_vols)} volumes >= {MIN_VOLUME_M3} m^3 "
          f"(cheap door/window-frame filter).", flush=True)

    candidates = InterfaceDetection.find_touching_surface_pairs()
    InterfaceDetection.classify_orientation(candidates)
    print(f"{len(candidates)} candidates total.", flush=True)

    numbered = [(i, c) for i, c in enumerate(candidates, start=1)
                if c["orientation"] in PLOT_ORIENTATIONS
                and c["volume_a"] in big_vol_tags and c["volume_b"] in big_vol_tags]
    print(f"{len(numbered)} candidates will be plotted/numbered "
          f"(orientation in {PLOT_ORIENTATIONS}, both volumes >= {MIN_VOLUME_M3} m^3).",
          flush=True)

    # Cheap building-shape context: each big (wall) volume's own centroid
    # as a small gray dot - NOT its boundary edges (that per-edge
    # getParametrizationBounds/getValue sampling loop, tried first, was
    # the likely cause of a hang/crash on this machine with 279 volumes;
    # a single getCenterOfMass call per volume is far cheaper and gives
    # enough of a silhouette to orient by).
    wall_centroids = np.array([gmsh.model.occ.getCenterOfMass(3, t) for t in big_vol_tags])
    print(f"{len(wall_centroids)} wall-volume centroids for context.", flush=True)

    fig = plt.figure(figsize=(13, 10))
    ax = fig.add_subplot(111, projection="3d")
    ax.scatter(wall_centroids[:, 0], wall_centroids[:, 1], wall_centroids[:, 2],
               color="lightgray", s=10, zorder=1, alpha=0.5)
    cmap = plt.get_cmap("tab20")
    for k, (i, c) in enumerate(numbered):
        cx, cy, cz = c["centroid"]
        ax.scatter([cx], [cy], [cz], color=cmap(k % 20), s=35, zorder=3)
        ax.text(cx, cy, cz, str(i), fontsize=6.5, zorder=4)
    ax.set_title(f"{len(numbered)} vertical_joint candidates (walls only, "
                 f"door/window frames filtered by volume)")
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
    path = os.path.join(OUT_DIR, "candidate_interfaces_overview.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {path}", flush=True)

print("\nDone. Look at the PNG under output/castelnuovo/plots/, note the numbers "
      "you want, then run scripts/inspect_interfaces.py and type them in when asked.",
      flush=True)
