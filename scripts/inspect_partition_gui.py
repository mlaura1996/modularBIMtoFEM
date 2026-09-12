"""
Same partition-coloring as scripts/render_partition_views.py, but opens
gmsh's own interactive GUI (gmsh.fltk.run()) instead of taking headless
screenshots - so you can orbit/zoom yourself and grab whatever view you
like (Edit > Copy or a screen capture tool). Also meshes at
GLOBAL_MESH_SIZE (0.6 m - same as the real analysis,
docker/opensees/full_aggregate_with_interfaces_clean.py, so the mesh you
see matches the partition data exactly) so the actual tetrahedral mesh is
visible, not just the smooth CAD wireframe.

Run locally, on the castelnuovo_viewer conda environment:

    conda activate castelnuovo_viewer
    python scripts/inspect_partition_gui.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
# Pick which run's partition data to render - pass "selfweight" as
# argv[1] for docker/opensees/self_weight_check_full_aggregate_clean.py's
# (bonded, no Task A interfaces) partition, default is the with-interfaces
# one (docker/opensees/full_aggregate_with_interfaces_clean.py).
if len(sys.argv) > 1 and sys.argv[1] == "selfweight":
    PARTITION_JSON = "output/castelnuovo/plots/full_aggregate_clean_partition_by_volume.json"
else:
    PARTITION_JSON = "output/castelnuovo/plots/full_aggregate_interfaces_clean_partition_by_volume.json"
GLOBAL_MESH_SIZE = 0.167  # m - 3 elements through the ~0.50 m wall thickness (brief's target
# resolution, see docs/source/case_study/overview.md - ~279k nodes/954k tets for the whole
# aggregate, never actually run in the analysis because of exactly that size; fine for a
# visual-only mesh here, just expect meshing itself to take noticeably longer than 0.6 m did.

PARTITION_COLORS = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44),
    (214, 39, 40), (148, 103, 189), (140, 86, 75),
]
MATCH_TOL_M = 0.05

if not os.path.isfile(PARTITION_JSON):
    sys.exit(f"Missing {PARTITION_JSON} - run docker/opensees/"
              f"full_aggregate_with_interfaces_clean.py first.")
with open(PARTITION_JSON) as f:
    exported = json.load(f)
print(f"{len(exported)} volumes' partition data loaded.")

with apeGmsh(model_name="inspect_partition_gui") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    # Raw gmsh fragment() (needed for conformal interfaces - see
    # scripts/select_interfaces_gui.py) doesn't update apeGmsh's own
    # entity-metadata bookkeeping, so a couple of consumed (3, tag) keys
    # go stale - apeGmsh's pre-mesh validation (added since the render/
    # detection-only scripts that don't mesh never hit this) catches it
    # and refuses to mesh otherwise. Sweep it, as the error itself suggests.
    g.model.geometry.remove_orphans()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} local volumes loaded.")

    unmatched = 0
    for _dim, vol in all_vols:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        best = min(exported, key=lambda e: math.dist(e["centroid"], (cx, cy, cz)))
        d = math.dist(best["centroid"], (cx, cy, cz))
        if d > MATCH_TOL_M:
            unmatched += 1
        r, gg, b = PARTITION_COLORS[best["rank"] % len(PARTITION_COLORS)]
        gmsh.model.setColor([(3, vol)], r, gg, b, 255, recursive=True)
    print(f"{len(all_vols) - unmatched}/{len(all_vols)} volumes matched within tolerance.")

    print(f"Meshing at {GLOBAL_MESH_SIZE} m (same as the real analysis) - a few seconds...")
    g.mesh.sizing.set_size_sources(from_points=False)
    g.mesh.sizing.set_global_size(GLOBAL_MESH_SIZE)
    g.mesh.generation.generate(dim=3)

    # Show the actual mesh triangulation (not the smooth CAD wireframe) -
    # colors set on the geometry above carry over to the mesh display too,
    # but ONLY if ColorCarousel=1 ("by elementary entity") - the default,
    # 0 ("by element type"), paints every triangle the same colour
    # regardless of any gmsh.model.setColor call (found the hard way: the
    # first version of this script came up solid orange, every volume's
    # per-partition color ignored).
    gmsh.option.setNumber("Geometry.Surfaces", 0)
    gmsh.option.setNumber("Geometry.Curves", 0)
    gmsh.option.setNumber("Mesh.SurfaceEdges", 1)
    gmsh.option.setNumber("Mesh.SurfaceFaces", 1)
    gmsh.option.setNumber("Mesh.VolumeEdges", 0)
    gmsh.option.setNumber("Mesh.ColorCarousel", 1)

    # Same "Vista 3" angle used everywhere else in this project
    # (select_interfaces_gui.py, render_partition_views.py) - a
    # reproducible starting point; rotate freely from here.
    gmsh.option.setNumber("General.RotationX", -25)
    gmsh.option.setNumber("General.RotationY", 0)
    gmsh.option.setNumber("General.RotationZ", -25)

    print("\nOpening gmsh's GUI - orbit/zoom as usual, screenshot however you like "
          "(File > Export, or a screen capture tool). Close the window when done.")
    gmsh.fltk.run()

print("Window closed.")
