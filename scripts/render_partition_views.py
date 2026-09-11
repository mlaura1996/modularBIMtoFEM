"""
Renders the MPI partition map as a real gmsh screenshot of the building
(same technique as select_interfaces_gui.py), at three camera angles -
gmsh.write() hangs indefinitely inside the Docker analysis container (its
Xvfb/software-OpenGL stack - confirmed by isolated testing, even for a
trivial one-box scene with LIBGL_ALWAYS_SOFTWARE=1 set), so this renders
LOCALLY instead, using per-volume partition data
docker/opensees/full_aggregate_with_interfaces_clean.py already exported
to JSON.

The two environments' apeGmsh/gmsh versions number volumes differently
(same lesson as InterfaceSelection.key_for's docstring - hit first on
interface selection), so volumes are matched back by nearest CENTROID
distance, not by tag - a geometric invariant, unlike gmsh's internal
numbering.

Run locally, on the castelnuovo_viewer conda environment:

    conda activate castelnuovo_viewer
    python scripts/render_partition_views.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmsh
from apeGmsh import apeGmsh

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
PARTITION_JSON = "output/castelnuovo/plots/full_aggregate_interfaces_clean_partition_by_volume.json"
OUT_DIR = "output/castelnuovo/plots"
OUT_PREFIX = "full_aggregate_interfaces_clean_partitions_gmsh"

VIEWS = [
    ("Vista 1", -35, 0, -35),
    ("Vista 2", -25, 0, -35),
    ("Vista 3", -25, 0, -25),
]
# tab10, first 6 - same palette the earlier matplotlib partition plot used,
# so a reader comparing the two figures isn't looking at a different color
# per rank.
PARTITION_COLORS = [
    (31, 119, 180), (255, 127, 14), (44, 160, 44),
    (214, 39, 40), (148, 103, 189), (140, 86, 75),
]
MATCH_TOL_M = 0.05  # a volume's centroid should match to millimetres, not just cm - see below

if not os.path.isfile(PARTITION_JSON):
    sys.exit(f"Missing {PARTITION_JSON} - run docker/opensees/"
              f"full_aggregate_with_interfaces_clean.py first.")
with open(PARTITION_JSON) as f:
    exported = json.load(f)
print(f"{len(exported)} volumes' partition data loaded from {PARTITION_JSON}")

os.makedirs(OUT_DIR, exist_ok=True)

with apeGmsh(model_name="render_partition_views") as g:
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()

    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} local volumes loaded (Docker exported {len(exported)} - "
          f"should match if example_clean_PRONTO.stp hasn't changed).")

    # Nearest-centroid match, local volume -> exported rank.
    unmatched = 0
    for _dim, vol in all_vols:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(3, vol)
        best = min(exported, key=lambda e: math.dist(e["centroid"], (cx, cy, cz)))
        d = math.dist(best["centroid"], (cx, cy, cz))
        if d > MATCH_TOL_M:
            unmatched += 1
            print(f"  WARNING: volume {vol} centroid ({cx:.3f},{cy:.3f},{cz:.3f}) - "
                  f"nearest exported match is {d:.4f}m away (rank {best['rank']}), "
                  f"past the {MATCH_TOL_M}m tolerance - using it anyway, but check "
                  f"the render for a stray-colored volume here.")
        r, gg, b = PARTITION_COLORS[best["rank"] % len(PARTITION_COLORS)]
        gmsh.model.setColor([(3, vol)], r, gg, b, 255, recursive=True)
    if unmatched:
        print(f"{unmatched}/{len(all_vols)} volumes matched past tolerance - see warnings above.")
    else:
        print("All volumes matched within tolerance.")

    gmsh.option.setNumber("General.GraphicsPositionX", -32000)
    gmsh.option.setNumber("General.GraphicsPositionY", -32000)
    gmsh.option.setNumber("General.GraphicsWidth", 50)
    gmsh.option.setNumber("General.GraphicsHeight", 50)
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Geometry.Surfaces", 1)
    gmsh.option.setNumber("Geometry.SurfaceType", 0)  # wireframe
    gmsh.option.setNumber("Geometry.LineWidth", 2)
    gmsh.option.setNumber("General.Trackball", 0)
    gmsh.fltk.initialize()

    written = []
    for view_name, rx, ry, rz in VIEWS:
        # Real gmsh quirk - only the FIRST write() after initialize() honors
        # Print.Width/Height, every later one silently drops to a smaller
        # size otherwise - see select_interfaces_gui.py's BuildingRenderer
        # docstring for how this was found. Fixed the same way here.
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("Print.Width", 2400)
        gmsh.option.setNumber("Print.Height", 1800)
        gmsh.option.setNumber("General.RotationX", rx)
        gmsh.option.setNumber("General.RotationY", ry)
        gmsh.option.setNumber("General.RotationZ", rz)
        path = os.path.join(OUT_DIR, f"{OUT_PREFIX}_{view_name.replace(' ', '_')}.png")
        gmsh.write(path)
        written.append(path)
        print(f"Wrote {path}")

print(f"\nDone - wrote {len(written)} partition-map screenshots under {OUT_DIR}/.")
