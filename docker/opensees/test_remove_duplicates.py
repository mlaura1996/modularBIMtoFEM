"""
Last standard-option attempt before writing custom geometry healing:
occ.removeAllDuplicates(), which merges entities that coincide within
Geometry.Tolerance. (core/mesh_generation/mesh.py's own fast_meshing calls
the .geo-kernel equivalent, so it is already part of the user's normal
workflow - just never combined with a raised tolerance on this geometry.)

Previous results for context:
  - Geometry.Tolerance alone (import):            0 / 21 junctions fused
  - Geometry.ToleranceBoolean = 2-5 cm:          10 / 21
  - OCCSewFaces + OCCMakeSolids:                 model destroyed (0 volumes)

Checks, per recipe: volumes (baseline 279), total volume (baseline
623.06 m3), volume pairs fragment() sees as touching, and how many of the
21 known open junctions became fused.
"""
import sys

sys.path.insert(0, "/app")

import gmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
BASELINE_VOLUMES = 279
BASELINE_TOTAL = 623.0566

KNOWN_GAPS = [
    (81, 101), (91, 102), (91, 103), (92, 102), (92, 103), (81, 102),
    (91, 101), (107, 118), (105, 107), (107, 110), (85, 111), (89, 111),
    (96, 107), (99, 107), (104, 106), (107, 281), (107, 280), (91, 107),
    (92, 107), (59, 115), (106, 107),
]

RECIPES = [
    ("removeAllDuplicates, default tol", None, True, False),
    ("removeAllDuplicates, tol=5mm", 5e-3, True, False),
    ("removeAllDuplicates, tol=2cm", 2e-2, True, False),
    ("removeAllDuplicates, tol=5cm", 5e-2, True, False),
    ("removeAllDuplicates tol=5cm + Bool=5cm", 5e-2, True, True),
]

print(f"{'recipe':>42}  {'vols':>5}  {'total vol':>10}  {'pairs':>6}  {'gaps fused':>11}")
print("-" * 88)

for label, tol, do_dedup, bool_tol in RECIPES:
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        if tol is not None:
            gmsh.option.setNumber("Geometry.Tolerance", tol)
        if bool_tol and tol is not None:
            gmsh.option.setNumber("Geometry.ToleranceBoolean", tol)
        gmsh.model.add(label.replace(" ", "_").replace(",", ""))
        gmsh.open(STEP_PATH)
        if do_dedup:
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
        gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
        gmsh.model.occ.synchronize()

        vols = gmsh.model.getEntities(3)
        total_vol = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)
        candidates = InterfaceDetection.find_touching_surface_pairs()
        pairs = {(min(c["volume_a"], c["volume_b"]), max(c["volume_a"], c["volume_b"]))
                 for c in candidates}
        fused = sum(1 for a, b in KNOWN_GAPS if (min(a, b), max(a, b)) in pairs)

        flag = ""
        if len(vols) != BASELINE_VOLUMES:
            flag += f"  [volumes {len(vols)-BASELINE_VOLUMES:+d}, tags shifted]"
        if abs(total_vol - BASELINE_TOTAL) > 0.5:
            flag += f"  [MASS {total_vol-BASELINE_TOTAL:+.2f} m3]"
        print(f"{label:>42}  {len(vols):5d}  {total_vol:10.2f}  {len(pairs):6d}  "
              f"{fused:5d} / {len(KNOWN_GAPS)}{flag}")
    except Exception as e:
        print(f"{label:>42}  FAILED: {e}")
    finally:
        gmsh.finalize()

print("\nDone.")
