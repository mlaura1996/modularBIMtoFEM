"""
Re-plots the deformed-shape figure from full_aggregate_with_interfaces_
clean.py's ALREADY-CACHED recorder files (output/castelnuovo/recorders_
full_aggregate_interfaces_clean/) without re-running the MPI analysis -
same idea as docker/opensees/replot_full_aggregate.py, just for this
model. Only reason to run this on its own: iterating on plot styling
(here, the camera angle) without paying for mpirun again.

Rebuilds the SAME mesh (same STEP, same fragment, same GLOBAL_MESH_SIZE)
so node/element numbering matches the cached recorder files exactly - it
does not re-detect interfaces or re-run the analysis, just enough
geometry+mesh to get a FEMData object Results.from_recorders() can bind
the cached data to.
"""
import os
import sys

sys.path.insert(0, "/app")
os.makedirs("output/castelnuovo/plots", exist_ok=True)

import gmsh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from apeGmsh import apeGmsh, Results
from apeGmsh.solvers.Recorders import Recorders

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
RECORDER_DIR = "output/castelnuovo/recorders_full_aggregate_interfaces_clean"
GLOBAL_MESH_SIZE = 0.6
DEFORM_SCALE = 200.0
# Matches scripts/inspect_partition_gui.py's "Vista 3" gmsh rotation
# (RotationX=-25, RotationZ=-25) as closely as matplotlib's (elev, azim)
# convention allows - not an exact analytical conversion between the two
# camera models, tuned by eye instead.
VIEW_ELEV, VIEW_AZIM = 18, -65

with apeGmsh(model_name="replot_full_aggregate_interfaces_clean") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    g.parts.from_model("replot_full_aggregate_interfaces_clean")
    g.physical.add_volume([t for _, t in all_vols], name="Masonry")
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)
    g.mesh.partitioning.partition(n_parts=6)
    fem = g.mesh.queries.get_fem_data(dim=3)
    print(f"FEMData: {len(fem.nodes.ids)} nodes, {len(fem.elements.ids)} elements")

    rec = Recorders()
    rec.nodes(pg="Masonry", components="displacement")
    spec = rec.resolve(fem, ndm=3, ndf=3)

    results = Results.from_recorders(spec, output_dir=RECORDER_DIR, fem=fem)
    print(results)

    ax = results.plot.deformed(
        component="displacement_z", scale=DEFORM_SCALE,
        cmap="Blues", edge_color="#3a3a3a", linewidth=0.25, ghost=True,
    )
    ax.view_init(elev=VIEW_ELEV, azim=VIEW_AZIM)
    ax.set_title(
        "Castelnuovo full aggregate + 11 Task A interfaces - "
        f"self-weight, deformed ×{DEFORM_SCALE:g}",
        fontsize=10,
    )
    ax.set_xlabel("X", fontsize=8)
    ax.set_ylabel("Y", fontsize=8)
    ax.set_zlabel("Z", fontsize=8)
    for axis in ax.figure.axes:
        axis.tick_params(labelsize=7)
        if axis is not ax:
            axis.set_ylabel(axis.get_ylabel(), fontsize=8)

    path = "output/castelnuovo/plots/full_aggregate_interfaces_clean_deformed_uz_matched_view.png"
    ax.figure.savefig(path, dpi=200, bbox_inches="tight")
    print(f"Wrote {path}")
